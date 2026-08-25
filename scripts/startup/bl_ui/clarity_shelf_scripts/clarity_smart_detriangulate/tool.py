# SPDX-License-Identifier: MIT
# Smart Detriangulate for Blender
# Smart Detriangulate 2.5.0 logic adapted for Clarity
# UI language: English
# Blender Python 3 / BMesh

from __future__ import annotations

import math
import traceback
from dataclasses import dataclass, replace
from typing import Dict, List, Optional, Sequence, Set, Tuple

import bpy
import bmesh
from mathutils import Vector


bl_info = {
    "name": "Smart Detriangulate",
    "author": "Adapted for Clarity",
    "version": (2, 5, 0),
    "blender": (4, 3, 0),
    "location": "3D View > Sidebar > Tool > Smart Detriangulate",
    "description": "Smartly reconstruct quads from triangulated meshes",
    "category": "Mesh",
}


TOOL_TITLE = "Smart Detriangulate"
VERSION = "2.5.0-blender"
EPS = 1.0e-10
UV_EPS = 1.0e-6
HARD_SURFACE_CREASE_ANGLE = 80.0
RECONSTRUCT_MIN_ANGLE = 3.0
RECONSTRUCT_MAX_ANGLE = 177.0
RECONSTRUCT_MAX_DIAGONAL_RATIO = 60.0
RECONSTRUCT_MAX_TWIST = 1.25
STRICT_MAX_TWIST = 0.75
STRICT_MAX_DIAGONAL_NORMAL_DEVIATION = 65.0
COVERAGE_UTILITY_BONUS = 0.03
STRIP_ASPECT_RATIO = 2.2
STRUCTURAL_CONTINUATION_DOT = 0.965
STRUCTURAL_CONTINUATION_MIN_SCORE = 1.90
STRUCTURAL_CONTINUATION_PENALTY = 0.18


@dataclass
class Settings:
    analysis_mode: str = "auto"
    max_normal_angle: float = 12.0
    min_quad_angle: float = 25.0
    max_quad_angle: float = 155.0
    max_planarity_error: float = 0.015
    max_diagonal_ratio: float = 2.5
    min_quality: float = 0.58
    preserve_hard_edges: bool = True
    preserve_uv_seams: bool = True
    preserve_material_borders: bool = True
    blender_core_angle: float = 30.0
    selection_only: bool = False
    keep_history: bool = False  # Clarity uses undo, not construction history.
    reconstruct_all: bool = False
    use_blender_core: bool = False
    smart_fallback: bool = False
    allow_relaxed_blender_core: bool = False
    flow_reconstruct: bool = True
    symmetry_assist: bool = True
    ring_tube_detect: bool = True
    planar_patch_solve: bool = True


ANALYSIS_PRESETS = {
    "conservative": Settings(
        analysis_mode="conservative",
        max_normal_angle=10.0,
        min_quad_angle=28.0,
        max_quad_angle=152.0,
        max_planarity_error=0.01,
        max_diagonal_ratio=2.2,
        min_quality=0.64,
        preserve_hard_edges=True,
        preserve_uv_seams=True,
        preserve_material_borders=True,
    ),
    "balanced": Settings(
        analysis_mode="balanced",
        max_normal_angle=18.0,
        min_quad_angle=18.0,
        max_quad_angle=162.0,
        max_planarity_error=0.03,
        max_diagonal_ratio=3.5,
        min_quality=0.48,
        preserve_hard_edges=False,
        preserve_uv_seams=False,
        preserve_material_borders=True,
    ),
    "aggressive": Settings(
        analysis_mode="aggressive",
        max_normal_angle=179.0,
        min_quad_angle=4.0,
        max_quad_angle=176.0,
        max_planarity_error=0.35,
        max_diagonal_ratio=25.0,
        min_quality=0.08,
        preserve_hard_edges=False,
        preserve_uv_seams=False,
        preserve_material_borders=True,
    ),
    "reconstruct": Settings(
        analysis_mode="reconstruct",
        max_normal_angle=179.0,
        min_quad_angle=0.0,
        max_quad_angle=180.0,
        max_planarity_error=999.0,
        max_diagonal_ratio=999.0,
        min_quality=0.0,
        preserve_hard_edges=False,
        preserve_uv_seams=False,
        preserve_material_borders=True,
        reconstruct_all=True,
    ),
}


@dataclass
class Candidate:
    mesh: str  # Blender object name
    edge_id: int
    face_a: int
    face_b: int
    quality: float
    normal_angle: float
    planarity: float
    min_angle: float
    max_angle: float
    diagonal_ratio: float
    quad_vertices: Tuple[int, int, int, int] = (-1, -1, -1, -1)
    centroid: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    flow_score: float = 0.0
    symmetry_score: float = 0.0
    tube_score: float = 0.0
    planar_score: float = 0.0
    structural_score: float = 0.0
    solver_tags: str = ""


# -----------------------------------------------------------------------------
# Math helpers
# -----------------------------------------------------------------------------


def clamp(value, low, high):
    return max(low, min(high, value))


def settings_from_preset(name, base):
    preset = ANALYSIS_PRESETS.get(name, ANALYSIS_PRESETS["balanced"])
    return Settings(
        analysis_mode=name,
        max_normal_angle=preset.max_normal_angle,
        min_quad_angle=preset.min_quad_angle,
        max_quad_angle=preset.max_quad_angle,
        max_planarity_error=preset.max_planarity_error,
        max_diagonal_ratio=preset.max_diagonal_ratio,
        min_quality=preset.min_quality,
        preserve_hard_edges=preset.preserve_hard_edges,
        preserve_uv_seams=preset.preserve_uv_seams,
        preserve_material_borders=base.preserve_material_borders,
        blender_core_angle=base.blender_core_angle,
        selection_only=base.selection_only,
        keep_history=base.keep_history,
        reconstruct_all=preset.reconstruct_all,
        use_blender_core=base.use_blender_core,
        smart_fallback=base.smart_fallback,
        allow_relaxed_blender_core=base.allow_relaxed_blender_core,
        flow_reconstruct=base.flow_reconstruct,
        symmetry_assist=base.symmetry_assist,
        ring_tube_detect=base.ring_tube_detect,
        planar_patch_solve=base.planar_patch_solve,
    )


def is_reconstruct_mode(settings):
    return settings.reconstruct_all or "reconstruct" in settings.analysis_mode


def angle_degrees(a: Vector, b: Vector):
    la, lb = a.length, b.length
    if la < EPS or lb < EPS:
        return 180.0
    return math.degrees(math.acos(clamp(a.dot(b) / (la * lb), -1.0, 1.0)))


def distance(a: Vector, b: Vector):
    return (a - b).length


def triangle_area(a: Vector, b: Vector, c: Vector):
    return 0.5 * (b - a).cross(c - a).length


def newell_vector(points: Sequence[Vector]):
    n = Vector((0.0, 0.0, 0.0))
    count = len(points)
    for i in range(count):
        p = points[i]
        q = points[(i + 1) % count]
        n.x += (p.y - q.y) * (p.z + q.z)
        n.y += (p.z - q.z) * (p.x + q.x)
        n.z += (p.x - q.x) * (p.y + q.y)
    return n


def normalized_newell(points: Sequence[Vector]):
    n = newell_vector(points)
    return n.normalized() if n.length > EPS else Vector((0.0, 0.0, 0.0))


def triangle_normal_from_points(a: Vector, b: Vector, c: Vector):
    n = (b - a).cross(c - a)
    return n.normalized() if n.length > EPS else Vector((0.0, 0.0, 0.0))


def edge_key(a, b):
    return (a, b) if a < b else (b, a)


def triangle_edges(vertices):
    return [(vertices[i], vertices[(i + 1) % 3]) for i in range(3)]


# -----------------------------------------------------------------------------
# Blender mesh access
# -----------------------------------------------------------------------------


