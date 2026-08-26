bl_info = {
    "name": "Tree Vertex Data Baker",
    "author": "OpenAI",
    "version": (4, 2, 0),
    "blender": (5, 2, 0),
    "location": "Script Tool Window",
    "description": "Bake shader-compatible RGB tree vertex data and preview material shading",
    "category": "Object",
}

import bpy
import gpu
import math
import heapq
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass
from array import array

from mathutils import Vector, Euler
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
from gpu_extras.batch import batch_for_shader
from clarity_proxy_log import (
    CLARITY_PROXY_LOG_PATH,
    clarity_proxy_log,
    clarity_proxy_log_reset,
)
from clarity_foliage_normals import (
    CLARITY_NORMAL_BACKUP,
    clarity_build_foliage_proxy_generator,
    clarity_delete_foliage_proxy,
    clarity_restore_foliage_normals,
    clarity_transfer_foliage_normals_generator,
)


# =============================================================================
# Constants / schema
# =============================================================================

ADDON_VERSION = (4, 2, 0)
MIN_BLENDER_VERSION = (5, 2, 0)
SCHEMA_VERSION = 6

ATTRIBUTE_DEFAULT = "TreeVertexData"
LEAF_FLUTTER_ATTRIBUTE = "TreeLeafFlutter"
LEGACY_WIND_MASK_ATTRIBUTE = "TreeWindMask"
CLARITY_FLUTTER_PHASE_ATTRIBUTE = "clarity_leaf_flutter_phase"
CLARITY_FLUTTER_DIRECTION_ATTRIBUTE = "clarity_leaf_flutter_direction"
CLARITY_FLUTTER_SCALE_ATTRIBUTE = "clarity_leaf_flutter_scale"
CLARITY_DEBUG_ATTRIBUTE = "clarity_debug_vertex_channel"
CLARITY_DEBUG_PREVIOUS_COLOR = "clarity_debug_previous_active_color"
CLARITY_NORMAL_DEBUG_HANDLER_KEY = "clarity_tree_normal_debug_handler"

TREE_NODE_TAG = "tree_vdb_node"
TREE_NODE_VERSION = "tree_vdb_node_version"
TREE_MATERIAL_ROLE = "tree_vdb_role"
TREE_OWNER_ID = "tree_vdb_owner"
TREE_OBJECT_ID = "tree_vdb_tree_id"
CLARITY_SOURCE_MATERIAL = "clarity_source_material"
CLARITY_SOURCE_MATERIAL_EMPTY = "clarity_source_material_was_empty"

TREE_WIND_MODIFIER = "TreeVDB Wind Preview"

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
CH_ALL = CH_R | CH_G | CH_B

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
    if hi - lo <= 1e-6:
        return v
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
    flutter_values: list
    flutter_phase_values: list
    flutter_direction_values: list
    flutter_scale_values: list
    elapsed: float
    warnings: list
    summary: str


@dataclass
class ClarityLeafAttachment:
    root: int
    indices: tuple
    anchor_vertex: int
    closest_point: Vector
    triangle_index: int
    triangle_vertices: tuple
    barycentric: Vector
    distance: float


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


def _clarity_virtual_position_pairs(clarity_positions, clarity_epsilon):
    if clarity_epsilon <= 0.0:
        return []
    clarity_inverse = 1.0 / clarity_epsilon
    clarity_buckets = defaultdict(list)
    clarity_pairs = []
    for clarity_index, clarity_position in enumerate(clarity_positions):
        clarity_cell = tuple(
            math.floor(clarity_position[clarity_axis] * clarity_inverse)
            for clarity_axis in range(3)
        )
        for clarity_dx in (-1, 0, 1):
            for clarity_dy in (-1, 0, 1):
                for clarity_dz in (-1, 0, 1):
                    clarity_neighbor = (
                        clarity_cell[0] + clarity_dx,
                        clarity_cell[1] + clarity_dy,
                        clarity_cell[2] + clarity_dz,
                    )
                    for clarity_other in clarity_buckets.get(clarity_neighbor, ()):
                        if (
                            clarity_position - clarity_positions[clarity_other]
                        ).length <= clarity_epsilon:
                            clarity_pairs.append((clarity_other, clarity_index))
        clarity_buckets[clarity_cell].append(clarity_index)
    return clarity_pairs


def compute_leaf_components(mesh, world_matrix=None, merge_epsilon=0.0):
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

    if merge_epsilon > 0.0:
        clarity_positions = [
            world_matrix @ clarity_vertex.co if world_matrix is not None else clarity_vertex.co.copy()
            for clarity_vertex in mesh.vertices
        ]
        for clarity_a, clarity_b in _clarity_virtual_position_pairs(
                clarity_positions, merge_epsilon):
            union(clarity_a, clarity_b)

    roots = [find(i) for i in range(count)]
    islands = defaultdict(list)
    for i, root in enumerate(roots):
        islands[root].append(i)
    return roots, dict(islands)


def build_vertex_adjacency(mesh, world_matrix=None, virtual_epsilon=0.0):
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
    if virtual_epsilon > 0.0:
        clarity_positions = [
            world_matrix @ clarity_vertex.co if world_matrix is not None else clarity_vertex.co.copy()
            for clarity_vertex in mesh.vertices
        ]
        for clarity_a, clarity_b in _clarity_virtual_position_pairs(
                clarity_positions, virtual_epsilon):
            clarity_length = max(
                float((clarity_positions[clarity_a] - clarity_positions[clarity_b]).length),
                1e-8,
            )
            adjacency[clarity_a].append((clarity_b, clarity_length))
            adjacency[clarity_b].append((clarity_a, clarity_length))
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


def _clarity_barycentric_coordinates(clarity_point, clarity_a, clarity_b, clarity_c):
    clarity_v0 = clarity_b - clarity_a
    clarity_v1 = clarity_c - clarity_a
    clarity_v2 = clarity_point - clarity_a
    clarity_d00 = clarity_v0.dot(clarity_v0)
    clarity_d01 = clarity_v0.dot(clarity_v1)
    clarity_d11 = clarity_v1.dot(clarity_v1)
    clarity_d20 = clarity_v2.dot(clarity_v0)
    clarity_d21 = clarity_v2.dot(clarity_v1)
    clarity_denominator = clarity_d00 * clarity_d11 - clarity_d01 * clarity_d01
    if abs(clarity_denominator) <= 1e-20:
        return Vector((1.0, 0.0, 0.0))
    clarity_v = (
        clarity_d11 * clarity_d20 - clarity_d01 * clarity_d21
    ) / clarity_denominator
    clarity_w = (
        clarity_d00 * clarity_d21 - clarity_d01 * clarity_d20
    ) / clarity_denominator
    return Vector((1.0 - clarity_v - clarity_w, clarity_v, clarity_w))


def build_leaf_attachments(trunk_obj, leaves_obj, islands):
    clarity_trunk_mesh = trunk_obj.data
    clarity_trunk_mesh.calc_loop_triangles()
    clarity_trunk_vertices = object_world_vertices(trunk_obj)
    clarity_trunk_triangles = [
        tuple(int(clarity_index) for clarity_index in clarity_triangle.vertices)
        for clarity_triangle in clarity_trunk_mesh.loop_triangles
    ]
    if not clarity_trunk_triangles:
        raise RuntimeError("Trunk mesh has no triangles for foliage attachment.")
    clarity_bvh = BVHTree.FromPolygons(
        clarity_trunk_vertices,
        clarity_trunk_triangles,
        all_triangles=True,
        epsilon=0.0,
    )
    clarity_leaf_positions = object_world_vertices(leaves_obj)
    clarity_distances = [math.inf] * len(clarity_leaf_positions)
    clarity_hits = [None] * len(clarity_leaf_positions)
    for clarity_index, clarity_position in enumerate(clarity_leaf_positions):
        clarity_location, _clarity_normal, clarity_face, clarity_distance = (
            clarity_bvh.find_nearest(clarity_position)
        )
        if clarity_location is None or clarity_face is None:
            continue
        clarity_distances[clarity_index] = float(clarity_distance)
        clarity_hits[clarity_index] = (clarity_location.copy(), int(clarity_face))

    clarity_attachments = {}
    for clarity_root, clarity_indices in islands.items():
        clarity_anchor = min(
            clarity_indices,
            key=lambda clarity_index: clarity_distances[clarity_index],
        )
        clarity_hit = clarity_hits[clarity_anchor]
        if clarity_hit is None:
            clarity_attachments[clarity_root] = ClarityLeafAttachment(
                root=int(clarity_root),
                indices=tuple(clarity_indices),
                anchor_vertex=int(clarity_anchor),
                closest_point=clarity_leaf_positions[clarity_anchor].copy(),
                triangle_index=-1,
                triangle_vertices=(),
                barycentric=Vector((1.0, 0.0, 0.0)),
                distance=math.inf,
            )
            continue
        clarity_point, clarity_triangle_index = clarity_hit
        clarity_triangle = clarity_trunk_triangles[clarity_triangle_index]
        clarity_barycentric = _clarity_barycentric_coordinates(
            clarity_point,
            clarity_trunk_vertices[clarity_triangle[0]],
            clarity_trunk_vertices[clarity_triangle[1]],
            clarity_trunk_vertices[clarity_triangle[2]],
        )
        clarity_attachments[clarity_root] = ClarityLeafAttachment(
            root=int(clarity_root),
            indices=tuple(clarity_indices),
            anchor_vertex=int(clarity_anchor),
            closest_point=clarity_point,
            triangle_index=clarity_triangle_index,
            triangle_vertices=clarity_triangle,
            barycentric=clarity_barycentric,
            distance=clarity_distances[clarity_anchor],
        )
    return clarity_attachments, clarity_distances


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
    """Compact RGB + opaque alpha buffer: four floats per POINT-domain vertex."""
    b = 0.5 if is_leaf else 0.0
    flat = array('f')
    for _ in range(count):
        flat.extend((1.0, 1.0, b, 1.0))
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


def clarity_debug_range_values(clarity_settings, clarity_channel):
    if clarity_channel == 'OFF':
        return 0.0, 1.0
    clarity_component = {'R': 0, 'G': 1, 'B': 2}.get(clarity_channel)
    if clarity_component is None:
        return 0.0, 1.0
    clarity_values = []
    for clarity_object, clarity_is_leaf in (
            (clarity_settings.trunk_object, False),
            (clarity_settings.leaves_object, True)):
        if clarity_object is None or clarity_object.type != 'MESH':
            continue
        clarity_colors = read_color_attribute(
            clarity_object.data,
            clarity_settings.attribute_name.strip(),
            clarity_is_leaf,
        )
        clarity_values.extend(
            clarity_colors[clarity_index]
            for clarity_index in range(clarity_component, len(clarity_colors), 4)
        )
    clarity_minimum = min(clarity_values, default=0.0)
    clarity_maximum = max(clarity_values, default=0.0)
    return clarity_minimum, clarity_maximum


def clarity_debug_range_text(clarity_settings, clarity_channel):
    if clarity_channel == 'OFF':
        return ""
    clarity_minimum, clarity_maximum = clarity_debug_range_values(
        clarity_settings,
        clarity_channel,
    )
    clarity_flat = " — FLAT" if clarity_maximum - clarity_minimum <= 1e-5 else ""
    return f"Stored range: {clarity_minimum:.4f} … {clarity_maximum:.4f}{clarity_flat}"


def clarity_update_solid_debug_attribute(clarity_settings):
    clarity_channel = clarity_settings.clarity_debug_channel
    if clarity_channel == 'OFF':
        for clarity_object in (clarity_settings.trunk_object, clarity_settings.leaves_object):
            if clarity_object is None or clarity_object.type != 'MESH':
                continue
            clarity_mesh = clarity_object.data
            clarity_attribute = clarity_mesh.color_attributes.get(CLARITY_DEBUG_ATTRIBUTE)
            if clarity_attribute is not None:
                clarity_mesh.color_attributes.remove(clarity_attribute)
            clarity_previous = clarity_mesh.get(CLARITY_DEBUG_PREVIOUS_COLOR, "")
            clarity_previous_index = clarity_mesh.color_attributes.find(clarity_previous)
            if clarity_previous_index >= 0:
                clarity_mesh.color_attributes.active_color_index = clarity_previous_index
            if CLARITY_DEBUG_PREVIOUS_COLOR in clarity_mesh:
                del clarity_mesh[CLARITY_DEBUG_PREVIOUS_COLOR]
            clarity_mesh.update()
        return

    clarity_component = {'R': 0, 'G': 1, 'B': 2}.get(clarity_channel)
    if clarity_component is None:
        return
    clarity_minimum = clarity_settings.clarity_debug_min
    clarity_span = max(
        clarity_settings.clarity_debug_max - clarity_settings.clarity_debug_min,
        1e-6,
    )
    for clarity_object, clarity_is_leaf in (
            (clarity_settings.trunk_object, False),
            (clarity_settings.leaves_object, True)):
        if clarity_object is None or clarity_object.type != 'MESH':
            continue
        clarity_mesh = clarity_object.data
        if CLARITY_DEBUG_PREVIOUS_COLOR not in clarity_mesh:
            clarity_mesh[CLARITY_DEBUG_PREVIOUS_COLOR] = (
                clarity_mesh.attributes.active_color_name or ""
            )
        clarity_source = read_color_attribute(
            clarity_mesh,
            clarity_settings.attribute_name.strip(),
            clarity_is_leaf,
        )
        clarity_colors = array('f')
        for clarity_index in range(clarity_component, len(clarity_source), 4):
            clarity_value = clamp01(
                (clarity_source[clarity_index] - clarity_minimum) / clarity_span
            )
            clarity_colors.extend((clarity_value, clarity_value, clarity_value, 1.0))
        clarity_attribute = ensure_color_attribute(
            clarity_mesh,
            CLARITY_DEBUG_ATTRIBUTE,
            False,
            replace_incompatible=True,
        )
        write_color_attribute(clarity_attribute, clarity_colors)
        clarity_attribute_index = clarity_mesh.color_attributes.find(CLARITY_DEBUG_ATTRIBUTE)
        if clarity_attribute_index >= 0:
            clarity_mesh.color_attributes.active_color_index = clarity_attribute_index
        clarity_mesh.update()


