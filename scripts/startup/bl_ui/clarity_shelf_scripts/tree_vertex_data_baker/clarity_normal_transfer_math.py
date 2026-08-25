"""Exact closest-triangle normal-transfer math ported for Clarity."""

import math

from mathutils import Vector


def _clarity_point_triangle_closest(clarity_point, clarity_a, clarity_b, clarity_c):
    clarity_ab = clarity_b - clarity_a
    clarity_ac = clarity_c - clarity_a
    clarity_ap = clarity_point - clarity_a
    clarity_d1 = clarity_ab.dot(clarity_ap)
    clarity_d2 = clarity_ac.dot(clarity_ap)
    if clarity_d1 <= 0.0 and clarity_d2 <= 0.0:
        return (clarity_point - clarity_a).length_squared, clarity_a, Vector((1.0, 0.0, 0.0))
    clarity_bp = clarity_point - clarity_b
    clarity_d3 = clarity_ab.dot(clarity_bp)
    clarity_d4 = clarity_ac.dot(clarity_bp)
    if clarity_d3 >= 0.0 and clarity_d4 <= clarity_d3:
        return (clarity_point - clarity_b).length_squared, clarity_b, Vector((0.0, 1.0, 0.0))
    clarity_vc = clarity_d1 * clarity_d4 - clarity_d3 * clarity_d2
    if clarity_vc <= 0.0 and clarity_d1 >= 0.0 and clarity_d3 <= 0.0:
        clarity_edge = clarity_d1 / (clarity_d1 - clarity_d3)
        clarity_closest = clarity_a + clarity_edge * clarity_ab
        return (clarity_point - clarity_closest).length_squared, clarity_closest, Vector((1.0 - clarity_edge, clarity_edge, 0.0))
    clarity_cp = clarity_point - clarity_c
    clarity_d5 = clarity_ab.dot(clarity_cp)
    clarity_d6 = clarity_ac.dot(clarity_cp)
    if clarity_d6 >= 0.0 and clarity_d5 <= clarity_d6:
        return (clarity_point - clarity_c).length_squared, clarity_c, Vector((0.0, 0.0, 1.0))
    clarity_vb = clarity_d5 * clarity_d2 - clarity_d1 * clarity_d6
    if clarity_vb <= 0.0 and clarity_d2 >= 0.0 and clarity_d6 <= 0.0:
        clarity_edge = clarity_d2 / (clarity_d2 - clarity_d6)
        clarity_closest = clarity_a + clarity_edge * clarity_ac
        return (clarity_point - clarity_closest).length_squared, clarity_closest, Vector((1.0 - clarity_edge, 0.0, clarity_edge))
    clarity_va = clarity_d3 * clarity_d6 - clarity_d5 * clarity_d4
    if clarity_va <= 0.0 and clarity_d4 - clarity_d3 >= 0.0 and clarity_d5 - clarity_d6 >= 0.0:
        clarity_edge = (clarity_d4 - clarity_d3) / (
            clarity_d4 - clarity_d3 + clarity_d5 - clarity_d6
        )
        clarity_closest = clarity_b + clarity_edge * (clarity_c - clarity_b)
        return (clarity_point - clarity_closest).length_squared, clarity_closest, Vector((0.0, 1.0 - clarity_edge, clarity_edge))
    clarity_normal = clarity_ab.cross(clarity_ac)
    clarity_inverse_length = 1.0 / max(1e-12, clarity_normal.length)
    clarity_distance = clarity_ap.dot(clarity_normal) * clarity_inverse_length
    clarity_projection = clarity_point - clarity_distance * (clarity_normal * clarity_inverse_length)
    clarity_v0 = clarity_b - clarity_a
    clarity_v1 = clarity_c - clarity_a
    clarity_v2 = clarity_projection - clarity_a
    clarity_d00 = clarity_v0.dot(clarity_v0)
    clarity_d01 = clarity_v0.dot(clarity_v1)
    clarity_d11 = clarity_v1.dot(clarity_v1)
    clarity_d20 = clarity_v2.dot(clarity_v0)
    clarity_d21 = clarity_v2.dot(clarity_v1)
    clarity_inverse_denominator = 1.0 / (clarity_d00 * clarity_d11 - clarity_d01 * clarity_d01)
    clarity_bary_v = (clarity_d11 * clarity_d20 - clarity_d01 * clarity_d21) * clarity_inverse_denominator
    clarity_bary_w = (clarity_d00 * clarity_d21 - clarity_d01 * clarity_d20) * clarity_inverse_denominator
    clarity_bary = Vector((1.0 - clarity_bary_v - clarity_bary_w, clarity_bary_v, clarity_bary_w))
    return (clarity_point - clarity_projection).length_squared, clarity_projection, clarity_bary