def _unique_mesh_objects(objects):
    result = []
    seen_data = set()
    for obj in objects:
        if obj is None or obj.type != "MESH":
            continue
        ptr = obj.data.as_pointer()
        if ptr in seen_data:
            continue
        seen_data.add(ptr)
        result.append(obj)
    return result


def selected_mesh_objects(context=None):
    context = context or bpy.context
    if context.mode == "EDIT_MESH":
        objects = list(getattr(context, "objects_in_mode_unique_data", []) or [])
        if not objects:
            objects = [
                obj for obj in context.selected_objects
                if obj.type == "MESH" and obj.mode == "EDIT"
            ]
    else:
        objects = [obj for obj in context.selected_objects if obj.type == "MESH"]
    return _unique_mesh_objects(objects)


def _open_bmesh(obj):
    edit = obj.mode == "EDIT"
    if edit:
        bm = bmesh.from_edit_mesh(obj.data)
        owned = False
    else:
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        owned = True
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    bm.verts.index_update()
    bm.edges.index_update()
    bm.faces.index_update()
    bm.normal_update()
    return bm, owned


def _close_bmesh(obj, bm, owned, write=False, destructive=False):
    if owned:
        if write:
            bm.to_mesh(obj.data)
            obj.data.update()
        bm.free()
    elif write:
        bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=destructive)


def selected_face_ids_by_mesh(context=None):
    context = context or bpy.context
    result = {}
    if context.mode != "EDIT_MESH":
        return result
    for obj in selected_mesh_objects(context):
        bm, owned = _open_bmesh(obj)
        try:
            ids = {face.index for face in bm.faces if face.select and not face.hide}
            if ids:
                result[obj.name_full] = ids
        finally:
            _close_bmesh(obj, bm, owned, write=False)
    return result


def selected_face_components(context=None):
    """Compatibility helper: returns [(object_name, face_id), ...]."""
    result = []
    for obj_name, face_ids in selected_face_ids_by_mesh(context).items():
        result.extend((obj_name, face_id) for face_id in sorted(face_ids))
    return result


def count_mesh_triangles(objects):
    counts = {}
    for obj in objects:
        try:
            bm, owned = _open_bmesh(obj)
            try:
                faces = len(bm.faces)
                triangles = sum(1 for face in bm.faces if len(face.verts) == 3)
                counts[obj.name_full] = {"faces": faces, "triangles": triangles}
            finally:
                _close_bmesh(obj, bm, owned, write=False)
        except Exception:
            counts[obj.name_full] = {"faces": 0, "triangles": 0}
    return counts


def total_count(counts, key):
    return sum(item.get(key, 0) for item in counts.values())


# -----------------------------------------------------------------------------
# Topology / UV helpers
# -----------------------------------------------------------------------------


def _uv_layer_for_bmesh(bm):
    try:
        return bm.loops.layers.uv.active
    except Exception:
        return None


def edge_is_uv_seam(edge, face_a, face_b, uv_layer):
    # Blender's explicit seam flag is always treated as a UV boundary.
    if edge.seam:
        return True
    if uv_layer is None:
        return False

    edge_vert_ids = {edge.verts[0].index, edge.verts[1].index}

    def face_uvs(face):
        result = {}
        for loop in face.loops:
            vid = loop.vert.index
            if vid in edge_vert_ids:
                result[vid] = loop[uv_layer].uv.copy()
        return result

    uvs_a = face_uvs(face_a)
    uvs_b = face_uvs(face_b)
    if len(uvs_a) != 2 or len(uvs_b) != 2:
        return True
    for vid in edge_vert_ids:
        if vid not in uvs_a or vid not in uvs_b:
            return True
        if (uvs_a[vid] - uvs_b[vid]).length > UV_EPS:
            return True
    return False


def boundary_quad_options(tri_a, tri_b, edge_vertices):
    shared = set(edge_vertices)
    unique_a = [v for v in tri_a if v not in shared]
    unique_b = [v for v in tri_b if v not in shared]
    if len(unique_a) != 1 or len(unique_b) != 1:
        return []

    shared_key = edge_key(edge_vertices[0], edge_vertices[1])
    boundary_edges = []
    for a, b in triangle_edges(tri_a) + triangle_edges(tri_b):
        if edge_key(a, b) != shared_key:
            boundary_edges.append((a, b))

    adjacency = {}
    for a, b in boundary_edges:
        adjacency.setdefault(a, set()).add(b)
        adjacency.setdefault(b, set()).add(a)

    if len(boundary_edges) == 4 and len(adjacency) == 4 and all(
            len(neighbors) == 2 for neighbors in adjacency.values()):
        cycles = []
        start = unique_a[0]
        for first_neighbor in sorted(adjacency[start]):
            cycle = [start, first_neighbor]
            prev, current = start, first_neighbor
            while len(cycle) < 4:
                next_values = [v for v in adjacency[current] if v != prev]
                if not next_values:
                    break
                prev, current = current, next_values[0]
                cycle.append(current)
            if len(cycle) == 4 and start in adjacency[cycle[-1]]:
                cycles.append(tuple(cycle))
        unique_cycles = []
        seen = set()
        for cycle in cycles:
            key = min(cycle, tuple(reversed(cycle)))
            if key not in seen:
                seen.add(key)
                unique_cycles.append(cycle)
        if unique_cycles:
            return unique_cycles

    u, v = edge_vertices
    return [
        (unique_a[0], u, unique_b[0], v),
        (unique_a[0], v, unique_b[0], u),
    ]


def quad_metrics(vertex_ids, points, source_normal, source_area=None, tolerant=False):
    ids = list(vertex_ids)
    if len(ids) != 4 or len(set(ids)) != 4:
        return None
    quad = [points[i] for i in ids]
    n = normalized_newell(quad)
    if n.length < EPS:
        return None
    if n.dot(source_normal) < 0.0:
        ids = [ids[0], ids[3], ids[2], ids[1]]
        quad = [points[i] for i in ids]
        n = normalized_newell(quad)
        if n.length < EPS:
            return None

    angles, turns = [], []
    for i in range(4):
        prev_p = quad[(i - 1) % 4]
        curr_p = quad[i]
        next_p = quad[(i + 1) % 4]
        incoming = prev_p - curr_p
        outgoing = next_p - curr_p
        if incoming.length < EPS or outgoing.length < EPS:
            return None
        angles.append(angle_degrees(incoming, outgoing))
        turns.append((curr_p - prev_p).cross(next_p - curr_p).dot(n))
    if any(value <= EPS for value in turns):
        return None

    centroid = Vector((
        sum(p.x for p in quad) / 4.0,
        sum(p.y for p in quad) / 4.0,
        sum(p.z for p in quad) / 4.0,
    ))
    perimeter = sum(distance(quad[i], quad[(i + 1) % 4]) for i in range(4))
    scale = max(perimeter / 4.0, EPS)
    planarity = max(abs((p - centroid).dot(n)) for p in quad) / scale

    d1 = distance(quad[0], quad[2])
    d2 = distance(quad[1], quad[3])
    diagonal_ratio = max(d1, d2) / max(min(d1, d2), EPS)
    edge_lengths = [distance(quad[i], quad[(i + 1) % 4]) for i in range(4)]
    if min(edge_lengths) <= EPS:
        return None
    edge_ratio = max(edge_lengths) / max(min(edge_lengths), EPS)
    opposite_length_similarity = min(
        min(edge_lengths[0], edge_lengths[2]) / max(edge_lengths[0], edge_lengths[2], EPS),
        min(edge_lengths[1], edge_lengths[3]) / max(edge_lengths[1], edge_lengths[3], EPS),
    )
    edge_dirs = [
        (quad[(i + 1) % 4] - quad[i]).normalized()
        for i in range(4)
    ]
    opposite_direction_similarity = min(
        abs(edge_dirs[0].dot(edge_dirs[2])),
        abs(edge_dirs[1].dot(edge_dirs[3])),
    )
    twist = ((quad[0] - quad[1]) + (quad[2] - quad[3])).length / scale

    n012 = triangle_normal_from_points(quad[0], quad[1], quad[2])
    n023 = triangle_normal_from_points(quad[0], quad[2], quad[3])
    n013 = triangle_normal_from_points(quad[0], quad[1], quad[3])
    n123 = triangle_normal_from_points(quad[1], quad[2], quad[3])
    if min(n012.length, n023.length, n013.length, n123.length) < EPS:
        return None
    diagonal_normal_deviation = min(
        angle_degrees(n012, n023),
        angle_degrees(n013, n123),
    )

    if source_area is None:
        source_area = (
            triangle_area(quad[0], quad[1], quad[2]) +
            triangle_area(quad[0], quad[2], quad[3])
        )
    quad_area = 0.5 * newell_vector(quad).length
    area_consistency = min(source_area, quad_area) / max(source_area, quad_area, EPS)
    scaled_jacobian = min(
        abs(turns[i]) / max(edge_lengths[(i - 1) % 4] * edge_lengths[i], EPS)
        for i in range(4)
    )
    strip_score = clamp(
        (edge_ratio - STRIP_ASPECT_RATIO) / STRIP_ASPECT_RATIO,
        0.0,
        1.0,
    ) * opposite_length_similarity * opposite_direction_similarity

    return {
        "min_angle": min(angles),
        "max_angle": max(angles),
        "planarity": planarity,
        "diagonal_ratio": diagonal_ratio,
        "edge_ratio": edge_ratio,
        "area_consistency": area_consistency,
        "twist": twist,
        "diagonal_normal_deviation": diagonal_normal_deviation,
        "opposite_length_similarity": opposite_length_similarity,
        "opposite_direction_similarity": opposite_direction_similarity,
        "scaled_jacobian": scaled_jacobian,
        "strip_score": strip_score,
    }


