bl_info = {
    "name": "Tree Vertex Data Baker",
    "author": "OpenAI",
    "version": (2, 6, 0),
    "blender": (5, 2, 0),
    "location": "Script Tool Window",
    "description": "Bake RGBA tree vertex data, augment albedo materials, and preview coherent wind",
    "category": "Object",
}

import bpy
import math
import random
import heapq
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass
from array import array

from mathutils import Vector, Euler
from mathutils.kdtree import KDTree
from mathutils.bvhtree import BVHTree
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import Operator, Panel, PropertyGroup
from bpy_extras.script_tool import ScriptToolWindow


# =============================================================================
# Constants / schema
# =============================================================================

ADDON_VERSION = (2, 6, 0)
MIN_BLENDER_VERSION = (5, 2, 0)
SCHEMA_VERSION = 2

ATTRIBUTE_DEFAULT = "TreeVertexData"
LEAF_FLUTTER_ATTRIBUTE = "TreeLeafFlutter"
WIND_MASK_ATTRIBUTE = "TreeWindMask"

TREE_NODE_TAG = "tree_vdb_node"
TREE_NODE_VERSION = "tree_vdb_node_version"
TREE_MATERIAL_ROLE = "tree_vdb_role"
TREE_OWNER_ID = "tree_vdb_owner"
TREE_OBJECT_ID = "tree_vdb_tree_id"
TREE_GROUP_ROLE = "tree_vdb_group_role"
TREE_MOD_TAG = "tree_vdb_modifier"

TREE_WIND_MODIFIER = "TreeVDB Wind Preview"
TREE_GN_TRUNK = "TreeVDB_Wind_Trunk"
TREE_GN_LEAVES = "TreeVDB_Wind_Leaves"

# Script Tool API identity. Window lifecycle is owned by ScriptToolWindow.
TREE_TOOL_CONTEXT = "tree_vdb"
TREE_TOOL_TITLE = "Tree Vertex Data Baker"
TREE_TOOL_WIDTH = 380
TREE_TOOL_HEIGHT = 730
TREE_TOOL_INSTANCE = "main"

KIND_WOOD = 0
KIND_LEAF = 1
OWNER_TRUNK = "TRUNK"
OWNER_LEAVES = "LEAVES"

CH_R = 1 << 0
CH_G = 1 << 1
CH_B = 1 << 2
CH_A = 1 << 3
CH_ALL = CH_R | CH_G | CH_B | CH_A

SAMPLE_BANK_COUNT = 8
_SAMPLE_CACHE = {}


# =============================================================================
# Logging / compatibility
# =============================================================================

def _version_string(v):
    return ".".join(str(x) for x in v[:3])


def log_info(message):
    print(f"[TreeVDB { _version_string(ADDON_VERSION) }] {message}")


def log_warning(message):
    print(f"[TreeVDB WARNING] {message}")


def ensure_supported_blender():
    if bpy.app.version < MIN_BLENDER_VERSION:
        raise RuntimeError(
            f"TreeVDB {_version_string(ADDON_VERSION)} requires Blender {_version_string(MIN_BLENDER_VERSION)}+; "
            f"current version is {_version_string(bpy.app.version)}."
        )


# =============================================================================
# Math helpers
# =============================================================================

def clamp01(x):
    return max(0.0, min(1.0, float(x)))


def smoothstep01(x):
    x = clamp01(x)
    return x * x * (3.0 - 2.0 * x)


def lerp(a, b, t):
    return a + (b - a) * t


def radical_inverse_vdc(bits):
    bits = (bits << 16) | (bits >> 16)
    bits = ((bits & 0x55555555) << 1) | ((bits & 0xAAAAAAAA) >> 1)
    bits = ((bits & 0x33333333) << 2) | ((bits & 0xCCCCCCCC) >> 2)
    bits = ((bits & 0x0F0F0F0F) << 4) | ((bits & 0xF0F0F0F0) >> 4)
    bits = ((bits & 0x00FF00FF) << 8) | ((bits & 0xFF00FF00) >> 8)
    return bits * 2.3283064365386963e-10


def make_cosine_hemisphere_samples(count):
    count = max(1, int(count))
    result = []
    for i in range(count):
        u1 = (i + 0.5) / count
        u2 = radical_inverse_vdc(i)
        r = math.sqrt(u1)
        phi = math.tau * u2
        result.append(Vector((
            r * math.cos(phi),
            r * math.sin(phi),
            math.sqrt(max(0.0, 1.0 - u1)),
        )))
    return result


def make_fibonacci_sphere_samples(count):
    count = max(1, int(count))
    if count == 1:
        return [Vector((0.0, 0.0, 1.0))]
    result = []
    golden_angle = math.pi * (3.0 - math.sqrt(5.0))
    for i in range(count):
        y = 1.0 - 2.0 * ((i + 0.5) / count)
        radius = math.sqrt(max(0.0, 1.0 - y * y))
        theta = golden_angle * i
        result.append(Vector((
            math.cos(theta) * radius,
            y,
            math.sin(theta) * radius,
        )))
    return result


def _sample_banks(kind, count):
    """Deterministic rotated banks reduce visible directional sampling patterns."""
    key = (kind, int(count), SAMPLE_BANK_COUNT)
    cached = _SAMPLE_CACHE.get(key)
    if cached is not None:
        return cached

    if kind == "HEMI":
        base = make_cosine_hemisphere_samples(count)
        banks = []
        for bank in range(SAMPLE_BANK_COUNT):
            phase = math.tau * bank / SAMPLE_BANK_COUNT
            c = math.cos(phase)
            s = math.sin(phase)
            banks.append([
                Vector((c * v.x - s * v.y, s * v.x + c * v.y, v.z))
                for v in base
            ])
    else:
        base = make_fibonacci_sphere_samples(count)
        banks = []
        for bank in range(SAMPLE_BANK_COUNT):
            # Fixed irrational-ish rotations. Deterministic across sessions.
            rot = Euler((
                0.37 * bank,
                0.61 * bank,
                1.13 * bank,
            ), 'XYZ').to_matrix()
            banks.append([(rot @ v).normalized() for v in base])

    _SAMPLE_CACHE[key] = banks
    return banks


def stable_bank(index, seed=0):
    h = (int(index) * 73856093) ^ (int(seed) * 19349663)
    return abs(h) % SAMPLE_BANK_COUNT


def orient_hemisphere_sample(local_dir, normal):
    n = normal.normalized()
    helper = Vector((0.0, 0.0, 1.0))
    if abs(n.dot(helper)) > 0.999:
        helper = Vector((0.0, 1.0, 0.0))
    tangent = helper.cross(n).normalized()
    bitangent = n.cross(tangent).normalized()
    return (
        tangent * local_dir.x
        + bitangent * local_dir.y
        + n * local_dir.z
    ).normalized()


def speedtree_style_remap(value, brightness, contrast, min_value, max_value):
    v = ((value + brightness - 0.5) * contrast) + 0.5
    v = clamp01(v)
    lo = min(min_value, max_value)
    hi = max(min_value, max_value)
    return lo + v * (hi - lo)


def axis_index(axis_name):
    return {'X': 0, 'Y': 1, 'Z': 2}.get(axis_name, 2)


def axis_value(v, axis_name):
    return v[axis_index(axis_name)]


def plane_coords(v, axis_name):
    idx = axis_index(axis_name)
    if idx == 0:
        return Vector((v.y, v.z))
    if idx == 1:
        return Vector((v.x, v.z))
    return Vector((v.x, v.y))


# =============================================================================
# Geometry caches
# =============================================================================

@dataclass
class TriangleMeta:
    kind: int
    owner: str
    local_vertices: tuple
    leaf_root: int = -1


@dataclass
class BakeTarget:
    indices: tuple
    position: Vector
    source_vertex: int = -1
    leaf_root: int = -1
    normal: Vector = None
    stable_id: int = 0


@dataclass
class BakeResult:
    colors_by_object: dict
    wind_by_object: dict
    flutter_values: list
    elapsed: float
    warnings: list
    summary: str


def mesh_object_poll(self, obj):
    return obj is not None and obj.type == 'MESH'


def object_world_vertices(obj):
    mw = obj.matrix_world
    return [mw @ v.co for v in obj.data.vertices]


def object_world_normal(obj, vertex, normal_matrix=None):
    if normal_matrix is None:
        normal_matrix = obj.matrix_world.to_3x3().inverted_safe().transposed()
    n = normal_matrix @ vertex.normal
    if n.length_squared < 1e-16:
        return Vector((0.0, 0.0, 1.0))
    return n.normalized()


def compute_leaf_components(mesh):
    count = len(mesh.vertices)
    parent = list(range(count))
    rank = [0] * count

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra = find(a)
        rb = find(b)
        if ra == rb:
            return
        if rank[ra] < rank[rb]:
            parent[ra] = rb
        elif rank[ra] > rank[rb]:
            parent[rb] = ra
        else:
            parent[rb] = ra
            rank[ra] += 1

    for edge in mesh.edges:
        a, b = edge.vertices
        union(a, b)

    roots = [find(i) for i in range(count)]
    islands = defaultdict(list)
    for i, root in enumerate(roots):
        islands[root].append(i)
    return roots, dict(islands)


def build_vertex_adjacency(mesh, world_matrix=None):
    adjacency = [[] for _ in mesh.vertices]
    mw = world_matrix
    for edge in mesh.edges:
        a, b = edge.vertices
        if mw is None:
            pa = mesh.vertices[a].co
            pb = mesh.vertices[b].co
        else:
            pa = mw @ mesh.vertices[a].co
            pb = mw @ mesh.vertices[b].co
        length = max(float((pa - pb).length), 1e-8)
        adjacency[a].append((b, length))
        adjacency[b].append((a, length))
    return adjacency


def compute_tree_bounds(trunk_obj, leaves_obj, up_axis='Z'):
    trunk_points = object_world_vertices(trunk_obj)
    leaf_points = object_world_vertices(leaves_obj)
    points = trunk_points + leaf_points
    if not points:
        raise RuntimeError("Tree objects have no vertices.")

    min_v = Vector((
        min(p.x for p in points),
        min(p.y for p in points),
        min(p.z for p in points),
    ))
    max_v = Vector((
        max(p.x for p in points),
        max(p.y for p in points),
        max(p.z for p in points),
    ))
    size = max_v - min_v
    diagonal = max(size.length, 1e-6)

    base_points = trunk_points if trunk_points else points
    plane = [plane_coords(p, up_axis) for p in base_points]
    axis_plane = Vector((
        (min(p.x for p in plane) + max(p.x for p in plane)) * 0.5,
        (min(p.y for p in plane) + max(p.y for p in plane)) * 0.5,
    ))

    max_radius = 0.0
    for p in points:
        max_radius = max(max_radius, (plane_coords(p, up_axis) - axis_plane).length)

    up_values = [axis_value(p, up_axis) for p in points]
    up_min = min(up_values)
    up_max = max(up_values)
    up_size = max(up_max - up_min, 1e-6)

    # AO should remain local. Canopy depth sees the whole crown.
    auto_ao_radius = max(diagonal * 0.06, max_radius * 0.30)
    auto_canopy_radius = diagonal

    return {
        'min': min_v,
        'max': max_v,
        'size': size,
        'diagonal': diagonal,
        'axis_plane': axis_plane,
        'max_radius': max(max_radius, 1e-6),
        'up_min': up_min,
        'up_max': up_max,
        'up_size': up_size,
        'auto_ao_radius': max(auto_ao_radius, 1e-5),
        'auto_canopy_radius': max(auto_canopy_radius, 1e-5),
        'epsilon': max(diagonal * 1e-5, 1e-6),
    }


def build_tree_bvh(trunk_obj, leaves_obj, leaf_roots):
    all_vertices = []
    triangles = []
    metadata = []

    for obj, kind, owner in (
        (trunk_obj, KIND_WOOD, OWNER_TRUNK),
        (leaves_obj, KIND_LEAF, OWNER_LEAVES),
    ):
        mesh = obj.data
        mesh.calc_loop_triangles()
        base = len(all_vertices)
        mw = obj.matrix_world
        all_vertices.extend(mw @ v.co for v in mesh.vertices)

        for tri in mesh.loop_triangles:
            local_vertices = tuple(int(i) for i in tri.vertices)
            triangles.append(tuple(base + i for i in local_vertices))
            root = -1
            if owner == OWNER_LEAVES and local_vertices:
                root = int(leaf_roots[local_vertices[0]])
            metadata.append(TriangleMeta(
                kind=kind,
                owner=owner,
                local_vertices=local_vertices,
                leaf_root=root,
            ))

    if not triangles:
        raise RuntimeError("No triangles found in Trunk/Leaves objects.")

    bvh = BVHTree.FromPolygons(
        all_vertices,
        triangles,
        all_triangles=True,
        epsilon=0.0,
    )
    return bvh, metadata


def build_object_bvh(obj):
    mesh = obj.data
    mesh.calc_loop_triangles()
    verts = object_world_vertices(obj)
    tris = [tuple(int(i) for i in tri.vertices) for tri in mesh.loop_triangles]
    if not tris:
        return None
    return BVHTree.FromPolygons(verts, tris, all_triangles=True, epsilon=0.0)


# =============================================================================
# Ray tracing / AO
# =============================================================================