def _clarity_bounds_for_triangles(clarity_vertices, clarity_triangles, clarity_indices):
    clarity_points = [
        clarity_vertices[clarity_triangles[clarity_triangle][clarity_corner]]
        for clarity_triangle in clarity_indices for clarity_corner in range(3)
    ]
    clarity_minimum = Vector(tuple(min(clarity_point[clarity_axis] for clarity_point in clarity_points) for clarity_axis in range(3)))
    clarity_maximum = Vector(tuple(max(clarity_point[clarity_axis] for clarity_point in clarity_points) for clarity_axis in range(3)))
    clarity_centroids = [sum(
        (clarity_vertices[clarity_index] for clarity_index in clarity_triangles[clarity_triangle]),
        Vector((0.0, 0.0, 0.0)),
    ) / 3.0 for clarity_triangle in clarity_indices]
    clarity_centroid_minimum = Vector(tuple(min(clarity_point[clarity_axis] for clarity_point in clarity_centroids) for clarity_axis in range(3)))
    clarity_centroid_maximum = Vector(tuple(max(clarity_point[clarity_axis] for clarity_point in clarity_centroids) for clarity_axis in range(3)))
    return clarity_minimum, clarity_maximum, clarity_centroid_minimum, clarity_centroid_maximum


def _clarity_build_bvh_generator(clarity_vertices, clarity_triangles):
    clarity_permutation = list(range(len(clarity_triangles)))
    clarity_nodes = []

    def clarity_recursive(clarity_start, clarity_count):
        clarity_indices = clarity_permutation[clarity_start:clarity_start + clarity_count]
        clarity_minimum, clarity_maximum, clarity_centroid_minimum, clarity_centroid_maximum = _clarity_bounds_for_triangles(
            clarity_vertices, clarity_triangles, clarity_indices
        )
        clarity_node_index = len(clarity_nodes)
        clarity_nodes.append(None)
        yield 1
        if clarity_count <= 8:
            clarity_nodes[clarity_node_index] = (
                clarity_minimum, clarity_maximum, -1, -1, clarity_start, clarity_count
            )
            return clarity_node_index
        clarity_extent = clarity_centroid_maximum - clarity_centroid_minimum
        clarity_axis = 0
        if clarity_extent.y > clarity_extent.x and clarity_extent.y >= clarity_extent.z:
            clarity_axis = 1
        elif clarity_extent.z > clarity_extent.x and clarity_extent.z >= clarity_extent.y:
            clarity_axis = 2
        clarity_indices.sort(key=lambda clarity_triangle: sum(
            clarity_vertices[clarity_index][clarity_axis]
            for clarity_index in clarity_triangles[clarity_triangle]
        ) / 3.0)
        clarity_permutation[clarity_start:clarity_start + clarity_count] = clarity_indices
        clarity_midpoint = clarity_start + clarity_count // 2
        clarity_left = yield from clarity_recursive(
            clarity_start, clarity_midpoint - clarity_start
        )
        clarity_right = yield from clarity_recursive(
            clarity_midpoint, clarity_start + clarity_count - clarity_midpoint
        )
        clarity_nodes[clarity_node_index] = (
            clarity_minimum, clarity_maximum, clarity_left, clarity_right, clarity_start, clarity_count
        )
        return clarity_node_index

    yield from clarity_recursive(0, len(clarity_triangles))
    return clarity_nodes, clarity_permutation


def _clarity_distance_to_bounds_sq(clarity_point, clarity_minimum, clarity_maximum):
    clarity_delta = [
        max(0.0, clarity_minimum[clarity_axis] - clarity_point[clarity_axis], clarity_point[clarity_axis] - clarity_maximum[clarity_axis])
        for clarity_axis in range(3)
    ]
    return sum(clarity_value * clarity_value for clarity_value in clarity_delta)