def quality_score(normal_angle, metrics, settings):
    normal_score = 1.0 - clamp(
        normal_angle / max(settings.max_normal_angle, EPS), 0.0, 1.0)
    planar_score = 1.0 - clamp(
        metrics["planarity"] / max(settings.max_planarity_error, EPS), 0.0, 1.0)
    angle_error = max(
        abs(metrics["min_angle"] - 90.0),
        abs(metrics["max_angle"] - 90.0),
    )
    angle_score = 1.0 - clamp(angle_error / 90.0, 0.0, 1.0)
    diagonal_score = 1.0 - clamp(
        (metrics["diagonal_ratio"] - 1.0) /
        max(settings.max_diagonal_ratio - 1.0, EPS),
        0.0,
        1.0,
    )
    edge_score = 1.0 - clamp(
        (metrics["edge_ratio"] - 1.0) / 5.0, 0.0, 1.0)
    twist_score = 1.0 - clamp(
        metrics["twist"] / max(STRICT_MAX_TWIST, EPS), 0.0, 1.0)
    diagonal_normal_score = 1.0 - clamp(
        metrics["diagonal_normal_deviation"] /
        max(STRICT_MAX_DIAGONAL_NORMAL_DEVIATION, EPS),
        0.0,
        1.0,
    )
    strip_score = metrics["strip_score"]
    shape_score = (
        angle_score * (0.16 - 0.06 * strip_score) +
        diagonal_score * (0.10 - 0.04 * strip_score) +
        edge_score * (0.08 - 0.06 * strip_score) +
        metrics["opposite_length_similarity"] * 0.04 * strip_score +
        metrics["opposite_direction_similarity"] * 0.06 * strip_score
    )
    return (
        normal_score * 0.18 +
        planar_score * 0.16 +
        shape_score +
        metrics["area_consistency"] * 0.08 +
        twist_score * 0.12 +
        diagonal_normal_score * 0.10 +
        metrics["scaled_jacobian"] * 0.06
    )


def point_average(points, vertex_ids):
    count = max(len(vertex_ids), 1)
    return (
        sum(points[i].x for i in vertex_ids) / count,
        sum(points[i].y for i in vertex_ids) / count,
        sum(points[i].z for i in vertex_ids) / count,
    )


def vector_between(points, a, b):
    v = points[b] - points[a]
    return v.normalized() if v.length > EPS else Vector((0.0, 0.0, 0.0))


def edge_lengths_for_quad(points, quad):
    return [distance(points[quad[i]], points[quad[(i + 1) % 4]]) for i in range(4)]


def edge_dirs_for_quad(points, quad):
    return [vector_between(points, quad[i], quad[(i + 1) % 4]) for i in range(4)]


def build_vertex_edge_adjacency(bm):
    adjacency = {}
    for edge in bm.edges:
        a, b = edge.verts[0].index, edge.verts[1].index
        adjacency.setdefault(a, []).append((edge.index, b))
        adjacency.setdefault(b, []).append((edge.index, a))
    return adjacency


def structural_continuation_score(edge_vertices, edge_id, points, vertex_edges):
    a, b = edge_vertices
    edge_vec = points[b] - points[a]
    if edge_vec.length < EPS:
        return 0.0
    edge_dir = edge_vec.normalized()

    def endpoint_score(vertex_id, away_dir):
        best = 0.0
        for other_edge_id, other_vertex in vertex_edges.get(vertex_id, []):
            if other_edge_id == edge_id:
                continue
            other_vec = points[other_vertex] - points[vertex_id]
            if other_vec.length < EPS:
                continue
            alignment = abs(other_vec.normalized().dot(away_dir))
            if alignment > best:
                best = alignment
        if best < STRUCTURAL_CONTINUATION_DOT:
            return 0.0
        return best

    return endpoint_score(a, edge_dir * -1.0) + endpoint_score(b, edge_dir)


def add_solver_tag(candidate, tag):
    tags = set(candidate.solver_tags.split(",")) if candidate.solver_tags else set()
    tags.add(tag)
    candidate.solver_tags = ",".join(sorted(t for t in tags if t))


def boost(candidate, amount, tag, attr_name):
    setattr(candidate, attr_name, getattr(candidate, attr_name) + amount)
    candidate.quality = clamp(candidate.quality + amount, 0.0, 2.0)
    add_solver_tag(candidate, tag)


def score_tube_candidate(candidate, points):
    quad = candidate.quad_vertices
    if min(quad) < 0:
        return 0.0
    lengths = edge_lengths_for_quad(points, quad)
    dirs = edge_dirs_for_quad(points, quad)
    opposite_parallel = [
        abs(dirs[0].dot(dirs[2])) if dirs[0].length > EPS and dirs[2].length > EPS else 0.0,
        abs(dirs[1].dot(dirs[3])) if dirs[1].length > EPS and dirs[3].length > EPS else 0.0,
    ]
    opposite_similarity = [
        min(lengths[0], lengths[2]) / max(lengths[0], lengths[2], EPS),
        min(lengths[1], lengths[3]) / max(lengths[1], lengths[3], EPS),
    ]
    pair_a = (lengths[0] + lengths[2]) * 0.5
    pair_b = (lengths[1] + lengths[3]) * 0.5
    strip_ratio = max(pair_a, pair_b) / max(min(pair_a, pair_b), EPS)
    score = max(
        opposite_parallel[0] * opposite_similarity[0],
        opposite_parallel[1] * opposite_similarity[1],
    )
    if score > 0.88 and strip_ratio > 1.35:
        return 0.12 * clamp((score - 0.88) / 0.12, 0.0, 1.0)
    if score > 0.95:
        return 0.05
    return 0.0


def score_planar_candidate(candidate):
    normal_score = 1.0 - clamp(candidate.normal_angle / 18.0, 0.0, 1.0)
    planar_score = 1.0 - clamp(candidate.planarity / 0.08, 0.0, 1.0)
    angle_score = 1.0 - clamp(
        max(abs(candidate.min_angle - 90.0), abs(candidate.max_angle - 90.0)) / 90.0,
        0.0,
        1.0,
    )
    return 0.10 * normal_score * planar_score + 0.04 * angle_score