def trace_visibility(
    bvh,
    triangle_meta,
    origin,
    direction,
    max_distance,
    leaf_occlusion,
    max_leaf_hits,
    epsilon,
    source_owner,
    source_vertex=-1,
    source_leaf_root=-1,
):
    """Trace transmissive foliage AO while explicitly skipping self geometry."""
    direction = direction.normalized()
    if direction.length_squared < 1e-16:
        return 1.0

    transmission = 1.0
    leaf_hits = 0
    current_origin = origin.copy()
    travelled = 0.0
    remaining = max_distance
    safety_iterations = max_leaf_hits + 32

    for _ in range(safety_iterations):
        if remaining <= epsilon:
            break

        location, _normal, face_index, distance = bvh.ray_cast(
            current_origin,
            direction,
            remaining,
        )
        if face_index is None or location is None or distance is None:
            break

        distance = float(distance)
        if distance <= epsilon * 1.5:
            step = epsilon * 4.0
            current_origin += direction * step
            travelled += step
            remaining = max_distance - travelled
            continue

        meta = triangle_meta[face_index]

        # Robust self-filtering. A leaf island must never darken itself merely
        # because the ray starts on the card. Wood skips incident triangles.
        is_self = False
        if meta.owner == source_owner:
            if source_owner == OWNER_LEAVES and source_leaf_root >= 0:
                is_self = meta.leaf_root == source_leaf_root
            elif source_vertex >= 0:
                is_self = source_vertex in meta.local_vertices

        if is_self:
            current_origin = location + direction * (epsilon * 4.0)
            travelled = max(0.0, (current_origin - origin).dot(direction))
            remaining = max_distance - travelled
            continue

        if meta.kind == KIND_WOOD:
            return 0.0

        transmission *= (1.0 - clamp01(leaf_occlusion))
        leaf_hits += 1
        if transmission <= 0.005 or leaf_hits >= max_leaf_hits:
            return clamp01(transmission)

        current_origin = location + direction * (epsilon * 4.0)
        travelled = max(0.0, (current_origin - origin).dot(direction))
        remaining = max_distance - travelled

    return clamp01(transmission)


def build_leaf_targets(obj, islands, settings, need_normal=False):
    mesh = obj.data
    mw = obj.matrix_world
    normal_matrix = mw.to_3x3().inverted_safe().transposed()
    world_positions = [mw @ v.co for v in mesh.vertices]

    mode = settings.leaf_sampling_mode
    max_island = max(1, settings.leaf_island_max_vertices)
    targets = []

    for root, indices in islands.items():
        use_island = mode == 'ISLAND' or (mode == 'AUTO' and len(indices) <= max_island)
        if use_island:
            center = Vector((0.0, 0.0, 0.0))
            for i in indices:
                center += world_positions[i]
            center /= max(1, len(indices))
            normal = None
            if need_normal:
                n = Vector((0.0, 0.0, 0.0))
                for i in indices:
                    n += object_world_normal(obj, mesh.vertices[i], normal_matrix)
                normal = n.normalized() if n.length_squared > 1e-16 else Vector((0, 0, 1))
            targets.append(BakeTarget(
                indices=tuple(indices),
                position=center,
                source_vertex=-1,
                leaf_root=int(root),
                normal=normal,
                stable_id=int(root),
            ))
        else:
            for i in indices:
                normal = object_world_normal(obj, mesh.vertices[i], normal_matrix) if need_normal else None
                targets.append(BakeTarget(
                    indices=(i,),
                    position=world_positions[i],
                    source_vertex=i,
                    # Per-vertex mode skips only incident triangles. Skipping the
                    # entire connected island would under-occlude large clusters.
                    leaf_root=-1,
                    normal=normal,
                    stable_id=i,
                ))
    return targets


def build_trunk_targets(obj):
    mesh = obj.data
    mw = obj.matrix_world
    normal_matrix = mw.to_3x3().inverted_safe().transposed()
    targets = []
    for i, v in enumerate(mesh.vertices):
        targets.append(BakeTarget(
            indices=(i,),
            position=mw @ v.co,
            source_vertex=i,
            leaf_root=-1,
            normal=object_world_normal(obj, v, normal_matrix),
            stable_id=i,
        ))
    return targets


def topology_smooth(values, adjacency, iterations, strength):
    iterations = max(0, int(iterations))
    strength = clamp01(strength)
    if iterations <= 0 or strength <= 0.0 or not values:
        return values

    current = list(values)
    for _ in range(iterations):
        nxt = list(current)
        for i, neighbors in enumerate(adjacency):
            if not neighbors:
                continue
            avg = sum(current[n] for n, _length in neighbors) / len(neighbors)
            nxt[i] = lerp(current[i], avg, strength)
        current = nxt
    return current


def apply_ground_effect(values, obj, bounds, settings):
    if not settings.ground_effect:
        return values
    distance = settings.ground_distance
    if distance <= 0.0:
        distance = bounds['up_size'] * 0.15
    distance = max(distance, 1e-6)
    floor_value = clamp01(settings.ground_value)
    power = max(settings.ground_power, 0.05)
    mw = obj.matrix_world
    out = list(values)
    for i, v in enumerate(obj.data.vertices):
        p = mw @ v.co
        h = clamp01((axis_value(p, settings.up_axis) - bounds['up_min']) / distance)
        mask = smoothstep01(h) ** power
        ground_limit = lerp(floor_value, 1.0, mask)
        out[i] = min(out[i], ground_limit)
    return out


def compute_ao_generator(
    obj,
    is_leaf,
    targets,
    bvh,
    triangle_meta,
    bounds,
    settings,
):
    radius = settings.ao_radius if settings.ao_radius > 0.0 else bounds['auto_ao_radius']
    epsilon = bounds['epsilon']
    banks = _sample_banks('SPHERE' if is_leaf else 'HEMI', settings.ao_samples)
    owner = OWNER_LEAVES if is_leaf else OWNER_TRUNK
    values = [1.0] * len(obj.data.vertices)

    for target_index, target in enumerate(targets):
        bank = banks[stable_bank(target.stable_id, settings.variation_seed)]
        visibility = 0.0
        for sample in bank:
            if is_leaf:
                direction = sample
                origin = target.position + direction * epsilon
            else:
                direction = orient_hemisphere_sample(sample, target.normal)
                origin = target.position + target.normal * epsilon

            visibility += trace_visibility(
                bvh=bvh,
                triangle_meta=triangle_meta,
                origin=origin,
                direction=direction,
                max_distance=radius,
                leaf_occlusion=settings.leaf_occlusion,
                max_leaf_hits=settings.max_leaf_hits,
                epsilon=epsilon,
                source_owner=owner,
                source_vertex=target.source_vertex,
                source_leaf_root=target.leaf_root,
            )

        raw = visibility / max(1, len(bank))
        baked = speedtree_style_remap(
            raw,
            settings.ao_brightness,
            settings.ao_contrast,
            settings.ao_min,
            settings.ao_max,
        )
        for i in target.indices:
            values[i] = baked
        yield 1

    adjacency = build_vertex_adjacency(obj.data)
    values = topology_smooth(
        values,
        adjacency,
        settings.ao_smooth_iterations,
        settings.ao_smooth_strength,
    )
    values = apply_ground_effect(values, obj, bounds, settings)
    return values


def compute_canopy_generator(
    obj,
    targets,
    bvh,
    triangle_meta,
    bounds,
    settings,
):
    radius = settings.canopy_radius if settings.canopy_radius > 0.0 else bounds['auto_canopy_radius']
    epsilon = bounds['epsilon']
    banks = _sample_banks('SPHERE', settings.canopy_samples)
    values = [0.0] * len(obj.data.vertices)
    bias = clamp01(settings.canopy_bias)
    denom = max(1.0 - bias, 1e-6)
    power = max(settings.canopy_power, 0.01)

    for target in targets:
        bank = banks[stable_bank(target.stable_id, settings.variation_seed + 17)]
        visibility = 0.0
        for direction in bank:
            origin = target.position + direction * epsilon
            visibility += trace_visibility(
                bvh=bvh,
                triangle_meta=triangle_meta,
                origin=origin,
                direction=direction,
                max_distance=radius,
                leaf_occlusion=settings.leaf_occlusion,
                max_leaf_hits=settings.max_leaf_hits,
                epsilon=epsilon,
                source_owner=OWNER_LEAVES,
                source_vertex=target.source_vertex,
                source_leaf_root=target.leaf_root,
            )
        visibility /= max(1, len(bank))
        occ = 1.0 - clamp01(visibility)
        depth = clamp01((occ - bias) / denom) ** power
        for i in target.indices:
            values[i] = clamp01(depth)
        yield 1

    adjacency = build_vertex_adjacency(obj.data)
    values = topology_smooth(
        values,
        adjacency,
        settings.canopy_smooth_iterations,
        settings.canopy_smooth_strength,
    )
    return values


# =============================================================================
# Vertex data / wind
# =============================================================================

def default_colors(count, is_leaf):
    """Compact flat RGBA float buffer: four floats per POINT-domain vertex."""
    b = 0.5 if is_leaf else 0.0
    flat = array('f')
    for _ in range(count):
        flat.extend((1.0, 0.0, b, 0.0))
    return flat


def read_color_attribute(mesh, name, is_leaf, allow_incompatible_default=False):
    attr = mesh.color_attributes.get(name)
    if attr is None:
        return default_colors(len(mesh.vertices), is_leaf)
    if attr.domain != 'POINT' or attr.data_type != 'FLOAT_COLOR':
        if allow_incompatible_default:
            return default_colors(len(mesh.vertices), is_leaf)
        raise RuntimeError(
            f'Color attribute "{name}" on {mesh.name} is {attr.domain}/{attr.data_type}, '
            'expected POINT/FLOAT_COLOR.'
        )

    count = len(mesh.vertices)
    flat = array('f', [0.0]) * (count * 4)
    try:
        attr.data.foreach_get('color', flat)
        return flat
    except Exception:
        flat = array('f')
        for item in attr.data:
            c = item.color
            flat.extend((float(c[0]), float(c[1]), float(c[2]), float(c[3])))
        return flat


def ensure_color_attribute(mesh, name, is_leaf, replace_incompatible=False):
    attr = mesh.color_attributes.get(name)
    if attr is not None and (attr.domain != 'POINT' or attr.data_type != 'FLOAT_COLOR'):
        if not replace_incompatible:
            raise RuntimeError(
                f'Attribute "{name}" exists on {mesh.name} but is not POINT/FLOAT_COLOR. '
                'Enable Replace Incompatible Attribute or rename it.'
            )
        mesh.color_attributes.remove(attr)
        attr = None

    created = attr is None
    if attr is None:
        attr = mesh.color_attributes.new(name=name, type='FLOAT_COLOR', domain='POINT')

    if created:
        write_color_attribute(attr, default_colors(len(mesh.vertices), is_leaf))
    return attr


def write_color_attribute(attr, colors):
    # colors is a compact flat array('f') in RGBA order.
    try:
        attr.data.foreach_set('color', colors)
    except Exception:
        count = len(colors) // 4
        for i in range(count):
            j = i * 4
            attr.data[i].color = (colors[j], colors[j + 1], colors[j + 2], colors[j + 3])


def ensure_float_attribute(mesh, name, default=0.0, replace_incompatible=False):
    attr = mesh.attributes.get(name)
    if attr is not None and (attr.domain != 'POINT' or attr.data_type != 'FLOAT'):
        if not replace_incompatible:
            raise RuntimeError(
                f'Attribute "{name}" exists on {mesh.name} but is not POINT/FLOAT.'
            )
        mesh.attributes.remove(attr)
        attr = None
    if attr is None:
        attr = mesh.attributes.new(name=name, type='FLOAT', domain='POINT')
        write_float_attribute(attr, [default] * len(mesh.vertices))
    return attr


def write_float_attribute(attr, values):
    flat = array('f', (float(v) for v in values))
    try:
        attr.data.foreach_set('value', flat)
    except Exception:
        for i, v in enumerate(values):
            attr.data[i].value = float(v)


def leaf_variation_values(mesh, islands, seed, value_min, value_max):
    lo = min(value_min, value_max)
    hi = max(value_min, value_max)
    result = [0.5] * len(mesh.vertices)
    for root, indices in islands.items():
        local_seed = (int(seed) * 73856093) ^ (int(root) * 19349663)
        rng = random.Random(local_seed)
        value = rng.uniform(lo, hi)
        for i in indices:
            result[i] = value
    return result


def wind_value(world_pos, bounds, settings, is_leaf):
    h = clamp01(
        (axis_value(world_pos, settings.up_axis) - bounds['up_min'])
        / bounds['up_size']
    )
    start = clamp01(settings.wind_start_height)
    if start >= 0.999999:
        h_mask = 0.0
    else:
        h_mask = clamp01((h - start) / (1.0 - start))
    h_mask = smoothstep01(h_mask) ** max(settings.wind_power, 0.01)

    radial = (
        plane_coords(world_pos, settings.up_axis) - bounds['axis_plane']
    ).length / bounds['max_radius']
    radial = clamp01(radial)
    ri = clamp01(settings.wind_radial_influence)
    radial_factor = (1.0 - ri) + radial * ri
    multiplier = 1.0 if is_leaf else clamp01(settings.wind_trunk_multiplier)
    return clamp01(h_mask * radial_factor * multiplier)


def compute_coherent_wind_generator(trunk_obj, leaves_obj, bounds, settings):
    trunk_values = []
    for v in trunk_obj.data.vertices:
        trunk_values.append(wind_value(trunk_obj.matrix_world @ v.co, bounds, settings, False))
        yield 1

    trunk_world = object_world_vertices(trunk_obj)
    kd = KDTree(max(1, len(trunk_world)))
    if trunk_world:
        for i, co in enumerate(trunk_world):
            kd.insert(co, i)
        kd.balance()

    follow = clamp01(settings.wind_leaf_follow)
    leaf_values = []
    for v in leaves_obj.data.vertices:
        p = leaves_obj.matrix_world @ v.co
        own = wind_value(p, bounds, settings, True)
        if trunk_world:
            _co, idx, _dist = kd.find(p)
            wood = trunk_values[idx]
            value = lerp(own, wood, follow)
        else:
            value = own
        leaf_values.append(clamp01(value))
        yield 1

    return trunk_values, leaf_values


