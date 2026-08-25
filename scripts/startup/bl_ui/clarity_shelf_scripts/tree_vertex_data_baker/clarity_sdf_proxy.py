"""Direct Clarity port of the Unity foliage renormalizer SDF proxy builder."""

import math

import numpy as np
from mathutils import Vector

from clarity_convex_hull import clarity_build_convex_hull
from clarity_marching_cubes_table import CLARITY_TRIANGLE_CONNECTION_TABLE
from clarity_proxy_log import clarity_proxy_log


_CLARITY_CORNERS = (
    (0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1),
    (0, 1, 0), (1, 1, 0), (1, 1, 1), (0, 1, 1),
)
_CLARITY_EDGES = (
    (0, 1, 'X', (0, 0, 0)), (1, 2, 'Z', (1, 0, 0)),
    (3, 2, 'X', (0, 0, 1)), (0, 3, 'Z', (0, 0, 0)),
    (4, 5, 'X', (0, 1, 0)), (5, 6, 'Z', (1, 1, 0)),
    (7, 6, 'X', (0, 1, 1)), (4, 7, 'Z', (0, 1, 0)),
    (0, 4, 'Y', (0, 0, 0)), (1, 5, 'Y', (1, 0, 0)),
    (2, 6, 'Y', (1, 0, 1)), (3, 7, 'Y', (0, 0, 1)),
)


def _clarity_point_triangle_distance_sq_array(
        clarity_points, clarity_a, clarity_b, clarity_c):
    clarity_ab = clarity_b - clarity_a
    clarity_ac = clarity_c - clarity_a
    clarity_normal = np.cross(clarity_ab, clarity_ac)
    clarity_normal_sq = float(np.dot(clarity_normal, clarity_normal))
    clarity_ap = clarity_points - clarity_a
    clarity_plane_dot = clarity_ap @ clarity_normal
    clarity_projected = (
        clarity_points
        - clarity_plane_dot[:, None] * clarity_normal[None, :] / clarity_normal_sq
    )

    clarity_d00 = float(np.dot(clarity_ab, clarity_ab))
    clarity_d01 = float(np.dot(clarity_ab, clarity_ac))
    clarity_d11 = float(np.dot(clarity_ac, clarity_ac))
    clarity_denominator = clarity_d00 * clarity_d11 - clarity_d01 * clarity_d01
    clarity_projected_ap = clarity_projected - clarity_a
    clarity_d20 = clarity_projected_ap @ clarity_ab
    clarity_d21 = clarity_projected_ap @ clarity_ac
    clarity_v = (clarity_d11 * clarity_d20 - clarity_d01 * clarity_d21) / clarity_denominator
    clarity_w = (clarity_d00 * clarity_d21 - clarity_d01 * clarity_d20) / clarity_denominator
    clarity_inside = (
        (clarity_v >= -1e-12)
        & (clarity_w >= -1e-12)
        & (clarity_v + clarity_w <= 1.0 + 1e-12)
    )
    clarity_result = np.full(len(clarity_points), np.inf, dtype=np.float64)
    clarity_result[clarity_inside] = (
        clarity_plane_dot[clarity_inside] * clarity_plane_dot[clarity_inside]
        / clarity_normal_sq
    )

    for clarity_start, clarity_end in (
            (clarity_a, clarity_b),
            (clarity_b, clarity_c),
            (clarity_c, clarity_a)):
        clarity_edge = clarity_end - clarity_start
        clarity_edge_sq = float(np.dot(clarity_edge, clarity_edge))
        clarity_t = np.clip(
            ((clarity_points - clarity_start) @ clarity_edge) / clarity_edge_sq,
            0.0,
            1.0,
        )
        clarity_delta = clarity_points - (
            clarity_start + clarity_t[:, None] * clarity_edge[None, :]
        )
        np.minimum(
            clarity_result,
            np.einsum('ij,ij->i', clarity_delta, clarity_delta),
            out=clarity_result,
        )
    return clarity_result