def max_direction_alignment(points, candidate_a, candidate_b):
    dirs_a = edge_dirs_for_quad(points, candidate_a.quad_vertices)
    dirs_b = edge_dirs_for_quad(points, candidate_b.quad_vertices)
    best = 0.0
    for a in dirs_a:
        if a.length < EPS:
            continue
        for b in dirs_b:
            if b.length < EPS:
                continue
            best = max(best, abs(a.dot(b)))
    return best


def enrich_candidates(mesh, candidates, points, face_normals, settings):
    if not candidates:
        return candidates

    if settings.ring_tube_detect:
        for candidate in candidates:
            amount = score_tube_candidate(candidate, points)
            if amount > 0.0:
                boost(candidate, amount, "RingTube", "tube_score")

    if settings.planar_patch_solve:
        for candidate in candidates:
            amount = score_planar_candidate(candidate)
            if amount > 0.0:
                boost(candidate, amount, "PlanarPatch", "planar_score")

    by_vertex = {}
    for candidate in candidates:
        for vertex_id in candidate.quad_vertices:
            if vertex_id >= 0:
                by_vertex.setdefault(vertex_id, []).append(candidate)

    if settings.flow_reconstruct:
        flow_accum = {id(candidate): 0.0 for candidate in candidates}
        for linked in by_vertex.values():
            for i, candidate_a in enumerate(linked):
                for candidate_b in linked[i + 1:]:
                    if candidate_a.mesh != candidate_b.mesh:
                        continue
                    if candidate_a.face_a in (candidate_b.face_a, candidate_b.face_b):
                        continue
                    if candidate_a.face_b in (candidate_b.face_a, candidate_b.face_b):
                        continue
                    alignment = max_direction_alignment(points, candidate_a, candidate_b)
                    if alignment > 0.92:
                        amount = 0.035 * clamp((alignment - 0.92) / 0.08, 0.0, 1.0)
                        flow_accum[id(candidate_a)] += amount
                        flow_accum[id(candidate_b)] += amount
        for candidate in candidates:
            amount = min(flow_accum[id(candidate)], 0.22)
            if amount > 0.0:
                boost(candidate, amount, "Flow", "flow_score")

    if settings.symmetry_assist and len(candidates) > 1 and points:
        xs = [point.x for point in points]
        ys = [point.y for point in points]
        zs = [point.z for point in points]
        centers = (
            (min(xs) + max(xs)) * 0.5,
            (min(ys) + max(ys)) * 0.5,
            (min(zs) + max(zs)) * 0.5,
        )
        max_extent = max(
            max(xs) - min(xs),
            max(ys) - min(ys),
            max(zs) - min(zs),
            EPS,
        )
        tolerance = max_extent * 0.025

        def mirrored_key(centroid, axis):
            values = [centroid[0], centroid[1], centroid[2]]
            values[axis] = centers[axis] * 2.0 - values[axis]
            return tuple(round(v / max(tolerance, EPS)) for v in values)

        buckets = {}
        for candidate in candidates:
            key = tuple(round(v / max(tolerance, EPS)) for v in candidate.centroid)
            buckets.setdefault(key, []).append(candidate)

        for axis in range(3):
            hits = []
            for candidate in candidates:
                mirror_bucket = buckets.get(mirrored_key(candidate.centroid, axis), [])
                for other in mirror_bucket:
                    if other is candidate:
                        continue
                    if abs(candidate.diagonal_ratio - other.diagonal_ratio) < 0.35:
                        hits.append(candidate)
                        hits.append(other)
                        break
            if len(hits) >= max(4, len(candidates) * 0.08):
                unique_hits = {id(candidate): candidate for candidate in hits}
                for candidate in unique_hits.values():
                    boost(candidate, 0.07, "Symmetry", "symmetry_score")
                break

    return candidates


# -----------------------------------------------------------------------------
# Analysis
# -----------------------------------------------------------------------------


def analyze_mesh(obj, settings, allowed_faces=None):
    bm, owned = _open_bmesh(obj)
    try:
        points = [vert.co.copy() for vert in bm.verts]
        face_vertices = {}
        face_normals = {}
        triangles = set()

        for face in bm.faces:
            face_id = face.index
            verts = [vert.index for vert in face.verts]
            face_vertices[face_id] = verts
            face_normals[face_id] = (
                normalized_newell([points[v] for v in verts])
                if len(verts) >= 3 else Vector((0.0, 0.0, 0.0))
            )
            if len(verts) == 3 and (allowed_faces is None or face_id in allowed_faces):
                triangles.add(face_id)

        uv_layer = _uv_layer_for_bmesh(bm)
        vertex_edges = build_vertex_edge_adjacency(bm)
        stats = {key: 0 for key in (
            "triangles",
            "internal_edges",
            "rejected_hard",
            "rejected_uv",
            "rejected_material",
            "rejected_normal",
            "rejected_shape",
            "rejected_structural",
            "candidates",
        )}
        stats["triangles"] = len(triangles)
        candidates = []
        reconstruct = is_reconstruct_mode(settings)

        for edge in bm.edges:
            connected = list(edge.link_faces)
            if len(connected) != 2:
                continue
            face_a_obj, face_b_obj = connected
            face_a, face_b = face_a_obj.index, face_b_obj.index
            if face_a not in triangles or face_b not in triangles:
                continue
            stats["internal_edges"] += 1
            edge_vertices = (edge.verts[0].index, edge.verts[1].index)

            if settings.preserve_hard_edges and not edge.smooth:
                stats["rejected_hard"] += 1
                continue

            if settings.preserve_uv_seams and edge_is_uv_seam(
                    edge, face_a_obj, face_b_obj, uv_layer):
                stats["rejected_uv"] += 1
                continue

            if (
                settings.preserve_material_borders and
                face_a_obj.material_index != face_b_obj.material_index
            ):
                stats["rejected_material"] += 1
                continue

            continuation_score = structural_continuation_score(
                edge_vertices, edge.index, points, vertex_edges)
            if continuation_score >= STRUCTURAL_CONTINUATION_MIN_SCORE:
                stats["rejected_structural"] += 1

            normal_a, normal_b = face_normals[face_a], face_normals[face_b]
            normal_angle = angle_degrees(normal_a, normal_b)
            if normal_angle > HARD_SURFACE_CREASE_ANGLE:
                stats["rejected_normal"] += 1
                continue
            if normal_angle > settings.max_normal_angle and not reconstruct:
                stats["rejected_normal"] += 1
                continue
            if normal_angle > settings.max_normal_angle:
                stats["rejected_normal"] += 1

            quad_options = boundary_quad_options(
                face_vertices[face_a],
                face_vertices[face_b],
                edge_vertices,
            )
            source_normal = normal_a + normal_b
            if source_normal.length < EPS:
                source_normal = normal_a if normal_a.length > EPS else normal_b
            if not quad_options or source_normal.length < EPS:
                stats["rejected_shape"] += 1
                continue
            source_normal.normalize()

            av = face_vertices[face_a]
            bv = face_vertices[face_b]
            source_area = (
                triangle_area(points[av[0]], points[av[1]], points[av[2]]) +
                triangle_area(points[bv[0]], points[bv[1]], points[bv[2]])
            )

            viable_options = []
            for quad in quad_options:
                metrics = quad_metrics(
                    quad, points, source_normal, source_area, reconstruct)
                if metrics is None:
                    continue
                if reconstruct:
                    if (
                        metrics["min_angle"] >= RECONSTRUCT_MIN_ANGLE and
                        metrics["max_angle"] <= RECONSTRUCT_MAX_ANGLE and
                        metrics["diagonal_ratio"] <= RECONSTRUCT_MAX_DIAGONAL_RATIO and
                        metrics["twist"] <= RECONSTRUCT_MAX_TWIST
                    ):
                        viable_options.append((tuple(quad), metrics))
                elif (
                    metrics["min_angle"] >= settings.min_quad_angle and
                    metrics["max_angle"] <= settings.max_quad_angle and
                    metrics["planarity"] <= settings.max_planarity_error and
                    metrics["diagonal_ratio"] <= settings.max_diagonal_ratio and
                    metrics["area_consistency"] >= 0.985 and
                    metrics["twist"] <= STRICT_MAX_TWIST and
                    metrics["diagonal_normal_deviation"] <= STRICT_MAX_DIAGONAL_NORMAL_DEVIATION
                ):
                    viable_options.append((tuple(quad), metrics))

            if not viable_options:
                stats["rejected_shape"] += 1
                continue

            quad, metrics = max(
                viable_options,
                key=lambda item: quality_score(normal_angle, item[1], settings),
            )
            quality = quality_score(normal_angle, metrics, settings)
            if quality < settings.min_quality and not reconstruct:
                stats["rejected_shape"] += 1
                continue

            candidates.append(Candidate(
                obj.name_full,
                edge.index,
                face_a,
                face_b,
                quality,
                normal_angle,
                metrics["planarity"],
                metrics["min_angle"],
                metrics["max_angle"],
                metrics["diagonal_ratio"],
                quad,
                point_average(points, quad),
                structural_score=continuation_score,
            ))
            stats["candidates"] += 1

        return enrich_candidates(
            obj.name_full, candidates, points, face_normals, settings), stats
    finally:
        _close_bmesh(obj, bm, owned, write=False)