def _clarity_closest_triangle(
        clarity_nodes, clarity_permutation, clarity_point, clarity_vertices, clarity_triangles):
    clarity_best_triangle = -1
    clarity_best_barycentric = Vector()
    clarity_best_point = Vector()
    clarity_best_distance_sq = math.inf
    clarity_stack = [0]
    while clarity_stack:
        clarity_node_index = clarity_stack.pop()
        if not 0 <= clarity_node_index < len(clarity_nodes):
            continue
        clarity_minimum, clarity_maximum, clarity_left, clarity_right, clarity_start, clarity_count = clarity_nodes[clarity_node_index]
        if _clarity_distance_to_bounds_sq(clarity_point, clarity_minimum, clarity_maximum) > clarity_best_distance_sq:
            continue
        if clarity_left < 0:
            for clarity_offset in range(clarity_count):
                clarity_triangle_index = clarity_permutation[clarity_start + clarity_offset]
                clarity_triangle = clarity_triangles[clarity_triangle_index]
                clarity_distance_sq, clarity_candidate, clarity_barycentric = _clarity_point_triangle_closest(
                    clarity_point,
                    clarity_vertices[clarity_triangle[0]],
                    clarity_vertices[clarity_triangle[1]],
                    clarity_vertices[clarity_triangle[2]],
                )
                if clarity_distance_sq < clarity_best_distance_sq:
                    clarity_best_distance_sq = clarity_distance_sq
                    clarity_best_triangle = clarity_triangle_index
                    clarity_best_barycentric = clarity_barycentric
                    clarity_best_point = clarity_candidate
        else:
            clarity_left_node = clarity_nodes[clarity_left]
            clarity_right_node = clarity_nodes[clarity_right]
            clarity_left_distance = _clarity_distance_to_bounds_sq(clarity_point, clarity_left_node[0], clarity_left_node[1])
            clarity_right_distance = _clarity_distance_to_bounds_sq(clarity_point, clarity_right_node[0], clarity_right_node[1])
            if clarity_left_distance < clarity_right_distance:
                if clarity_right_distance <= clarity_best_distance_sq:
                    clarity_stack.append(clarity_right)
                if clarity_left_distance <= clarity_best_distance_sq:
                    clarity_stack.append(clarity_left)
            else:
                if clarity_left_distance <= clarity_best_distance_sq:
                    clarity_stack.append(clarity_left)
                if clarity_right_distance <= clarity_best_distance_sq:
                    clarity_stack.append(clarity_right)
    return clarity_best_triangle, clarity_best_barycentric, clarity_best_point, clarity_best_distance_sq


def _clarity_slerp(clarity_a, clarity_b, clarity_factor):
    clarity_a = clarity_a.normalized()
    clarity_b = clarity_b.normalized()
    if clarity_factor <= 0.0:
        return clarity_a
    if clarity_factor >= 1.0:
        return clarity_b
    clarity_dot = max(-1.0, min(1.0, clarity_a.dot(clarity_b)))
    if clarity_dot > 0.9995:
        clarity_result = clarity_a + clarity_factor * (clarity_b - clarity_a)
        return clarity_result.normalized()
    if clarity_dot < -0.9995:
        clarity_axis = Vector((1.0, 0.0, 0.0))
        if abs(clarity_a.x) > abs(clarity_a.y):
            clarity_axis = Vector((0.0, 1.0, 0.0))
        clarity_orthogonal = clarity_a.cross(clarity_axis).normalized()
        clarity_angle = math.pi * clarity_factor
        return (math.cos(clarity_angle) * clarity_a + math.sin(clarity_angle) * clarity_orthogonal).normalized()
    clarity_angle = math.acos(clarity_dot)
    clarity_sine = math.sin(clarity_angle)
    return (
        math.sin((1.0 - clarity_factor) * clarity_angle) / clarity_sine * clarity_a
        + math.sin(clarity_factor * clarity_angle) / clarity_sine * clarity_b
    ).normalized()