def _clarity_edt_lines(clarity_source, clarity_cap_sq):
    clarity_source = np.minimum(clarity_source, clarity_cap_sq).astype(
        np.float32, copy=False
    )
    clarity_line_count, clarity_length = clarity_source.shape
    clarity_rows = np.arange(clarity_line_count, dtype=np.int32)
    clarity_sites = np.zeros((clarity_line_count, clarity_length), dtype=np.int32)
    clarity_breaks = np.empty((clarity_line_count, clarity_length + 1), dtype=np.float32)
    clarity_breaks[:, 0] = -1e20
    clarity_breaks[:, 1] = 1e20
    clarity_levels = np.zeros(clarity_line_count, dtype=np.int32)

    for clarity_q in range(1, clarity_length):
        while True:
            clarity_previous = clarity_sites[clarity_rows, clarity_levels]
            clarity_split = (
                (clarity_source[:, clarity_q] + clarity_q * clarity_q)
                - (
                    clarity_source[clarity_rows, clarity_previous]
                    + clarity_previous * clarity_previous
                )
            ) / (2.0 * (clarity_q - clarity_previous))
            clarity_rewind = (
                clarity_split <= clarity_breaks[clarity_rows, clarity_levels]
            )
            if not np.any(clarity_rewind):
                break
            clarity_levels[clarity_rewind] -= 1
        clarity_levels += 1
        clarity_sites[clarity_rows, clarity_levels] = clarity_q
        clarity_breaks[clarity_rows, clarity_levels] = clarity_split
        clarity_breaks[clarity_rows, clarity_levels + 1] = 1e20

    clarity_result = np.empty_like(clarity_source)
    clarity_levels.fill(0)
    for clarity_q in range(clarity_length):
        while True:
            clarity_advance = (
                clarity_breaks[clarity_rows, clarity_levels + 1] < clarity_q
            )
            if not np.any(clarity_advance):
                break
            clarity_levels[clarity_advance] += 1
        clarity_site = clarity_sites[clarity_rows, clarity_levels]
        clarity_delta = clarity_q - clarity_site
        clarity_result[:, clarity_q] = np.minimum(
            clarity_delta * clarity_delta
            + clarity_source[clarity_rows, clarity_site],
            clarity_cap_sq,
        )
    return clarity_result