def candidate_utility(candidate):
    distortion = max(candidate.diagonal_ratio - 1.0, 0.0) * 0.015
    normal_penalty = max(
        candidate.normal_angle - HARD_SURFACE_CREASE_ANGLE * 0.5, 0.0) * 0.002
    structural_penalty = max(
        candidate.structural_score - STRUCTURAL_CONTINUATION_MIN_SCORE,
        0.0,
    ) * STRUCTURAL_CONTINUATION_PENALTY
    return (
        candidate.quality +
        COVERAGE_UTILITY_BONUS -
        distortion -
        normal_penalty -
        structural_penalty
    )


def non_conflicting(candidates):
    def face_key(candidate):
        return (candidate.mesh, candidate.face_a), (candidate.mesh, candidate.face_b)

    def greedy(order):
        used, accepted = set(), []
        for c in order:
            a, b = face_key(c)
            if a in used or b in used:
                continue
            used.update((a, b))
            accepted.append(c)
        return accepted

    orders = [
        sorted(candidates, key=lambda c: (
            -candidate_utility(c), c.normal_angle, c.planarity, c.diagonal_ratio, c.edge_id)),
        sorted(candidates, key=lambda c: (
            c.normal_angle, -candidate_utility(c), c.planarity, c.diagonal_ratio, c.edge_id)),
        sorted(candidates, key=lambda c: (
            c.planarity, c.diagonal_ratio, c.normal_angle, -candidate_utility(c), c.edge_id)),
        sorted(candidates, key=lambda c: (
            c.diagonal_ratio, c.planarity, c.normal_angle, -candidate_utility(c), c.edge_id)),
    ]
    accepted = max(
        (greedy(order) for order in orders),
        key=lambda items: (sum(candidate_utility(c) for c in items), len(items)),
    )

    improved = True
    while improved:
        improved = False
        used = set()
        by_face = {}
        for c in accepted:
            a, b = face_key(c)
            used.update((a, b))
            by_face[a] = c
            by_face[b] = c

        unmatched = [
            c for c in candidates
            if face_key(c)[0] not in used and face_key(c)[1] not in used
        ]
        if unmatched:
            continue

        accepted_set = {(c.mesh, c.edge_id) for c in accepted}
        for c in sorted(candidates, key=lambda item: -candidate_utility(item)):
            a, b = face_key(c)
            if (c.mesh, c.edge_id) in accepted_set:
                continue
            blockers = []
            if a in by_face:
                blockers.append(by_face[a])
            if b in by_face and by_face[b] not in blockers:
                blockers.append(by_face[b])
            if len(blockers) != 1:
                continue
            blocker = blockers[0]
            old_score = candidate_utility(blocker)
            if candidate_utility(c) <= old_score:
                continue
            trial = [item for item in accepted if item is not blocker]
            trial_faces = set()
            valid = True
            for item in trial:
                fa, fb = face_key(item)
                if fa in trial_faces or fb in trial_faces:
                    valid = False
                    break
                trial_faces.update((fa, fb))
            if valid and a not in trial_faces and b not in trial_faces:
                trial.append(c)
                accepted = trial
                improved = True
                break
    return accepted


def non_conflicting_exact(candidates):
    by_node, edges_by_node = {}, {}
    nodes = []
    for c in candidates:
        a, b = (c.mesh, c.face_a), (c.mesh, c.face_b)
        for node in (a, b):
            if node not in by_node:
                by_node[node] = len(nodes)
                nodes.append(node)
            edges_by_node.setdefault(node, []).append(c)

    remaining = set(nodes)
    components = []
    while remaining:
        start = remaining.pop()
        stack, component = [start], {start}
        while stack:
            node = stack.pop()
            for c in edges_by_node.get(node, []):
                for other in ((c.mesh, c.face_a), (c.mesh, c.face_b)):
                    if other not in component:
                        component.add(other)
                        remaining.discard(other)
                        stack.append(other)
        components.append(component)

    result = []
    for component in components:
        component_candidates = [
            c for c in candidates
            if (c.mesh, c.face_a) in component and (c.mesh, c.face_b) in component
        ]
        if len(component) > 24:
            result.extend(non_conflicting(component_candidates))
            continue

        component_nodes = sorted(component)
        index = {node: i for i, node in enumerate(component_nodes)}
        incident = {i: [] for i in range(len(component_nodes))}
        for c in component_candidates:
            a = index[(c.mesh, c.face_a)]
            b = index[(c.mesh, c.face_b)]
            incident[a].append((b, c))
            incident[b].append((a, c))

        memo = {}

        def solve(mask):
            if mask == 0:
                return 0.0, 0, []
            if mask in memo:
                return memo[mask]
            first = (mask & -mask).bit_length() - 1
            best_score, best_count, best_items = solve(mask & ~(1 << first))
            for other, c in incident[first]:
                if not (mask & (1 << other)):
                    continue
                next_mask = mask & ~(1 << first) & ~(1 << other)
                score, count, items = solve(next_mask)
                candidate = (
                    score + candidate_utility(c),
                    count + 1,
                    items + [c],
                )
                if (candidate[0], candidate[1]) > (best_score, best_count):
                    best_score, best_count, best_items = candidate
            memo[mask] = best_score, best_count, best_items
            return memo[mask]

        full_mask = (1 << len(component_nodes)) - 1
        result.extend(solve(full_mask)[2])
    return result


def select_candidates(candidates):
    greedy = non_conflicting(candidates)
    exact = non_conflicting_exact(candidates)
    return max(
        (greedy, exact),
        key=lambda items: (sum(candidate_utility(c) for c in items), len(items)),
    )


def analyze_once(settings, context=None):
    context = context or bpy.context
    objects = selected_mesh_objects(context)
    if not objects:
        raise RuntimeError("Select at least one polygon mesh or polygon face.")
    selected_faces = selected_face_ids_by_mesh(context)
    if settings.selection_only and not selected_faces:
        raise RuntimeError("Selection Only is enabled, but no polygon faces are selected.")
    if settings.selection_only:
        objects = [obj for obj in objects if obj.name_full in selected_faces]

    all_candidates, all_stats = [], {}
    for obj in objects:
        allowed = selected_faces.get(obj.name_full) if settings.selection_only else None
        candidates, stats = analyze_mesh(obj, settings, allowed)
        stats["analysis_mode"] = settings.analysis_mode
        all_candidates.extend(candidates)
        all_stats[obj.name_full] = stats
    return select_candidates(all_candidates), all_stats