def compute_leaf_flutter_generator(trunk_obj, leaves_obj, islands, settings):
    mesh = leaves_obj.data
    count = len(mesh.vertices)
    if count == 0:
        return []

    trunk_bvh = build_object_bvh(trunk_obj)
    if trunk_bvh is None:
        return [1.0] * count

    adjacency = build_vertex_adjacency(mesh, leaves_obj.matrix_world)
    world_positions = object_world_vertices(leaves_obj)
    nearest_dist = [0.0] * count

    for i, p in enumerate(world_positions):
        _loc, _normal, _face, dist = trunk_bvh.find_nearest(p)
        nearest_dist[i] = float(dist) if dist is not None else 1e20
        yield 1

    result = [0.0] * count
    anchor_band = clamp01(settings.leaf_flutter_anchor_band)

    for indices in islands.values():
        if len(indices) <= 1:
            result[indices[0]] = 0.0
            yield 1
            continue

        min_d = min(nearest_dist[i] for i in indices)
        pts = [world_positions[i] for i in indices]
        min_p = Vector((
            min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)
        ))
        max_p = Vector((
            max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)
        ))
        island_diag = max((max_p - min_p).length, 1e-6)
        band = max(island_diag * anchor_band, 1e-6)

        anchors = [i for i in indices if nearest_dist[i] <= min_d + band]
        if not anchors:
            anchors = [min(indices, key=lambda i: nearest_dist[i])]

        allowed = set(indices)
        dist_map = {i: math.inf for i in indices}
        queue = []
        for a in anchors:
            dist_map[a] = 0.0
            heapq.heappush(queue, (0.0, a))

        while queue:
            d, v = heapq.heappop(queue)
            if d != dist_map[v]:
                continue
            for n, edge_len in adjacency[v]:
                if n not in allowed:
                    continue
                nd = d + edge_len
                if nd < dist_map[n]:
                    dist_map[n] = nd
                    heapq.heappush(queue, (nd, n))

        finite = [d for d in dist_map.values() if math.isfinite(d)]
        max_d = max(finite, default=0.0)
        if max_d <= 1e-8:
            for i in indices:
                result[i] = 0.0
        else:
            for i in indices:
                d = dist_map[i]
                t = clamp01(d / max_d) if math.isfinite(d) else 1.0
                result[i] = smoothstep01(t)
        yield 1

    return result


# =============================================================================
# Validation / planning
# =============================================================================

def ensure_tree_id(settings):
    trunk = settings.trunk_object
    leaves = settings.leaves_object
    existing = None
    if trunk is not None:
        existing = trunk.get(TREE_OBJECT_ID)
    if not existing and leaves is not None:
        existing = leaves.get(TREE_OBJECT_ID)
    tree_id = existing or uuid.uuid4().hex[:12]
    if trunk is not None:
        trunk[TREE_OBJECT_ID] = tree_id
    if leaves is not None:
        leaves[TREE_OBJECT_ID] = tree_id
    return tree_id


def validate_settings(context, settings, for_write=True):
    ensure_supported_blender()
    warnings = []
    trunk = settings.trunk_object
    leaves = settings.leaves_object

    if trunk is None:
        raise RuntimeError("Choose a Trunk object.")
    if leaves is None:
        raise RuntimeError("Choose a Leaves object.")
    if trunk.type != 'MESH' or leaves.type != 'MESH':
        raise RuntimeError("Trunk and Leaves must both be Mesh objects.")
    if trunk == leaves:
        raise RuntimeError("Trunk and Leaves must be different objects.")
    if trunk.data == leaves.data:
        raise RuntimeError("Trunk and Leaves share one Mesh datablock. Make them Single User first.")
    if len(trunk.data.vertices) == 0 or len(trunk.data.polygons) == 0:
        raise RuntimeError("Trunk mesh is empty.")
    if len(leaves.data.vertices) == 0 or len(leaves.data.polygons) == 0:
        raise RuntimeError("Leaves mesh is empty.")
    if not settings.attribute_name.strip():
        raise RuntimeError("Output Attribute name cannot be empty.")
    if context.mode != 'OBJECT':
        raise RuntimeError("Switch Blender to Object Mode before baking.")

    for obj in (trunk, leaves):
        if obj.library is not None or obj.data.library is not None:
            message = f"{obj.name} is library-linked/read-only. Make it local first."
            if for_write:
                raise RuntimeError(message)
            warnings.append(message)
        if obj.data.users > 1:
            message = (
                f"{obj.name} mesh has {obj.data.users} users. "
                "Use Make Tree Meshes Single User before baking."
            )
            if for_write:
                raise RuntimeError(message)
            warnings.append(message)

    for obj in (trunk, leaves):
        attr = obj.data.color_attributes.get(settings.attribute_name.strip())
        if attr is not None and (attr.domain != 'POINT' or attr.data_type != 'FLOAT_COLOR'):
            if not settings.replace_incompatible_attribute:
                raise RuntimeError(
                    f'{obj.name}: "{settings.attribute_name.strip()}" exists as '
                    f'{attr.domain}/{attr.data_type}, not POINT/FLOAT_COLOR.'
                )
            warnings.append(f"{obj.name}: incompatible output attribute will be replaced.")

        external_modifiers = [
            m.name for m in obj.modifiers
            if m.show_viewport and not m.get(TREE_MOD_TAG)
        ]
        if external_modifiers:
            warnings.append(
                f"{obj.name}: bake uses base mesh; visible modifiers are ignored: "
                + ", ".join(external_modifiers[:4])
            )

        if any(abs(s - 1.0) > 1e-4 for s in obj.scale):
            warnings.append(f"{obj.name}: unapplied scale is supported because bake runs in world space.")

    return warnings


def estimate_leaf_target_count(islands, settings):
    total = 0
    for indices in islands.values():
        if settings.leaf_sampling_mode == 'VERTEX':
            total += len(indices)
        elif settings.leaf_sampling_mode == 'ISLAND':
            total += 1
        else:
            total += 1 if len(indices) <= settings.leaf_island_max_vertices else len(indices)
    return total


def build_bake_plan(context, channels, for_write=True):
    s = context.scene.tree_vertex_data_settings
    warnings = validate_settings(context, s, for_write=for_write)
    trunk = s.trunk_object
    leaves = s.leaves_object
    leaf_roots, islands = compute_leaf_components(leaves.data)
    trunk_targets = build_trunk_targets(trunk)
    leaf_targets = build_leaf_targets(leaves, islands, s, need_normal=False)
    bounds = compute_tree_bounds(trunk, leaves, s.up_axis)

    work = 0
    if channels & CH_R:
        work += len(trunk_targets) + len(leaf_targets)
    if channels & CH_G:
        work += len(leaf_targets)
    if channels & CH_B:
        work += len(islands)
    if channels & CH_A:
        work += len(trunk.data.vertices) + len(leaves.data.vertices)
        work += len(leaves.data.vertices) + len(islands)

    return {
        'settings': s,
        'trunk': trunk,
        'leaves': leaves,
        'leaf_roots': leaf_roots,
        'islands': islands,
        'trunk_targets': trunk_targets,
        'leaf_targets': leaf_targets,
        'bounds': bounds,
        'work': max(work, 1),
        'warnings': warnings,
    }


# =============================================================================
# Atomic modal bake
# =============================================================================

def bake_job_generator(plan, channels):
    started = time.perf_counter()
    s = plan['settings']
    trunk = plan['trunk']
    leaves = plan['leaves']
    islands = plan['islands']
    bounds = plan['bounds']
    total = plan['work']
    done = 0

    # Read old values only. No datablocks are modified before the final commit.
    colors = {
        trunk: read_color_attribute(
            trunk.data, s.attribute_name.strip(), False, s.replace_incompatible_attribute
        ),
        leaves: read_color_attribute(
            leaves.data, s.attribute_name.strip(), True, s.replace_incompatible_attribute
        ),
    }
    wind_by_object = {}
    flutter_values = []

    bvh, tri_meta = build_tree_bvh(trunk, leaves, plan['leaf_roots'])

    if channels & CH_R:
        gen = compute_ao_generator(
            trunk, False, plan['trunk_targets'], bvh, tri_meta, bounds, s
        )
        while True:
            try:
                step = next(gen)
                done += step
                yield done, total, "Baking R: trunk AO"
            except StopIteration as stop:
                values = stop.value
                break
        for i, value in enumerate(values):
            colors[trunk][i * 4 + 0] = value

        gen = compute_ao_generator(
            leaves, True, plan['leaf_targets'], bvh, tri_meta, bounds, s
        )
        while True:
            try:
                step = next(gen)
                done += step
                yield done, total, "Baking R: foliage AO"
            except StopIteration as stop:
                values = stop.value
                break
        for i, value in enumerate(values):
            colors[leaves][i * 4 + 0] = value

    if channels & CH_G:
        # G is a foliage/crown semantic. Trunk remains explicitly 0.
        for i in range(len(trunk.data.vertices)):
            colors[trunk][i * 4 + 1] = 0.0

        gen = compute_canopy_generator(
            leaves, plan['leaf_targets'], bvh, tri_meta, bounds, s
        )
        while True:
            try:
                step = next(gen)
                done += step
                yield done, total, "Baking G: canopy depth"
            except StopIteration as stop:
                values = stop.value
                break
        for i, value in enumerate(values):
            colors[leaves][i * 4 + 1] = value

    if channels & CH_B:
        variation = leaf_variation_values(
            leaves.data,
            islands,
            s.variation_seed,
            s.variation_min,
            s.variation_max,
        )
        for i in range(len(trunk.data.vertices)):
            colors[trunk][i * 4 + 2] = 0.0
        for root, indices in islands.items():
            for i in indices:
                colors[leaves][i * 4 + 2] = variation[i]
            done += 1
            yield done, total, "Baking B: leaf variation"

    if channels & CH_A:
        gen = compute_coherent_wind_generator(trunk, leaves, bounds, s)
        while True:
            try:
                step = next(gen)
                done += step
                yield done, total, "Baking A: coherent wind mask"
            except StopIteration as stop:
                trunk_wind, leaf_wind = stop.value
                break

        wind_by_object = {trunk: trunk_wind, leaves: leaf_wind}
        for i, value in enumerate(trunk_wind):
            colors[trunk][i * 4 + 3] = value
        for i, value in enumerate(leaf_wind):
            colors[leaves][i * 4 + 3] = value

        gen = compute_leaf_flutter_generator(trunk, leaves, islands, s)
        while True:
            try:
                step = next(gen)
                done += step
                yield done, total, "Building leaf attachment mask"
            except StopIteration as stop:
                flutter_values = stop.value
                break

    elapsed = time.perf_counter() - started
    summary = (
        f"Bake complete: {len(trunk.data.vertices):,} trunk verts, "
        f"{len(leaves.data.vertices):,} leaf verts, {len(islands):,} leaf islands, "
        f"{elapsed:.2f}s"
    )
    return BakeResult(
        colors_by_object=colors,
        wind_by_object=wind_by_object,
        flutter_values=flutter_values,
        elapsed=elapsed,
        warnings=plan['warnings'],
        summary=summary,
    )


def commit_bake_result(s, result):
    trunk = s.trunk_object
    leaves = s.leaves_object
    name = s.attribute_name.strip()

    # Commit is intentionally short. Long calculations happened entirely in RAM.
    for obj, is_leaf in ((trunk, False), (leaves, True)):
        attr = ensure_color_attribute(
            obj.data,
            name,
            is_leaf,
            replace_incompatible=s.replace_incompatible_attribute,
        )
        write_color_attribute(attr, result.colors_by_object[obj])

        if obj in result.wind_by_object:
            wind_attr = ensure_float_attribute(
                obj.data,
                WIND_MASK_ATTRIBUTE,
                0.0,
                replace_incompatible=s.replace_incompatible_attribute,
            )
            write_float_attribute(wind_attr, result.wind_by_object[obj])

        obj.data.update()

    if result.flutter_values:
        flutter = ensure_float_attribute(
            leaves.data,
            LEAF_FLUTTER_ATTRIBUTE,
            0.0,
            replace_incompatible=s.replace_incompatible_attribute,
        )
        write_float_attribute(flutter, result.flutter_values)
        leaves.data.update()


def clear_vertex_data(context):
    s = context.scene.tree_vertex_data_settings
    name = s.attribute_name.strip()
    for obj in (s.trunk_object, s.leaves_object):
        if obj is None or obj.type != 'MESH':
            continue
        attr = obj.data.color_attributes.get(name)
        if attr is not None:
            obj.data.color_attributes.remove(attr)
        wind = obj.data.attributes.get(WIND_MASK_ATTRIBUTE)
        if wind is not None:
            obj.data.attributes.remove(wind)
        if obj == s.leaves_object:
            flutter = obj.data.attributes.get(LEAF_FLUTTER_ATTRIBUTE)
            if flutter is not None:
                obj.data.attributes.remove(flutter)
        obj.data.update()


# =============================================================================
# Materials
# =============================================================================

def safe_node_input(node, name=None, index=None):
    sock = None
    if name is not None and hasattr(node.inputs, 'get'):
        sock = node.inputs.get(name)
    if sock is None and index is not None and 0 <= index < len(node.inputs):
        sock = node.inputs[index]
    return sock


def safe_node_output(node, name=None, index=None):
    sock = None
    if name is not None and hasattr(node.outputs, 'get'):
        sock = node.outputs.get(name)
    if sock is None and index is not None and 0 <= index < len(node.outputs):
        sock = node.outputs[index]
    return sock


def tag_node(node, tag, principled_name):
    node[TREE_NODE_TAG] = tag
    node[TREE_NODE_VERSION] = SCHEMA_VERSION
    node['tree_vdb_principled'] = principled_name


def node_by_tag(nodes, tag, principled_name=None):
    for node in nodes:
        if node.get(TREE_NODE_TAG) != tag:
            continue
        if principled_name is not None and node.get('tree_vdb_principled') != principled_name:
            continue
        return node
    return None


def collect_reachable_principled(material):
    """Only modify Principled nodes that actually feed an active Material Output."""
    if not material.use_nodes or material.node_tree is None:
        return []
    nodes = material.node_tree.nodes
    outputs = [
        n for n in nodes
        if n.bl_idname == 'ShaderNodeOutputMaterial' and getattr(n, 'is_active_output', True)
    ]
    if not outputs:
        return []

    found = []
    visited = set()

    def visit_node(node):
        ptr = node.as_pointer()
        if ptr in visited:
            return
        visited.add(ptr)
        if node.bl_idname == 'ShaderNodeBsdfPrincipled':
            found.append(node)
            return
        for inp in node.inputs:
            for link in inp.links:
                visit_node(link.from_node)

    for out in outputs:
        surf = safe_node_input(out, 'Surface', 0)
        if surf:
            for link in surf.links:
                visit_node(link.from_node)
    return found