def _clarity_distance_transform_generator(
        clarity_occupied, clarity_voxel_size, clarity_cap_meters):
    clarity_cap_voxels = max(0.0, clarity_cap_meters / clarity_voxel_size)
    clarity_cap_sq = clarity_cap_voxels * clarity_cap_voxels
    clarity_distance = np.where(clarity_occupied, 0.0, 1e20).astype(np.float32)
    clarity_batch_size = 4096
    clarity_axis_batches = [
        math.ceil(
            (clarity_distance.size // clarity_distance.shape[clarity_axis])
            / clarity_batch_size
        )
        for clarity_axis in range(3)
    ]
    clarity_total = max(1, sum(clarity_axis_batches))
    clarity_done = 0
    for clarity_axis in range(3):
        clarity_moved = np.moveaxis(clarity_distance, clarity_axis, -1)
        clarity_moved_shape = clarity_moved.shape
        clarity_lines = clarity_moved.reshape(-1, clarity_moved_shape[-1])
        clarity_transformed = np.empty_like(clarity_lines)
        for clarity_start in range(0, len(clarity_lines), clarity_batch_size):
            clarity_end = min(clarity_start + clarity_batch_size, len(clarity_lines))
            clarity_transformed[clarity_start:clarity_end] = _clarity_edt_lines(
                np.ascontiguousarray(clarity_lines[clarity_start:clarity_end]),
                clarity_cap_sq,
            )
            clarity_done += 1
            yield clarity_done / clarity_total
        clarity_distance = np.moveaxis(
            clarity_transformed.reshape(clarity_moved_shape), -1, clarity_axis
        )
    np.maximum(clarity_distance, 0.0, out=clarity_distance)
    np.sqrt(clarity_distance, out=clarity_distance)
    clarity_distance *= clarity_voxel_size
    return clarity_distance


def _clarity_seed_surface_generator(
        clarity_vertices,
        clarity_triangles,
        clarity_grid_min,
        clarity_shape,
        clarity_voxel_size,
        clarity_seed_radius_voxels):
    clarity_occupied = np.zeros(clarity_shape, dtype=np.bool_)
    clarity_radius = clarity_seed_radius_voxels * clarity_voxel_size
    clarity_radius_sq = clarity_radius * clarity_radius
    clarity_grid_min_array = np.asarray(tuple(clarity_grid_min), dtype=np.float64)
    clarity_triangle_count = max(1, len(clarity_triangles))
    for clarity_triangle_number, clarity_triangle in enumerate(clarity_triangles):
        clarity_a = np.asarray(tuple(clarity_vertices[clarity_triangle[0]]), dtype=np.float64)
        clarity_b = np.asarray(tuple(clarity_vertices[clarity_triangle[1]]), dtype=np.float64)
        clarity_c = np.asarray(tuple(clarity_vertices[clarity_triangle[2]]), dtype=np.float64)
        clarity_normal = np.cross(clarity_b - clarity_a, clarity_c - clarity_a)
        clarity_normal_length = float(np.linalg.norm(clarity_normal))
        if clarity_normal_length < 1e-10:
            yield (clarity_triangle_number + 1) / clarity_triangle_count
            continue
        clarity_minimum = np.minimum(np.minimum(clarity_a, clarity_b), clarity_c) - clarity_radius
        clarity_maximum = np.maximum(np.maximum(clarity_a, clarity_b), clarity_c) + clarity_radius
        clarity_lower = [
            max(0, min(clarity_shape[clarity_axis] - 1, math.floor(
                (clarity_minimum[clarity_axis] - clarity_grid_min_array[clarity_axis])
                / clarity_voxel_size
            ))) for clarity_axis in range(3)
        ]
        clarity_upper = [
            max(0, min(clarity_shape[clarity_axis] - 1, math.floor(
                (clarity_maximum[clarity_axis] - clarity_grid_min_array[clarity_axis])
                / clarity_voxel_size
            ))) for clarity_axis in range(3)
        ]

        clarity_dominant_axis = int(np.argmax(np.abs(clarity_normal)))
        clarity_surface_axes = [
            clarity_axis for clarity_axis in range(3)
            if clarity_axis != clarity_dominant_axis
        ]
        clarity_u_axis, clarity_v_axis = clarity_surface_axes
        clarity_u, clarity_v = np.meshgrid(
            np.arange(clarity_lower[clarity_u_axis], clarity_upper[clarity_u_axis] + 1),
            np.arange(clarity_lower[clarity_v_axis], clarity_upper[clarity_v_axis] + 1),
            indexing='ij',
        )
        clarity_u = clarity_u.ravel()
        clarity_v = clarity_v.ravel()
        clarity_u_world = (
            clarity_grid_min_array[clarity_u_axis] + clarity_u * clarity_voxel_size
        )
        clarity_v_world = (
            clarity_grid_min_array[clarity_v_axis] + clarity_v * clarity_voxel_size
        )
        clarity_plane_world = clarity_a[clarity_dominant_axis] - (
            clarity_normal[clarity_u_axis] * (clarity_u_world - clarity_a[clarity_u_axis])
            + clarity_normal[clarity_v_axis] * (clarity_v_world - clarity_a[clarity_v_axis])
        ) / clarity_normal[clarity_dominant_axis]
        clarity_plane_index = (
            clarity_plane_world - clarity_grid_min_array[clarity_dominant_axis]
        ) / clarity_voxel_size
        clarity_layer_count = max(1, math.ceil(
            clarity_seed_radius_voxels * clarity_normal_length
            / abs(float(clarity_normal[clarity_dominant_axis]))
        ))
        clarity_layer_offsets = np.arange(
            -clarity_layer_count, clarity_layer_count + 1, dtype=np.int32
        )
        clarity_dominant = (
            np.floor(clarity_plane_index).astype(np.int32)[:, None]
            + clarity_layer_offsets[None, :]
        )
        clarity_u = np.repeat(clarity_u, len(clarity_layer_offsets))
        clarity_v = np.repeat(clarity_v, len(clarity_layer_offsets))
        clarity_dominant = clarity_dominant.ravel()
        clarity_valid = (
            (clarity_dominant >= clarity_lower[clarity_dominant_axis])
            & (clarity_dominant <= clarity_upper[clarity_dominant_axis])
        )
        clarity_indices = np.empty((int(np.count_nonzero(clarity_valid)), 3), dtype=np.int32)
        clarity_indices[:, clarity_u_axis] = clarity_u[clarity_valid]
        clarity_indices[:, clarity_v_axis] = clarity_v[clarity_valid]
        clarity_indices[:, clarity_dominant_axis] = clarity_dominant[clarity_valid]
        clarity_points = (
            clarity_grid_min_array[None, :]
            + clarity_indices * clarity_voxel_size
        )
        clarity_near_surface = _clarity_point_triangle_distance_sq_array(
            clarity_points, clarity_a, clarity_b, clarity_c
        ) <= clarity_radius_sq * (1.0 + 1e-12)
        clarity_selected = clarity_indices[clarity_near_surface]
        clarity_occupied[
            clarity_selected[:, 0], clarity_selected[:, 1], clarity_selected[:, 2]
        ] = True
        yield (clarity_triangle_number + 1) / clarity_triangle_count
    return clarity_occupied


def _clarity_flood_sign_generator(clarity_unsigned, clarity_block_meters):
    clarity_shape = clarity_unsigned.shape
    clarity_passable = clarity_unsigned > clarity_block_meters
    clarity_outside = np.zeros(clarity_shape, dtype=np.bool_)
    clarity_outside[0, :, :] = clarity_passable[0, :, :]
    clarity_outside[-1, :, :] = clarity_passable[-1, :, :]
    clarity_outside[:, 0, :] = clarity_passable[:, 0, :]
    clarity_outside[:, -1, :] = clarity_passable[:, -1, :]
    clarity_outside[:, :, 0] = clarity_passable[:, :, 0]
    clarity_outside[:, :, -1] = clarity_passable[:, :, -1]
    clarity_frontier = clarity_outside.copy()
    clarity_neighbors = np.zeros_like(clarity_outside)
    clarity_processed = int(np.count_nonzero(clarity_outside))
    clarity_total = max(1, int(np.count_nonzero(clarity_passable)))
    while np.any(clarity_frontier):
        clarity_neighbors.fill(False)
        clarity_neighbors[1:, :, :] |= clarity_frontier[:-1, :, :]
        clarity_neighbors[:-1, :, :] |= clarity_frontier[1:, :, :]
        clarity_neighbors[:, 1:, :] |= clarity_frontier[:, :-1, :]
        clarity_neighbors[:, :-1, :] |= clarity_frontier[:, 1:, :]
        clarity_neighbors[:, :, 1:] |= clarity_frontier[:, :, :-1]
        clarity_neighbors[:, :, :-1] |= clarity_frontier[:, :, 1:]
        clarity_neighbors &= clarity_passable
        clarity_neighbors[clarity_outside] = False
        clarity_new_count = int(np.count_nonzero(clarity_neighbors))
        if clarity_new_count == 0:
            break
        clarity_outside |= clarity_neighbors
        clarity_processed += clarity_new_count
        clarity_frontier, clarity_neighbors = clarity_neighbors, clarity_frontier
        yield min(0.99, clarity_processed / clarity_total)
    yield 1.0
    np.negative(clarity_unsigned, out=clarity_unsigned)
    np.negative(clarity_unsigned, out=clarity_unsigned, where=clarity_outside)
    return clarity_unsigned


def _clarity_blur_sdf_generator(clarity_sdf, clarity_iterations):
    clarity_result = clarity_sdf
    clarity_total = max(1, clarity_iterations * 3)
    clarity_done = 0
    for _clarity_iteration in range(clarity_iterations):
        for clarity_axis in range(3):
            clarity_output = clarity_result.copy()
            clarity_output *= 4.0
            clarity_current = [slice(None)] * 3
            clarity_neighbor = [slice(None)] * 3
            clarity_current[clarity_axis] = slice(1, None)
            clarity_neighbor[clarity_axis] = slice(None, -1)
            np.add(
                clarity_output[tuple(clarity_current)],
                clarity_result[tuple(clarity_neighbor)],
                out=clarity_output[tuple(clarity_current)],
            )
            clarity_current[clarity_axis] = slice(None, -1)
            clarity_neighbor[clarity_axis] = slice(1, None)
            np.add(
                clarity_output[tuple(clarity_current)],
                clarity_result[tuple(clarity_neighbor)],
                out=clarity_output[tuple(clarity_current)],
            )
            clarity_boundary = [slice(None)] * 3
            clarity_boundary[clarity_axis] = 0
            np.add(
                clarity_output[tuple(clarity_boundary)],
                clarity_result[tuple(clarity_boundary)],
                out=clarity_output[tuple(clarity_boundary)],
            )
            clarity_boundary[clarity_axis] = -1
            np.add(
                clarity_output[tuple(clarity_boundary)],
                clarity_result[tuple(clarity_boundary)],
                out=clarity_output[tuple(clarity_boundary)],
            )
            clarity_output /= 6.0
            np.copyto(clarity_result, clarity_output)
            del clarity_output
            clarity_done += 1
            yield clarity_done / clarity_total
    if clarity_iterations == 0:
        yield 1.0
    return clarity_result


def _clarity_convex_hull_arrays(clarity_vertices):
    return clarity_build_convex_hull(clarity_vertices)


def _clarity_sample_sdf_array(
        clarity_sdf, clarity_points, clarity_grid_min, clarity_voxel_size):
    clarity_shape = np.asarray(clarity_sdf.shape, dtype=np.int32)
    clarity_coordinate = np.clip(
        (clarity_points - clarity_grid_min[None, :]) / clarity_voxel_size,
        0.0,
        clarity_shape[None, :] - 1.001,
    )
    clarity_lower = np.floor(clarity_coordinate).astype(np.int32)
    clarity_upper = np.minimum(clarity_lower + 1, clarity_shape[None, :] - 1)
    clarity_fraction = clarity_coordinate - clarity_lower
    clarity_x0, clarity_y0, clarity_z0 = clarity_lower.T
    clarity_x1, clarity_y1, clarity_z1 = clarity_upper.T
    clarity_fx, clarity_fy, clarity_fz = clarity_fraction.T
    clarity_c00 = (
        (1.0 - clarity_fx) * clarity_sdf[clarity_x0, clarity_y0, clarity_z0]
        + clarity_fx * clarity_sdf[clarity_x1, clarity_y0, clarity_z0]
    )
    clarity_c10 = (
        (1.0 - clarity_fx) * clarity_sdf[clarity_x0, clarity_y1, clarity_z0]
        + clarity_fx * clarity_sdf[clarity_x1, clarity_y1, clarity_z0]
    )
    clarity_c01 = (
        (1.0 - clarity_fx) * clarity_sdf[clarity_x0, clarity_y0, clarity_z1]
        + clarity_fx * clarity_sdf[clarity_x1, clarity_y0, clarity_z1]
    )
    clarity_c11 = (
        (1.0 - clarity_fx) * clarity_sdf[clarity_x0, clarity_y1, clarity_z1]
        + clarity_fx * clarity_sdf[clarity_x1, clarity_y1, clarity_z1]
    )
    clarity_c0 = (1.0 - clarity_fy) * clarity_c00 + clarity_fy * clarity_c10
    clarity_c1 = (1.0 - clarity_fy) * clarity_c01 + clarity_fy * clarity_c11
    return (1.0 - clarity_fz) * clarity_c0 + clarity_fz * clarity_c1


def _clarity_sample_gradient_array(
        clarity_sdf, clarity_points, clarity_grid_min, clarity_voxel_size):
    clarity_gradient = np.empty_like(clarity_points)
    for clarity_axis in range(3):
        clarity_offset = np.zeros(3, dtype=np.float64)
        clarity_offset[clarity_axis] = clarity_voxel_size
        clarity_gradient[:, clarity_axis] = (
            _clarity_sample_sdf_array(
                clarity_sdf,
                clarity_points + clarity_offset[None, :],
                clarity_grid_min,
                clarity_voxel_size,
            )
            - _clarity_sample_sdf_array(
                clarity_sdf,
                clarity_points - clarity_offset[None, :],
                clarity_grid_min,
                clarity_voxel_size,
            )
        ) / (2.0 * clarity_voxel_size)
    return clarity_gradient


def _clarity_refine_edges_generator(
        clarity_sdf, clarity_edge_keys, clarity_grid_min, clarity_voxel_size):
    clarity_grid_min = np.asarray(tuple(clarity_grid_min), dtype=np.float64)
    clarity_axis_indices = {'X': 0, 'Y': 1, 'Z': 2}
    clarity_vertices = []
    clarity_normals = []
    clarity_batch_size = 8192
    clarity_edge_count = max(1, len(clarity_edge_keys))
    for clarity_start in range(0, len(clarity_edge_keys), clarity_batch_size):
        clarity_keys = clarity_edge_keys[clarity_start:clarity_start + clarity_batch_size]
        clarity_axes = np.fromiter(
            (clarity_axis_indices[clarity_key[0]] for clarity_key in clarity_keys),
            dtype=np.int32,
            count=len(clarity_keys),
        )
        clarity_coordinates = np.asarray(
            [clarity_key[1:] for clarity_key in clarity_keys], dtype=np.int32
        )
        clarity_rows = np.arange(len(clarity_keys), dtype=np.int32)
        clarity_end_coordinates = clarity_coordinates.copy()
        clarity_end_coordinates[clarity_rows, clarity_axes] += 1
        clarity_value_a = clarity_sdf[
            clarity_coordinates[:, 0],
            clarity_coordinates[:, 1],
            clarity_coordinates[:, 2],
        ].astype(np.float64)
        clarity_value_b = clarity_sdf[
            clarity_end_coordinates[:, 0],
            clarity_end_coordinates[:, 1],
            clarity_end_coordinates[:, 2],
        ].astype(np.float64)
        clarity_denominator = clarity_value_b - clarity_value_a
        clarity_t = np.divide(
            -clarity_value_a,
            clarity_denominator,
            out=np.full(len(clarity_keys), 0.5, dtype=np.float64),
            where=clarity_denominator != 0.0,
        )
        np.clip(clarity_t, 0.0, 1.0, out=clarity_t)
        clarity_edge = np.zeros((len(clarity_keys), 3), dtype=np.float64)
        clarity_edge[clarity_rows, clarity_axes] = clarity_voxel_size
        clarity_a = (
            clarity_grid_min[None, :]
            + clarity_coordinates * clarity_voxel_size
        )
        clarity_active = np.ones(len(clarity_keys), dtype=np.bool_)
        for _clarity_iteration in range(2):
            clarity_points = clarity_a + clarity_t[:, None] * clarity_edge
            clarity_value = _clarity_sample_sdf_array(
                clarity_sdf,
                clarity_points,
                clarity_grid_min,
                clarity_voxel_size,
            )
            clarity_gradient = _clarity_sample_gradient_array(
                clarity_sdf,
                clarity_points,
                clarity_grid_min,
                clarity_voxel_size,
            )
            clarity_derivative = np.einsum('ij,ij->i', clarity_gradient, clarity_edge)
            clarity_valid = clarity_active & (np.abs(clarity_derivative) >= 1e-8)
            clarity_delta = np.zeros(len(clarity_keys), dtype=np.float64)
            clarity_delta[clarity_valid] = np.clip(
                -clarity_value[clarity_valid] / clarity_derivative[clarity_valid],
                -0.5,
                0.5,
            )
            clarity_t[clarity_valid] = np.clip(
                clarity_t[clarity_valid] + clarity_delta[clarity_valid], 0.0, 1.0
            )
            clarity_active = clarity_valid & (np.abs(clarity_delta) >= 1e-4)
        clarity_points = clarity_a + clarity_t[:, None] * clarity_edge
        clarity_gradient = _clarity_sample_gradient_array(
            clarity_sdf,
            clarity_points,
            clarity_grid_min,
            clarity_voxel_size,
        )
        clarity_lengths = np.linalg.norm(clarity_gradient, axis=1)
        clarity_valid_normals = clarity_lengths > 1e-10
        clarity_gradient[clarity_valid_normals] /= clarity_lengths[clarity_valid_normals, None]
        clarity_gradient[~clarity_valid_normals] = (0.0, 1.0, 0.0)
        clarity_vertices.extend(Vector(clarity_point) for clarity_point in clarity_points)
        clarity_normals.extend(Vector(clarity_normal) for clarity_normal in clarity_gradient)
        yield min(1.0, (clarity_start + len(clarity_keys)) / clarity_edge_count)
    if not clarity_edge_keys:
        yield 1.0
    return clarity_vertices, clarity_normals


def _clarity_marching_cubes_generator(clarity_sdf, clarity_voxel_size, clarity_grid_min):
    clarity_corners = [
        clarity_sdf[clarity_dx:clarity_sdf.shape[0] - 1 + clarity_dx,
                    clarity_dy:clarity_sdf.shape[1] - 1 + clarity_dy,
                    clarity_dz:clarity_sdf.shape[2] - 1 + clarity_dz]
        for clarity_dx, clarity_dy, clarity_dz in _CLARITY_CORNERS
    ]
    clarity_minimum = np.minimum.reduce(clarity_corners)
    clarity_maximum = np.maximum.reduce(clarity_corners)
    clarity_cells = np.argwhere((clarity_minimum <= 0.0) & (clarity_maximum >= 0.0))
    clarity_triangles = []
    clarity_edge_cache = {}
    clarity_edge_keys = []
    clarity_cell_count = max(1, len(clarity_cells))
    for clarity_cell_number, (clarity_x, clarity_y, clarity_z) in enumerate(clarity_cells):
        clarity_values = [float(clarity_corner[clarity_x, clarity_y, clarity_z]) for clarity_corner in clarity_corners]
        clarity_cube_index = sum(
            (1 << clarity_index) for clarity_index, clarity_value in enumerate(clarity_values)
            if clarity_value < 0.0
        )
        if clarity_cube_index in (0, 255):
            continue
        def clarity_edge_vertex(clarity_edge):
            _clarity_a, _clarity_b, clarity_axis, clarity_offset = _CLARITY_EDGES[clarity_edge]
            clarity_key = (
                clarity_axis,
                int(clarity_x) + clarity_offset[0],
                int(clarity_y) + clarity_offset[1],
                int(clarity_z) + clarity_offset[2],
            )
            clarity_cached = clarity_edge_cache.get(clarity_key)
            if clarity_cached is not None:
                return clarity_cached
            clarity_index = len(clarity_edge_keys)
            clarity_edge_keys.append(clarity_key)
            clarity_edge_cache[clarity_key] = clarity_index
            return clarity_index

        clarity_row = CLARITY_TRIANGLE_CONNECTION_TABLE[clarity_cube_index]
        for clarity_index in range(0, 16, 3):
            if clarity_row[clarity_index] == -1:
                break
            clarity_triangles.append((
                clarity_edge_vertex(clarity_row[clarity_index]),
                clarity_edge_vertex(clarity_row[clarity_index + 1]),
                clarity_edge_vertex(clarity_row[clarity_index + 2]),
            ))
        if clarity_cell_number % 64 == 0:
            yield 0.9 * (clarity_cell_number + 1) / clarity_cell_count
    clarity_refine_generator = _clarity_refine_edges_generator(
        clarity_sdf, clarity_edge_keys, clarity_grid_min, clarity_voxel_size
    )
    while True:
        try:
            yield 0.9 + 0.1 * next(clarity_refine_generator)
        except StopIteration as clarity_stop:
            clarity_vertices, clarity_normals = clarity_stop.value
            break
    yield 1.0
    return clarity_vertices, clarity_triangles, clarity_normals


def _clarity_weld_generator(
        clarity_vertices, clarity_triangles, clarity_normals, clarity_epsilon):
    clarity_epsilon = max(1e-9, clarity_epsilon)
    clarity_map = {}
    clarity_new_vertices = []
    clarity_new_normals = []
    clarity_remap = [0] * len(clarity_vertices)
    clarity_vertex_count = max(1, len(clarity_vertices))
    for clarity_index, clarity_vertex in enumerate(clarity_vertices):
        clarity_key = tuple(int(round(clarity_component / clarity_epsilon)) for clarity_component in clarity_vertex)
        clarity_new_index = clarity_map.get(clarity_key)
        if clarity_new_index is None:
            clarity_new_index = len(clarity_new_vertices)
            clarity_map[clarity_key] = clarity_new_index
            clarity_new_vertices.append(clarity_vertex)
            clarity_new_normals.append(clarity_normals[clarity_index].copy())
        else:
            clarity_new_normals[clarity_new_index] += clarity_normals[clarity_index]
        clarity_remap[clarity_index] = clarity_new_index
        if clarity_index % 256 == 0:
            yield 0.75 * (clarity_index + 1) / clarity_vertex_count
    for clarity_index, clarity_normal in enumerate(clarity_new_normals):
        clarity_new_normals[clarity_index] = (
            clarity_normal.normalized() if clarity_normal.length > 1e-6 else Vector((0.0, 0.0, 0.0))
        )
        if clarity_index % 256 == 0:
            yield 0.75 + 0.15 * (clarity_index + 1) / max(1, len(clarity_new_normals))
    clarity_new_triangles = []
    clarity_collapsed_triangles = 0
    for clarity_triangle in clarity_triangles:
        clarity_remapped = tuple(
            clarity_remap[clarity_index] for clarity_index in clarity_triangle
        )
        if len(set(clarity_remapped)) != 3:
            clarity_collapsed_triangles += 1
            continue
        clarity_new_triangles.append(clarity_remapped)
    clarity_proxy_log(
        "weld-topology-finalized",
        vertices=len(clarity_new_vertices),
        triangles=len(clarity_new_triangles),
        collapsed_triangles=clarity_collapsed_triangles,
    )
    yield 1.0
    return clarity_new_vertices, clarity_new_triangles, clarity_new_normals


def _clarity_stage(clarity_generator, clarity_start, clarity_span, clarity_status):
    while True:
        try:
            clarity_progress = next(clarity_generator)
            yield (
                clarity_start + clarity_span * max(0.0, min(1.0, clarity_progress)),
                clarity_status,
            )
        except StopIteration as clarity_stop:
            return clarity_stop.value


def clarity_build_sdf_proxy_generator(
        clarity_source_vertices,
        clarity_source_triangles,
        clarity_resolution,
        clarity_tightness,
        clarity_blur_iterations,
        clarity_weld,
        clarity_weld_epsilon):
    clarity_vertices = [Vector(clarity_vertex) for clarity_vertex in clarity_source_vertices]
    if not clarity_vertices or not clarity_source_triangles:
        raise RuntimeError("Leaves mesh has no triangulated surface.")
    clarity_minimum = Vector(tuple(min(clarity_vertex[clarity_axis] for clarity_vertex in clarity_vertices) for clarity_axis in range(3)))
    clarity_maximum = Vector(tuple(max(clarity_vertex[clarity_axis] for clarity_vertex in clarity_vertices) for clarity_axis in range(3)))
    clarity_size = clarity_maximum - clarity_minimum
    clarity_voxel_size = max(clarity_size) / max(1, clarity_resolution)
    if clarity_voxel_size <= 1e-12:
        raise RuntimeError("Leaves bounds are too small to build an SDF proxy.")
    clarity_pad = 5
    clarity_cells = [max(1, math.ceil(clarity_size[clarity_axis] / clarity_voxel_size)) for clarity_axis in range(3)]
    clarity_shape = tuple(clarity_cells[clarity_axis] + 1 + 2 * clarity_pad for clarity_axis in range(3))
    clarity_grid_min = clarity_minimum - Vector((clarity_pad * clarity_voxel_size,) * 3)
    clarity_cap_meters = (clarity_resolution // 2) * clarity_voxel_size
    clarity_proxy_log(
        "sdf-grid-configured",
        resolution=clarity_resolution,
        shape=clarity_shape,
        voxels=int(np.prod(clarity_shape, dtype=np.int64)),
        voxel_size=clarity_voxel_size,
        source_vertices=len(clarity_vertices),
        source_triangles=len(clarity_source_triangles),
    )

    clarity_tight_occupied = yield from _clarity_stage(
        _clarity_seed_surface_generator(
        clarity_vertices,
        clarity_source_triangles,
        clarity_grid_min,
        clarity_shape,
        clarity_voxel_size,
        0.25,
        ),
        0.01,
        0.15,
        "Seeding foliage surface",
    )
    clarity_tight_unsigned = yield from _clarity_stage(
        _clarity_distance_transform_generator(
            clarity_tight_occupied, clarity_voxel_size, clarity_cap_meters
        ),
        0.16,
        0.20,
        "Computing tight distance field",
    )
    del clarity_tight_occupied
    clarity_tight = yield from _clarity_stage(
        _clarity_flood_sign_generator(clarity_tight_unsigned, clarity_voxel_size),
        0.36,
        0.10,
        "Signing tight distance field",
    )
    del clarity_tight_unsigned
    clarity_tight -= clarity_voxel_size
    clarity_t = max(0.0, min(1.0, clarity_tightness))
    if clarity_t >= 0.999:
        clarity_final_sdf = yield from _clarity_stage(
            _clarity_blur_sdf_generator(clarity_tight, clarity_blur_iterations),
            0.46,
            0.22,
            "Smoothing distance field",
        )
    else:
        yield 0.47, "Building convex hull"
        clarity_hull_vertices, clarity_hull_triangles = _clarity_convex_hull_arrays(clarity_vertices)
        clarity_hull_occupied = yield from _clarity_stage(
            _clarity_seed_surface_generator(
                clarity_hull_vertices,
                clarity_hull_triangles,
                clarity_grid_min,
                clarity_shape,
                clarity_voxel_size,
                0.6,
            ),
            0.48,
            0.07,
            "Seeding convex hull",
        )
        clarity_hull_unsigned = yield from _clarity_stage(
            _clarity_distance_transform_generator(
                clarity_hull_occupied, clarity_voxel_size, clarity_cap_meters
            ),
            0.55,
            0.07,
            "Computing hull distance field",
        )
        del clarity_hull_occupied
        clarity_hull = yield from _clarity_stage(
            _clarity_flood_sign_generator(
                clarity_hull_unsigned, 0.5 * clarity_voxel_size
            ),
            0.62,
            0.03,
            "Signing hull distance field",
        )
        del clarity_hull_unsigned
        clarity_blend = clarity_hull
        clarity_blend *= 1.0 - clarity_t
        clarity_tight *= clarity_t
        clarity_blend += clarity_tight
        del clarity_hull
        del clarity_tight
        clarity_final_sdf = yield from _clarity_stage(
            _clarity_blur_sdf_generator(clarity_blend, clarity_blur_iterations),
            0.65,
            0.03,
            "Blending and smoothing fields",
        )
    (
        clarity_proxy_vertices,
        clarity_proxy_triangles,
        clarity_proxy_normals,
    ) = yield from _clarity_stage(
        _clarity_marching_cubes_generator(
            clarity_final_sdf, clarity_voxel_size, clarity_grid_min
        ),
        0.68,
        0.27,
        "Extracting proxy surface",
    )
    if clarity_weld:
        (
            clarity_proxy_vertices,
            clarity_proxy_triangles,
            clarity_proxy_normals,
        ) = yield from _clarity_stage(
            _clarity_weld_generator(
                clarity_proxy_vertices,
                clarity_proxy_triangles,
                clarity_proxy_normals,
                clarity_weld_epsilon,
            ),
            0.95,
            0.04,
            "Welding proxy surface",
        )
    clarity_proxy_log(
        "sdf-data-finalized",
        vertices=len(clarity_proxy_vertices),
        triangles=len(clarity_proxy_triangles),
        normals=len(clarity_proxy_normals),
    )
    yield 0.995, "Finalizing proxy data"
    return clarity_proxy_vertices, clarity_proxy_triangles, clarity_proxy_normals


def clarity_build_sdf_proxy(
        clarity_source_vertices,
        clarity_source_triangles,
        clarity_resolution,
        clarity_tightness,
        clarity_blur_iterations,
        clarity_weld,
        clarity_weld_epsilon):
    clarity_generator = clarity_build_sdf_proxy_generator(
        clarity_source_vertices,
        clarity_source_triangles,
        clarity_resolution,
        clarity_tightness,
        clarity_blur_iterations,
        clarity_weld,
        clarity_weld_epsilon,
    )
    while True:
        try:
            next(clarity_generator)
        except StopIteration as clarity_stop:
            return clarity_stop.value