def analyze(settings, context=None):
    if settings.analysis_mode != "auto":
        return analyze_once(settings, context)
    return smart_auto_analyze(settings, context)


def average(values):
    return sum(values) / len(values) if values else 0.0


def auto_preset_score(candidates, stats):
    # Preserved from the original implementation for future tuning.
    total_triangles = max(sum(s["triangles"] for s in stats.values()), 1)
    total_internal = max(sum(s["internal_edges"] for s in stats.values()), 1)
    coverage = len(candidates) * 2.0 / total_triangles
    avg_utility = average([candidate_utility(c) for c in candidates])
    patch_consistency = average([c.planar_score + c.tube_score for c in candidates])
    flow_consistency = average([c.flow_score for c in candidates])
    distortion_penalty = average([
        max(c.diagonal_ratio - 3.0, 0.0) / 10.0 +
        max(c.max_angle - 165.0, 0.0) / 90.0 +
        max(12.0 - c.min_angle, 0.0) / 90.0
        for c in candidates
    ])
    boundary_damage_penalty = (
        sum(s["rejected_normal"] for s in stats.values()) / total_internal)
    reconstruct_penalty = 0.20 if any(
        "reconstruct" in s.get("analysis_mode", "") for s in stats.values()) else 0.0
    return (
        coverage * 2.0 +
        avg_utility * 4.0 +
        patch_consistency * 3.0 +
        flow_consistency * 3.0 -
        distortion_penalty * 4.0 -
        boundary_damage_penalty * 1.5 -
        reconstruct_penalty
    )


def merge_auto_stats(stats_items, candidates):
    merged = {}
    for stats in stats_items:
        for mesh, values in stats.items():
            target = merged.setdefault(mesh, {
                "triangles": 0,
                "internal_edges": 0,
                "rejected_hard": 0,
                "rejected_uv": 0,
                "rejected_material": 0,
                "rejected_normal": 0,
                "rejected_shape": 0,
                "rejected_structural": 0,
                "candidates": 0,
                "analysis_mode": "unified auto snapshot",
            })
            target["triangles"] = max(target["triangles"], values.get("triangles", 0))
            target["internal_edges"] = max(
                target["internal_edges"], values.get("internal_edges", 0))
            for key in (
                "rejected_hard",
                "rejected_uv",
                "rejected_material",
                "rejected_normal",
                "rejected_shape",
                "rejected_structural",
            ):
                target[key] = max(target[key], values.get(key, 0))

    candidate_count_by_mesh = {}
    for candidate in candidates:
        candidate_count_by_mesh[candidate.mesh] = (
            candidate_count_by_mesh.get(candidate.mesh, 0) + 1)
    for mesh, count in candidate_count_by_mesh.items():
        merged.setdefault(mesh, {
            "triangles": 0,
            "internal_edges": 0,
            "rejected_hard": 0,
            "rejected_uv": 0,
            "rejected_material": 0,
            "rejected_normal": 0,
            "rejected_shape": 0,
            "rejected_structural": 0,
            "analysis_mode": "unified auto snapshot",
        })["candidates"] = count
    return merged


def smart_auto_analyze(settings, context=None):
    best_by_edge = {}
    stats_items = []
    preset_plan = [
        (name, settings_from_preset(name, settings))
        for name in ("conservative", "balanced", "aggressive", "reconstruct")
    ]
    for preset_name, preset_settings in preset_plan:
        candidates, stats = analyze_once(preset_settings, context)
        stats_items.append(stats)
        for candidate in candidates:
            key = (candidate.mesh, candidate.edge_id)
            current = best_by_edge.get(key)
            if current is None or candidate_utility(candidate) > candidate_utility(current):
                best_by_edge[key] = candidate
    if not best_by_edge:
        return [], merge_auto_stats(stats_items, [])
    unified_candidates = list(best_by_edge.values())
    merged_stats = merge_auto_stats(stats_items, unified_candidates)
    return select_candidates(unified_candidates), merged_stats


# -----------------------------------------------------------------------------
# Apply / native Blender fallback
# -----------------------------------------------------------------------------


def apply_candidates(candidates, keep_history=False):
    by_mesh = {}
    for candidate in candidates:
        by_mesh.setdefault(candidate.mesh, []).append(candidate.edge_id)
    if not by_mesh:
        return 0

    applied = 0
    for object_name, edge_ids in by_mesh.items():
        obj = bpy.data.objects.get(object_name)
        if obj is None or obj.type != "MESH":
            continue
        bm, owned = _open_bmesh(obj)
        try:
            valid_edges = []
            for edge_id in sorted(set(edge_ids)):
                if 0 <= edge_id < len(bm.edges):
                    edge = bm.edges[edge_id]
                    if edge.is_valid and len(edge.link_faces) == 2:
                        valid_edges.append(edge)
            if valid_edges:
                # Remove the dissolved edge's now-unused vertices where possible.
                # with cleanVertices=False: remove only the accepted diagonals.
                bmesh.ops.dissolve_edges(
                    bm,
                    edges=valid_edges,
                    use_verts=False,
                    use_face_split=False,
                )
                applied += len(valid_edges)
                bm.normal_update()
        finally:
            _close_bmesh(obj, bm, owned, write=True, destructive=True)
    return applied


def smart_pass_settings(base):
    plan = [
        settings_from_preset("conservative", base),
        settings_from_preset("balanced", base),
        settings_from_preset("aggressive", base),
        settings_from_preset("reconstruct", base),
    ]
    for item in plan:
        item.use_blender_core = False
        item.keep_history = base.keep_history
        item.selection_only = base.selection_only
    return plan


def smart_combined_cleanup(settings, max_rounds=1, context=None):
    candidates, stats = smart_auto_analyze(settings, context)
    total_triangles = sum(s["triangles"] for s in stats.values())
    raw_candidates = sum(s.get("candidates", 0) for s in stats.values())
    internal_edges = sum(s["internal_edges"] for s in stats.values())
    modes = sorted(set(s.get("analysis_mode", "auto") for s in stats.values()))
    count = apply_candidates(candidates, settings.keep_history)
    passes = [{
        "round": 1,
        "mode": "snapshot {}".format(", ".join(modes)),
        "quads": count,
        "triangles": total_triangles,
        "raw_candidates": raw_candidates,
        "internal_edges": internal_edges,
    }]
    return count, passes, candidates, stats


def run_blender_quadrangulate(settings, context=None):
    context = context or bpy.context
    objects = selected_mesh_objects(context)
    if not objects:
        raise RuntimeError("Select at least one polygon mesh or polygon face.")

    selected_faces = selected_face_ids_by_mesh(context)
    if settings.selection_only and not selected_faces:
        raise RuntimeError("Selection Only is enabled, but no polygon faces are selected.")

    before = count_mesh_triangles(objects)
    before_triangles = total_count(before, "triangles")

    total_joined = 0
    for obj in objects:
        bm, owned = _open_bmesh(obj)
        try:
            if settings.selection_only:
                allowed = selected_faces.get(obj.name_full, set())
                faces = [
                    face for face in bm.faces
                    if face.index in allowed and len(face.verts) == 3
                ]
            else:
                faces = [face for face in bm.faces if len(face.verts) == 3]

            before_faces_local = len(bm.faces)
            if faces:
                kwargs = dict(
                    faces=faces,
                    cmp_seam=settings.preserve_uv_seams,
                    cmp_sharp=settings.preserve_hard_edges,
                    cmp_uvs=settings.preserve_uv_seams,
                    cmp_vcols=False,
                    cmp_materials=settings.preserve_material_borders,
                    angle_face_threshold=math.radians(settings.blender_core_angle),
                    angle_shape_threshold=math.radians(settings.blender_core_angle),
                )
                bmesh.ops.join_triangles(bm, **kwargs)
                total_joined += max(before_faces_local - len(bm.faces), 0)
                bm.normal_update()
        finally:
            _close_bmesh(obj, bm, owned, write=True, destructive=True)

    after = count_mesh_triangles(objects)
    return {
        "engine": "Blender Tris to Quads Core",
        "meshes": len(objects),
        "faces_before": total_count(before, "faces"),
        "triangles_before": before_triangles,
        "faces_after": total_count(after, "faces"),
        "triangles_after": total_count(after, "triangles"),
        "triangles_removed": max(
            before_triangles - total_count(after, "triangles"), 0),
        "attempt": "bmesh.ops.join_triangles",
        "joined_faces": total_joined,
    }