def ensure_principled_material_tree(material):
    material.use_nodes = True
    nt = material.node_tree
    nodes = nt.nodes
    links = nt.links
    principled = collect_reachable_principled(material)
    if principled:
        return principled

    outputs = [n for n in nodes if n.bl_idname == 'ShaderNodeOutputMaterial']
    for out in outputs:
        surface = safe_node_input(out, 'Surface', 0)
        if surface is not None and surface.is_linked:
            # Product safety: a custom/group shader we cannot safely inject into
            # is left untouched instead of replacing the user's surface graph.
            log_warning(
                f'Material "{material.name}" has a custom surface graph with no reachable '
                'top-level Principled BSDF; TreeVDB shading was skipped for this material.'
            )
            return []

    bsdf = nodes.new('ShaderNodeBsdfPrincipled')
    bsdf.location = (0, 0)
    out = outputs[0] if outputs else None
    if out is None:
        out = nodes.new('ShaderNodeOutputMaterial')
        out.location = (360, 0)
    links.new(safe_node_output(bsdf, 'BSDF', 0), safe_node_input(out, 'Surface', 0))
    return [bsdf]


def ensure_object_materials(obj, role, tree_id):
    if len(obj.material_slots) == 0:
        mat = bpy.data.materials.new(f"{obj.name}_{role}_Material")
        mat.use_nodes = True
        obj.data.materials.append(mat)

    result = []
    copied = {}
    for slot_index, slot in enumerate(obj.material_slots):
        mat = slot.material
        if mat is None:
            mat = bpy.data.materials.new(f"{obj.name}_{role}_{slot_index:02d}")
            mat.use_nodes = True
            slot.material = mat

        original_ptr = mat.as_pointer()
        if original_ptr in copied:
            slot.material = copied[original_ptr]
            mat = slot.material
        else:
            owner = mat.get(TREE_OWNER_ID)
            managed_role = mat.get(TREE_MATERIAL_ROLE)
            must_copy = (
                mat.library is not None
                or (mat.users > 1 and owner != tree_id)
                or (managed_role not in (None, role))
            )
            if must_copy:
                new_mat = mat.copy()
                new_mat.name = f"{mat.name}_{role}_{tree_id[:6]}"
                slot.material = new_mat
                copied[original_ptr] = new_mat
                mat = new_mat

        mat[TREE_OWNER_ID] = tree_id
        mat[TREE_MATERIAL_ROLE] = role
        if mat not in result:
            result.append(mat)
    return result


def _remove_managed_stack(material, principled):
    """Migrate old TreeVDB stacks while preserving the original albedo source."""
    nt = material.node_tree
    nodes = nt.nodes
    links = nt.links
    pname = principled.name
    base = safe_node_input(principled, 'Base Color', 0)
    if base is None:
        return None, None

    managed = [n for n in nodes if n.get('tree_vdb_principled') == pname and n.get(TREE_NODE_TAG)]
    if not managed:
        return None, tuple(base.default_value)

    final = node_by_tag(nodes, 'surface_final', pname)
    original_source = None
    original_default = tuple(base.default_value)
    if final is not None:
        if final.bl_idname == 'ShaderNodeMixRGB':
            src_input = safe_node_input(final, 'Color1', 1)
        else:
            src_input = safe_node_input(final, 'Vector', 0)
        if src_input is not None:
            if src_input.is_linked and src_input.links:
                original_source = src_input.links[0].from_socket
            elif hasattr(src_input, 'default_value'):
                dv = src_input.default_value
                try:
                    original_default = (dv[0], dv[1], dv[2], 1.0)
                except Exception:
                    pass

    for link in list(base.links):
        if link.from_node in managed:
            links.remove(link)
    for node in managed:
        nodes.remove(node)
    return original_source, original_default


def create_surface_stack(material, principled, role, settings):
    nt = material.node_tree
    nodes = nt.nodes
    links = nt.links
    pname = principled.name
    base = safe_node_input(principled, 'Base Color', 0)
    if base is None:
        return False

    final = node_by_tag(nodes, 'surface_final', pname)
    if final is not None and final.get(TREE_NODE_VERSION) == SCHEMA_VERSION:
        vcol = node_by_tag(nodes, 'surface_attribute', pname)
        if vcol is not None and hasattr(vcol, 'layer_name'):
            vcol.layer_name = settings.attribute_name.strip()
        values = {
            'surface_ao_strength': settings.shader_ao_strength,
            'surface_canopy_strength': settings.shader_canopy_strength,
            'surface_variation_strength': settings.shader_variation_strength if role == 'LEAVES' else 0.0,
        }
        for tag, value in values.items():
            node = node_by_tag(nodes, tag, pname)
            if node is not None:
                out = safe_node_output(node, 'Value', 0)
                if out is not None:
                    out.default_value = float(value)
        return True

    old_source, old_default = _remove_managed_stack(material, principled)
    if old_source is None:
        if base.is_linked and base.links:
            old_source = base.links[0].from_socket
            links.remove(base.links[0])
        elif old_default is None:
            old_default = tuple(base.default_value)

    x0 = principled.location.x - 1120
    y0 = principled.location.y + 120

    vcol = nodes.new('ShaderNodeVertexColor')
    vcol.layer_name = settings.attribute_name.strip()
    vcol.label = 'Tree RGBA'
    vcol.location = (x0, y0 + 280)
    tag_node(vcol, 'surface_attribute', pname)

    sep = nodes.new('ShaderNodeSeparateColor')
    sep.mode = 'RGB'
    sep.location = (x0 + 190, y0 + 280)
    sep.label = 'R AO | G Canopy | B Variation'
    tag_node(sep, 'surface_separate', pname)
    links.new(safe_node_output(vcol, 'Color', 0), safe_node_input(sep, 'Color', 0))

    def value_node(tag, label, value, y):
        n = nodes.new('ShaderNodeValue')
        n.label = label
        n.location = (x0 + 190, y)
        safe_node_output(n, 'Value', 0).default_value = float(value)
        tag_node(n, tag, pname)
        return n

    ao_strength = value_node('surface_ao_strength', 'AO Strength', settings.shader_ao_strength, y0 + 70)
    canopy_strength = value_node('surface_canopy_strength', 'Canopy Shade', settings.shader_canopy_strength, y0 - 40)
    variation_strength = value_node(
        'surface_variation_strength',
        'Variation Strength',
        settings.shader_variation_strength if role == 'LEAVES' else 0.0,
        y0 - 150,
    )

    one_minus_r = nodes.new('ShaderNodeMath')
    one_minus_r.operation = 'SUBTRACT'
    one_minus_r.location = (x0 + 400, y0 + 245)
    safe_node_input(one_minus_r, index=0).default_value = 1.0
    links.new(safe_node_output(sep, 'Red', 0), safe_node_input(one_minus_r, index=1))
    tag_node(one_minus_r, 'surface_math', pname)

    ao_scaled = nodes.new('ShaderNodeMath')
    ao_scaled.operation = 'MULTIPLY'
    ao_scaled.location = (x0 + 570, y0 + 225)
    links.new(safe_node_output(one_minus_r, 'Value', 0), safe_node_input(ao_scaled, index=0))
    links.new(safe_node_output(ao_strength, 'Value', 0), safe_node_input(ao_scaled, index=1))
    tag_node(ao_scaled, 'surface_math', pname)

    ao_factor = nodes.new('ShaderNodeMath')
    ao_factor.operation = 'SUBTRACT'
    ao_factor.location = (x0 + 740, y0 + 210)
    safe_node_input(ao_factor, index=0).default_value = 1.0
    links.new(safe_node_output(ao_scaled, 'Value', 0), safe_node_input(ao_factor, index=1))
    tag_node(ao_factor, 'surface_math', pname)

    canopy_scaled = nodes.new('ShaderNodeMath')
    canopy_scaled.operation = 'MULTIPLY'
    canopy_scaled.location = (x0 + 570, y0 + 70)
    links.new(safe_node_output(sep, 'Green', 1), safe_node_input(canopy_scaled, index=0))
    links.new(safe_node_output(canopy_strength, 'Value', 0), safe_node_input(canopy_scaled, index=1))
    tag_node(canopy_scaled, 'surface_math', pname)

    canopy_factor = nodes.new('ShaderNodeMath')
    canopy_factor.operation = 'SUBTRACT'
    canopy_factor.location = (x0 + 740, y0 + 60)
    safe_node_input(canopy_factor, index=0).default_value = 1.0
    links.new(safe_node_output(canopy_scaled, 'Value', 0), safe_node_input(canopy_factor, index=1))
    tag_node(canopy_factor, 'surface_math', pname)

    b_center = nodes.new('ShaderNodeMath')
    b_center.operation = 'SUBTRACT'
    b_center.location = (x0 + 400, y0 - 80)
    links.new(safe_node_output(sep, 'Blue', 2), safe_node_input(b_center, index=0))
    safe_node_input(b_center, index=1).default_value = 0.5
    tag_node(b_center, 'surface_math', pname)

    b_double = nodes.new('ShaderNodeMath')
    b_double.operation = 'MULTIPLY'
    b_double.location = (x0 + 570, y0 - 80)
    links.new(safe_node_output(b_center, 'Value', 0), safe_node_input(b_double, index=0))
    safe_node_input(b_double, index=1).default_value = 2.0
    tag_node(b_double, 'surface_math', pname)

    b_scaled = nodes.new('ShaderNodeMath')
    b_scaled.operation = 'MULTIPLY'
    b_scaled.location = (x0 + 740, y0 - 80)
    links.new(safe_node_output(b_double, 'Value', 0), safe_node_input(b_scaled, index=0))
    links.new(safe_node_output(variation_strength, 'Value', 0), safe_node_input(b_scaled, index=1))
    tag_node(b_scaled, 'surface_math', pname)

    variation_factor = nodes.new('ShaderNodeMath')
    variation_factor.operation = 'ADD'
    variation_factor.location = (x0 + 900, y0 - 70)
    safe_node_input(variation_factor, index=0).default_value = 1.0
    links.new(safe_node_output(b_scaled, 'Value', 0), safe_node_input(variation_factor, index=1))
    tag_node(variation_factor, 'surface_math', pname)

    factors1 = nodes.new('ShaderNodeMath')
    factors1.operation = 'MULTIPLY'
    factors1.location = (x0 + 900, y0 + 140)
    links.new(safe_node_output(ao_factor, 'Value', 0), safe_node_input(factors1, index=0))
    links.new(safe_node_output(canopy_factor, 'Value', 0), safe_node_input(factors1, index=1))
    tag_node(factors1, 'surface_math', pname)

    factors2 = nodes.new('ShaderNodeMath')
    factors2.operation = 'MULTIPLY'
    factors2.location = (x0 + 1040, y0 + 120)
    links.new(safe_node_output(factors1, 'Value', 0), safe_node_input(factors2, index=0))
    links.new(safe_node_output(variation_factor, 'Value', 0), safe_node_input(factors2, index=1))
    tag_node(factors2, 'surface_math', pname)

    # Blender 5.x deprecates MixRGB. VectorMath SCALE performs Color * scalar
    # without relying on a node scheduled for removal.
    final = nodes.new('ShaderNodeVectorMath')
    final.operation = 'SCALE'
    final.label = 'TreeVDB Albedo × Vertex Data'
    final.location = (principled.location.x - 260, principled.location.y + 40)
    tag_node(final, 'surface_final', pname)

    vector_in = safe_node_input(final, 'Vector', 0)
    if old_source is not None:
        links.new(old_source, vector_in)
    else:
        default = old_default or tuple(base.default_value)
        vector_in.default_value = default[:3]
    links.new(safe_node_output(factors2, 'Value', 0), safe_node_input(final, 'Scale', 3))
    links.new(safe_node_output(final, 'Vector', 0), base)
    return True


def setup_tree_materials(settings):
    tree_id = ensure_tree_id(settings)
    result = []
    for obj, role in ((settings.trunk_object, 'TRUNK'), (settings.leaves_object, 'LEAVES')):
        for mat in ensure_object_materials(obj, role, tree_id):
            for principled in ensure_principled_material_tree(mat):
                create_surface_stack(mat, principled, role, settings)
            result.append(mat.name)
    return result


# =============================================================================
# Geometry Nodes wind preview
# =============================================================================

def normalize_wind_direction(v):
    d = Vector(v)
    if d.length_squared < 1e-10:
        d = Vector((1.0, 0.0, 0.0))
    d.normalize()
    return d


def create_geometry_group_socket(group, name, in_out, socket_type):
    return group.interface.new_socket(name=name, in_out=in_out, socket_type=socket_type)


def clear_group_interface(group):
    # API-safe removal for Blender 4.5/5.2 interface items.
    for item in list(group.interface.items_tree):
        try:
            group.interface.remove(item)
        except Exception:
            pass