def clarity_set_solid_debug_view(context, clarity_settings, clarity_enabled):
    for clarity_window in context.window_manager.windows:
        if clarity_window.screen is None:
            continue
        for clarity_area in clarity_window.screen.areas:
            if clarity_area.type != 'VIEW_3D':
                continue
            clarity_shading = clarity_area.spaces.active.shading
            if clarity_enabled:
                if not clarity_settings.clarity_debug_previous_color_type:
                    clarity_settings.clarity_debug_previous_color_type = clarity_shading.color_type
                    clarity_settings.clarity_debug_previous_light = clarity_shading.light
                clarity_shading.color_type = 'VERTEX'
                clarity_shading.light = 'FLAT'
            else:
                if clarity_settings.clarity_debug_previous_color_type:
                    clarity_shading.color_type = clarity_settings.clarity_debug_previous_color_type
                if clarity_settings.clarity_debug_previous_light:
                    clarity_shading.light = clarity_settings.clarity_debug_previous_light
    if not clarity_enabled:
        clarity_settings.clarity_debug_previous_color_type = ""
        clarity_settings.clarity_debug_previous_light = ""


_CLARITY_NORMAL_DEBUG_CACHE = {
    'signature': None,
    'batches': (),
}


def _clarity_tag_view3d_redraw():
    for clarity_window in bpy.context.window_manager.windows:
        if clarity_window.screen is None:
            continue
        for clarity_area in clarity_window.screen.areas:
            if clarity_area.type == 'VIEW_3D':
                clarity_area.tag_redraw()


def clarity_refresh_normal_debug():
    _CLARITY_NORMAL_DEBUG_CACHE['signature'] = None
    _CLARITY_NORMAL_DEBUG_CACHE['batches'] = ()
    _clarity_tag_view3d_redraw()


def _clarity_normal_debug_source(clarity_mesh, clarity_before):
    if clarity_before:
        clarity_attribute = clarity_mesh.attributes.get(CLARITY_NORMAL_BACKUP)
        if clarity_attribute is not None and (
                clarity_attribute.data_type == 'FLOAT_VECTOR'
                and clarity_attribute.domain == 'CORNER'
                and len(clarity_attribute.data) == len(clarity_mesh.loops)):
            clarity_values = [0.0] * (len(clarity_mesh.loops) * 3)
            clarity_attribute.data.foreach_get('vector', clarity_values)
            return [
                Vector(clarity_values[clarity_index:clarity_index + 3])
                for clarity_index in range(0, len(clarity_values), 3)
            ]
    return [clarity_loop.normal.copy() for clarity_loop in clarity_mesh.loops]


def _clarity_normal_debug_batch(clarity_object, clarity_normals, clarity_size):
    clarity_mesh = clarity_object.data
    clarity_matrix = clarity_object.matrix_world
    clarity_normal_matrix = clarity_matrix.to_3x3().inverted_safe().transposed()
    clarity_coordinates = []
    clarity_seen = set()
    for clarity_loop, clarity_normal in zip(clarity_mesh.loops, clarity_normals):
        if clarity_normal.length_squared <= 1e-16:
            continue
        clarity_key = (
            clarity_loop.vertex_index,
            int(round(clarity_normal.x * 10000.0)),
            int(round(clarity_normal.y * 10000.0)),
            int(round(clarity_normal.z * 10000.0)),
        )
        if clarity_key in clarity_seen:
            continue
        clarity_seen.add(clarity_key)
        clarity_start = clarity_matrix @ clarity_mesh.vertices[clarity_loop.vertex_index].co
        clarity_world_normal = clarity_normal_matrix @ clarity_normal
        if clarity_world_normal.length_squared <= 1e-16:
            continue
        clarity_world_normal.normalize()
        clarity_coordinates.extend((
            clarity_start,
            clarity_start + clarity_world_normal * clarity_size,
        ))
    if not clarity_coordinates:
        return None
    clarity_shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    return clarity_shader, batch_for_shader(
        clarity_shader,
        'LINES',
        {'pos': clarity_coordinates},
    )


def _clarity_normal_debug_batches(clarity_settings):
    clarity_object = clarity_settings.leaves_object
    clarity_mode = clarity_settings.clarity_normal_debug_mode
    if clarity_object is None or clarity_object.type != 'MESH' or clarity_mode == 'OFF':
        return ()
    clarity_mesh = clarity_object.data
    clarity_bounds = [
        clarity_object.matrix_world @ Vector(clarity_corner)
        for clarity_corner in clarity_object.bound_box
    ]
    clarity_minimum = Vector(tuple(
        min(clarity_point[clarity_axis] for clarity_point in clarity_bounds)
        for clarity_axis in range(3)
    ))
    clarity_maximum = Vector(tuple(
        max(clarity_point[clarity_axis] for clarity_point in clarity_bounds)
        for clarity_axis in range(3)
    ))
    clarity_size = max(
        (clarity_maximum - clarity_minimum).length
        * 0.02
        * clarity_settings.clarity_normal_debug_size,
        1e-5,
    )
    clarity_signature = (
        clarity_object.as_pointer(),
        clarity_mesh.as_pointer(),
        clarity_mode,
        len(clarity_mesh.loops),
        tuple(round(clarity_value, 6) for clarity_row in clarity_object.matrix_world for clarity_value in clarity_row),
        round(clarity_size, 8),
    )
    if _CLARITY_NORMAL_DEBUG_CACHE['signature'] == clarity_signature:
        return _CLARITY_NORMAL_DEBUG_CACHE['batches']
    clarity_batches = []
    if clarity_mode in {'BEFORE', 'BOTH'}:
        clarity_batch = _clarity_normal_debug_batch(
            clarity_object,
            _clarity_normal_debug_source(clarity_mesh, True),
            clarity_size,
        )
        if clarity_batch is not None:
            clarity_batches.append((clarity_batch, (0.05, 0.65, 1.0, 1.0)))
    if clarity_mode in {'RESULT', 'BOTH'}:
        clarity_batch = _clarity_normal_debug_batch(
            clarity_object,
            _clarity_normal_debug_source(clarity_mesh, False),
            clarity_size,
        )
        if clarity_batch is not None:
            clarity_batches.append((clarity_batch, (1.0, 0.25, 0.03, 1.0)))
    _CLARITY_NORMAL_DEBUG_CACHE['signature'] = clarity_signature
    _CLARITY_NORMAL_DEBUG_CACHE['batches'] = tuple(clarity_batches)
    return _CLARITY_NORMAL_DEBUG_CACHE['batches']


def _clarity_draw_normal_debug():
    clarity_scene = getattr(bpy.context, 'scene', None)
    if clarity_scene is None or not hasattr(clarity_scene, 'tree_vertex_data_settings'):
        return
    clarity_settings = clarity_scene.tree_vertex_data_settings
    try:
        clarity_batches = _clarity_normal_debug_batches(clarity_settings)
        if not clarity_batches:
            return
        gpu.state.blend_set('ALPHA')
        gpu.state.depth_test_set('LESS_EQUAL')
        gpu.state.line_width_set(2.0)
        for (clarity_shader, clarity_batch), clarity_color in clarity_batches:
            clarity_shader.bind()
            clarity_shader.uniform_float('color', clarity_color)
            clarity_batch.draw(clarity_shader)
    finally:
        gpu.state.line_width_set(1.0)
        gpu.state.depth_test_set('NONE')
        gpu.state.blend_set('NONE')


def clarity_remove_normal_debug():
    clarity_handler = bpy.app.driver_namespace.pop(
        CLARITY_NORMAL_DEBUG_HANDLER_KEY,
        None,
    )
    if clarity_handler is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(clarity_handler, 'WINDOW')
        except Exception:
            pass
    clarity_refresh_normal_debug()


def clarity_enable_normal_debug(clarity_settings):
    clarity_remove_normal_debug()
    if clarity_settings.clarity_normal_debug_mode == 'OFF':
        return
    clarity_handler = bpy.types.SpaceView3D.draw_handler_add(
        _clarity_draw_normal_debug,
        (),
        'WINDOW',
        'POST_VIEW',
    )
    bpy.app.driver_namespace[CLARITY_NORMAL_DEBUG_HANDLER_KEY] = clarity_handler
    clarity_refresh_normal_debug()


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


def ensure_vector_attribute(mesh, name, replace_incompatible=False):
    attr = mesh.attributes.get(name)
    if attr is not None and (attr.domain != 'POINT' or attr.data_type != 'FLOAT_VECTOR'):
        if not replace_incompatible:
            raise RuntimeError(
                f'Attribute "{name}" exists on {mesh.name} but is not POINT/FLOAT_VECTOR.'
            )
        mesh.attributes.remove(attr)
        attr = None
    if attr is None:
        attr = mesh.attributes.new(name=name, type='FLOAT_VECTOR', domain='POINT')
    return attr


def write_vector_attribute(attr, values):
    flat = array('f', (float(component) for value in values for component in value))
    try:
        attr.data.foreach_set('vector', flat)
    except Exception:
        for i, value in enumerate(values):
            attr.data[i].vector = value


def _clarity_mix_u32(clarity_hash, clarity_value):
    clarity_hash ^= int(clarity_value) & 0xFFFFFFFF
    return (clarity_hash * 16777619) & 0xFFFFFFFF


def _clarity_island_geometry_hash(mesh, indices, seed, quantization):
    clarity_hash = _clarity_mix_u32(2166136261, seed)
    clarity_hash = _clarity_mix_u32(clarity_hash, len(indices))
    clarity_inverse = 1.0 / max(quantization, 1e-12)
    clarity_points = sorted(
        tuple(int(round(mesh.vertices[i].co[axis] * clarity_inverse)) for axis in range(3))
        for i in indices
    )
    for clarity_point in clarity_points:
        for clarity_component in clarity_point:
            clarity_hash = _clarity_mix_u32(clarity_hash, clarity_component)
    return clarity_hash


def _clarity_mesh_quantization(mesh):
    if not mesh.vertices:
        return 1e-6
    clarity_min = Vector((
        min(clarity_vertex.co.x for clarity_vertex in mesh.vertices),
        min(clarity_vertex.co.y for clarity_vertex in mesh.vertices),
        min(clarity_vertex.co.z for clarity_vertex in mesh.vertices),
    ))
    clarity_max = Vector((
        max(clarity_vertex.co.x for clarity_vertex in mesh.vertices),
        max(clarity_vertex.co.y for clarity_vertex in mesh.vertices),
        max(clarity_vertex.co.z for clarity_vertex in mesh.vertices),
    ))
    return max((clarity_max - clarity_min).length * 1e-6, 1e-7)


def leaf_variation_values(mesh, islands, seed, value_min, value_max):
    lo = min(value_min, value_max)
    hi = max(value_min, value_max)
    result = [0.5] * len(mesh.vertices)
    clarity_quantization = _clarity_mesh_quantization(mesh)
    for indices in islands.values():
        clarity_hash = _clarity_island_geometry_hash(
            mesh, indices, seed, clarity_quantization
        )
        clarity_unit = clarity_hash / 4294967295.0
        value = lerp(lo, hi, clarity_unit)
        for i in indices:
            result[i] = value
    return result