def clean_model(settings, context=None):
    context = context or bpy.context
    analysis_settings = replace(
        settings,
        analysis_mode="auto",
        use_blender_core=False,
        smart_fallback=True,
        allow_relaxed_blender_core=False,
    )
    analysis_settings.use_blender_core = False
    pre_candidates, pre_stats = smart_auto_analyze(analysis_settings, context)
    objects = selected_mesh_objects(context)
    before = count_mesh_triangles(objects)

    count, smart_passes, last_candidates, last_stats = smart_combined_cleanup(
        analysis_settings, context=context)
    after = count_mesh_triangles(objects)
    smart_removed = max(
        total_count(before, "triangles") - total_count(after, "triangles"), 0)

    if count > 0 or not settings.use_blender_core:
        return {
            "engine": "Smart Snapshot Auto",
            "attempt": "unified smart snapshot",
            "meshes": len(objects),
            "faces_before": total_count(before, "faces"),
            "faces_after_fallback": total_count(after, "faces"),
            "triangles_before": total_count(before, "triangles"),
            "triangles_removed": smart_removed,
            "triangles_after_fallback": total_count(after, "triangles"),
            "pre_analysis_quads": len(pre_candidates),
            "smart_fallback_quads": count,
            "smart_fallback_mode": ", ".join(
                sorted(set(s.get("analysis_mode", "auto") for s in last_stats.values()))
            ) if last_stats else "none",
            "smart_passes": smart_passes,
        }, last_candidates, last_stats

    if settings.use_blender_core:
        native_stats = run_blender_quadrangulate(settings, context)
        native_stats["pre_analysis_quads"] = len(pre_candidates)
        return native_stats, pre_candidates, pre_stats


# -----------------------------------------------------------------------------
# Reporting
# -----------------------------------------------------------------------------


def report_text(candidates, stats, applied=False):
    total_triangles = sum(s["triangles"] for s in stats.values())
    total_raw = sum(s.get("candidates", 0) for s in stats.values())
    coverage = (len(candidates) * 2.0 / total_triangles) if total_triangles else 0.0
    modes = sorted(set(s.get("analysis_mode", "custom") for s in stats.values()))
    lines = [
        "Applied successfully." if applied else "Analysis complete.",
        "",
        "Profile used: {}".format(", ".join(modes).title()),
        "Meshes: {}".format(len(stats)),
        "Triangles in scope: {}".format(total_triangles),
        "Internal triangle-pair edges: {}".format(
            sum(s["internal_edges"] for s in stats.values())),
        "Valid pair candidates: {}".format(total_raw),
        "Accepted non-conflicting quads: {}".format(len(candidates)),
        "Triangle coverage: {:.1f}%".format(coverage * 100.0),
        "Unpaired triangles: {}".format(max(total_triangles - len(candidates) * 2, 0)),
        "Rejected by pairing conflicts: {}".format(max(total_raw - len(candidates), 0)),
    ]
    if candidates:
        qualities = [c.quality for c in candidates]
        lines += [
            "Average quality: {:.3f}".format(sum(qualities) / len(qualities)),
            "Quality range: {:.3f} - {:.3f}".format(min(qualities), max(qualities)),
        ]
        tag_counts = {}
        for candidate in candidates:
            for tag in candidate.solver_tags.split(","):
                if tag:
                    tag_counts[tag] = tag_counts.get(tag, 0) + 1
        if tag_counts:
            lines.append("Solver boosts: {}".format(
                ", ".join(
                    "{} {}".format(tag, count)
                    for tag, count in sorted(tag_counts.items())
                )
            ))
    lines += [
        "",
        "Preserved / rejected:",
        "Hard edges: {}".format(sum(s.get("rejected_hard", 0) for s in stats.values())),
        "UV seams: {}".format(sum(s.get("rejected_uv", 0) for s in stats.values())),
        "Material borders: {}".format(sum(s.get("rejected_material", 0) for s in stats.values())),
        "Structural continuations: {}".format(
            sum(s.get("rejected_structural", 0) for s in stats.values())),
        "Normal-angle failures: {}".format(
            sum(s.get("rejected_normal", 0) for s in stats.values())),
        "Shape-quality failures: {}".format(
            sum(s.get("rejected_shape", 0) for s in stats.values())),
    ]
    return "\n".join(lines)


def clean_report_text(clean_stats, candidates=None, stats=None):
    lines = [
        "Applied successfully.",
        "",
        "Engine: {}".format(clean_stats.get("engine", "Unknown")),
        "Attempt: {}".format(clean_stats.get("attempt", "unknown")),
        "Meshes: {}".format(clean_stats.get("meshes", 0)),
    ]
    if "faces_before" in clean_stats:
        lines.extend([
            "Faces before: {}".format(clean_stats.get("faces_before", 0)),
            "Faces after: {}".format(clean_stats.get(
                "faces_after_fallback", clean_stats.get("faces_after", 0))),
        ])
    lines.extend([
        "Triangles before: {}".format(clean_stats.get("triangles_before", 0)),
        "Triangles after: {}".format(clean_stats.get(
            "triangles_after_fallback", clean_stats.get("triangles_after", 0))),
        "Triangles removed: {}".format(clean_stats.get("triangles_removed", 0)),
    ])
    if "pre_analysis_quads" in clean_stats:
        lines.append("Smart pre-analysis quads: {}".format(
            clean_stats.get("pre_analysis_quads", 0)))
    if "smart_fallback_quads" in clean_stats:
        lines.append("Smart fallback mode: {}".format(
            clean_stats.get("smart_fallback_mode", "custom")))
        lines.append("Smart fallback quads: {}".format(
            clean_stats["smart_fallback_quads"]))
    if clean_stats.get("smart_passes"):
        lines.append("")
        lines.append("Smart combined passes:")
        for item in clean_stats["smart_passes"]:
            lines.append(
                "R{round} {mode}: {quads} quads, {raw_candidates} candidates, "
                "{triangles} tris".format(**item)
            )
    if candidates is not None and stats is not None:
        lines.extend(["", report_text(candidates, stats, applied=False)])
    return "\n".join(lines)


# -----------------------------------------------------------------------------
# Blender UI / operators
# -----------------------------------------------------------------------------


_LAST_CANDIDATES = []
_LAST_STATS = None
_LAST_SETTINGS_KEY = None
_LAST_REPORT = "Ready.\n\nAuto mode restored."


def default_settings(context=None):
    context = context or bpy.context
    settings = Settings()
    settings.analysis_mode = "auto"
    settings.selection_only = bool(selected_face_components(context))
    settings.use_blender_core = False
    settings.smart_fallback = False
    settings.allow_relaxed_blender_core = False
    settings.flow_reconstruct = True
    settings.symmetry_assist = True
    settings.ring_tube_detect = True
    settings.planar_patch_solve = True
    return settings


def settings_key(settings):
    return tuple(getattr(settings, field) for field in Settings.__dataclass_fields__)


def _set_last_report(text):
    global _LAST_REPORT
    _LAST_REPORT = text
    print("\n{}\n{}\n".format(TOOL_TITLE, text))