def rebuild_wind_node_group(group, is_leaf, settings, tree_id):
    group[TREE_OWNER_ID] = tree_id
    group[TREE_GROUP_ROLE] = 'LEAVES' if is_leaf else 'TRUNK'
    group['tree_vdb_schema'] = SCHEMA_VERSION
    if hasattr(group, 'is_modifier'):
        group.is_modifier = True
    if hasattr(group, 'description'):
        group.description = 'TreeVDB wind preview driven by baked vertex attributes'

    for node in list(group.nodes):
        group.nodes.remove(node)
    clear_group_interface(group)
    create_geometry_group_socket(group, 'Geometry', 'INPUT', 'NodeSocketGeometry')
    create_geometry_group_socket(group, 'Geometry', 'OUTPUT', 'NodeSocketGeometry')

    nodes = group.nodes
    links = group.links

    inp = nodes.new('NodeGroupInput')
    inp.location = (-900, 0)
    out = nodes.new('NodeGroupOutput')
    out.location = (820, 0)

    set_pos = nodes.new('GeometryNodeSetPosition')
    set_pos.location = (590, 0)
    links.new(safe_node_output(inp, 'Geometry', 0), safe_node_input(set_pos, 'Geometry', 0))
    links.new(safe_node_output(set_pos, 'Geometry', 0), safe_node_input(out, 'Geometry', 0))

    color_attr = nodes.new('GeometryNodeInputNamedAttribute')
    color_attr.data_type = 'FLOAT_COLOR'
    color_attr.location = (-900, 340)
    safe_node_input(color_attr, 'Name', 0).default_value = settings.attribute_name.strip()

    sep = nodes.new('FunctionNodeSeparateColor')
    sep.mode = 'RGB'
    sep.location = (-700, 340)
    links.new(safe_node_output(color_attr, 'Attribute', 0), safe_node_input(sep, 'Color', 0))

    wind_attr = nodes.new('GeometryNodeInputNamedAttribute')
    wind_attr.data_type = 'FLOAT'
    wind_attr.location = (-900, 230)
    safe_node_input(wind_attr, 'Name', 0).default_value = WIND_MASK_ATTRIBUTE

    time_node = nodes.new('GeometryNodeInputSceneTime')
    time_node.location = (-900, -220)

    pos = nodes.new('GeometryNodeInputPosition')
    pos.location = (-900, -430)
    pos_sep = nodes.new('ShaderNodeSeparateXYZ')
    pos_sep.location = (-700, -430)
    links.new(safe_node_output(pos, 'Position', 0), safe_node_input(pos_sep, 'Vector', 0))

    time_mul = nodes.new('ShaderNodeMath')
    time_mul.operation = 'MULTIPLY'
    time_mul.location = (-670, -210)
    links.new(safe_node_output(time_node, 'Seconds', 1), safe_node_input(time_mul, index=0))
    safe_node_input(time_mul, index=1).default_value = settings.preview_wind_speed

    spatial = nodes.new('ShaderNodeMath')
    spatial.operation = 'MULTIPLY'
    spatial.location = (-500, -400)
    axis_socket_name = settings.up_axis
    axis_socket_index = {'X': 0, 'Y': 1, 'Z': 2}[settings.up_axis]
    links.new(safe_node_output(pos_sep, axis_socket_name, axis_socket_index), safe_node_input(spatial, index=0))
    safe_node_input(spatial, index=1).default_value = settings.preview_wind_spatial

    phase_add = nodes.new('ShaderNodeMath')
    phase_add.operation = 'ADD'
    phase_add.location = (-320, -220)
    links.new(safe_node_output(time_mul, 'Value', 0), safe_node_input(phase_add, index=0))
    links.new(safe_node_output(spatial, 'Value', 0), safe_node_input(phase_add, index=1))

    wave = nodes.new('ShaderNodeMath')
    wave.operation = 'SINE'
    wave.location = (-150, -210)
    links.new(safe_node_output(phase_add, 'Value', 0), safe_node_input(wave, index=0))

    strength = nodes.new('ShaderNodeMath')
    strength.operation = 'MULTIPLY'
    strength.location = (20, -190)
    links.new(safe_node_output(wave, 'Value', 0), safe_node_input(strength, index=0))
    safe_node_input(strength, index=1).default_value = settings.preview_wind_strength

    masked = nodes.new('ShaderNodeMath')
    masked.operation = 'MULTIPLY'
    masked.location = (190, -150)
    links.new(safe_node_output(strength, 'Value', 0), safe_node_input(masked, index=0))
    links.new(safe_node_output(wind_attr, 'Attribute', 0), safe_node_input(masked, index=1))

    direction = normalize_wind_direction(settings.preview_wind_direction)
    direction_node = nodes.new('ShaderNodeCombineXYZ')
    direction_node.location = (10, -360)
    safe_node_input(direction_node, 'X', 0).default_value = direction.x
    safe_node_input(direction_node, 'Y', 1).default_value = direction.y
    safe_node_input(direction_node, 'Z', 2).default_value = direction.z

    main_offset = nodes.new('ShaderNodeVectorMath')
    main_offset.operation = 'SCALE'
    main_offset.location = (360, -140)
    links.new(safe_node_output(direction_node, 'Vector', 0), safe_node_input(main_offset, 'Vector', 0))
    links.new(safe_node_output(masked, 'Value', 0), safe_node_input(main_offset, 'Scale', 3))
    final_offset = safe_node_output(main_offset, 'Vector', 0)

    if is_leaf:
        flutter_attr = nodes.new('GeometryNodeInputNamedAttribute')
        flutter_attr.data_type = 'FLOAT'
        flutter_attr.location = (-900, 120)
        safe_node_input(flutter_attr, 'Name', 0).default_value = LEAF_FLUTTER_ATTRIBUTE

        ft = nodes.new('ShaderNodeMath')
        ft.operation = 'MULTIPLY'
        ft.location = (-500, 40)
        links.new(safe_node_output(time_node, 'Seconds', 1), safe_node_input(ft, index=0))
        safe_node_input(ft, index=1).default_value = settings.preview_flutter_speed

        phase_b = nodes.new('ShaderNodeMath')
        phase_b.operation = 'MULTIPLY'
        phase_b.location = (-500, 160)
        links.new(safe_node_output(sep, 'Blue', 2), safe_node_input(phase_b, index=0))
        safe_node_input(phase_b, index=1).default_value = math.tau

        phase = nodes.new('ShaderNodeMath')
        phase.operation = 'ADD'
        phase.location = (-310, 70)
        links.new(safe_node_output(ft, 'Value', 0), safe_node_input(phase, index=0))
        links.new(safe_node_output(phase_b, 'Value', 0), safe_node_input(phase, index=1))

        fwave = nodes.new('ShaderNodeMath')
        fwave.operation = 'SINE'
        fwave.location = (-130, 70)
        links.new(safe_node_output(phase, 'Value', 0), safe_node_input(fwave, index=0))

        fstrength = nodes.new('ShaderNodeMath')
        fstrength.operation = 'MULTIPLY'
        fstrength.location = (40, 70)
        links.new(safe_node_output(fwave, 'Value', 0), safe_node_input(fstrength, index=0))
        safe_node_input(fstrength, index=1).default_value = settings.preview_flutter_strength

        fmask = nodes.new('ShaderNodeMath')
        fmask.operation = 'MULTIPLY'
        fmask.location = (210, 80)
        links.new(safe_node_output(fstrength, 'Value', 0), safe_node_input(fmask, index=0))
        links.new(safe_node_output(flutter_attr, 'Attribute', 0), safe_node_input(fmask, index=1))

        fd = Vector((-direction.y, direction.x, 0.25))
        if fd.length_squared < 1e-10:
            fd = Vector((0.0, 1.0, 0.25))
        fd.normalize()
        fdir = nodes.new('ShaderNodeCombineXYZ')
        fdir.location = (40, -20)
        safe_node_input(fdir, 'X', 0).default_value = fd.x
        safe_node_input(fdir, 'Y', 1).default_value = fd.y
        safe_node_input(fdir, 'Z', 2).default_value = fd.z

        foffset = nodes.new('ShaderNodeVectorMath')
        foffset.operation = 'SCALE'
        foffset.location = (380, 70)
        links.new(safe_node_output(fdir, 'Vector', 0), safe_node_input(foffset, 'Vector', 0))
        links.new(safe_node_output(fmask, 'Value', 0), safe_node_input(foffset, 'Scale', 3))

        add = nodes.new('ShaderNodeVectorMath')
        add.operation = 'ADD'
        add.location = (520, -80)
        links.new(safe_node_output(main_offset, 'Vector', 0), safe_node_input(add, index=0))
        links.new(safe_node_output(foffset, 'Vector', 0), safe_node_input(add, index=1))
        final_offset = safe_node_output(add, 'Vector', 0)

    links.new(final_offset, safe_node_input(set_pos, 'Offset', 3))


def ensure_wind_group(base_name, is_leaf, settings, tree_id):
    name = f"{base_name}::{tree_id}"
    group = bpy.data.node_groups.get(name)
    if group is None or group.bl_idname != 'GeometryNodeTree':
        if group is not None:
            name = f"{name}_v{SCHEMA_VERSION}"
        group = bpy.data.node_groups.new(name, 'GeometryNodeTree')
    elif group.get(TREE_OWNER_ID) not in (None, tree_id):
        group = bpy.data.node_groups.new(f"{name}_v{SCHEMA_VERSION}", 'GeometryNodeTree')

    rebuild_wind_node_group(group, is_leaf, settings, tree_id)
    return group


def ensure_wind_modifier(obj, group, tree_id, role):
    managed = None
    for mod in obj.modifiers:
        if mod.type == 'NODES' and mod.get(TREE_MOD_TAG) == tree_id and mod.get(TREE_GROUP_ROLE) == role:
            managed = mod
            break

    if managed is None:
        legacy = obj.modifiers.get(TREE_WIND_MODIFIER)
        if (
            legacy is not None
            and legacy.type == 'NODES'
            and legacy.node_group is not None
            and legacy.node_group.name.startswith('TreeVDB_Wind_')
        ):
            managed = legacy
        else:
            managed = obj.modifiers.new(TREE_WIND_MODIFIER, 'NODES')

    managed[TREE_MOD_TAG] = tree_id
    managed[TREE_GROUP_ROLE] = role
    managed.node_group = group
    managed.show_viewport = True
    managed.show_render = True
    return managed


def setup_tree_wind_preview(settings):
    tree_id = ensure_tree_id(settings)
    trunk_group = ensure_wind_group(TREE_GN_TRUNK, False, settings, tree_id)
    leaves_group = ensure_wind_group(TREE_GN_LEAVES, True, settings, tree_id)
    ensure_wind_modifier(settings.trunk_object, trunk_group, tree_id, 'TRUNK')
    ensure_wind_modifier(settings.leaves_object, leaves_group, tree_id, 'LEAVES')


def sync_wind_preview_attributes(settings):
    name = settings.attribute_name.strip()
    for obj, is_leaf in ((settings.trunk_object, False), (settings.leaves_object, True)):
        colors = read_color_attribute(obj.data, name, is_leaf)
        values = [colors[i * 4 + 3] for i in range(len(obj.data.vertices))]
        attr = ensure_float_attribute(
            obj.data,
            WIND_MASK_ATTRIBUTE,
            0.0,
            replace_incompatible=settings.replace_incompatible_attribute,
        )
        write_float_attribute(attr, values)
        obj.data.update()


def ensure_flutter_attribute(settings):
    _roots, islands = compute_leaf_components(settings.leaves_object.data)
    gen = compute_leaf_flutter_generator(
        settings.trunk_object,
        settings.leaves_object,
        islands,
        settings,
    )
    while True:
        try:
            next(gen)
        except StopIteration as stop:
            values = stop.value
            break
    attr = ensure_float_attribute(
        settings.leaves_object.data,
        LEAF_FLUTTER_ATTRIBUTE,
        0.0,
        replace_incompatible=settings.replace_incompatible_attribute,
    )
    write_float_attribute(attr, values)
    settings.leaves_object.data.update()


# =============================================================================
# Settings
# =============================================================================

def quality_update(self, context):
    presets = {
        'PREVIEW': (12, 8),
        'MEDIUM': (32, 20),
        'HIGH': (64, 40),
        'ULTRA': (128, 80),
    }
    if self.quality_preset in presets:
        self.ao_samples, self.canopy_samples = presets[self.quality_preset]