def clarity_transfer_normals_exact_generator(
        clarity_foliage_vertices,
        clarity_existing_normals,
        clarity_proxy_vertices,
        clarity_proxy_triangles,
        clarity_proxy_normals,
        clarity_influence,
        clarity_upward_bias,
        clarity_up):
    if not clarity_proxy_triangles:
        raise RuntimeError("Normal proxy mesh has no triangles.")
    clarity_triangle_normals = []
    clarity_triangle_count = max(1, len(clarity_proxy_triangles))
    for clarity_triangle_number, clarity_triangle in enumerate(clarity_proxy_triangles):
        clarity_normal = (
            clarity_proxy_vertices[clarity_triangle[1]] - clarity_proxy_vertices[clarity_triangle[0]]
        ).cross(
            clarity_proxy_vertices[clarity_triangle[2]] - clarity_proxy_vertices[clarity_triangle[0]]
        )
        clarity_triangle_normals.append(
            clarity_normal.normalized() if clarity_normal.length > 1e-12 else Vector((0.0, 1.0, 0.0))
        )
        if clarity_triangle_number % 256 == 0:
            yield (
                0.05 * (clarity_triangle_number + 1) / clarity_triangle_count,
                "Preparing proxy triangles",
            )
    clarity_safe_normals = [
        clarity_normal.normalized()
        if clarity_normal.length_squared > 1e-12
        else Vector((0.0, 1.0, 0.0))
        for clarity_normal in clarity_proxy_normals
    ]
    clarity_bvh_generator = _clarity_build_bvh_generator(
        clarity_proxy_vertices, clarity_proxy_triangles
    )
    clarity_bvh_steps = 0
    clarity_bvh_estimate = max(1, 2 * math.ceil(clarity_triangle_count / 8))
    while True:
        try:
            clarity_bvh_steps += next(clarity_bvh_generator)
            yield (
                0.05 + 0.20 * min(1.0, clarity_bvh_steps / clarity_bvh_estimate),
                "Building transfer acceleration structure",
            )
        except StopIteration as clarity_stop:
            clarity_nodes, clarity_permutation = clarity_stop.value
            break
    clarity_output = []
    clarity_foliage_count = max(1, len(clarity_foliage_vertices))
    for clarity_vertex_number, (clarity_point, clarity_existing) in enumerate(
            zip(clarity_foliage_vertices, clarity_existing_normals)):
        clarity_triangle_index, clarity_barycentric, _clarity_closest, _clarity_distance_sq = _clarity_closest_triangle(
            clarity_nodes,
            clarity_permutation,
            clarity_point,
            clarity_proxy_vertices,
            clarity_proxy_triangles,
        )
        if clarity_triangle_index < 0:
            clarity_proxy_normal = Vector((0.0, 1.0, 0.0))
        else:
            clarity_triangle = clarity_proxy_triangles[clarity_triangle_index]
            clarity_proxy_normal = (
                clarity_safe_normals[clarity_triangle[0]] * clarity_barycentric.x
                + clarity_safe_normals[clarity_triangle[1]] * clarity_barycentric.y
                + clarity_safe_normals[clarity_triangle[2]] * clarity_barycentric.z
            )
            if clarity_proxy_normal.length_squared < 1e-12:
                clarity_proxy_normal = clarity_triangle_normals[clarity_triangle_index]
            else:
                clarity_proxy_normal.normalize()
                if clarity_proxy_normal.dot(clarity_triangle_normals[clarity_triangle_index]) < 0.0:
                    clarity_proxy_normal.negate()
        clarity_result = _clarity_slerp(clarity_existing, clarity_proxy_normal, clarity_influence)
        clarity_result = _clarity_slerp(clarity_result, clarity_up, clarity_upward_bias)
        clarity_output.append(clarity_result.normalized())
        yield (
            0.25 + 0.75 * (clarity_vertex_number + 1) / clarity_foliage_count,
            "Transferring normals to foliage",
        )
    return clarity_output


def clarity_transfer_normals_exact(
        clarity_foliage_vertices,
        clarity_existing_normals,
        clarity_proxy_vertices,
        clarity_proxy_triangles,
        clarity_proxy_normals,
        clarity_influence,
        clarity_upward_bias,
        clarity_up):
    clarity_generator = clarity_transfer_normals_exact_generator(
        clarity_foliage_vertices,
        clarity_existing_normals,
        clarity_proxy_vertices,
        clarity_proxy_triangles,
        clarity_proxy_normals,
        clarity_influence,
        clarity_upward_bias,
        clarity_up,
    )
    while True:
        try:
            next(clarity_generator)
        except StopIteration as clarity_stop:
            return clarity_stop.value