def select_candidate_edges(candidates, context=None):
    context = context or bpy.context
    by_obj = {}
    for candidate in candidates:
        by_obj.setdefault(candidate.mesh, set()).add(candidate.edge_id)

    # If necessary, enter multi-object Edit Mode so the selection is visible.
    if context.mode != "EDIT_MESH":
        if context.mode != "OBJECT" and context.object is not None:
            bpy.ops.object.mode_set(mode="OBJECT")
        bpy.ops.object.select_all(action="DESELECT")
        objects = []
        for name in by_obj:
            obj = bpy.data.objects.get(name)
            if obj is not None and obj.type == "MESH":
                obj.select_set(True)
                objects.append(obj)
        if objects:
            context.view_layer.objects.active = objects[0]
            bpy.ops.object.mode_set(mode="EDIT")

    try:
        bpy.ops.mesh.select_mode(type="EDGE")
    except Exception:
        pass

    for obj in selected_mesh_objects(context):
        bm, owned = _open_bmesh(obj)
        try:
            for vert in bm.verts:
                vert.select = False
            for edge in bm.edges:
                edge.select = False
            for face in bm.faces:
                face.select = False
            wanted = by_obj.get(obj.name_full, set())
            for edge_id in wanted:
                if 0 <= edge_id < len(bm.edges):
                    bm.edges[edge_id].select = True
            bm.select_mode = {"EDGE"}
            bm.select_flush_mode()
        finally:
            _close_bmesh(obj, bm, owned, write=True, destructive=False)


class SMARTDETRIANGULATE_OT_analyze(bpy.types.Operator):
    bl_idname = "mesh.smart_detriangulate_analyze"
    bl_label = "Analyze"
    bl_description = "Analyze topology and select diagonals that would be removed"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        global _LAST_CANDIDATES, _LAST_STATS, _LAST_SETTINGS_KEY
        try:
            settings = default_settings(context)
            candidates, stats = analyze(settings, context)
            _LAST_CANDIDATES = candidates
            _LAST_STATS = stats
            _LAST_SETTINGS_KEY = settings_key(settings)
            text = report_text(candidates, stats)
            _set_last_report(text)
            select_candidate_edges(candidates, context)
            self.report({"INFO"}, "{}: {} diagonals selected.".format(
                TOOL_TITLE, len(candidates)))
            return {"FINISHED"}
        except Exception as exc:
            _set_last_report("Error:\n{}".format(exc))
            self.report({"ERROR"}, "{}: {}".format(TOOL_TITLE, exc))
            traceback.print_exc()
            return {"CANCELLED"}


class SMARTDETRIANGULATE_OT_apply(bpy.types.Operator):
    bl_idname = "mesh.smart_detriangulate_apply"
    bl_label = "Apply"
    bl_description = "Apply the current smart detriangulation analysis"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        global _LAST_CANDIDATES, _LAST_STATS, _LAST_SETTINGS_KEY
        try:
            settings = default_settings(context)
            key = settings_key(settings)
            if _LAST_STATS is not None and _LAST_SETTINGS_KEY == key:
                candidates, stats = _LAST_CANDIDATES, _LAST_STATS
            else:
                candidates, stats = analyze(settings, context)
            count = apply_candidates(candidates, settings.keep_history)
            _LAST_CANDIDATES = []
            _LAST_STATS = None
            _LAST_SETTINGS_KEY = None
            _set_last_report(report_text(candidates, stats, applied=True))
            self.report({"INFO"}, "{}: created {} quads.".format(TOOL_TITLE, count))
            return {"FINISHED"}
        except Exception as exc:
            _set_last_report("Error:\n{}".format(exc))
            self.report({"ERROR"}, "{}: {}".format(TOOL_TITLE, exc))
            traceback.print_exc()
            return {"CANCELLED"}


class SMARTDETRIANGULATE_OT_clean_model(bpy.types.Operator):
    bl_idname = "mesh.smart_detriangulate_clean_model"
    bl_label = "Clean Model"
    bl_description = "Run unified Smart Snapshot Auto cleanup"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        global _LAST_CANDIDATES, _LAST_STATS, _LAST_SETTINGS_KEY
        try:
            settings = default_settings(context)
            clean_stats, candidates, stats = clean_model(settings, context)
            _LAST_CANDIDATES = []
            _LAST_STATS = None
            _LAST_SETTINGS_KEY = None
            text = clean_report_text(clean_stats, candidates, stats)
            _set_last_report(text)
            self.report({"INFO"}, "{}: {} removed {} triangles.".format(
                TOOL_TITLE,
                clean_stats.get("engine", "Clean Model"),
                clean_stats.get("triangles_removed", 0),
            ))
            return {"FINISHED"}
        except Exception as exc:
            _set_last_report("Error:\n{}".format(exc))
            self.report({"ERROR"}, "{}: {}".format(TOOL_TITLE, exc))
            traceback.print_exc()
            return {"CANCELLED"}


class SMARTDETRIANGULATE_OT_restore_defaults(bpy.types.Operator):
    bl_idname = "mesh.smart_detriangulate_restore_defaults"
    bl_label = "Reset"
    bl_description = "Clear cached analysis and restore Auto mode"

    def execute(self, context):
        global _LAST_CANDIDATES, _LAST_STATS, _LAST_SETTINGS_KEY
        _LAST_CANDIDATES = []
        _LAST_STATS = None
        _LAST_SETTINGS_KEY = None
        _set_last_report("Ready.\n\nAuto mode restored.")
        return {"FINISHED"}


class SMARTDETRIANGULATE_PT_panel(bpy.types.Panel):
    bl_label = "Smart Detriangulate"
    bl_idname = "SMARTDETRIANGULATE_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Tool"

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        col.operator("mesh.smart_detriangulate_clean_model", icon="MOD_TRIANGULATE")
        row = col.row(align=True)
        row.operator("mesh.smart_detriangulate_analyze", icon="VIEWZOOM")
        row.operator("mesh.smart_detriangulate_apply", icon="CHECKMARK")
        col.operator("mesh.smart_detriangulate_restore_defaults", icon="LOOP_BACK")

        layout.separator()
        box = layout.box()
        box.label(text="Mode: Auto / Smart Snapshot")
        selection_only = bool(selected_face_components(context))
        box.label(text="Scope: Selected Faces" if selection_only else "Scope: Selected Meshes")
        box.label(text="UV / Hard / Material borders preserved by presets")

        if _LAST_REPORT:
            layout.separator()
            report_box = layout.box()
            for line in _LAST_REPORT.splitlines()[:12]:
                report_box.label(text=line if line else " ")


CLASSES = (
    SMARTDETRIANGULATE_OT_analyze,
    SMARTDETRIANGULATE_OT_apply,
    SMARTDETRIANGULATE_OT_clean_model,
    SMARTDETRIANGULATE_OT_restore_defaults,
    SMARTDETRIANGULATE_PT_panel,
)


def register():
    for cls in CLASSES:
        try:
            bpy.utils.register_class(cls)
        except ValueError:
            pass


def unregister():
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass


def run_now(context=None):
    """Clean the current selection immediately."""
    context = context or bpy.context
    runner_settings = default_settings(context)
    try:
        clean_stats, candidates, stats = clean_model(runner_settings, context)
        text = clean_report_text(clean_stats, candidates, stats)
        _set_last_report(text)
        print("{}: {} removed {} triangles.".format(
            TOOL_TITLE,
            clean_stats.get("engine", "Clean Model"),
            clean_stats.get("triangles_removed", 0),
        ))
        return clean_stats
    except Exception as exc:
        _set_last_report("Error:\n{}".format(exc))
        traceback.print_exc()
        return None


def show():
    """Register the N-panel UI and clean the current selection."""
    register()
    return run_now()


if __name__ == "__main__":
    register()
    run_now()