class TREEVDB_Settings(PropertyGroup):
    trunk_object: PointerProperty(
        name="Trunk / Branches",
        description="Wood mesh containing the trunk and branches",
        type=bpy.types.Object,
        poll=mesh_object_poll,
    )
    leaves_object: PointerProperty(
        name="Leaves",
        description="Foliage mesh; disconnected cards/islands are detected automatically",
        type=bpy.types.Object,
        poll=mesh_object_poll,
    )
    attribute_name: StringProperty(
        name="Output Attribute",
        description="POINT/FLOAT_COLOR attribute: R AO, G Canopy, B Variation, A Wind",
        default=ATTRIBUTE_DEFAULT,
    )
    up_axis: EnumProperty(
        name="Up Axis",
        items=(('X', 'X', ''), ('Y', 'Y', ''), ('Z', 'Z', '')),
        default='Z',
    )

    quality_preset: EnumProperty(
        name="Quality",
        items=(
            ('PREVIEW', 'Preview', 'Fast test bake'),
            ('MEDIUM', 'Medium', 'Working quality'),
            ('HIGH', 'High', 'Recommended final quality'),
            ('ULTRA', 'Ultra', 'Slow high-sample bake'),
            ('CUSTOM', 'Custom', 'Keep manual sample counts'),
        ),
        default='HIGH',
        update=quality_update,
    )

    leaf_sampling_mode: EnumProperty(
        name="Leaf Sampling",
        items=(
            ('AUTO', 'Auto', 'One ray target for small leaf islands; per-vertex for large islands'),
            ('VERTEX', 'Per Vertex', 'Maximum fidelity, slowest'),
            ('ISLAND', 'Per Island', 'One value per disconnected foliage island, fastest'),
        ),
        default='AUTO',
    )
    leaf_island_max_vertices: IntProperty(
        name="Auto Island Max",
        description="In Auto mode, islands up to this vertex count use one AO/Canopy sample target",
        default=8,
        min=3,
        max=128,
    )

    # R AO
    ao_samples: IntProperty(name="Samples", default=64, min=4, max=512)
    ao_radius: FloatProperty(
        name="Radius",
        description="0 = automatic local radius",
        default=0.0,
        min=0.0,
        subtype='DISTANCE',
    )
    leaf_occlusion: FloatProperty(
        name="Leaf Occlusion",
        description="Opacity proxy per foliage-card hit; several hits accumulate",
        default=0.35,
        min=0.0,
        max=1.0,
        subtype='FACTOR',
    )
    max_leaf_hits: IntProperty(name="Max Leaf Hits", default=8, min=1, max=64)
    ao_brightness: FloatProperty(name="Brightness", default=0.5, min=0.0, max=1.0)
    ao_contrast: FloatProperty(name="Contrast", default=1.0, min=0.0, max=4.0)
    ao_min: FloatProperty(name="Min", default=0.20, min=0.0, max=1.0)
    ao_max: FloatProperty(name="Max", default=1.0, min=0.0, max=1.0)
    ao_smooth_iterations: IntProperty(name="Smooth Iterations", default=1, min=0, max=8)
    ao_smooth_strength: FloatProperty(name="Smooth Strength", default=0.12, min=0.0, max=1.0)

    ground_effect: BoolProperty(name="Ground Effect", default=False)
    ground_value: FloatProperty(name="Ground Min", default=0.45, min=0.0, max=1.0)
    ground_distance: FloatProperty(
        name="Ground Distance",
        description="0 = 15% of tree height",
        default=0.0,
        min=0.0,
        subtype='DISTANCE',
    )
    ground_power: FloatProperty(name="Ground Falloff", default=1.0, min=0.05, max=8.0)

    # G canopy
    canopy_samples: IntProperty(name="Samples", default=40, min=4, max=512)
    canopy_radius: FloatProperty(
        name="Radius",
        description="0 = full tree diagonal",
        default=0.0,
        min=0.0,
        subtype='DISTANCE',
    )
    canopy_bias: FloatProperty(name="Outer Bias", default=0.12, min=0.0, max=0.95)
    canopy_power: FloatProperty(name="Depth Power", default=1.25, min=0.1, max=8.0)
    canopy_smooth_iterations: IntProperty(name="Smooth Iterations", default=1, min=0, max=8)
    canopy_smooth_strength: FloatProperty(name="Smooth Strength", default=0.10, min=0.0, max=1.0)

    # B variation
    variation_seed: IntProperty(name="Seed", default=1337, min=0, max=2147483647)
    variation_min: FloatProperty(name="Min", default=0.15, min=0.0, max=1.0)
    variation_max: FloatProperty(name="Max", default=0.85, min=0.0, max=1.0)

    # A wind
    wind_start_height: FloatProperty(name="Root Lock", default=0.05, min=0.0, max=0.95)
    wind_power: FloatProperty(name="Height Power", default=1.35, min=0.05, max=8.0)
    wind_radial_influence: FloatProperty(name="Radial Influence", default=0.30, min=0.0, max=1.0)
    wind_trunk_multiplier: FloatProperty(name="Trunk Multiplier", default=1.0, min=0.0, max=1.0)
    wind_leaf_follow: FloatProperty(
        name="Branch Follow",
        description="How strongly leaves inherit wind weight from nearest branch/trunk vertex",
        default=0.85,
        min=0.0,
        max=1.0,
    )
    leaf_flutter_anchor_band: FloatProperty(
        name="Leaf Anchor Band",
        description="Region closest to wood locked against secondary leaf flutter",
        default=0.18,
        min=0.0,
        max=0.49,
    )

    # Material
    shader_ao_strength: FloatProperty(name="AO Strength", default=1.0, min=0.0, max=2.0)
    shader_canopy_strength: FloatProperty(name="Canopy Shade", default=0.30, min=0.0, max=1.0)
    shader_variation_strength: FloatProperty(name="Leaf Variation", default=0.08, min=0.0, max=0.5)

    # Preview
    preview_wind_strength: FloatProperty(
        name="Sway Strength", default=0.12, min=0.0, soft_max=2.0, subtype='DISTANCE'
    )
    preview_wind_speed: FloatProperty(name="Sway Speed", default=1.2, min=0.0, soft_max=10.0)
    preview_wind_spatial: FloatProperty(name="Spatial Phase", default=0.65, min=0.0, soft_max=10.0)
    preview_wind_direction: FloatVectorProperty(
        name="Wind Direction", default=(1.0, 0.25, 0.0), size=3, subtype='DIRECTION'
    )
    preview_flutter_strength: FloatProperty(
        name="Leaf Flutter", default=0.035, min=0.0, soft_max=0.5, subtype='DISTANCE'
    )
    preview_flutter_speed: FloatProperty(name="Flutter Speed", default=4.0, min=0.0, soft_max=20.0)

    # Safety / runtime
    replace_incompatible_attribute: BoolProperty(
        name="Replace Incompatible Attribute",
        description="Allow TreeVDB to replace an existing attribute with the same name but wrong type",
        default=False,
    )
    modal_budget_ms: IntProperty(
        name="UI Budget",
        description="Approximate milliseconds of bake work per UI timer tick",
        default=12,
        min=2,
        max=100,
    )
    show_advanced: BoolProperty(name="Advanced", default=False)
    show_materials: BoolProperty(name="Materials & Wind Preview", default=True)

    bake_running: BoolProperty(default=False, options={'SKIP_SAVE'})
    bake_cancel_requested: BoolProperty(default=False, options={'SKIP_SAVE'})
    bake_progress: FloatProperty(default=0.0, min=0.0, max=1.0, options={'SKIP_SAVE'})
    bake_status: StringProperty(default="Ready", options={'SKIP_SAVE'})
    last_status: StringProperty(default="", options={'SKIP_SAVE'})
    last_warning_count: IntProperty(default=0, options={'SKIP_SAVE'})


# =============================================================================
# Operators
# =============================================================================

class TREEVDB_OT_Bake(Operator):
    bl_idname = "tree_vdb.bake"
    bl_label = "Bake Tree Vertex Data"
    bl_description = "Modal, cancellable and atomic bake of the selected RGBA channels"
    bl_options = {'REGISTER', 'UNDO'}

    channel: EnumProperty(
        name="Channel",
        items=(
            ('ALL', 'All RGBA', ''),
            ('R', 'R - AO', ''),
            ('G', 'G - Canopy', ''),
            ('B', 'B - Variation', ''),
            ('A', 'A - Wind', ''),
        ),
        default='ALL',
    )

    _timer = None
    _generator = None
    _started = 0.0
    _settings = None

    def _cleanup(self, context):
        s = self._settings or context.scene.tree_vertex_data_settings
        if self._timer is not None:
            try:
                context.window_manager.event_timer_remove(self._timer)
            except Exception:
                pass
            self._timer = None
        context.window_manager.progress_end()
        s.bake_running = False
        s.bake_cancel_requested = False

    def _start(self, context):
        s = context.scene.tree_vertex_data_settings
        if s.bake_running:
            self.report({'WARNING'}, "A TreeVDB bake is already running.")
            return {'CANCELLED'}

        mapping = {'ALL': CH_ALL, 'R': CH_R, 'G': CH_G, 'B': CH_B, 'A': CH_A}
        try:
            # Build once and pass the immutable object/target plan into the job.
            plan = build_bake_plan(context, mapping[self.channel], for_write=True)
            self._settings = s
            self._generator = bake_job_generator(plan, mapping[self.channel])
        except Exception as exc:
            s.last_status = f"Validation failed: {exc}"
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}

        self._started = time.perf_counter()
        s.bake_running = True
        s.bake_cancel_requested = False
        s.bake_progress = 0.0
        s.bake_status = "Starting bake…"
        s.last_status = ""
        s.last_warning_count = 0

        wm = context.window_manager
        wm.progress_begin(0, 1000)
        self._timer = wm.event_timer_add(0.01, window=context.window)
        wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _redirect_from_tool_window(self, context, operator_context):
        """Run the real modal bake in a normal Blender window.

        A user may close the floating tool from its OS title bar, which Blender
        does not expose as a cancellable Python event.  Keeping the modal
        handler and event timer in the main window means the atomic bake stays
        alive and cancellable even if the UI window disappears.
        """
        if not _is_tree_vdb_tool_window(context.window):
            return None

        window, area, region = _find_main_animation_context(context)
        if window is None or area is None:
            self.report({'ERROR'}, 'No normal Blender window is available to host the bake.')
            return {'CANCELLED'}

        kwargs = {'window': window, 'area': area}
        if region is not None:
            kwargs['region'] = region
        try:
            with context.temp_override(**kwargs):
                result = bpy.ops.tree_vdb.bake(operator_context, channel=self.channel)
        except Exception as exc:
            self.report({'ERROR'}, f'Could not start bake in the main window: {exc}')
            return {'CANCELLED'}

        if 'CANCELLED' in result:
            return {'CANCELLED'}
        # This wrapper instance must not become modal; the redirected operator
        # owns the modal handler in the normal Blender window.
        return {'FINISHED'}

    def invoke(self, context, event):
        redirected = self._redirect_from_tool_window(context, 'INVOKE_DEFAULT')
        if redirected is not None:
            return redirected
        return self._start(context)

    def execute(self, context):
        redirected = self._redirect_from_tool_window(context, 'INVOKE_DEFAULT')
        if redirected is not None:
            return redirected
        return self._start(context)

    def modal(self, context, event):
        s = self._settings or context.scene.tree_vertex_data_settings

        if event.type == 'ESC' or s.bake_cancel_requested:
            if self._generator is not None:
                try:
                    self._generator.close()
                except Exception:
                    pass
            elapsed = time.perf_counter() - self._started
            s.bake_status = "Cancelled"
            s.last_status = f"Bake cancelled after {elapsed:.2f}s. No vertex data was changed."
            self._cleanup(context)
            self.report({'WARNING'}, "TreeVDB bake cancelled; no partial result was committed.")
            return {'CANCELLED'}

        if event.type != 'TIMER':
            return {'PASS_THROUGH'}

        deadline = time.perf_counter() + (max(2, s.modal_budget_ms) / 1000.0)
        try:
            while time.perf_counter() < deadline:
                done, total, status = next(self._generator)
                progress = clamp01(done / max(total, 1))
                s.bake_progress = progress
                _tag_tree_tool_redraw()
                s.bake_status = status
                context.window_manager.progress_update(int(progress * 1000))
        except StopIteration as stop:
            result = stop.value
            try:
                commit_bake_result(s, result)
            except Exception as exc:
                s.bake_status = "Commit failed"
                s.last_status = f"Commit failed: {exc}"
                self._cleanup(context)
                self.report({'ERROR'}, f"Bake calculated but could not commit data: {exc}")
                return {'CANCELLED'}

            s.bake_progress = 1.0
            _tag_tree_tool_redraw()
            s.bake_status = "Complete"
            s.last_status = result.summary
            s.last_warning_count = len(result.warnings)
            for warning in result.warnings:
                log_warning(warning)
            self._cleanup(context)
            self.report({'INFO'}, result.summary)
            return {'FINISHED'}
        except Exception as exc:
            s.bake_status = "Failed"
            s.last_status = f"Bake failed: {exc}"
            self._cleanup(context)
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}

        return {'RUNNING_MODAL'}

    def cancel(self, context):
        if self._generator is not None:
            try:
                self._generator.close()
            except Exception:
                pass
        self._cleanup(context)


class TREEVDB_OT_CancelBake(Operator):
    bl_idname = "tree_vdb.cancel_bake"
    bl_label = "Cancel Bake"
    bl_description = "Request a safe cancellation of the active TreeVDB bake"

    def execute(self, context):
        s = context.scene.tree_vertex_data_settings
        if not s.bake_running:
            self.report({'INFO'}, "No TreeVDB bake is running.")
            return {'CANCELLED'}
        s.bake_cancel_requested = True
        s.bake_status = "Cancelling…"
        return {'FINISHED'}


class TREEVDB_OT_Validate(Operator):
    bl_idname = "tree_vdb.validate"
    bl_label = "Validate Tree"
    bl_description = "Validate objects, attributes and estimate the bake workload"

    def execute(self, context):
        s = context.scene.tree_vertex_data_settings
        try:
            plan = build_bake_plan(context, CH_ALL, for_write=False)
            leaf_targets = len(plan['leaf_targets'])
            primary_rays = (
                len(plan['trunk_targets']) * s.ao_samples
                + leaf_targets * s.ao_samples
                + leaf_targets * s.canopy_samples
            )
            s.last_warning_count = len(plan['warnings'])
            s.last_status = (
                f"Valid: trunk {len(plan['trunk'].data.vertices):,} verts, "
                f"leaves {len(plan['leaves'].data.vertices):,} verts, "
                f"{len(plan['islands']):,} islands, {leaf_targets:,} leaf ray targets, "
                f"~{primary_rays:,} primary rays. "
                f"Auto R radius {plan['bounds']['auto_ao_radius']:.3f}, "
                f"Auto G radius {plan['bounds']['auto_canopy_radius']:.3f}."
            )
            for warning in plan['warnings']:
                log_warning(warning)
            self.report({'INFO'}, "Tree validation passed.")
            return {'FINISHED'}
        except Exception as exc:
            s.last_status = f"Validation failed: {exc}"
            s.last_warning_count = 0
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}


class TREEVDB_OT_MakeSingleUser(Operator):
    bl_idname = "tree_vdb.make_single_user"
    bl_label = "Make Tree Meshes Single User"
    bl_description = "Copy shared Trunk/Leaves mesh datablocks so baking cannot affect other objects"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        s = context.scene.tree_vertex_data_settings
        if s.bake_running:
            self.report({'WARNING'}, "Cancel the current bake first.")
            return {'CANCELLED'}
        changed = []
        for obj in (s.trunk_object, s.leaves_object):
            if obj is not None and obj.type == 'MESH' and obj.data.users > 1:
                obj.data = obj.data.copy()
                changed.append(obj.name)
        if changed:
            self.report({'INFO'}, "Made single-user: " + ", ".join(changed))
        else:
            self.report({'INFO'}, "Tree meshes were already single-user.")
        return {'FINISHED'}


class TREEVDB_OT_Clear(Operator):
    bl_idname = "tree_vdb.clear"
    bl_label = "Clear Vertex Data"
    bl_description = "Remove TreeVDB output and internal preview attributes"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        s = context.scene.tree_vertex_data_settings
        if s.bake_running:
            self.report({'WARNING'}, "Cancel the current bake first.")
            return {'CANCELLED'}
        clear_vertex_data(context)
        s.last_status = "TreeVDB vertex attributes removed."
        self.report({'INFO'}, s.last_status)
        return {'FINISHED'}