def compute_leaf_flutter_generator(
        leaves_obj, islands, attachments, nearest_dist, merge_epsilon, settings):
    mesh = leaves_obj.data
    count = len(mesh.vertices)
    if count == 0:
        return [], [], [], []

    adjacency = build_vertex_adjacency(
        mesh, leaves_obj.matrix_world, merge_epsilon
    )
    world_positions = object_world_vertices(leaves_obj)
    result = [0.0] * count
    clarity_phase_values = [0.0] * count
    clarity_direction_values = [Vector((0.0, 0.0, 1.0)) for _i in range(count)]
    clarity_scale_values = [1.0] * count
    anchor_band = clamp01(settings.leaf_flutter_anchor_band)
    clarity_flutter_power = max(settings.clarity_flutter_power, 0.01)
    clarity_quantization = _clarity_mesh_quantization(mesh)
    clarity_island_diagonals = {}
    for clarity_root, clarity_indices in islands.items():
        clarity_points = [world_positions[i] for i in clarity_indices]
        clarity_minimum = Vector((
            min(p.x for p in clarity_points),
            min(p.y for p in clarity_points),
            min(p.z for p in clarity_points),
        ))
        clarity_maximum = Vector((
            max(p.x for p in clarity_points),
            max(p.y for p in clarity_points),
            max(p.z for p in clarity_points),
        ))
        clarity_island_diagonals[clarity_root] = max(
            (clarity_maximum - clarity_minimum).length, 1e-8
        )
    clarity_sorted_diagonals = sorted(clarity_island_diagonals.values())
    clarity_median_diagonal = (
        clarity_sorted_diagonals[len(clarity_sorted_diagonals) // 2]
        if clarity_sorted_diagonals else 1.0
    )

    for clarity_root, indices in islands.items():
        clarity_hash = _clarity_island_geometry_hash(
            mesh, indices, settings.variation_seed ^ 0x51F15EED, clarity_quantization
        )
        clarity_phase = math.tau * (clarity_hash / 4294967295.0)
        clarity_reference_normal = mesh.vertices[indices[0]].normal.copy()
        clarity_island_normal = Vector((0.0, 0.0, 0.0))
        for clarity_index in indices:
            clarity_normal = mesh.vertices[clarity_index].normal.copy()
            if clarity_normal.dot(clarity_reference_normal) < 0.0:
                clarity_normal.negate()
            clarity_island_normal += clarity_normal
        if clarity_island_normal.length_squared <= 1e-16:
            clarity_island_normal = clarity_reference_normal
        if clarity_island_normal.length_squared <= 1e-16:
            clarity_island_normal = Vector((0.0, 0.0, 1.0))
        else:
            clarity_island_normal.normalize()
        clarity_island_scale = max(0.5, min(
            2.0,
            math.sqrt(
                clarity_island_diagonals[clarity_root]
                / max(clarity_median_diagonal, 1e-8)
            ),
        ))
        for clarity_index in indices:
            clarity_phase_values[clarity_index] = clarity_phase
            clarity_direction_values[clarity_index] = clarity_island_normal.copy()
            clarity_scale_values[clarity_index] = clarity_island_scale
        if len(indices) <= 1:
            result[indices[0]] = 0.0
            yield 1
            continue

        clarity_attachment = attachments.get(clarity_root)
        min_d = (
            clarity_attachment.distance
            if clarity_attachment is not None
            else min(nearest_dist[i] for i in indices)
        )
        island_diag = max(clarity_island_diagonals[clarity_root], 1e-6)
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
                result[i] = smoothstep01(t) ** clarity_flutter_power
        yield 1

    return (
        result,
        clarity_phase_values,
        clarity_direction_values,
        clarity_scale_values,
    )


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
            if m.show_viewport and not is_clarity_wind_preview_modifier(m)
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
    bounds = compute_tree_bounds(trunk, leaves, s.up_axis)
    clarity_leaf_merge_epsilon = (
        s.clarity_leaf_merge_epsilon
        if s.clarity_leaf_merge_epsilon > 0.0
        else max(bounds['diagonal'] * 1e-6, 1e-7)
    )
    leaf_roots, islands = compute_leaf_components(
        leaves.data,
        leaves.matrix_world,
        clarity_leaf_merge_epsilon,
    )
    clarity_leaf_attachments, clarity_leaf_trunk_distances = build_leaf_attachments(
        trunk, leaves, islands
    )
    trunk_targets = build_trunk_targets(trunk)
    leaf_targets = build_leaf_targets(leaves, islands, s, need_normal=False)

    work = 0
    if channels & CH_R:
        work += len(islands)
    if channels & CH_G:
        work += len(trunk_targets) + len(leaf_targets)
    if channels & CH_B:
        work += len(islands)
    return {
        'settings': s,
        'trunk': trunk,
        'leaves': leaves,
        'leaf_roots': leaf_roots,
        'islands': islands,
        'leaf_merge_epsilon': clarity_leaf_merge_epsilon,
        'leaf_attachments': clarity_leaf_attachments,
        'leaf_trunk_distances': clarity_leaf_trunk_distances,
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
    flutter_values = []
    flutter_phase_values = []
    flutter_direction_values = []
    flutter_scale_values = []

    bvh, tri_meta = build_tree_bvh(trunk, leaves, plan['leaf_roots'])

    # Alpha is no longer a TreeVDB data channel. Keep exported vertex colors
    # conventionally opaque and migrate old A Wind values during any bake.
    for clarity_colors in colors.values():
        for clarity_index in range(3, len(clarity_colors), 4):
            clarity_colors[clarity_index] = 1.0

    if channels & CH_R:
        for i in range(len(trunk.data.vertices)):
            colors[trunk][i * 4 + 0] = 0.0

        gen = compute_leaf_flutter_generator(
            leaves,
            islands,
            plan['leaf_attachments'],
            plan['leaf_trunk_distances'],
            plan['leaf_merge_epsilon'],
            s,
        )
        while True:
            try:
                step = next(gen)
                done += step
                yield done, total, "Baking R: leaf flutter mask"
            except StopIteration as stop:
                (
                    flutter_values,
                    flutter_phase_values,
                    flutter_direction_values,
                    flutter_scale_values,
                ) = stop.value
                break
        for i, value in enumerate(flutter_values):
            colors[leaves][i * 4 + 0] = value

    if channels & CH_G:
        gen = compute_ao_generator(
            trunk, False, plan['trunk_targets'], bvh, tri_meta, bounds, s
        )
        while True:
            try:
                step = next(gen)
                done += step
                yield done, total, "Baking G: trunk AO"
            except StopIteration as stop:
                values = stop.value
                break
        for i, value in enumerate(values):
            colors[trunk][i * 4 + 1] = value

        gen = compute_ao_generator(
            leaves, True, plan['leaf_targets'], bvh, tri_meta, bounds, s
        )
        while True:
            try:
                step = next(gen)
                done += step
                yield done, total, "Baking G: foliage AO"
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

    elapsed = time.perf_counter() - started
    summary = (
        f"Bake complete: {len(trunk.data.vertices):,} trunk verts, "
        f"{len(leaves.data.vertices):,} leaf verts, {len(islands):,} leaf islands, "
        f"{elapsed:.2f}s"
    )
    return BakeResult(
        colors_by_object=colors,
        flutter_values=flutter_values,
        flutter_phase_values=flutter_phase_values,
        flutter_direction_values=flutter_direction_values,
        flutter_scale_values=flutter_scale_values,
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

        legacy_wind = obj.data.attributes.get(LEGACY_WIND_MASK_ATTRIBUTE)
        if legacy_wind is not None:
            obj.data.attributes.remove(legacy_wind)

        obj.data.update()

    s.clarity_debug_min, s.clarity_debug_max = clarity_debug_range_values(
        s,
        s.clarity_debug_channel,
    )
    s.clarity_debug_range = clarity_debug_range_text(s, s.clarity_debug_channel)
    clarity_update_debug_material_range(s)
    clarity_update_solid_debug_attribute(s)

    if result.flutter_values:
        flutter = ensure_float_attribute(
            leaves.data,
            LEAF_FLUTTER_ATTRIBUTE,
            0.0,
            replace_incompatible=s.replace_incompatible_attribute,
        )
        write_float_attribute(flutter, result.flutter_values)
        flutter_phase = ensure_float_attribute(
            leaves.data,
            CLARITY_FLUTTER_PHASE_ATTRIBUTE,
            0.0,
            replace_incompatible=s.replace_incompatible_attribute,
        )
        write_float_attribute(flutter_phase, result.flutter_phase_values)
        flutter_direction = ensure_vector_attribute(
            leaves.data,
            CLARITY_FLUTTER_DIRECTION_ATTRIBUTE,
            replace_incompatible=s.replace_incompatible_attribute,
        )
        write_vector_attribute(flutter_direction, result.flutter_direction_values)
        flutter_scale = ensure_float_attribute(
            leaves.data,
            CLARITY_FLUTTER_SCALE_ATTRIBUTE,
            1.0,
            replace_incompatible=s.replace_incompatible_attribute,
        )
        write_float_attribute(flutter_scale, result.flutter_scale_values)
        leaves.data.update()

    remove_clarity_wind_preview(s)


def clear_vertex_data(context):
    s = context.scene.tree_vertex_data_settings
    name = s.attribute_name.strip()
    for obj in (s.trunk_object, s.leaves_object):
        if obj is None or obj.type != 'MESH':
            continue
        attr = obj.data.color_attributes.get(name)
        if attr is not None:
            obj.data.color_attributes.remove(attr)
        legacy_wind = obj.data.attributes.get(LEGACY_WIND_MASK_ATTRIBUTE)
        if legacy_wind is not None:
            obj.data.attributes.remove(legacy_wind)
        if obj == s.leaves_object:
            flutter = obj.data.attributes.get(LEAF_FLUTTER_ATTRIBUTE)
            if flutter is not None:
                obj.data.attributes.remove(flutter)
            flutter_phase = obj.data.attributes.get(CLARITY_FLUTTER_PHASE_ATTRIBUTE)
            if flutter_phase is not None:
                obj.data.attributes.remove(flutter_phase)
            flutter_direction = obj.data.attributes.get(CLARITY_FLUTTER_DIRECTION_ATTRIBUTE)
            if flutter_direction is not None:
                obj.data.attributes.remove(flutter_direction)
            flutter_scale = obj.data.attributes.get(CLARITY_FLUTTER_SCALE_ATTRIBUTE)
            if flutter_scale is not None:
                obj.data.attributes.remove(flutter_scale)
        obj.data.update()
    s.clarity_debug_channel = 'OFF'
    s.clarity_debug_range = ""
    clarity_update_solid_debug_attribute(s)
    clarity_set_solid_debug_view(context, s, False)
    remove_clarity_wind_preview(s)


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
            mat[CLARITY_SOURCE_MATERIAL_EMPTY] = True
            slot.material = mat

        original_ptr = mat.as_pointer()
        if original_ptr in copied:
            slot.material = copied[original_ptr]
            mat = slot.material
        else:
            owner = mat.get(TREE_OWNER_ID)
            managed_role = mat.get(TREE_MATERIAL_ROLE)
            must_copy = (
                not mat.get(CLARITY_SOURCE_MATERIAL_EMPTY)
                and (owner != tree_id or managed_role != role)
            )
            if must_copy:
                new_mat = mat.copy()
                new_mat.name = f"{mat.name}_{role}_{tree_id[:6]}"
                clarity_source_material = mat.get(CLARITY_SOURCE_MATERIAL)
                if not isinstance(clarity_source_material, bpy.types.Material):
                    clarity_source_material = mat
                new_mat[CLARITY_SOURCE_MATERIAL] = clarity_source_material
                if CLARITY_SOURCE_MATERIAL_EMPTY in new_mat:
                    del new_mat[CLARITY_SOURCE_MATERIAL_EMPTY]
                slot.material = new_mat
                copied[original_ptr] = new_mat
                mat = new_mat

        mat[TREE_OWNER_ID] = tree_id
        mat[TREE_MATERIAL_ROLE] = role
        if mat not in result:
            result.append(mat)
    return result


def _clarity_legacy_source_material(clarity_material):
    clarity_role = clarity_material.get(TREE_MATERIAL_ROLE)
    clarity_owner = clarity_material.get(TREE_OWNER_ID)
    if clarity_role not in {'TRUNK', 'LEAVES'} or not clarity_owner:
        return None
    clarity_suffix = f"_{clarity_role}_{str(clarity_owner)[:6]}"
    clarity_name = clarity_material.name
    clarity_suffix_position = clarity_name.rfind(clarity_suffix)
    if clarity_suffix_position <= 0:
        return None
    clarity_tail = clarity_name[clarity_suffix_position + len(clarity_suffix):]
    if clarity_tail and not (
            len(clarity_tail) == 4
            and clarity_tail[0] == '.'
            and clarity_tail[1:].isdigit()):
        return None
    return bpy.data.materials.get(clarity_name[:clarity_suffix_position])


def clarity_restore_original_materials(settings):
    clarity_restored = 0
    clarity_remove_candidates = []
    for clarity_object in (settings.trunk_object, settings.leaves_object):
        if clarity_object is None or clarity_object.type != 'MESH':
            continue
        for clarity_slot in clarity_object.material_slots:
            clarity_material = clarity_slot.material
            if clarity_material is None:
                continue
            clarity_source = clarity_material.get(CLARITY_SOURCE_MATERIAL)
            if not isinstance(clarity_source, bpy.types.Material):
                clarity_source = _clarity_legacy_source_material(clarity_material)
            if isinstance(clarity_source, bpy.types.Material):
                clarity_slot.material = clarity_source
                clarity_remove_candidates.append(clarity_material)
                clarity_restored += 1
            elif clarity_material.get(CLARITY_SOURCE_MATERIAL_EMPTY):
                clarity_slot.material = None
                clarity_remove_candidates.append(clarity_material)
                clarity_restored += 1

    for clarity_material in set(clarity_remove_candidates):
        if clarity_material.users == 0 and clarity_material.name in bpy.data.materials:
            bpy.data.materials.remove(clarity_material)
    for clarity_material in list(bpy.data.materials):
        if (
                clarity_material.users == 0
                and clarity_material.get(TREE_OWNER_ID)
                and clarity_material.get(TREE_MATERIAL_ROLE) in {'TRUNK', 'LEAVES'}):
            bpy.data.materials.remove(clarity_material)
    return clarity_restored


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

    # Always rebuild the managed stack. This makes the Update button a reliable
    # hot-reload boundary while `_remove_managed_stack` preserves user-owned albedo.
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
    vcol.label = 'Tree RGB'
    vcol.location = (x0, y0 + 280)
    tag_node(vcol, 'surface_attribute', pname)

    sep = nodes.new('ShaderNodeSeparateColor')
    sep.mode = 'RGB'
    sep.location = (x0 + 190, y0 + 280)
    sep.label = 'R Flutter | G AO | B Variation'
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
    canopy_strength = value_node('surface_canopy_strength', 'Unused Legacy Canopy', 0.0, y0 - 40)
    variation_strength = value_node(
        'surface_variation_strength',
        'Variation Strength',
        settings.shader_variation_strength if role == 'LEAVES' else 0.0,
        y0 - 150,
    )

    clarity_one_minus_ao = nodes.new('ShaderNodeMath')
    clarity_one_minus_ao.operation = 'SUBTRACT'
    clarity_one_minus_ao.location = (x0 + 400, y0 + 245)
    safe_node_input(clarity_one_minus_ao, index=0).default_value = 1.0
    links.new(safe_node_output(sep, 'Green', 1), safe_node_input(clarity_one_minus_ao, index=1))
    tag_node(clarity_one_minus_ao, 'surface_math', pname)

    ao_scaled = nodes.new('ShaderNodeMath')
    ao_scaled.operation = 'MULTIPLY'
    ao_scaled.location = (x0 + 570, y0 + 225)
    links.new(safe_node_output(clarity_one_minus_ao, 'Value', 0), safe_node_input(ao_scaled, index=0))
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

    clarity_debug_source = {
        'R': safe_node_output(sep, 'Red', 0),
        'G': safe_node_output(sep, 'Green', 1),
        'B': safe_node_output(sep, 'Blue', 2),
    }.get(settings.clarity_debug_channel)
    if clarity_debug_source is not None:
        clarity_debug_subtract = nodes.new('ShaderNodeMath')
        clarity_debug_subtract.operation = 'SUBTRACT'
        clarity_debug_subtract.location = (
            principled.location.x - 660,
            principled.location.y - 230,
        )
        safe_node_input(clarity_debug_subtract, index=1).default_value = (
            settings.clarity_debug_min
        )
        tag_node(clarity_debug_subtract, 'surface_debug_range_min', pname)
        links.new(
            clarity_debug_source,
            safe_node_input(clarity_debug_subtract, index=0),
        )
        clarity_debug_divide = nodes.new('ShaderNodeMath')
        clarity_debug_divide.operation = 'DIVIDE'
        clarity_debug_divide.use_clamp = True
        clarity_debug_divide.location = (
            principled.location.x - 560,
            principled.location.y - 230,
        )
        safe_node_input(clarity_debug_divide, index=1).default_value = max(
            settings.clarity_debug_max - settings.clarity_debug_min,
            1e-6,
        )
        tag_node(clarity_debug_divide, 'surface_debug_range_span', pname)
        links.new(
            safe_node_output(clarity_debug_subtract, 'Value', 0),
            safe_node_input(clarity_debug_divide, index=0),
        )
        clarity_debug_source = safe_node_output(clarity_debug_divide, 'Value', 0)
    clarity_debug_color = nodes.new('ShaderNodeCombineColor')
    clarity_debug_color.mode = 'RGB'
    clarity_debug_color.label = 'Clarity Debug Channel'
    clarity_debug_color.location = (principled.location.x - 470, principled.location.y - 180)
    tag_node(clarity_debug_color, 'surface_debug', pname)
    if clarity_debug_source is not None:
        for clarity_input_name, clarity_input_index in (
                ('Red', 0), ('Green', 1), ('Blue', 2)):
            links.new(
                clarity_debug_source,
                safe_node_input(
                    clarity_debug_color,
                    clarity_input_name,
                    clarity_input_index,
                ),
            )

    clarity_debug_difference = nodes.new('ShaderNodeVectorMath')
    clarity_debug_difference.operation = 'SUBTRACT'
    clarity_debug_difference.location = (
        principled.location.x - 280,
        principled.location.y - 150,
    )
    tag_node(clarity_debug_difference, 'surface_debug', pname)
    links.new(
        safe_node_output(clarity_debug_color, 'Color', 0),
        safe_node_input(clarity_debug_difference, index=0),
    )
    links.new(
        safe_node_output(final, 'Vector', 0),
        safe_node_input(clarity_debug_difference, index=1),
    )

    clarity_debug_scaled = nodes.new('ShaderNodeVectorMath')
    clarity_debug_scaled.operation = 'SCALE'
    clarity_debug_scaled.location = (
        principled.location.x - 90,
        principled.location.y - 130,
    )
    safe_node_input(clarity_debug_scaled, 'Scale', 3).default_value = (
        0.0 if settings.clarity_debug_channel == 'OFF' else 1.0
    )
    tag_node(clarity_debug_scaled, 'surface_debug', pname)
    links.new(
        safe_node_output(clarity_debug_difference, 'Vector', 0),
        safe_node_input(clarity_debug_scaled, 'Vector', 0),
    )

    clarity_debug_result = nodes.new('ShaderNodeVectorMath')
    clarity_debug_result.operation = 'ADD'
    clarity_debug_result.location = (
        principled.location.x + 90,
        principled.location.y - 20,
    )
    tag_node(clarity_debug_result, 'surface_debug', pname)
    links.new(
        safe_node_output(final, 'Vector', 0),
        safe_node_input(clarity_debug_result, index=0),
    )
    links.new(
        safe_node_output(clarity_debug_scaled, 'Vector', 0),
        safe_node_input(clarity_debug_result, index=1),
    )
    links.new(safe_node_output(clarity_debug_result, 'Vector', 0), base)
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


def clarity_update_debug_material_range(clarity_settings):
    clarity_span = max(
        clarity_settings.clarity_debug_max - clarity_settings.clarity_debug_min,
        1e-6,
    )
    for clarity_object in (clarity_settings.trunk_object, clarity_settings.leaves_object):
        if clarity_object is None:
            continue
        for clarity_slot in clarity_object.material_slots:
            clarity_material = clarity_slot.material
            if clarity_material is None or not clarity_material.use_nodes:
                continue
            for clarity_node in clarity_material.node_tree.nodes:
                if clarity_node.get(TREE_NODE_TAG) == 'surface_debug_range_min':
                    safe_node_input(clarity_node, index=1).default_value = (
                        clarity_settings.clarity_debug_min
                    )
                elif clarity_node.get(TREE_NODE_TAG) == 'surface_debug_range_span':
                    safe_node_input(clarity_node, index=1).default_value = clarity_span


# =============================================================================
# Shader-style wind preview
# =============================================================================

def _clarity_wind_group_name(clarity_object):
    return f"Clarity_TreeWind_{clarity_object.name}"


def _clarity_math_node(clarity_nodes, clarity_operation, clarity_location):
    clarity_node = clarity_nodes.new('ShaderNodeMath')
    clarity_node.operation = clarity_operation
    clarity_node.location = clarity_location
    return clarity_node


def _clarity_vector_math_node(clarity_nodes, clarity_operation, clarity_location):
    clarity_node = clarity_nodes.new('ShaderNodeVectorMath')
    clarity_node.operation = clarity_operation
    clarity_node.location = clarity_location
    return clarity_node


def _clarity_build_wind_node_group(clarity_object, clarity_role, clarity_settings):
    clarity_group = bpy.data.node_groups.new(
        _clarity_wind_group_name(clarity_object),
        'GeometryNodeTree',
    )
    clarity_group.is_modifier = True
    clarity_group['clarity_tree_wind_preview'] = True
    clarity_group.interface.new_socket(
        name='Geometry', in_out='INPUT', socket_type='NodeSocketGeometry'
    )
    clarity_group.interface.new_socket(
        name='Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry'
    )
    clarity_nodes = clarity_group.nodes
    clarity_links = clarity_group.links

    clarity_input = clarity_nodes.new('NodeGroupInput')
    clarity_input.location = (-1260, 220)
    clarity_output = clarity_nodes.new('NodeGroupOutput')
    clarity_output.is_active_output = True
    clarity_output.location = (720, 220)
    clarity_position = clarity_nodes.new('GeometryNodeInputPosition')
    clarity_position.location = (-1260, -20)
    clarity_normal = clarity_nodes.new('GeometryNodeInputNormal')
    clarity_normal.location = (240, -310)
    clarity_time = clarity_nodes.new('GeometryNodeInputSceneTime')
    clarity_time.location = (-1260, -220)

    clarity_attribute = clarity_nodes.new('GeometryNodeInputNamedAttribute')
    clarity_attribute.data_type = 'FLOAT_COLOR'
    clarity_attribute.location = (-1260, 440)
    safe_node_input(clarity_attribute, 'Name', 0).default_value = (
        clarity_settings.attribute_name.strip()
    )
    clarity_separate = clarity_nodes.new('FunctionNodeSeparateColor')
    clarity_separate.mode = 'RGB'
    clarity_separate.location = (-1040, 440)
    clarity_links.new(
        safe_node_output(clarity_attribute, 'Attribute', 0),
        safe_node_input(clarity_separate, 'Color', 0),
    )

    clarity_up_index = {'X': 0, 'Y': 1, 'Z': 2}[clarity_settings.up_axis]
    clarity_tree_up = Vector((0.0, 0.0, 0.0))
    clarity_tree_up[clarity_up_index] = 1.0
    clarity_tree_direction = Vector(clarity_settings.preview_wind_direction)
    clarity_tree_direction -= clarity_tree_up * clarity_tree_direction.dot(clarity_tree_up)
    if clarity_tree_direction.length_squared < 1e-12:
        clarity_tree_direction = Vector((1.0, 0.0, 0.0))
        if clarity_up_index == 0:
            clarity_tree_direction = Vector((0.0, 1.0, 0.0))
    clarity_tree_direction.normalize()
    clarity_tree_rotation = clarity_settings.trunk_object.matrix_world.to_quaternion()
    clarity_object_rotation_inverse = clarity_object.matrix_world.to_quaternion().inverted()
    clarity_world_direction = clarity_tree_rotation @ clarity_tree_direction
    clarity_direction = clarity_object_rotation_inverse @ clarity_world_direction
    clarity_direction.normalize()
    clarity_world_axis = clarity_tree_rotation @ clarity_tree_up.cross(clarity_tree_direction)
    clarity_rotation_axis = clarity_object_rotation_inverse @ clarity_world_axis
    clarity_rotation_axis.normalize()
    clarity_tree_pivot_world = clarity_settings.trunk_object.matrix_world.translation
    clarity_pivot = clarity_object.matrix_world.inverted() @ clarity_tree_pivot_world

    clarity_scene = clarity_settings.id_data
    clarity_frame_span = max(1, clarity_scene.frame_end - clarity_scene.frame_start)
    clarity_frame_offset = _clarity_math_node(clarity_nodes, 'SUBTRACT', (-1220, -180))
    safe_node_input(clarity_frame_offset, index=1).default_value = clarity_scene.frame_start
    clarity_links.new(
        safe_node_output(clarity_time, 'Frame', 0),
        safe_node_input(clarity_frame_offset, index=0),
    )
    clarity_time_scale = _clarity_math_node(clarity_nodes, 'MULTIPLY', (-1030, -180))
    safe_node_input(clarity_time_scale, index=1).default_value = (
        math.tau * max(1, round(clarity_settings.preview_wind_speed))
        / clarity_frame_span
    )
    clarity_links.new(
        safe_node_output(clarity_frame_offset, 'Value', 0),
        safe_node_input(clarity_time_scale, index=0),
    )
    clarity_sine = _clarity_math_node(clarity_nodes, 'SINE', (-430, -40))
    clarity_links.new(
        safe_node_output(clarity_time_scale, 'Value', 0),
        safe_node_input(clarity_sine, index=0),
    )
    clarity_sway_strength = _clarity_math_node(
        clarity_nodes, 'MULTIPLY', (-240, -40)
    )
    safe_node_input(clarity_sway_strength, index=1).default_value = (
        clarity_settings.preview_wind_strength
    )
    clarity_links.new(
        safe_node_output(clarity_sine, 'Value', 0),
        safe_node_input(clarity_sway_strength, index=0),
    )
    clarity_rotate = clarity_nodes.new('ShaderNodeVectorRotate')
    clarity_rotate.rotation_type = 'AXIS_ANGLE'
    clarity_rotate.location = (160, 90)
    safe_node_input(clarity_rotate, 'Center', 1).default_value = clarity_pivot
    safe_node_input(clarity_rotate, 'Axis', 2).default_value = clarity_rotation_axis
    clarity_links.new(
        safe_node_output(clarity_position, 'Position', 0),
        safe_node_input(clarity_rotate, 'Vector', 0),
    )
    clarity_links.new(
        safe_node_output(clarity_sway_strength, 'Value', 0),
        safe_node_input(clarity_rotate, 'Angle', 3),
    )

    clarity_set_position = clarity_nodes.new('GeometryNodeSetPosition')
    clarity_set_position.location = (500, 220)
    clarity_links.new(
        safe_node_output(clarity_input, 'Geometry', 0),
        safe_node_input(clarity_set_position, 'Geometry', 0),
    )
    clarity_links.new(
        safe_node_output(clarity_rotate, 'Vector', 0),
        safe_node_input(clarity_set_position, 'Position', 2),
    )

    if clarity_role == 'LEAVES':
        clarity_flutter_phase_attribute = clarity_nodes.new(
            'GeometryNodeInputNamedAttribute'
        )
        clarity_flutter_phase_attribute.data_type = 'FLOAT'
        clarity_flutter_phase_attribute.location = (-430, -520)
        safe_node_input(
            clarity_flutter_phase_attribute, 'Name', 0
        ).default_value = CLARITY_FLUTTER_PHASE_ATTRIBUTE
        clarity_flutter_phase_scale = _clarity_math_node(
            clarity_nodes, 'MULTIPLY', (-230, -470)
        )
        safe_node_input(clarity_flutter_phase_scale, index=1).default_value = (
            clarity_settings.preview_wind_spatial
        )
        clarity_links.new(
            safe_node_output(clarity_flutter_phase_attribute, 'Attribute', 0),
            safe_node_input(clarity_flutter_phase_scale, index=0),
        )
        clarity_flutter_direction_attribute = clarity_nodes.new(
            'GeometryNodeInputNamedAttribute'
        )
        clarity_flutter_direction_attribute.data_type = 'FLOAT_VECTOR'
        clarity_flutter_direction_attribute.location = (120, -610)
        safe_node_input(
            clarity_flutter_direction_attribute, 'Name', 0
        ).default_value = CLARITY_FLUTTER_DIRECTION_ATTRIBUTE
        clarity_flutter_direction = clarity_nodes.new('GeometryNodeSwitch')
        clarity_flutter_direction.input_type = 'VECTOR'
        clarity_flutter_direction.location = (350, -570)
        clarity_links.new(
            safe_node_output(clarity_flutter_direction_attribute, 'Exists', 1),
            safe_node_input(clarity_flutter_direction, 'Switch', 0),
        )
        clarity_links.new(
            safe_node_output(clarity_normal, 'Normal', 0),
            safe_node_input(clarity_flutter_direction, 'False', 1),
        )
        clarity_links.new(
            safe_node_output(clarity_flutter_direction_attribute, 'Attribute', 0),
            safe_node_input(clarity_flutter_direction, 'True', 2),
        )
        clarity_flutter_scale_attribute = clarity_nodes.new(
            'GeometryNodeInputNamedAttribute'
        )
        clarity_flutter_scale_attribute.data_type = 'FLOAT'
        clarity_flutter_scale_attribute.location = (120, -740)
        safe_node_input(
            clarity_flutter_scale_attribute, 'Name', 0
        ).default_value = CLARITY_FLUTTER_SCALE_ATTRIBUTE
        clarity_flutter_scale = clarity_nodes.new('GeometryNodeSwitch')
        clarity_flutter_scale.input_type = 'FLOAT'
        clarity_flutter_scale.location = (350, -710)
        safe_node_input(clarity_flutter_scale, 'False', 1).default_value = 1.0
        clarity_links.new(
            safe_node_output(clarity_flutter_scale_attribute, 'Exists', 1),
            safe_node_input(clarity_flutter_scale, 'Switch', 0),
        )
        clarity_links.new(
            safe_node_output(clarity_flutter_scale_attribute, 'Attribute', 0),
            safe_node_input(clarity_flutter_scale, 'True', 2),
        )
        clarity_flutter_time = _clarity_math_node(
            clarity_nodes, 'MULTIPLY', (-230, -300)
        )
        safe_node_input(clarity_flutter_time, index=1).default_value = (
            math.tau * max(1, round(clarity_settings.preview_flutter_speed))
            / clarity_frame_span
        )
        clarity_links.new(
            safe_node_output(clarity_frame_offset, 'Value', 0),
            safe_node_input(clarity_flutter_time, index=0),
        )
        clarity_flutter_phase = _clarity_math_node(clarity_nodes, 'ADD', (-30, -300))
        clarity_links.new(
            safe_node_output(clarity_flutter_time, 'Value', 0),
            safe_node_input(clarity_flutter_phase, index=0),
        )
        clarity_links.new(
            safe_node_output(clarity_flutter_phase_scale, 'Value', 0),
            safe_node_input(clarity_flutter_phase, index=1),
        )
        clarity_flutter_sine = _clarity_math_node(clarity_nodes, 'SINE', (160, -260))
        clarity_links.new(
            safe_node_output(clarity_flutter_phase, 'Value', 0),
            safe_node_input(clarity_flutter_sine, index=0),
        )
        clarity_flutter_mask = _clarity_math_node(
            clarity_nodes, 'MULTIPLY', (160, -390)
        )
        clarity_links.new(
            safe_node_output(clarity_separate, 'Red', 0),
            safe_node_input(clarity_flutter_mask, index=0),
        )
        safe_node_input(clarity_flutter_mask, index=1).default_value = (
            clarity_settings.preview_flutter_strength
        )
        clarity_flutter_amount = _clarity_math_node(
            clarity_nodes, 'MULTIPLY', (350, -330)
        )
        clarity_links.new(
            safe_node_output(clarity_flutter_sine, 'Value', 0),
            safe_node_input(clarity_flutter_amount, index=0),
        )
        clarity_links.new(
            safe_node_output(clarity_flutter_mask, 'Value', 0),
            safe_node_input(clarity_flutter_amount, index=1),
        )
        clarity_flutter_scaled_amount = _clarity_math_node(
            clarity_nodes, 'MULTIPLY', (540, -350)
        )
        clarity_links.new(
            safe_node_output(clarity_flutter_amount, 'Value', 0),
            safe_node_input(clarity_flutter_scaled_amount, index=0),
        )
        clarity_links.new(
            safe_node_output(clarity_flutter_scale, 'Output', 0),
            safe_node_input(clarity_flutter_scaled_amount, index=1),
        )
        clarity_flutter_offset = _clarity_vector_math_node(
            clarity_nodes, 'SCALE', (560, -190)
        )
        clarity_links.new(
            safe_node_output(clarity_flutter_direction, 'Output', 0),
            safe_node_input(clarity_flutter_offset, 'Vector', 0),
        )
        clarity_links.new(
            safe_node_output(clarity_flutter_scaled_amount, 'Value', 0),
            safe_node_input(clarity_flutter_offset, 'Scale', 3),
        )
        clarity_links.new(
            safe_node_output(clarity_flutter_offset, 'Vector', 0),
            safe_node_input(clarity_set_position, 'Offset', 3),
        )

    clarity_links.new(
        safe_node_output(clarity_set_position, 'Geometry', 0),
        safe_node_input(clarity_output, 'Geometry', 0),
    )
    return clarity_group


def clarity_setup_wind_preview(clarity_settings, clarity_enabled=False):
    remove_clarity_wind_preview(clarity_settings)
    clarity_modifiers = []
    for clarity_object, clarity_role in (
            (clarity_settings.trunk_object, 'TRUNK'),
            (clarity_settings.leaves_object, 'LEAVES')):
        if clarity_object is None or clarity_object.type != 'MESH':
            continue
        clarity_group = _clarity_build_wind_node_group(
            clarity_object, clarity_role, clarity_settings
        )
        clarity_modifier = clarity_object.modifiers.new(
            name=TREE_WIND_MODIFIER,
            type='NODES',
        )
        clarity_modifier.node_group = clarity_group
        clarity_modifier.show_render = False
        clarity_modifier.show_viewport = clarity_enabled
        clarity_modifiers.append(clarity_modifier)
    return clarity_modifiers


def clarity_wind_preview_enabled(clarity_settings):
    return any(
        is_clarity_wind_preview_modifier(clarity_modifier)
        and clarity_modifier.show_viewport
        for clarity_object in (clarity_settings.trunk_object, clarity_settings.leaves_object)
        if clarity_object is not None
        for clarity_modifier in clarity_object.modifiers
    )


def clarity_set_wind_preview_enabled(clarity_settings, clarity_enabled):
    clarity_count = 0
    for clarity_object in (clarity_settings.trunk_object, clarity_settings.leaves_object):
        if clarity_object is None:
            continue
        for clarity_modifier in clarity_object.modifiers:
            if is_clarity_wind_preview_modifier(clarity_modifier):
                clarity_modifier.show_viewport = clarity_enabled
                clarity_count += 1
    return clarity_count

def is_clarity_wind_preview_modifier(clarity_modifier):
    clarity_group = getattr(clarity_modifier, 'node_group', None)
    return (
        clarity_modifier.type == 'NODES'
        and (
            clarity_modifier.name.startswith(TREE_WIND_MODIFIER)
            or (
                clarity_group is not None
                and (
                    clarity_group.name.startswith('TreeVDB_Wind_')
                    or clarity_group.get('clarity_tree_wind_preview')
                )
            )
        )
    )


def remove_clarity_wind_preview(settings):
    clarity_groups = []
    for clarity_object in (settings.trunk_object, settings.leaves_object):
        if clarity_object is None:
            continue
        for clarity_modifier in list(clarity_object.modifiers):
            if is_clarity_wind_preview_modifier(clarity_modifier):
                clarity_group = getattr(clarity_modifier, 'node_group', None)
                if clarity_group is not None:
                    clarity_groups.append(clarity_group)
                clarity_object.modifiers.remove(clarity_modifier)
    for clarity_group in clarity_groups:
        if clarity_group.users == 0 and clarity_group.get('clarity_tree_wind_preview'):
            bpy.data.node_groups.remove(clarity_group)
    for clarity_group in list(bpy.data.node_groups):
        if clarity_group.users == 0 and clarity_group.get('clarity_tree_wind_preview'):
            bpy.data.node_groups.remove(clarity_group)


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
        description="POINT/FLOAT_COLOR attribute: R Flutter, G AO, B Variation",
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

    # G AO
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

    leaf_flutter_anchor_band: FloatProperty(
        name="Leaf Anchor Band",
        description="Region closest to wood locked against secondary leaf flutter",
        default=0.18,
        min=0.0,
        max=0.49,
    )
    clarity_flutter_power: FloatProperty(
        name="Flutter Stiffness",
        description="Shapes the geodesic flutter falloff from the wood attachment",
        default=1.35,
        min=0.05,
        max=8.0,
    )
    clarity_leaf_merge_epsilon: FloatProperty(
        name="Leaf Merge Epsilon",
        description="Weld distance used only for island analysis; 0 selects a tree-scale automatic tolerance and does not modify the mesh",
        default=0.0,
        min=0.0,
        soft_max=0.01,
        precision=6,
        subtype='DISTANCE',
    )

    # Material
    shader_ao_strength: FloatProperty(name="AO Strength", default=1.0, min=0.0, max=2.0)
    shader_canopy_strength: FloatProperty(name="Canopy Shade", default=0.30, min=0.0, max=1.0)
    shader_variation_strength: FloatProperty(name="Leaf Variation", default=0.08, min=0.0, max=0.5)
    clarity_debug_channel: EnumProperty(
        name="Debug Channel",
        description="Display one baked vertex-data channel as grayscale",
        items=(
            ('OFF', "Off", "Show the regular material preview"),
            ('R', "R Flutter", "Show the leaf flutter mask"),
            ('G', "G AO", "Show baked ambient occlusion"),
            ('B', "B Variation", "Show the per-leaf variation value"),
        ),
        default='OFF',
    )
    clarity_debug_range: StringProperty(
        name="Debug Range",
        default="",
        options={'HIDDEN'},
    )
    clarity_debug_min: FloatProperty(default=0.0, options={'HIDDEN'})
    clarity_debug_max: FloatProperty(default=1.0, options={'HIDDEN'})
    clarity_debug_previous_color_type: StringProperty(default="", options={'HIDDEN'})
    clarity_debug_previous_light: StringProperty(default="", options={'HIDDEN'})

    # Clarity foliage normal proxy.
    clarity_normal_proxy_object: PointerProperty(
        name="Normal Proxy",
        description="Proxy surface used to generate smooth foliage normals",
        type=bpy.types.Object,
        poll=mesh_object_poll,
    )
    clarity_proxy_mode: EnumProperty(
        name="Proxy Shape",
        description="Choose a fitted SDF shell or an upward-facing hemisphere normal proxy",
        items=(
            ('SDF', "SDF Surface", "Build a tight surface around the foliage"),
            ('HEMISPHERE', "Upper Hemisphere", "Build a hemisphere whose normals never point down"),
        ),
        default='SDF',
    )
    clarity_proxy_resolution: IntProperty(
        name="Resolution", default=128, min=8, max=256
    )
    clarity_proxy_tightness: FloatProperty(
        name="Tightness", default=0.7, min=0.0, max=1.0
    )
    clarity_proxy_smooth_iterations: IntProperty(
        name="Blur Iterations", default=5, min=0, max=5
    )
    clarity_proxy_weld: BoolProperty(name="Weld Proxy", default=True)
    clarity_proxy_weld_distance: FloatProperty(
        name="Weld Distance", default=0.0001, min=0.0, soft_max=0.01,
        precision=6, subtype='DISTANCE',
    )
    clarity_normal_influence: FloatProperty(
        name="Proxy Influence", default=1.0, min=0.0, max=1.0
    )
    clarity_normal_upward_bias: FloatProperty(
        name="Upward Bias", default=0.25, min=0.0, max=1.0
    )
    clarity_normal_force_smooth: BoolProperty(name="Smooth Shading", default=True)
    clarity_normal_debug_mode: EnumProperty(
        name="Normal Preview",
        description="Draw original and transferred corner normals in the 3D viewport",
        items=(
            ('OFF', "Off", "Hide foliage normal visualization"),
            ('BEFORE', "Before", "Show normals saved before the first transfer"),
            ('RESULT', "Result", "Show the current transferred normals"),
            ('BOTH', "Both", "Overlay original and current normals"),
        ),
        default='OFF',
    )
    clarity_normal_debug_size: FloatProperty(
        name="Normal Size",
        description="Length multiplier for viewport normal lines",
        default=1.0,
        min=0.05,
        soft_max=10.0,
    )

    # Preview
    preview_wind_strength: FloatProperty(
        name="Sway Strength", default=0.12, min=0.0, soft_max=2.0,
        subtype='DISTANCE', options={'HIDDEN'},
    )
    preview_wind_speed: FloatProperty(
        name="Sway Cycles",
        description="Whole sway cycles across the scene frame range; rounded to an integer for a seamless loop",
        default=1.0,
        min=1.0,
        soft_max=10.0,
        options={'HIDDEN'},
    )
    preview_wind_spatial: FloatProperty(
        name="Flutter Phase Spread",
        description="Scales the stable per-island flutter phase offset",
        default=0.65,
        min=0.0,
        soft_max=10.0,
        options={'HIDDEN'},
    )
    preview_wind_direction: FloatVectorProperty(
        name="Wind Direction", default=(1.0, 0.25, 0.0), size=3,
        subtype='DIRECTION', options={'HIDDEN'},
    )
    preview_flutter_strength: FloatProperty(
        name="Leaf Flutter", default=0.035, min=0.0, soft_max=0.5,
        subtype='DISTANCE', options={'HIDDEN'},
    )
    preview_flutter_speed: FloatProperty(
        name="Flutter Cycles",
        description="Whole flutter cycles across the scene frame range; rounded to an integer for a seamless loop",
        default=4.0,
        min=1.0,
        soft_max=20.0,
        options={'HIDDEN'},
    )

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
    show_materials: BoolProperty(name="Material Preview", default=True)

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
    bl_description = "Modal, cancellable and atomic bake of the selected RGB channels"
    bl_options = {'REGISTER', 'UNDO'}

    channel: EnumProperty(
        name="Channel",
        items=(
            ('ALL', 'All RGB', ''),
            ('R', 'R - Flutter', ''),
            ('G', 'G - AO', ''),
            ('B', 'B - Variation', ''),
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

        mapping = {'ALL': CH_ALL, 'R': CH_R, 'G': CH_G, 'B': CH_B}
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
        if not _is_script_tool_window(context.window):
            return None

        window, area, region = _find_clarity_editor_context(context)
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
    bl_label = "Cancel Active Operation"
    bl_description = "Request safe cancellation of the active TreeVDB operation"

    def execute(self, context):
        s = context.scene.tree_vertex_data_settings
        if not s.bake_running:
            self.report({'INFO'}, "No TreeVDB operation is running.")
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
    bl_label = "Create / Update Materials"
    bl_description = "Rebuild the current TreeVDB material and wind preview from the latest script"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        s = context.scene.tree_vertex_data_settings
        if s.bake_running:
            self.report({'WARNING'}, "Cancel the current bake first.")
            return {'CANCELLED'}
        try:
            validate_settings(context, s, for_write=True)
            clarity_preview_enabled = clarity_wind_preview_enabled(s)
            ensure_color_attribute(
                s.trunk_object.data, s.attribute_name.strip(), False, s.replace_incompatible_attribute
            )
            ensure_color_attribute(
                s.leaves_object.data, s.attribute_name.strip(), True, s.replace_incompatible_attribute
            )
            mats = setup_tree_materials(s)
            clarity_modifiers = clarity_setup_wind_preview(
                s, clarity_enabled=clarity_preview_enabled
            )
            s.last_status = (
                f"Updated {len(mats)} material(s) and "
                f"{len(clarity_modifiers)} shader wind preview(s)."
            )
            self.report({'INFO'}, s.last_status)
            return {'FINISHED'}
        except Exception as exc:
            s.last_status = f"Material setup failed: {exc}"
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}


class CLARITY_OT_ToggleTreeWindPreview(Operator):
    bl_idname = "clarity.toggle_tree_wind_preview"
    bl_label = "Play / Stop Shader Wind"
    bl_description = "Start or stop the shader-style wind preview without keyframes"
    bl_options = {'REGISTER'}

    def execute(self, context):
        clarity_settings = context.scene.tree_vertex_data_settings
        try:
            clarity_enabled = clarity_wind_preview_enabled(clarity_settings)
            if clarity_enabled:
                clarity_set_wind_preview_enabled(clarity_settings, False)
                for clarity_window in context.window_manager.windows:
                    if clarity_window.screen is None or not clarity_window.screen.is_animation_playing:
                        continue
                    clarity_area = next(
                        (clarity_item for clarity_item in clarity_window.screen.areas
                         if clarity_item.type == 'VIEW_3D'),
                        clarity_window.screen.areas[0] if clarity_window.screen.areas else None,
                    )
                    if clarity_area is not None:
                        with context.temp_override(window=clarity_window, area=clarity_area):
                            bpy.ops.screen.animation_cancel(restore_frame=False)
                    break
                clarity_settings.last_status = "Shader wind preview stopped."
            else:
                validate_settings(context, clarity_settings, for_write=True)
                if clarity_set_wind_preview_enabled(clarity_settings, True) == 0:
                    ensure_color_attribute(
                        clarity_settings.trunk_object.data,
                        clarity_settings.attribute_name.strip(),
                        False,
                        clarity_settings.replace_incompatible_attribute,
                    )
                    ensure_color_attribute(
                        clarity_settings.leaves_object.data,
                        clarity_settings.attribute_name.strip(),
                        True,
                        clarity_settings.replace_incompatible_attribute,
                    )
                    clarity_setup_wind_preview(clarity_settings, clarity_enabled=True)
                clarity_window, clarity_area, clarity_region = _find_clarity_editor_context(context)
                if clarity_window is None or clarity_area is None:
                    raise RuntimeError("No regular Blender editor is available for playback.")
                clarity_override = {'window': clarity_window, 'area': clarity_area}
                if clarity_region is not None:
                    clarity_override['region'] = clarity_region
                with context.temp_override(**clarity_override):
                    if not clarity_window.screen.is_animation_playing:
                        bpy.ops.screen.animation_play()
                clarity_settings.last_status = "Shader wind preview playing."
            _tag_tree_tool_redraw()
            return {'FINISHED'}
        except Exception as clarity_exception:
            clarity_set_wind_preview_enabled(clarity_settings, False)
            clarity_settings.last_status = f"Shader wind preview failed: {clarity_exception}"
            self.report({'ERROR'}, str(clarity_exception))
            return {'CANCELLED'}


class CLARITY_OT_SetVertexDebugChannel(Operator):
    bl_idname = "clarity.set_vertex_debug_channel"
    bl_label = "Set Vertex Debug Channel"
    bl_description = "Show a baked TreeVertexData channel directly in the viewport"
    bl_options = {'REGISTER', 'UNDO'}

    channel: EnumProperty(
        name="Channel",
        items=(
            ('OFF', "Off", "Show regular materials"),
            ('R', "R Flutter", "Show the flutter mask"),
            ('G', "G AO", "Show ambient occlusion"),
            ('B', "B Variation", "Show leaf variation"),
        ),
        default='OFF',
    )

    def execute(self, context):
        clarity_settings = context.scene.tree_vertex_data_settings
        try:
            validate_settings(context, clarity_settings, for_write=True)
            ensure_color_attribute(
                clarity_settings.trunk_object.data,
                clarity_settings.attribute_name.strip(),
                False,
                clarity_settings.replace_incompatible_attribute,
            )
            ensure_color_attribute(
                clarity_settings.leaves_object.data,
                clarity_settings.attribute_name.strip(),
                True,
                clarity_settings.replace_incompatible_attribute,
            )
            clarity_settings.clarity_debug_channel = self.channel
            (
                clarity_settings.clarity_debug_min,
                clarity_settings.clarity_debug_max,
            ) = clarity_debug_range_values(clarity_settings, self.channel)
            clarity_settings.clarity_debug_range = clarity_debug_range_text(
                clarity_settings,
                self.channel,
            )
            if self.channel == 'OFF':
                clarity_restored_materials = clarity_restore_original_materials(clarity_settings)
                clarity_materials = []
            else:
                clarity_restored_materials = 0
                clarity_materials = setup_tree_materials(clarity_settings)
            clarity_update_solid_debug_attribute(clarity_settings)
            clarity_set_solid_debug_view(
                context,
                clarity_settings,
                self.channel != 'OFF',
            )
            clarity_label = dict(
                OFF='regular material',
                R='R Flutter',
                G='G AO',
                B='B Variation',
            )[self.channel]
            clarity_settings.last_status = (
                f"Debug preview: {clarity_label}; "
                + (
                    f"restored {clarity_restored_materials} original material slot(s). "
                    if self.channel == 'OFF'
                    else f"updated {len(clarity_materials)} material(s). "
                )
                + f"{clarity_settings.clarity_debug_range}"
            )
            self.report({'INFO'}, clarity_settings.last_status)
            return {'FINISHED'}
        except Exception as clarity_exception:
            clarity_settings.last_status = f"Debug preview failed: {clarity_exception}"
            self.report({'ERROR'}, str(clarity_exception))
            return {'CANCELLED'}


class CLARITY_OT_SetFoliageNormalDebug(Operator):
    bl_idname = "clarity.set_foliage_normal_debug"
    bl_label = "Set Foliage Normal Preview"
    bl_description = "Display original or transferred foliage normals in the 3D viewport"

    mode: EnumProperty(
        name="Mode",
        items=(
            ('OFF', "Off", "Hide normal lines"),
            ('BEFORE', "Before", "Show original normals in blue"),
            ('RESULT', "Result", "Show transferred normals in orange"),
            ('BOTH', "Both", "Overlay original and transferred normals"),
        ),
        default='BOTH',
    )

    def execute(self, context):
        clarity_settings = context.scene.tree_vertex_data_settings
        if self.mode != 'OFF' and (
                clarity_settings.leaves_object is None
                or clarity_settings.leaves_object.type != 'MESH'):
            self.report({'ERROR'}, "Choose a Leaves mesh first.")
            return {'CANCELLED'}
        clarity_settings.clarity_normal_debug_mode = self.mode
        clarity_enable_normal_debug(clarity_settings)
        clarity_label = {
            'OFF': "Normal preview disabled.",
            'BEFORE': "Showing original normals in blue.",
            'RESULT': "Showing current result normals in orange.",
            'BOTH': "Showing original blue and result orange normals.",
        }[self.mode]
        clarity_settings.last_status = clarity_label
        self.report({'INFO'}, clarity_label)
        return {'FINISHED'}


class _ClarityNormalModalOperator:
    _timer = None
    _generator = None
    _settings = None
    _started = 0.0
    _last_logged_status = None
    clarity_operator_name = ""
    clarity_job_label = "Normal operation"

    def _cleanup(self, context):
        if self.clarity_operator_name == "build_foliage_normal_proxy":
            clarity_proxy_log("operator-cleanup-begin")
        clarity_settings = self._settings or context.scene.tree_vertex_data_settings
        if self._timer is not None:
            try:
                context.window_manager.event_timer_remove(self._timer)
            except Exception:
                pass
            self._timer = None
        context.window_manager.progress_end()
        clarity_settings.bake_running = False
        clarity_settings.bake_cancel_requested = False
        self._generator = None
        self._settings = None
        if self.clarity_operator_name == "build_foliage_normal_proxy":
            clarity_proxy_log("operator-cleanup-complete")

    def _redirect_from_tool_window(self, context):
        if not _is_script_tool_window(context.window):
            return None
        clarity_window, clarity_area, clarity_region = _find_clarity_editor_context(context)
        if clarity_window is None or clarity_area is None:
            self.report({'ERROR'}, 'No normal Blender window is available to host the operation.')
            return {'CANCELLED'}
        clarity_override = {'window': clarity_window, 'area': clarity_area}
        if clarity_region is not None:
            clarity_override['region'] = clarity_region
        try:
            with context.temp_override(**clarity_override):
                clarity_operator = getattr(bpy.ops.clarity, self.clarity_operator_name)
                clarity_result = clarity_operator('INVOKE_DEFAULT')
        except Exception as clarity_exception:
            self.report({'ERROR'}, f'Could not start operation: {clarity_exception}')
            return {'CANCELLED'}
        return {'CANCELLED'} if 'CANCELLED' in clarity_result else {'FINISHED'}

    def _make_generator(self, clarity_settings):
        raise NotImplementedError

    def _finish_result(self, clarity_settings, clarity_result):
        raise NotImplementedError

    def _start(self, context):
        clarity_settings = context.scene.tree_vertex_data_settings
        if clarity_settings.bake_running:
            self.report({'WARNING'}, "Another TreeVDB operation is already running.")
            return {'CANCELLED'}
        try:
            if self.clarity_operator_name == "build_foliage_normal_proxy":
                clarity_leaves = clarity_settings.leaves_object
                clarity_proxy_log_reset(
                    blender=".".join(str(clarity_value) for clarity_value in bpy.app.version),
                    blend=bpy.data.filepath or "<unsaved>",
                    leaves=clarity_leaves.name if clarity_leaves else "<none>",
                    proxy_mode=clarity_settings.clarity_proxy_mode,
                    resolution=clarity_settings.clarity_proxy_resolution,
                    tightness=clarity_settings.clarity_proxy_tightness,
                    blur=clarity_settings.clarity_proxy_smooth_iterations,
                    weld=clarity_settings.clarity_proxy_weld,
                )
                log_info(f"Proxy diagnostic log: {CLARITY_PROXY_LOG_PATH}")
                self._last_logged_status = None
            self._settings = clarity_settings
            self._generator = self._make_generator(clarity_settings)
        except Exception as clarity_exception:
            clarity_settings.last_status = f"{self.clarity_job_label} failed: {clarity_exception}"
            self.report({'ERROR'}, str(clarity_exception))
            return {'CANCELLED'}
        self._started = time.perf_counter()
        clarity_settings.bake_running = True
        clarity_settings.bake_cancel_requested = False
        clarity_settings.bake_progress = 0.0
        clarity_settings.bake_status = f"{self.clarity_job_label}: starting…"
        clarity_settings.last_status = ""
        clarity_settings.last_warning_count = 0
        clarity_window_manager = context.window_manager
        clarity_window_manager.progress_begin(0, 1000)
        self._timer = clarity_window_manager.event_timer_add(0.01, window=context.window)
        clarity_window_manager.modal_handler_add(self)
        _tag_tree_tool_redraw()
        return {'RUNNING_MODAL'}

    def invoke(self, context, event):
        clarity_redirected = self._redirect_from_tool_window(context)
        if clarity_redirected is not None:
            return clarity_redirected
        return self._start(context)

    def execute(self, context):
        clarity_redirected = self._redirect_from_tool_window(context)
        if clarity_redirected is not None:
            return clarity_redirected
        return self._start(context)

    def modal(self, context, event):
        clarity_settings = self._settings or context.scene.tree_vertex_data_settings
        if event.type == 'ESC' or clarity_settings.bake_cancel_requested:
            if self._generator is not None:
                try:
                    self._generator.close()
                except Exception:
                    pass
            clarity_elapsed = time.perf_counter() - self._started
            clarity_settings.bake_status = "Cancelled"
            clarity_settings.last_status = (
                f"{self.clarity_job_label} cancelled after {clarity_elapsed:.2f}s; "
                "no partial result was committed."
            )
            self._cleanup(context)
            _tag_tree_tool_redraw()
            self.report({'WARNING'}, clarity_settings.last_status)
            return {'CANCELLED'}
        if event.type != 'TIMER':
            return {'PASS_THROUGH'}

        clarity_deadline = time.perf_counter() + (
            max(2, clarity_settings.modal_budget_ms) / 1000.0
        )
        try:
            while time.perf_counter() < clarity_deadline:
                clarity_progress, clarity_status = next(self._generator)
                clarity_progress = clamp01(clarity_progress)
                clarity_settings.bake_progress = clarity_progress
                clarity_settings.bake_status = f"{self.clarity_job_label}: {clarity_status}"
                if (
                        self.clarity_operator_name == "build_foliage_normal_proxy"
                        and clarity_status != self._last_logged_status):
                    clarity_proxy_log(
                        "modal-stage",
                        status=clarity_status,
                        progress=round(clarity_progress, 6),
                    )
                    self._last_logged_status = clarity_status
                context.window_manager.progress_update(int(clarity_progress * 1000))
                _tag_tree_tool_redraw()
                if clarity_progress >= 0.96:
                    break
        except StopIteration as clarity_stop:
            try:
                if self.clarity_operator_name == "build_foliage_normal_proxy":
                    clarity_proxy_log("operator-generator-stopped")
                clarity_settings.bake_progress = 1.0
                clarity_settings.bake_status = "Complete"
                if self.clarity_operator_name == "build_foliage_normal_proxy":
                    clarity_proxy_log("operator-finish-result-begin")
                self._finish_result(clarity_settings, clarity_stop.value)
                if self.clarity_operator_name == "build_foliage_normal_proxy":
                    clarity_proxy_log("operator-finish-result-complete")
            except Exception as clarity_exception:
                if self.clarity_operator_name == "build_foliage_normal_proxy":
                    clarity_proxy_log(
                        "operator-commit-exception", error=repr(clarity_exception)
                    )
                clarity_settings.bake_status = "Commit failed"
                clarity_settings.last_status = (
                    f"{self.clarity_job_label} commit failed: {clarity_exception}"
                )
                self._cleanup(context)
                _tag_tree_tool_redraw()
                self.report({'ERROR'}, str(clarity_exception))
                return {'CANCELLED'}
            self._cleanup(context)
            _tag_tree_tool_redraw()
            self.report({'INFO'}, clarity_settings.last_status)
            if self.clarity_operator_name == "build_foliage_normal_proxy":
                clarity_proxy_log("operator-return-finished")
            return {'FINISHED'}
        except Exception as clarity_exception:
            if self.clarity_operator_name == "build_foliage_normal_proxy":
                clarity_proxy_log(
                    "operator-generator-exception", error=repr(clarity_exception)
                )
            clarity_settings.bake_status = "Failed"
            clarity_settings.last_status = (
                f"{self.clarity_job_label} failed: {clarity_exception}"
            )
            self._cleanup(context)
            _tag_tree_tool_redraw()
            self.report({'ERROR'}, str(clarity_exception))
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}

    def cancel(self, context):
        if self._generator is not None:
            try:
                self._generator.close()
            except Exception:
                pass
        self._cleanup(context)


class CLARITY_OT_BuildFoliageNormalProxy(_ClarityNormalModalOperator, Operator):
    bl_idname = "clarity.build_foliage_normal_proxy"
    bl_label = "Build Normal Proxy"
    bl_description = "Build or update a proxy surface around the Leaves mesh"
    # Proxy geometry is fully reconstructible. A global undo snapshot taken after
    # FINISHED can duplicate a high-resolution proxy and exhaust memory.
    bl_options = {'REGISTER'}
    clarity_operator_name = "build_foliage_normal_proxy"
    clarity_job_label = "Normal proxy"

    def _make_generator(self, clarity_settings):
        return clarity_build_foliage_proxy_generator(
            clarity_settings.leaves_object,
            clarity_settings.trunk_object,
            clarity_settings.clarity_normal_proxy_object,
            clarity_settings.clarity_proxy_mode,
            clarity_settings.up_axis,
            clarity_settings.clarity_proxy_resolution,
            clarity_settings.clarity_proxy_tightness,
            clarity_settings.clarity_proxy_smooth_iterations,
            clarity_settings.clarity_proxy_weld,
            clarity_settings.clarity_proxy_weld_distance,
        )

    def _finish_result(self, clarity_settings, clarity_proxy):
        clarity_settings.clarity_normal_proxy_object = clarity_proxy
        clarity_settings.last_status = (
            f'Built normal proxy "{clarity_proxy.name}": '
            f'{len(clarity_proxy.data.vertices):,} verts, '
            f'{len(clarity_proxy.data.polygons):,} faces.'
        )


class CLARITY_OT_TransferFoliageNormals(_ClarityNormalModalOperator, Operator):
    bl_idname = "clarity.transfer_foliage_normals"
    bl_label = "Transfer Normals to Leaves"
    bl_description = "Transfer smooth proxy normals to the Leaves mesh without changing its geometry"
    bl_options = {'REGISTER', 'UNDO'}
    clarity_operator_name = "transfer_foliage_normals"
    clarity_job_label = "Normal transfer"

    def _make_generator(self, clarity_settings):
        clarity_leaves = clarity_settings.leaves_object
        if clarity_leaves is not None and clarity_leaves.data.users > 1:
            raise RuntimeError("Make the Leaves mesh Single User before transferring normals.")
        return clarity_transfer_foliage_normals_generator(
            clarity_leaves,
            clarity_settings.clarity_normal_proxy_object,
            clarity_settings.clarity_normal_influence,
            clarity_settings.clarity_normal_upward_bias,
            clarity_settings.up_axis,
            clarity_settings.clarity_normal_force_smooth,
        )

    def _finish_result(self, clarity_settings, clarity_count):
        clarity_settings.last_status = (
            f"Transferred proxy normals to {clarity_count:,} leaf vertices."
        )
        clarity_refresh_normal_debug()


class CLARITY_OT_RestoreFoliageNormals(Operator):
    bl_idname = "clarity.restore_foliage_normals"
    bl_label = "Restore Original Normals"
    bl_description = "Restore the corner normals saved before the first proxy transfer"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        clarity_settings = context.scene.tree_vertex_data_settings
        try:
            clarity_restore_foliage_normals(clarity_settings.leaves_object)
            clarity_refresh_normal_debug()
            clarity_settings.last_status = "Restored original foliage normals."
            self.report({'INFO'}, clarity_settings.last_status)
            return {'FINISHED'}
        except Exception as clarity_exception:
            clarity_settings.last_status = f"Normal restore failed: {clarity_exception}"
            self.report({'ERROR'}, str(clarity_exception))
            return {'CANCELLED'}


class CLARITY_OT_DeleteFoliageNormalProxy(Operator):
    bl_idname = "clarity.delete_foliage_normal_proxy"
    bl_label = "Delete Normal Proxy"
    bl_description = "Delete the Clarity-owned foliage normal proxy object"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        clarity_settings = context.scene.tree_vertex_data_settings
        clarity_proxy = clarity_settings.clarity_normal_proxy_object
        try:
            clarity_settings.clarity_normal_proxy_object = None
            clarity_delete_foliage_proxy(clarity_proxy)
            clarity_settings.last_status = "Deleted foliage normal proxy."
            self.report({'INFO'}, clarity_settings.last_status)
            return {'FINISHED'}
        except Exception as clarity_exception:
            clarity_settings.clarity_normal_proxy_object = clarity_proxy
            clarity_settings.last_status = f"Proxy deletion failed: {clarity_exception}"
            self.report({'ERROR'}, str(clarity_exception))
            return {'CANCELLED'}


class TREEVDB_OT_ResetDefaults(Operator):
    bl_idname = "tree_vdb.reset_defaults"
    bl_label = "Reset Bake Defaults"
    bl_description = "Reset the main TreeVDB bake and material settings"
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
            'variation_min', 'variation_max',
            'leaf_flutter_anchor_band', 'clarity_flutter_power',
            'clarity_leaf_merge_epsilon', 'shader_ao_strength', 'shader_canopy_strength',
            'shader_variation_strength', 'preview_wind_strength', 'preview_wind_speed',
            'preview_wind_spatial', 'preview_wind_direction', 'preview_flutter_strength',
            'preview_flutter_speed', 'modal_budget_ms',
            'clarity_debug_channel',
            'clarity_proxy_mode', 'clarity_proxy_resolution', 'clarity_proxy_tightness',
            'clarity_proxy_smooth_iterations', 'clarity_proxy_weld',
            'clarity_proxy_weld_distance', 'clarity_normal_influence',
            'clarity_normal_upward_bias', 'clarity_normal_force_smooth',
            'clarity_normal_debug_mode', 'clarity_normal_debug_size',
        )
        for prop in props:
            try:
                s.property_unset(prop)
            except Exception:
                pass
        clarity_enable_normal_debug(s)
        s.last_status = "TreeVDB settings reset to defaults."
        return {'FINISHED'}


# =============================================================================
# UI
# =============================================================================

# One colour per baked channel, used by the legend, the per-channel panels and the
# bake buttons alike, so the window teaches the mapping once instead of three times.
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
}

CHANNEL_LABELS = (
    ('R', 'Flutter'),
    ('G', 'AO'),
    ('B', 'Variation'),
)

# Spelled out in each channel panel's header.
CHANNEL_NAMES = {
    'R': 'Red',
    'G': 'Green',
    'B': 'Blue',
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

    # Channel legend. Equal cells rather than one packed string, so each colour
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
    op = row.operator('tree_vdb.bake', text='BAKE ALL RGB', icon='RENDER_STILL')
    op.channel = 'ALL'

    # Same colours as the legend and the per-channel panels, in the same order.
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
    if abs(s.ao_max - s.ao_min) <= 1e-6:
        layout.label(text='Min = Max: preserving calculated AO range.', icon='INFO')


def _draw_canopy_body(layout, s):
    _draw_pair(layout, s, 'canopy_samples', 'Samples', 'canopy_radius', 'Radius')
    _draw_pair(layout, s, 'canopy_bias', 'Outer Bias', 'canopy_power', 'Depth Power')


def _draw_variation_body(layout, s):
    layout.prop(s, 'variation_seed', text='Seed')
    _draw_pair(layout, s, 'variation_min', 'Min', 'variation_max', 'Max')


def _draw_foliage_normals_body(layout, s):
    if s.bake_running and s.bake_status.startswith('Normal'):
        clarity_progress = layout.row(align=True)
        clarity_progress.prop(
            s,
            'bake_progress',
            text=s.bake_status,
            slider=True,
        )
        clarity_progress.operator('tree_vdb.cancel_bake', text='', icon='CANCEL')
    clarity_controls = layout.column()
    clarity_controls.enabled = not s.bake_running
    clarity_controls.prop(s, 'clarity_normal_proxy_object', text='Proxy')
    clarity_controls.prop(s, 'clarity_proxy_mode', text='Shape')
    clarity_controls.prop(
        s,
        'clarity_proxy_resolution',
        text='Segments' if s.clarity_proxy_mode == 'HEMISPHERE' else 'Resolution',
    )
    if s.clarity_proxy_mode == 'SDF':
        _draw_pair(clarity_controls, s, 'clarity_proxy_tightness', 'Tightness',
                   'clarity_proxy_smooth_iterations', 'Blur')
        clarity_controls.prop(s, 'clarity_proxy_weld', text='Weld Proxy')
        if s.clarity_proxy_weld:
            clarity_controls.prop(s, 'clarity_proxy_weld_distance', text='Weld Distance')

    clarity_row = clarity_controls.row()
    clarity_row.scale_y = 1.15
    clarity_row.operator('clarity.build_foliage_normal_proxy', text='BUILD / UPDATE PROXY')

    clarity_controls.separator()
    _draw_pair(clarity_controls, s, 'clarity_normal_influence', 'Proxy Influence',
               'clarity_normal_upward_bias', 'Upward Bias')
    clarity_controls.prop(s, 'clarity_normal_force_smooth', text='Smooth Shading')
    clarity_row = clarity_controls.row()
    clarity_row.scale_y = 1.15
    clarity_row.operator('clarity.transfer_foliage_normals', text='TRANSFER NORMALS TO LEAVES')
    clarity_row = clarity_controls.row(align=True)
    clarity_row.operator('clarity.restore_foliage_normals', text='Restore Normals')
    clarity_row.operator('clarity.delete_foliage_normal_proxy', text='Delete Proxy')

    clarity_controls.separator()
    clarity_controls.label(text='Viewport Normal Comparison', icon='NORMALS_VERTEX_FACE')
    clarity_row = clarity_controls.row(align=True)
    for clarity_mode, clarity_label in (
            ('OFF', 'Off'), ('BEFORE', 'Before'),
            ('RESULT', 'Result'), ('BOTH', 'Both')):
        clarity_operator = clarity_row.operator(
            'clarity.set_foliage_normal_debug',
            text=clarity_label,
            depress=s.clarity_normal_debug_mode == clarity_mode,
        )
        clarity_operator.mode = clarity_mode
    clarity_controls.prop(s, 'clarity_normal_debug_size', text='Line Size')
    clarity_colors = clarity_controls.row(align=True)
    clarity_colors.label(text='Before: blue')
    clarity_colors.label(text='Result: orange')
    clarity_controls.label(text='AO remains baked to vertex color G.', icon='INFO')


def _draw_preview_body(layout, s):
    # Setup is the primary action; put it before tuning.
    row = layout.row()
    row.scale_y = 1.15
    row.operator(
        'tree_vdb.setup_shaders_wind',
        text='CREATE / UPDATE MATERIALS',
        icon='NODE_MATERIAL',
    )
    clarity_playing = clarity_wind_preview_enabled(s)
    row = layout.row()
    row.scale_y = 1.15
    row.operator(
        'clarity.toggle_tree_wind_preview',
        text='STOP SHADER WIND' if clarity_playing else 'PLAY SHADER WIND',
        icon='PAUSE' if clarity_playing else 'PLAY',
    )


def _draw_preview_shading_body(layout, s):
    layout.prop(s, 'shader_ao_strength', text='AO')
    layout.prop(s, 'shader_variation_strength', text='Variation')


def _draw_preview_motion_body(layout, s):
    _draw_pair(layout, s, 'preview_wind_strength', 'Sway Strength',
               'preview_wind_speed', 'Sway Cycles')
    layout.prop(s, 'preview_wind_direction', text='Direction')
    layout.prop(s, 'preview_wind_spatial', text='Flutter Phase Spread')
    _draw_pair(layout, s, 'preview_flutter_strength', 'Flutter Strength',
               'preview_flutter_speed', 'Flutter Cycles')


def _draw_debug_body(layout, s):
    clarity_off = layout.row()
    clarity_off.scale_y = 1.1
    clarity_operator = clarity_off.operator(
        'clarity.set_vertex_debug_channel',
        text='REGULAR MATERIAL',
        icon='MATERIAL',
        depress=s.clarity_debug_channel == 'OFF',
    )
    clarity_operator.channel = 'OFF'

    clarity_row = layout.row(align=True)
    for clarity_channel, clarity_label in (
            ('R', 'Flutter'), ('G', 'AO'), ('B', 'Variation')):
        clarity_operator = clarity_row.operator(
            'clarity.set_vertex_debug_channel',
            text=clarity_label,
            icon_value=_channel_icon(clarity_channel),
            depress=s.clarity_debug_channel == clarity_channel,
        )
        clarity_operator.channel = clarity_channel

    clarity_description = {
        'OFF': 'Regular material preview is active.',
        'R': 'R Flutter: stored min = black, max = white.',
        'G': 'G AO: stored min = black, max = white.',
        'B': 'B Variation: stored min = black, max = white.',
    }.get(s.clarity_debug_channel, 'Regular material preview is active.')
    layout.label(text=clarity_description, icon='INFO')
    if s.clarity_debug_range:
        layout.label(text=s.clarity_debug_range)


def _draw_advanced_body(layout, s):
    layout.prop(s, 'leaf_sampling_mode', text='Leaf Sampling')
    if s.leaf_sampling_mode == 'AUTO':
        layout.prop(s, 'leaf_island_max_vertices', text='Auto Island Max')
    layout.prop(s, 'max_leaf_hits', text='Max Leaf Hits')
    layout.prop(s, 'clarity_leaf_merge_epsilon', text='Leaf Merge Epsilon')

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


def _find_clarity_editor_context(context):
    """Find a regular Blender editor that can own the modal bake operation.

    The dedicated TreeVDB utility window is UI-only and should not become the
    execution context for the modal bake operator.
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
    bl_order = 4

    def draw_header(self, context):
        self.layout.label(text='', icon_value=_channel_icon('G'))

    def draw_header_preset(self, context):
        _draw_channel_header_name(self, 'G')

    def draw(self, context):
        _draw_ao_body(*_panel_body(self, context))


@TreeVDBToolWindow.panel
class TREEVDB_PT_canopy(_TreeVDBPanelMixin, Panel):
    bl_idname = 'TREEVDB_PT_canopy'
    bl_label = 'Leaf Flutter Mask'
    bl_options = {'DEFAULT_CLOSED'}
    bl_order = 3

    def draw_header(self, context):
        self.layout.label(text='', icon_value=_channel_icon('R'))

    def draw_header_preset(self, context):
        _draw_channel_header_name(self, 'R')

    def draw(self, context):
        layout, s = _panel_body(self, context)
        layout.prop(s, 'leaf_flutter_anchor_band', text='Anchor Band')
        layout.prop(s, 'clarity_flutter_power', text='Flutter Stiffness')


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
class CLARITY_PT_foliage_normals(_TreeVDBPanelMixin, Panel):
    bl_idname = 'CLARITY_PT_foliage_normals'
    bl_label = 'Foliage Normals & Proxy'
    bl_options = {'DEFAULT_CLOSED'}
    bl_order = 7

    def draw_header(self, context):
        self.layout.label(text='', icon='MOD_REMESH')

    def draw(self, context):
        clarity_layout = self.layout
        clarity_layout.use_property_split = True
        clarity_layout.use_property_decorate = False
        _draw_foliage_normals_body(
            clarity_layout,
            context.scene.tree_vertex_data_settings,
        )


@TreeVDBToolWindow.panel
class TREEVDB_PT_preview(_TreeVDBPanelMixin, Panel):
    bl_idname = 'TREEVDB_PT_preview'
    bl_label = 'Material Preview'
    bl_options = {'DEFAULT_CLOSED'}
    bl_order = 8

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
class CLARITY_PT_preview_motion(_TreeVDBPanelMixin, Panel):
    bl_idname = 'CLARITY_PT_preview_motion'
    bl_parent_id = 'TREEVDB_PT_preview'
    bl_label = 'Motion'
    bl_options = {'DEFAULT_CLOSED'}
    bl_order = 1

    def draw(self, context):
        _draw_preview_motion_body(*_panel_body(self, context))


@TreeVDBToolWindow.panel
class CLARITY_PT_debug_preview(_TreeVDBPanelMixin, Panel):
    bl_idname = 'CLARITY_PT_debug_preview'
    bl_label = 'Debug Preview'
    bl_options = {'DEFAULT_CLOSED'}
    bl_order = 9

    def draw_header(self, context):
        self.layout.label(text='', icon='SHADING_RENDERED')

    def draw(self, context):
        _draw_debug_body(*_panel_body(self, context))


@TreeVDBToolWindow.panel
class TREEVDB_PT_advanced(_TreeVDBPanelMixin, Panel):
    bl_idname = 'TREEVDB_PT_advanced'
    bl_label = 'Advanced'
    bl_options = {'DEFAULT_CLOSED'}
    bl_order = 10

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
    CLARITY_OT_ToggleTreeWindPreview,
    CLARITY_OT_SetVertexDebugChannel,
    CLARITY_OT_SetFoliageNormalDebug,
    CLARITY_OT_BuildFoliageNormalProxy,
    CLARITY_OT_TransferFoliageNormals,
    CLARITY_OT_RestoreFoliageNormals,
    CLARITY_OT_DeleteFoliageNormalProxy,
    TREEVDB_OT_ResetDefaults,
    TREEVDB_OT_CloseToolWindow,
    TREEVDB_OT_ShowUI,
)


def unregister_existing_by_name():
    """Development-safe cleanup for Text Editor Run Script iterations."""

    clarity_remove_normal_debug()

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

    clarity_remove_normal_debug()

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