class TREEVDB_OT_SetupShadersWind(Operator):
    bl_idname = "tree_vdb.setup_shaders_wind"
    bl_label = "Create / Update Materials + Wind"
    bl_description = "Non-destructively augment current albedo materials and create Geometry Nodes wind preview"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        s = context.scene.tree_vertex_data_settings
        if s.bake_running:
            self.report({'WARNING'}, "Cancel the current bake first.")
            return {'CANCELLED'}
        try:
            validate_settings(context, s, for_write=True)
            ensure_color_attribute(
                s.trunk_object.data, s.attribute_name.strip(), False, s.replace_incompatible_attribute
            )
            ensure_color_attribute(
                s.leaves_object.data, s.attribute_name.strip(), True, s.replace_incompatible_attribute
            )
            sync_wind_preview_attributes(s)
            ensure_flutter_attribute(s)
            mats = setup_tree_materials(s)
            setup_tree_wind_preview(s)
            s.last_status = f"Updated {len(mats)} material(s) and wind preview."
            self.report({'INFO'}, s.last_status)
            return {'FINISHED'}
        except Exception as exc:
            s.last_status = f"Material/wind setup failed: {exc}"
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}


class TREEVDB_OT_PlayAnimation(Operator):
    bl_idname = "tree_vdb.play_animation"
    bl_label = "Play"
    bl_description = "Start timeline playback for wind preview"

    def execute(self, context):
        window, area, region = _find_main_animation_context(context)
        if window is None:
            self.report({'ERROR'}, "No normal Blender window is available for playback.")
            return {'CANCELLED'}
        kwargs = {'window': window, 'area': area}
        if region is not None:
            kwargs['region'] = region
        try:
            with context.temp_override(**kwargs):
                if not window.screen.is_animation_playing:
                    bpy.ops.screen.animation_play()
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, f"Could not start playback: {exc}")
            return {'CANCELLED'}


class TREEVDB_OT_StopAnimation(Operator):
    bl_idname = "tree_vdb.stop_animation"
    bl_label = "Stop"
    bl_description = "Stop timeline playback at the current frame"

    def execute(self, context):
        window, area, region = _find_main_animation_context(context)
        if window is None:
            self.report({'ERROR'}, "No normal Blender window is available for playback.")
            return {'CANCELLED'}
        kwargs = {'window': window, 'area': area}
        if region is not None:
            kwargs['region'] = region
        try:
            with context.temp_override(**kwargs):
                if window.screen.is_animation_playing:
                    bpy.ops.screen.animation_cancel(restore_frame=False)
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, f"Could not stop playback: {exc}")
            return {'CANCELLED'}


class TREEVDB_OT_ResetDefaults(Operator):
    bl_idname = "tree_vdb.reset_defaults"
    bl_label = "Reset Bake Defaults"
    bl_description = "Reset the main TreeVDB bake and preview settings"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        s = context.scene.tree_vertex_data_settings
        if s.bake_running:
            self.report({'WARNING'}, "Cancel the current bake first.")
            return {'CANCELLED'}
        props = (
            'quality_preset', 'leaf_sampling_mode', 'leaf_island_max_vertices',
            'ao_radius', 'leaf_occlusion', 'max_leaf_hits', 'ao_brightness',
            'ao_contrast', 'ao_min', 'ao_max', 'ao_smooth_iterations',
            'ao_smooth_strength', 'ground_effect', 'ground_value', 'ground_distance',
            'ground_power', 'canopy_radius', 'canopy_bias', 'canopy_power',
            'canopy_smooth_iterations', 'canopy_smooth_strength', 'variation_seed',
            'variation_min', 'variation_max', 'wind_start_height', 'wind_power',
            'wind_radial_influence', 'wind_trunk_multiplier', 'wind_leaf_follow',
            'leaf_flutter_anchor_band', 'shader_ao_strength', 'shader_canopy_strength',
            'shader_variation_strength', 'preview_wind_strength', 'preview_wind_speed',
            'preview_wind_spatial', 'preview_wind_direction', 'preview_flutter_strength',
            'preview_flutter_speed', 'modal_budget_ms',
        )
        for prop in props:
            try:
                s.property_unset(prop)
            except Exception:
                pass
        s.last_status = "TreeVDB settings reset to defaults."
        return {'FINISHED'}


# =============================================================================
# UI
# =============================================================================

# One colour per baked channel, used by the legend, the per-channel panels and the
# bake buttons alike, so the window teaches the mapping once instead of four times.
#
# Blender's built-in `COLOR_RED`/`COLOR_GREEN`/`COLOR_BLUE` icons are letter glyphs,
# but they are monochrome: the theme tints every ordinary icon one colour, so an R
# drawn with them comes out the same grey as everything else. Real colour needs a
# preview icon, whose pixels are used as-is - so the swatches below are generated
# once and handed to the layout as `icon_value`.
CHANNEL_COLORS = {
    'R': (0.94, 0.33, 0.31),
    'G': (0.45, 0.83, 0.40),
    'B': (0.36, 0.60, 0.96),
    'A': (0.88, 0.88, 0.90),
}

CHANNEL_LABELS = (
    ('R', 'AO'),
    ('G', 'Depth'),
    ('B', 'Variation'),
    ('A', 'Wind'),
)

# Spelled out in each channel panel's header. R, G and B read as Red/Green/Blue on
# sight; A does not, and a grey dot beside "Wind Mask" says nothing about the data
# actually landing in the attribute's alpha component.
CHANNEL_NAMES = {
    'R': 'Red',
    'G': 'Green',
    'B': 'Blue',
    'A': 'Alpha',
}

CHANNEL_SWATCH_SIZE = 16

_channel_previews = None


def _channel_icon(channel):
    """`icon_value` of a filled dot in this channel's colour, built on first use."""
    global _channel_previews
    if _channel_previews is None:
        import bpy.utils.previews

        _channel_previews = bpy.utils.previews.new()

    if channel not in _channel_previews:
        size = CHANNEL_SWATCH_SIZE
        red, green, blue = CHANNEL_COLORS[channel]
        center = (size - 1) * 0.5
        radius = size * 0.34
        pixels = []
        # Preview pixels run bottom-up, like an image. The dot is drawn straight into
        # them with a one-pixel soft edge, which is all it takes not to look jagged
        # next to Blender's own icons.
        for y in range(size):
            for x in range(size):
                distance = math.hypot(x - center, y - center)
                alpha = clamp01(radius - distance + 0.5)
                pixels.extend((red, green, blue, alpha))
        preview = _channel_previews.new(channel)
        preview.icon_size = (size, size)
        preview.icon_pixels_float = pixels

    return _channel_previews[channel].icon_id


def _channel_previews_free():
    global _channel_previews
    if _channel_previews is not None:
        bpy.utils.previews.remove(_channel_previews)
        _channel_previews = None


def _draw_channel_header_name(panel, channel):
    """Name the target channel at the right edge of a channel panel's header."""
    row = panel.layout.row(align=True)
    row.active = False
    row.label(text=CHANNEL_NAMES[channel])


def _draw_pair(layout, s, prop_a, text_a, prop_b, text_b):
    """Two controls sharing one line, each carrying its own inline label.

    With `use_property_split` on, every property reserves a label column of its own,
    so a second one on the same line is left with almost no width and its label is cut
    down to "Radi..." or "Anc...". Switching the split off for the row moves each label
    inside its own widget, left aligned, where the two split the line evenly and the
    words fit.
    """
    row = layout.row(align=True)
    row.use_property_split = False
    row.prop(s, prop_a, text=text_a)
    row.prop(s, prop_b, text=text_b)


def _panel_body(panel, context):
    """Layout and settings every TreeVDB panel starts from.

    Greying the whole body while a bake runs is done here rather than in each
    function, so a new panel cannot forget it and become the one place the user
    can still change a value mid-bake.
    """
    s = context.scene.tree_vertex_data_settings
    layout = panel.layout
    layout.use_property_split = True
    layout.use_property_decorate = False
    layout.enabled = not s.bake_running
    return layout, s


def _draw_status_body(layout, s):
    if s.bake_running:
        row = layout.row(align=True)
        row.prop(s, 'bake_progress', text=s.bake_status or 'Baking', slider=True)
        row.operator('tree_vdb.cancel_bake', text='Cancel', icon='CANCEL')
        return

    failed = bool(s.last_status) and (
        'failed' in s.last_status.lower() or 'error' in s.last_status.lower()
    )

    if failed:
        icon = 'ERROR'
    elif s.last_warning_count:
        icon = 'ERROR'
    else:
        icon = 'CHECKMARK'

    label = s.last_status if s.last_status else 'Ready'
    # Long status strings make narrow panels unusable. Full detail remains in reports/console.
    if len(label) > 62:
        label = label[:59] + '\u2026'

    row = layout.row(align=True)
    # `alert` paints the row red, which says "this needs attention" before the text is
    # read at all - the difference between a status line and a status line that works.
    row.alert = failed
    row.label(text=label, icon=icon)

    # Named, and on its own line. As a bare tick pinned next to the status it was two
    # contradictory marks in one row - a red cross reporting failure beside a green
    # check that looked like it disagreed, when it was in fact the button that re-runs
    # the check. Nothing about an icon-only button said either what it did or that it
    # was a button at all.
    row = layout.row(align=True)
    row.operator(
        'tree_vdb.validate',
        text='Re-check Setup' if s.last_status else 'Check Setup',
        icon='VIEWZOOM',
    )


def _draw_tree_body(layout, s):
    layout.prop(s, 'trunk_object', text='Trunk')
    layout.prop(s, 'leaves_object', text='Leaves')

    # Channel legend. Four equal cells rather than one packed string, so each colour
    # sits directly above the column of controls and buttons that writes it.
    legend = layout.row(align=True)
    legend.use_property_split = False
    for channel, channel_text in CHANNEL_LABELS:
        legend.label(text='{:s}  {:s}'.format(channel, channel_text),
                     icon_value=_channel_icon(channel))


def _draw_tree_output_body(layout, s):
    layout.prop(s, 'attribute_name', text='Attribute')
    layout.prop(s, 'up_axis', text='Up Axis')
    layout.operator(
        'tree_vdb.make_single_user', text='Make Tree Meshes Single User', icon='DUPLICATE'
    )


def _draw_bake_body(layout, s):
    row = layout.row(align=True)
    row.prop(s, 'quality_preset', text='Quality')
    if s.quality_preset == 'CUSTOM':
        row.label(text='Custom samples', icon='INFO')

    row = layout.row()
    row.scale_y = 1.35
    op = row.operator('tree_vdb.bake', text='BAKE ALL RGBA', icon='RENDER_STILL')
    op.channel = 'ALL'

    # Same four colours as the legend and the per-channel panels, in the same order.
    row = layout.row(align=True)
    for channel, channel_text in CHANNEL_LABELS:
        op = row.operator('tree_vdb.bake', text=channel_text,
                          icon_value=_channel_icon(channel))
        op.channel = channel


def _draw_ao_body(layout, s):
    _draw_pair(layout, s, 'ao_samples', 'Samples', 'ao_radius', 'Radius')
    layout.prop(s, 'leaf_occlusion', text='Leaf Occlusion')
    _draw_pair(layout, s, 'ao_brightness', 'Brightness', 'ao_contrast', 'Contrast')
    _draw_pair(layout, s, 'ao_min', 'Min', 'ao_max', 'Max')


def _draw_canopy_body(layout, s):
    _draw_pair(layout, s, 'canopy_samples', 'Samples', 'canopy_radius', 'Radius')
    _draw_pair(layout, s, 'canopy_bias', 'Outer Bias', 'canopy_power', 'Depth Power')


def _draw_variation_body(layout, s):
    layout.prop(s, 'variation_seed', text='Seed')
    _draw_pair(layout, s, 'variation_min', 'Min', 'variation_max', 'Max')


def _draw_wind_body(layout, s):
    _draw_pair(layout, s, 'wind_start_height', 'Root Lock', 'wind_power', 'Height Power')
    _draw_pair(layout, s, 'wind_radial_influence', 'Radial',
               'wind_trunk_multiplier', 'Trunk')
    _draw_pair(layout, s, 'wind_leaf_follow', 'Branch Follow',
               'leaf_flutter_anchor_band', 'Anchor Band')


def _draw_preview_body(layout, s):
    # Setup is the primary action; put it before tuning.
    row = layout.row()
    row.scale_y = 1.15
    row.operator(
        'tree_vdb.setup_shaders_wind',
        text='CREATE / UPDATE PREVIEW',
        icon='NODE_MATERIAL',
    )

    row = layout.row(align=True)
    row.operator('tree_vdb.play_animation', text='Play', icon='PLAY')
    row.operator('tree_vdb.stop_animation', text='Stop', icon='PAUSE')


def _draw_preview_shading_body(layout, s):
    layout.prop(s, 'shader_ao_strength', text='AO')
    layout.prop(s, 'shader_canopy_strength', text='Canopy')
    layout.prop(s, 'shader_variation_strength', text='Variation')


def _draw_preview_motion_body(layout, s):
    _draw_pair(layout, s, 'preview_wind_strength', 'Sway',
               'preview_wind_speed', 'Speed')
    layout.prop(s, 'preview_wind_spatial', text='Spatial Phase')
    layout.prop(s, 'preview_wind_direction', text='Direction')
    _draw_pair(layout, s, 'preview_flutter_strength', 'Flutter',
               'preview_flutter_speed', 'Speed')


def _draw_advanced_body(layout, s):
    layout.prop(s, 'leaf_sampling_mode', text='Leaf Sampling')
    if s.leaf_sampling_mode == 'AUTO':
        layout.prop(s, 'leaf_island_max_vertices', text='Auto Island Max')
    layout.prop(s, 'max_leaf_hits', text='Max Leaf Hits')

    layout.prop(s, 'ground_effect')
    if s.ground_effect:
        _draw_pair(layout, s, 'ground_value', 'Ground Min',
                   'ground_distance', 'Distance')
        layout.prop(s, 'ground_power', text='Falloff')

    layout.prop(s, 'replace_incompatible_attribute')
    layout.prop(s, 'modal_budget_ms', text='UI Budget (ms)')

    row = layout.row(align=True)
    row.operator('tree_vdb.reset_defaults', text='Reset Defaults', icon='LOOP_BACK')
    row.operator('tree_vdb.clear', text='Clear Attributes', icon='TRASH')


def _draw_advanced_smoothing_body(layout, s):
    _draw_pair(layout, s, 'ao_smooth_iterations', 'AO Iter',
               'ao_smooth_strength', 'AO Strength')
    _draw_pair(layout, s, 'canopy_smooth_iterations', 'Depth Iter',
               'canopy_smooth_strength', 'Depth Strength')


class TreeVDBToolWindow(ScriptToolWindow):
    """TreeVDB's window declaration.

    All actual window lifecycle/discovery belongs to the universal
    bpy_extras.script_tool.ScriptToolWindow API provided by the fork.
    """

    tool_id = TREE_TOOL_CONTEXT
    title = TREE_TOOL_TITLE
    default_width = TREE_TOOL_WIDTH
    default_height = TREE_TOOL_HEIGHT
    default_instance_id = TREE_TOOL_INSTANCE


class TREEVDB_OT_CloseToolWindow(Operator):
    bl_idname = "tree_vdb.close_tool_window"
    bl_label = "Close Tree Vertex Data Baker"
    bl_description = "Close the TreeVDB Script Tool window"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        s = context.scene.tree_vertex_data_settings

        if s.bake_running:
            s.bake_cancel_requested = True
            s.bake_status = "Cancelling before close…"
            self.report(
                {"WARNING"},
                "Bake cancellation requested. Close the window after it stops.",
            )
            return {"CANCELLED"}

        try:
            TreeVDBToolWindow.close()
        except Exception as exc:
            self.report({"ERROR"}, f"Could not close TreeVDB window: {exc}")
            return {"CANCELLED"}

        return {"FINISHED"}


def _is_script_tool_window(window):
    """True for any universal Script Tool host window."""
    if window is None or window.screen is None:
        return False

    return any(area.type == "SCRIPT_TOOL" for area in window.screen.areas)


def _find_main_animation_context(context):
    """Find a regular Blender editor for modal bake/playback operations.

    The dedicated TreeVDB utility window is UI-only and should not become the
    execution context for viewport/timeline operators.
    """
    for window in context.window_manager.windows:
        if _is_script_tool_window(window) or window.screen is None:
            continue

        area = next(
            (area for area in window.screen.areas if area.type == "VIEW_3D"),
            None,
        )

        if area is None and window.screen.areas:
            area = window.screen.areas[0]

        if area is None:
            continue

        region = next(
            (region for region in area.regions if region.type == "WINDOW"),
            None,
        )
        return window, area, region

    return None, None, None


def _tag_tree_tool_redraw():
    """Redraw only TreeVDB Script Tool instances."""
    try:
        for window, area, space in TreeVDBToolWindow._iter_spaces():
            area.tag_redraw()
    except Exception:
        # Redraw is an optimization. It must never break a bake operation.
        pass


class TREEVDB_OT_ShowUI(Operator):
    bl_idname = "tree_vdb.show_ui"
    bl_label = "Tree Vertex Data Baker"
    bl_description = "Open or focus the TreeVDB Script Tool window"
    bl_options = {"REGISTER"}

    def execute(self, context):
        try:
            TreeVDBToolWindow.show()
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        return {"FINISHED"}


# Every section is a registered Panel rather than a `layout.panel()` sub-panel of one
# big one. Only a real Panel is drawn by the region's panel system, which is what
# gives it the boxed background, the drag handle and the collapse behaviour the
# Properties editor has; layout sub-panels nest flat inside their parent instead.
# `bl_order` fixes the sequence, since registration order does not.


class _TreeVDBPanelMixin:
    """Shared panel identity. Not a `Panel` itself, so it is never registered."""

    bl_label = ''


@TreeVDBToolWindow.panel
class TREEVDB_PT_status(_TreeVDBPanelMixin, Panel):
    bl_idname = 'TREEVDB_PT_status'
    bl_label = 'Status'
    # Headerless: the status line is the panel, and a header above one row would be
    # taller than the thing it labels.
    bl_options = {'HIDE_HEADER'}
    bl_order = 0

    def draw(self, context):
        s = context.scene.tree_vertex_data_settings
        # Deliberately not greyed while baking: this is the panel that reports the bake
        # and carries the button that cancels it.
        _draw_status_body(self.layout, s)


@TreeVDBToolWindow.panel
class TREEVDB_PT_tree(_TreeVDBPanelMixin, Panel):
    bl_idname = 'TREEVDB_PT_tree'
    bl_label = 'Tree'
    bl_order = 1

    def draw_header(self, context):
        self.layout.label(text='', icon='OUTLINER_OB_MESH')

    def draw(self, context):
        _draw_tree_body(*_panel_body(self, context))


@TreeVDBToolWindow.panel
class TREEVDB_PT_tree_output(_TreeVDBPanelMixin, Panel):
    bl_idname = 'TREEVDB_PT_tree_output'
    bl_parent_id = 'TREEVDB_PT_tree'
    bl_label = 'Output Settings'
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        _draw_tree_output_body(*_panel_body(self, context))


@TreeVDBToolWindow.panel
class TREEVDB_PT_bake(_TreeVDBPanelMixin, Panel):
    bl_idname = 'TREEVDB_PT_bake'
    bl_label = 'Bake'
    bl_order = 2

    def draw_header(self, context):
        self.layout.label(text='', icon='RENDER_STILL')

    def draw(self, context):
        _draw_bake_body(*_panel_body(self, context))


@TreeVDBToolWindow.panel
class TREEVDB_PT_ao(_TreeVDBPanelMixin, Panel):
    bl_idname = 'TREEVDB_PT_ao'
    bl_label = 'Ambient Occlusion'
    bl_options = {'DEFAULT_CLOSED'}
    bl_order = 3

    def draw_header(self, context):
        self.layout.label(text='', icon_value=_channel_icon('R'))

    def draw_header_preset(self, context):
        _draw_channel_header_name(self, 'R')

    def draw(self, context):
        _draw_ao_body(*_panel_body(self, context))


@TreeVDBToolWindow.panel
class TREEVDB_PT_canopy(_TreeVDBPanelMixin, Panel):
    bl_idname = 'TREEVDB_PT_canopy'
    bl_label = 'Canopy Depth'
    bl_options = {'DEFAULT_CLOSED'}
    bl_order = 4

    def draw_header(self, context):
        self.layout.label(text='', icon_value=_channel_icon('G'))

    def draw_header_preset(self, context):
        _draw_channel_header_name(self, 'G')

    def draw(self, context):
        _draw_canopy_body(*_panel_body(self, context))


@TreeVDBToolWindow.panel
class TREEVDB_PT_variation(_TreeVDBPanelMixin, Panel):
    bl_idname = 'TREEVDB_PT_variation'
    bl_label = 'Leaf Variation'
    bl_options = {'DEFAULT_CLOSED'}
    bl_order = 5

    def draw_header(self, context):
        self.layout.label(text='', icon_value=_channel_icon('B'))

    def draw_header_preset(self, context):
        _draw_channel_header_name(self, 'B')

    def draw(self, context):
        _draw_variation_body(*_panel_body(self, context))


@TreeVDBToolWindow.panel
class TREEVDB_PT_wind(_TreeVDBPanelMixin, Panel):
    bl_idname = 'TREEVDB_PT_wind'
    bl_label = 'Wind Mask'
    bl_options = {'DEFAULT_CLOSED'}
    bl_order = 6

    def draw_header(self, context):
        self.layout.label(text='', icon_value=_channel_icon('A'))

    def draw_header_preset(self, context):
        _draw_channel_header_name(self, 'A')

    def draw(self, context):
        _draw_wind_body(*_panel_body(self, context))


@TreeVDBToolWindow.panel
class TREEVDB_PT_preview(_TreeVDBPanelMixin, Panel):
    bl_idname = 'TREEVDB_PT_preview'
    bl_label = 'Material & Wind Preview'
    bl_options = {'DEFAULT_CLOSED'}
    bl_order = 7

    def draw_header(self, context):
        self.layout.label(text='', icon='NODE_MATERIAL')

    def draw(self, context):
        _draw_preview_body(*_panel_body(self, context))


@TreeVDBToolWindow.panel
class TREEVDB_PT_preview_shading(_TreeVDBPanelMixin, Panel):
    bl_idname = 'TREEVDB_PT_preview_shading'
    bl_parent_id = 'TREEVDB_PT_preview'
    bl_label = 'Shading'
    bl_options = {'DEFAULT_CLOSED'}
    bl_order = 0

    def draw(self, context):
        _draw_preview_shading_body(*_panel_body(self, context))


@TreeVDBToolWindow.panel
class TREEVDB_PT_preview_motion(_TreeVDBPanelMixin, Panel):
    bl_idname = 'TREEVDB_PT_preview_motion'
    bl_parent_id = 'TREEVDB_PT_preview'
    bl_label = 'Motion'
    bl_options = {'DEFAULT_CLOSED'}
    bl_order = 1

    def draw(self, context):
        _draw_preview_motion_body(*_panel_body(self, context))


@TreeVDBToolWindow.panel
class TREEVDB_PT_advanced(_TreeVDBPanelMixin, Panel):
    bl_idname = 'TREEVDB_PT_advanced'
    bl_label = 'Advanced'
    bl_options = {'DEFAULT_CLOSED'}
    bl_order = 8

    def draw_header(self, context):
        self.layout.label(text='', icon='PREFERENCES')

    def draw(self, context):
        _draw_advanced_body(*_panel_body(self, context))


@TreeVDBToolWindow.panel
class TREEVDB_PT_advanced_smoothing(_TreeVDBPanelMixin, Panel):
    bl_idname = 'TREEVDB_PT_advanced_smoothing'
    bl_parent_id = 'TREEVDB_PT_advanced'
    bl_label = 'Smoothing'
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        _draw_advanced_smoothing_body(*_panel_body(self, context))


# =============================================================================
# Registration
# =============================================================================

classes = (
    TREEVDB_Settings,
    TREEVDB_OT_Bake,
    TREEVDB_OT_CancelBake,
    TREEVDB_OT_Validate,
    TREEVDB_OT_MakeSingleUser,
    TREEVDB_OT_Clear,
    TREEVDB_OT_SetupShadersWind,
    TREEVDB_OT_PlayAnimation,
    TREEVDB_OT_StopAnimation,
    TREEVDB_OT_ResetDefaults,
    TREEVDB_OT_CloseToolWindow,
    TREEVDB_OT_ShowUI,
)


def unregister_existing_by_name():
    """Development-safe cleanup for Text Editor Run Script iterations."""

    # A reload rebuilds the module, so this call frees the previous module object's
    # swatches while its global still points at them.
    try:
        _channel_previews_free()
    except Exception:
        pass

    # Close a previous TreeVDB instance if the universal API is already present.
    try:
        if hasattr(bpy.ops.wm, "script_tool_window_close"):
            bpy.ops.wm.script_tool_window_close(
                tool_id=TREE_TOOL_CONTEXT,
                instance_id=TREE_TOOL_INSTANCE,
            )
    except Exception:
        pass

    if hasattr(bpy.types.Scene, "tree_vertex_data_settings"):
        try:
            del bpy.types.Scene.tree_vertex_data_settings
        except Exception:
            pass

    # Cleanup names from earlier TreeVDB UI generations only. The panels this version
    # registers are handled by `ScriptToolWindow.register(hot_reload=True)`; these are
    # names nothing refers to any more, so they can only be reached through `bpy.types`.
    # `TREEVDB_PT_Floating` was the single all-in-one panel that the per-section panels
    # replaced - left registered it would keep drawing the whole UI a second time.
    for name in (
        "TREEVDB_OT_HideSidebar",
        "TREEVDB_PT_Launcher",
        "TREEVDB_PT_Floating",
    ):
        old_cls = getattr(bpy.types, name, None)
        if old_cls is not None:
            try:
                bpy.utils.unregister_class(old_cls)
            except Exception:
                pass

    for cls in reversed(classes):
        old_cls = getattr(bpy.types, cls.__name__, None)
        if old_cls is not None and old_cls is not cls:
            try:
                bpy.utils.unregister_class(old_cls)
            except Exception:
                pass


def register():
    ensure_supported_blender()
    unregister_existing_by_name()

    # Settings/operators first. The Script Tool panel depends on the Scene
    # PropertyGroup being available when Blender first draws the new window.
    for cls in classes:
        try:
            bpy.utils.register_class(cls)
        except ValueError:
            pass

    bpy.types.Scene.tree_vertex_data_settings = PointerProperty(
        type=TREEVDB_Settings
    )

    # This is the only TreeVDB-specific window integration now.
    # Everything else is handled by the universal ScriptToolWindow API.
    TreeVDBToolWindow.register(hot_reload=True)

    log_info(
        f"Registered on Blender {_version_string(bpy.app.version)} "
        f"using ScriptToolWindow API"
    )


def unregister():
    # Facade owns its panel registration and every window instance.
    try:
        TreeVDBToolWindow.unregister(close_windows=True)
    except Exception:
        pass

    # The channel swatches are a preview collection, which Blender does not own and
    # will not reclaim: dropped without this, every reload leaks another set.
    try:
        _channel_previews_free()
    except Exception:
        pass

    if hasattr(bpy.types.Scene, "tree_vertex_data_settings"):
        del bpy.types.Scene.tree_vertex_data_settings

    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass


if __name__ == "__main__":
    try:
        register()
        TreeVDBToolWindow.show()
        print("[TreeVDB] Script Tool window ready.")
    except Exception:
        import traceback
        print("[TreeVDB][ERROR] Failed to start TreeVDB")
        traceback.print_exc()
        raise

