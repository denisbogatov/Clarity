"""Proxy generation and foliage-normal transfer for the Clarity tree tool."""

import math

import bpy
from mathutils import Vector

from clarity_normal_transfer_math import (
    clarity_transfer_normals_exact_generator,
)
from clarity_proxy_log import clarity_proxy_log
from clarity_sdf_proxy import clarity_build_sdf_proxy_generator


CLARITY_PROXY_TAG = "clarity_foliage_normal_proxy"
CLARITY_PROXY_NORMALS = "clarity_proxy_gradient_normals"
CLARITY_PROXY_UP_WORLD = "clarity_proxy_up_world"
CLARITY_NORMAL_BACKUP = "clarity_original_corner_normals"
CLARITY_SMOOTH_BACKUP = "clarity_original_smooth_faces"


def _clarity_proxy_name(clarity_leaves):
    return f"Clarity_NormalProxy::{clarity_leaves.name}"


def _clarity_hemisphere_world_axes(clarity_leaves, clarity_trunk, clarity_fallback_axis):
    clarity_world_vertices = [
        clarity_leaves.matrix_world @ clarity_vertex.co
        for clarity_vertex in clarity_leaves.data.vertices
    ]
    clarity_crown_center = sum(clarity_world_vertices, Vector()) / len(clarity_world_vertices)
    clarity_tree_origin = (
        clarity_trunk.matrix_world.translation.copy()
        if clarity_trunk is not None
        else clarity_leaves.matrix_world.translation.copy()
    )
    clarity_direction = clarity_crown_center - clarity_tree_origin
    if clarity_direction.length_squared <= 1e-12:
        clarity_up_index = {'X': 0, 'Y': 1, 'Z': 2}[clarity_fallback_axis]
        clarity_up_sign = 1.0
    else:
        clarity_up_index = max(range(3), key=lambda clarity_axis: abs(clarity_direction[clarity_axis]))
        clarity_up_sign = 1.0 if clarity_direction[clarity_up_index] >= 0.0 else -1.0

    clarity_up = Vector((0.0, 0.0, 0.0))
    clarity_up[clarity_up_index] = clarity_up_sign
    clarity_first_index, clarity_second_index = {
        0: (1, 2),
        1: (2, 0),
        2: (0, 1),
    }[clarity_up_index]
    clarity_first = Vector((0.0, 0.0, 0.0))
    clarity_second = Vector((0.0, 0.0, 0.0))
    clarity_first[clarity_first_index] = 1.0
    clarity_second[clarity_second_index] = clarity_up_sign
    clarity_axis_name = f"{'+' if clarity_up_sign > 0.0 else '-'}{'XYZ'[clarity_up_index]}"
    return clarity_world_vertices, clarity_first, clarity_second, clarity_up, clarity_axis_name


def _clarity_build_hemisphere_proxy_data(
        clarity_leaves,
        clarity_trunk,
        clarity_resolution,
        clarity_up_axis):
    (
        clarity_world_vertices,
        clarity_first_axis,
        clarity_second_axis,
        clarity_up_axis_world,
        clarity_axis_name,
    ) = _clarity_hemisphere_world_axes(
        clarity_leaves,
        clarity_trunk,
        clarity_up_axis,
    )
    clarity_first_values = [
        clarity_vertex.dot(clarity_first_axis) for clarity_vertex in clarity_world_vertices
    ]
    clarity_second_values = [
        clarity_vertex.dot(clarity_second_axis) for clarity_vertex in clarity_world_vertices
    ]
    clarity_up_values = [
        clarity_vertex.dot(clarity_up_axis_world) for clarity_vertex in clarity_world_vertices
    ]
    clarity_first_center = (min(clarity_first_values) + max(clarity_first_values)) * 0.5
    clarity_second_center = (min(clarity_second_values) + max(clarity_second_values)) * 0.5
    clarity_base_up = min(clarity_up_values)
    clarity_center_world = (
        clarity_first_axis * clarity_first_center
        + clarity_second_axis * clarity_second_center
        + clarity_up_axis_world * clarity_base_up
    )
    clarity_first_radius = max(
        (max(clarity_first_values) - min(clarity_first_values)) * 0.5,
        1e-6,
    )
    clarity_second_radius = max(
        (max(clarity_second_values) - min(clarity_second_values)) * 0.5,
        1e-6,
    )
    clarity_up_radius = max(max(clarity_up_values) - clarity_base_up, 1e-6)
    clarity_fit_scale = max(
        math.sqrt(
            (clarity_vertex.dot(clarity_first_axis) - clarity_first_center) ** 2
            / (clarity_first_radius * clarity_first_radius)
            + (clarity_vertex.dot(clarity_second_axis) - clarity_second_center) ** 2
            / (clarity_second_radius * clarity_second_radius)
            + (clarity_vertex.dot(clarity_up_axis_world) - clarity_base_up) ** 2
            / (clarity_up_radius * clarity_up_radius)
        )
        for clarity_vertex in clarity_world_vertices
    )
    clarity_fit_scale = max(1.0, clarity_fit_scale) * 1.01
    clarity_first_radius *= clarity_fit_scale
    clarity_second_radius *= clarity_fit_scale
    clarity_up_radius *= clarity_fit_scale
    if max(clarity_first_radius, clarity_second_radius, clarity_up_radius) <= 1e-8:
        raise RuntimeError("Leaves bounds are too small to build a hemisphere proxy.")

    clarity_world_to_local = clarity_leaves.matrix_world.inverted()
    clarity_world_to_local_normal = clarity_leaves.matrix_world.to_3x3().transposed()
    clarity_segments = max(8, min(256, int(clarity_resolution)))
    clarity_rings = max(2, clarity_segments // 4)
    clarity_proxy_vertices = []
    clarity_proxy_normals = []
    for clarity_ring in range(clarity_rings):
        clarity_elevation = (math.pi * 0.5) * clarity_ring / clarity_rings
        clarity_planar = math.cos(clarity_elevation)
        clarity_elevation_up = math.sin(clarity_elevation)
        for clarity_segment in range(clarity_segments):
            clarity_angle = math.tau * clarity_segment / clarity_segments
            clarity_first = clarity_planar * math.cos(clarity_angle)
            clarity_second = clarity_planar * math.sin(clarity_angle)
            clarity_position_world = (
                clarity_center_world
                + clarity_first_axis * (clarity_first * clarity_first_radius)
                + clarity_second_axis * (clarity_second * clarity_second_radius)
                + clarity_up_axis_world * (clarity_elevation_up * clarity_up_radius)
            )
            clarity_normal_world = (
                clarity_first_axis * (clarity_first / clarity_first_radius)
                + clarity_second_axis * (clarity_second / clarity_second_radius)
                + clarity_up_axis_world * (clarity_elevation_up / clarity_up_radius)
            ).normalized()
            clarity_normal_local = clarity_world_to_local_normal @ clarity_normal_world
            clarity_proxy_normals.append(clarity_normal_local.normalized())
            clarity_proxy_vertices.append(clarity_world_to_local @ clarity_position_world)

    clarity_pole_normal = clarity_world_to_local_normal @ clarity_up_axis_world
    clarity_pole_normal.normalize()
    clarity_pole_index = len(clarity_proxy_vertices)
    clarity_proxy_vertices.append(
        clarity_world_to_local @ (
            clarity_center_world + clarity_up_axis_world * clarity_up_radius
        )
    )
    clarity_proxy_normals.append(clarity_pole_normal)

    clarity_proxy_triangles = []
    for clarity_ring in range(clarity_rings - 1):
        clarity_lower = clarity_ring * clarity_segments
        clarity_upper = (clarity_ring + 1) * clarity_segments
        for clarity_segment in range(clarity_segments):
            clarity_next = (clarity_segment + 1) % clarity_segments
            clarity_proxy_triangles.append((
                clarity_lower + clarity_segment,
                clarity_lower + clarity_next,
                clarity_upper + clarity_next,
            ))
            clarity_proxy_triangles.append((
                clarity_lower + clarity_segment,
                clarity_upper + clarity_next,
                clarity_upper + clarity_segment,
            ))
    clarity_last_ring = (clarity_rings - 1) * clarity_segments
    for clarity_segment in range(clarity_segments):
        clarity_next = (clarity_segment + 1) % clarity_segments
        clarity_proxy_triangles.append((
            clarity_last_ring + clarity_segment,
            clarity_last_ring + clarity_next,
            clarity_pole_index,
        ))

    clarity_proxy_log(
        "hemisphere-data-finalized",
        requested_up_axis=clarity_up_axis,
        resolved_up_axis=clarity_axis_name,
        first_radius=clarity_first_radius,
        second_radius=clarity_second_radius,
        up_radius=clarity_up_radius,
        segments=clarity_segments,
        rings=clarity_rings,
        vertices=len(clarity_proxy_vertices),
        triangles=len(clarity_proxy_triangles),
    )
    return (
        clarity_proxy_vertices,
        clarity_proxy_triangles,
        clarity_proxy_normals,
        clarity_up_axis_world,
    )


def _clarity_replace_object_mesh(clarity_object, clarity_mesh):
    clarity_old_mesh = clarity_object.data
    clarity_object.data = clarity_mesh
    if clarity_old_mesh is not None and clarity_old_mesh.users == 0:
        bpy.data.meshes.remove(clarity_old_mesh)


def _clarity_sanitize_proxy_mesh_data(
        clarity_proxy_vertices,
        clarity_proxy_triangles,
        clarity_proxy_normals):
    clarity_vertex_count = len(clarity_proxy_vertices)
    if len(clarity_proxy_normals) != clarity_vertex_count:
        clarity_proxy_log(
            "mesh-data-invalid",
            reason="normal-count-mismatch",
            vertices=clarity_vertex_count,
            normals=len(clarity_proxy_normals),
        )
        raise RuntimeError("SDF proxy normal count does not match its vertex count.")

    clarity_vertices = [
        tuple(float(clarity_component) for clarity_component in clarity_vertex)
        for clarity_vertex in clarity_proxy_vertices
    ]
    clarity_non_finite_vertices = sum(
        not all(math.isfinite(clarity_component) for clarity_component in clarity_vertex)
        for clarity_vertex in clarity_vertices
    )
    if clarity_non_finite_vertices:
        clarity_proxy_log(
            "mesh-data-invalid",
            reason="non-finite-vertices",
            count=clarity_non_finite_vertices,
        )
        raise RuntimeError("SDF proxy contains non-finite vertex coordinates.")

    clarity_normals = []
    clarity_repaired_normals = 0
    for clarity_normal in clarity_proxy_normals:
        clarity_normal_tuple = tuple(float(component) for component in clarity_normal)
        if not all(math.isfinite(component) for component in clarity_normal_tuple):
            clarity_normal_tuple = (0.0, 1.0, 0.0)
            clarity_repaired_normals += 1
        clarity_normals.append(clarity_normal_tuple)

    clarity_triangles = []
    clarity_invalid_indices = 0
    clarity_collapsed_triangles = 0
    clarity_zero_area_triangles = 0
    clarity_duplicate_triangles = 0
    clarity_seen_triangles = set()
    for clarity_triangle in clarity_proxy_triangles:
        clarity_indices = tuple(int(index) for index in clarity_triangle)
        if len(clarity_indices) != 3 or any(
                index < 0 or index >= clarity_vertex_count for index in clarity_indices):
            clarity_invalid_indices += 1
            continue
        if len(set(clarity_indices)) != 3:
            clarity_collapsed_triangles += 1
            continue
        clarity_a = Vector(clarity_vertices[clarity_indices[0]])
        clarity_b = Vector(clarity_vertices[clarity_indices[1]])
        clarity_c = Vector(clarity_vertices[clarity_indices[2]])
        if (clarity_b - clarity_a).cross(clarity_c - clarity_a).length_squared <= 1e-20:
            clarity_zero_area_triangles += 1
            continue
        clarity_triangle_key = tuple(sorted(clarity_indices))
        if clarity_triangle_key in clarity_seen_triangles:
            clarity_duplicate_triangles += 1
            continue
        clarity_seen_triangles.add(clarity_triangle_key)
        clarity_triangles.append(clarity_indices)

    clarity_proxy_log(
        "mesh-data-sanitized",
        vertices=len(clarity_vertices),
        input_triangles=len(clarity_proxy_triangles),
        triangles=len(clarity_triangles),
        invalid_indices=clarity_invalid_indices,
        collapsed_triangles=clarity_collapsed_triangles,
        zero_area_triangles=clarity_zero_area_triangles,
        duplicate_triangles=clarity_duplicate_triangles,
        repaired_normals=clarity_repaired_normals,
    )
    if clarity_invalid_indices:
        raise RuntimeError("SDF proxy contains triangle indices outside its vertex array.")
    if not clarity_triangles:
        raise RuntimeError("SDF proxy contains no valid triangles after validation.")
    return clarity_vertices, clarity_triangles, clarity_normals


def _clarity_proxy_mesh_from_data(
        clarity_name,
        clarity_proxy_vertices,
        clarity_proxy_triangles,
        clarity_proxy_normals):
    if not clarity_proxy_vertices or not clarity_proxy_triangles:
        raise RuntimeError("SDF proxy generation returned an empty mesh.")
    clarity_proxy_log(
        "mesh-create-begin",
        vertices=len(clarity_proxy_vertices),
        triangles=len(clarity_proxy_triangles),
        normals=len(clarity_proxy_normals),
    )
    (
        clarity_proxy_vertices,
        clarity_proxy_triangles,
        clarity_proxy_normals,
    ) = _clarity_sanitize_proxy_mesh_data(
        clarity_proxy_vertices,
        clarity_proxy_triangles,
        clarity_proxy_normals,
    )
    clarity_mesh = bpy.data.meshes.new(clarity_name)
    clarity_proxy_log("mesh-datablock-created", mesh=clarity_mesh.name)
    clarity_mesh.from_pydata(clarity_proxy_vertices, (), clarity_proxy_triangles)
    clarity_proxy_log(
        "mesh-from-pydata-complete",
        vertices=len(clarity_mesh.vertices),
        polygons=len(clarity_mesh.polygons),
        loops=len(clarity_mesh.loops),
    )
    for clarity_polygon in clarity_mesh.polygons:
        clarity_polygon.use_smooth = True
    clarity_proxy_log("mesh-smooth-flags-complete")
    clarity_normal_attribute = clarity_mesh.attributes.new(
        CLARITY_PROXY_NORMALS,
        type='FLOAT_VECTOR',
        domain='POINT',
    )
    clarity_proxy_log("mesh-normal-attribute-created")
    clarity_normal_attribute.data.foreach_set(
        'vector',
        [
            clarity_component
            for clarity_normal in clarity_proxy_normals
            for clarity_component in clarity_normal
        ],
    )
    clarity_proxy_log("mesh-normal-attribute-filled")
    clarity_mesh.normals_split_custom_set_from_vertices(clarity_proxy_normals)
    clarity_proxy_log("mesh-custom-normals-complete")
    clarity_mesh.update()
    clarity_proxy_log("mesh-update-complete")
    return clarity_mesh


def clarity_build_foliage_proxy_generator(
        clarity_leaves,
        clarity_trunk,
        clarity_existing_proxy,
        clarity_proxy_mode,
        clarity_up_axis,
        clarity_resolution,
        clarity_tightness,
        clarity_smooth_iterations,
        clarity_weld,
        clarity_weld_distance):
    if clarity_leaves is None or clarity_leaves.type != 'MESH':
        raise RuntimeError("Choose a Leaves mesh first.")
    if len(clarity_leaves.data.vertices) < 4:
        raise RuntimeError("Leaves mesh does not contain enough vertices.")
    if clarity_existing_proxy is clarity_leaves:
        raise RuntimeError("Leaves cannot also be used as their own normal proxy.")
    if clarity_existing_proxy is not None and not clarity_existing_proxy.get(CLARITY_PROXY_TAG):
        raise RuntimeError("The Proxy field contains an object not owned by Clarity.")

    clarity_source = clarity_leaves.data
    clarity_source.calc_loop_triangles()
    clarity_proxy_log(
        "source-read-begin",
        leaves=clarity_leaves.name,
        proxy_mode=clarity_proxy_mode,
        up_axis=clarity_up_axis,
        resolution=clarity_resolution,
        tightness=clarity_tightness,
        blur=clarity_smooth_iterations,
        weld=clarity_weld,
        source_vertices=len(clarity_source.vertices),
        source_triangles=len(clarity_source.loop_triangles),
    )
    clarity_vertices = [
        clarity_vertex.co.copy() for clarity_vertex in clarity_source.vertices
    ]
    clarity_triangles = [
        tuple(clarity_triangle.vertices)
        for clarity_triangle in clarity_source.loop_triangles
    ]
    if clarity_proxy_mode == 'HEMISPHERE':
        yield 0.35, "Building upper hemisphere"
        (
            clarity_proxy_vertices,
            clarity_proxy_triangles,
            clarity_proxy_normals,
            clarity_proxy_up_world,
        ) = _clarity_build_hemisphere_proxy_data(
            clarity_leaves,
            clarity_trunk,
            clarity_resolution,
            clarity_up_axis,
        )
        yield 0.995, "Finalizing hemisphere proxy"
    else:
        clarity_proxy_up_world = None
        clarity_sdf_generator = clarity_build_sdf_proxy_generator(
            clarity_vertices,
            clarity_triangles,
            clarity_resolution,
            clarity_tightness,
            clarity_smooth_iterations,
            clarity_weld,
            clarity_weld_distance,
        )
        while True:
            try:
                yield next(clarity_sdf_generator)
            except StopIteration as clarity_stop:
                (
                    clarity_proxy_vertices,
                    clarity_proxy_triangles,
                    clarity_proxy_normals,
                ) = clarity_stop.value
                break
        clarity_proxy_log(
            "sdf-generator-complete",
            proxy_vertices=len(clarity_proxy_vertices),
            proxy_triangles=len(clarity_proxy_triangles),
            proxy_normals=len(clarity_proxy_normals),
        )

    clarity_name = _clarity_proxy_name(clarity_leaves)
    yield 0.997, "Creating Blender proxy mesh"
    clarity_mesh = _clarity_proxy_mesh_from_data(
        clarity_name,
        clarity_proxy_vertices,
        clarity_proxy_triangles,
        clarity_proxy_normals,
    )
    clarity_proxy_log("mesh-build-function-complete", mesh=clarity_mesh.name)

    clarity_proxy = clarity_existing_proxy
    if clarity_proxy is None or clarity_proxy.name not in bpy.data.objects:
        clarity_proxy_log("object-create-begin")
        clarity_proxy = bpy.data.objects.new(clarity_name, clarity_mesh)
        clarity_collection = (
            clarity_leaves.users_collection[0]
            if clarity_leaves.users_collection
            else bpy.context.scene.collection
        )
        clarity_collection.objects.link(clarity_proxy)
        clarity_proxy_log("object-created-and-linked", object=clarity_proxy.name)
    else:
        clarity_proxy_log("object-mesh-replace-begin", object=clarity_proxy.name)
        _clarity_replace_object_mesh(clarity_proxy, clarity_mesh)
        clarity_proxy_log("object-mesh-replace-complete", object=clarity_proxy.name)

    clarity_proxy.name = clarity_name
    clarity_proxy.matrix_world = clarity_leaves.matrix_world
    clarity_proxy[CLARITY_PROXY_TAG] = True
    if clarity_proxy_up_world is not None:
        clarity_proxy[CLARITY_PROXY_UP_WORLD] = tuple(clarity_proxy_up_world)
    elif CLARITY_PROXY_UP_WORLD in clarity_proxy:
        del clarity_proxy[CLARITY_PROXY_UP_WORLD]
    clarity_proxy.display_type = 'WIRE'
    clarity_proxy.show_in_front = True
    clarity_proxy.hide_render = True
    clarity_proxy_log("proxy-generator-return", object=clarity_proxy.name)
    return clarity_proxy


def clarity_build_foliage_proxy(
        clarity_leaves,
        clarity_trunk,
        clarity_existing_proxy,
        clarity_proxy_mode,
        clarity_up_axis,
        clarity_resolution,
        clarity_tightness,
        clarity_smooth_iterations,
        clarity_weld,
        clarity_weld_distance):
    clarity_generator = clarity_build_foliage_proxy_generator(
        clarity_leaves,
        clarity_trunk,
        clarity_existing_proxy,
        clarity_proxy_mode,
        clarity_up_axis,
        clarity_resolution,
        clarity_tightness,
        clarity_smooth_iterations,
        clarity_weld,
        clarity_weld_distance,
    )
    while True:
        try:
            next(clarity_generator)
        except StopIteration as clarity_stop:
            return clarity_stop.value


def _clarity_store_normal_backup(clarity_mesh, clarity_normals):
    clarity_attribute = clarity_mesh.attributes.get(CLARITY_NORMAL_BACKUP)
    if clarity_attribute is not None and (
            clarity_attribute.data_type != 'FLOAT_VECTOR'
            or clarity_attribute.domain != 'CORNER'):
        clarity_mesh.attributes.remove(clarity_attribute)
        clarity_attribute = None
    if clarity_attribute is None:
        clarity_attribute = clarity_mesh.attributes.new(
            CLARITY_NORMAL_BACKUP,
            type='FLOAT_VECTOR',
            domain='CORNER',
        )
        clarity_values = [clarity_component for clarity_normal in clarity_normals for clarity_component in clarity_normal]
        clarity_attribute.data.foreach_set('vector', clarity_values)
    clarity_smooth = clarity_mesh.attributes.get(CLARITY_SMOOTH_BACKUP)
    if clarity_smooth is None:
        clarity_smooth = clarity_mesh.attributes.new(
            CLARITY_SMOOTH_BACKUP,
            type='BOOLEAN',
            domain='FACE',
        )
        clarity_smooth.data.foreach_set(
            'value',
            [clarity_polygon.use_smooth for clarity_polygon in clarity_mesh.polygons],
        )


def clarity_transfer_foliage_normals_generator(
        clarity_leaves,
        clarity_proxy,
        clarity_influence,
        clarity_upward_bias,
        clarity_up_axis,
        clarity_force_smooth):
    if clarity_leaves is None or clarity_leaves.type != 'MESH':
        raise RuntimeError("Choose a Leaves mesh first.")
    if clarity_proxy is None or clarity_proxy.type != 'MESH':
        raise RuntimeError("Build or choose a normal proxy mesh first.")
    if clarity_proxy is clarity_leaves:
        raise RuntimeError("Leaves cannot also be used as their own normal proxy.")
    clarity_mesh = clarity_leaves.data
    clarity_proxy_mesh = clarity_proxy.data
    if len(clarity_proxy_mesh.polygons) == 0:
        raise RuntimeError("Normal proxy mesh has no faces.")

    clarity_proxy_mesh.update()
    clarity_proxy_mesh.calc_loop_triangles()
    yield 0.01, "Preparing normal transfer"
    clarity_proxy_to_target = clarity_leaves.matrix_world.inverted() @ clarity_proxy.matrix_world
    clarity_proxy_to_world_normal = clarity_proxy.matrix_world.to_3x3().inverted().transposed()
    clarity_world_to_target_normal = clarity_leaves.matrix_world.to_3x3().transposed()
    clarity_proxy_vertices = [
        clarity_proxy_to_target @ clarity_vertex.co
        for clarity_vertex in clarity_proxy_mesh.vertices
    ]
    clarity_proxy_triangles = [
        tuple(clarity_triangle.vertices)
        for clarity_triangle in clarity_proxy_mesh.loop_triangles
    ]
    yield 0.04, "Reading proxy geometry"
    clarity_stored_normals = clarity_proxy_mesh.attributes.get(CLARITY_PROXY_NORMALS)
    if clarity_stored_normals is not None and (
            clarity_stored_normals.data_type == 'FLOAT_VECTOR'
            and clarity_stored_normals.domain == 'POINT'
            and len(clarity_stored_normals.data) == len(clarity_proxy_mesh.vertices)):
        clarity_normal_values = [0.0] * (len(clarity_proxy_mesh.vertices) * 3)
        clarity_stored_normals.data.foreach_get('vector', clarity_normal_values)
        clarity_source_normals = [
            Vector(clarity_normal_values[clarity_index:clarity_index + 3])
            for clarity_index in range(0, len(clarity_normal_values), 3)
        ]
    else:
        clarity_source_normals = [
            clarity_vertex.normal.copy() for clarity_vertex in clarity_proxy_mesh.vertices
        ]
    clarity_proxy_normals = []
    for clarity_source_normal in clarity_source_normals:
        clarity_world_normal = clarity_proxy_to_world_normal @ clarity_source_normal
        clarity_target_normal = clarity_world_to_target_normal @ clarity_world_normal
        clarity_proxy_normals.append(
            clarity_target_normal.normalized()
            if clarity_target_normal.length_squared > 1e-20
            else Vector((0.0, 1.0, 0.0))
        )
    yield 0.08, "Transforming proxy normals"
    clarity_proxy_up_world = clarity_proxy.get(CLARITY_PROXY_UP_WORLD)
    if clarity_proxy_up_world is not None and len(clarity_proxy_up_world) == 3:
        clarity_up = clarity_leaves.matrix_world.to_3x3().transposed() @ Vector(
            clarity_proxy_up_world
        )
        clarity_up.normalize()
    else:
        clarity_up = {
            'X': Vector((1.0, 0.0, 0.0)),
            'Y': Vector((0.0, 1.0, 0.0)),
            'Z': Vector((0.0, 0.0, 1.0)),
        }[clarity_up_axis]

    clarity_original = [clarity_loop.normal.copy() for clarity_loop in clarity_mesh.loops]
    clarity_exact_generator = clarity_transfer_normals_exact_generator(
        [clarity_vertex.co.copy() for clarity_vertex in clarity_mesh.vertices],
        [clarity_vertex.normal.copy() for clarity_vertex in clarity_mesh.vertices],
        clarity_proxy_vertices,
        clarity_proxy_triangles,
        clarity_proxy_normals,
        clarity_influence,
        clarity_upward_bias,
        clarity_up,
    )
    while True:
        try:
            clarity_progress, clarity_status = next(clarity_exact_generator)
            yield 0.08 + 0.87 * clarity_progress, clarity_status
        except StopIteration as clarity_stop:
            clarity_result = clarity_stop.value
            break

    yield 0.97, "Saving original normals"
    _clarity_store_normal_backup(clarity_mesh, clarity_original)
    if clarity_force_smooth:
        for clarity_polygon in clarity_mesh.polygons:
            clarity_polygon.use_smooth = True
    clarity_mesh.normals_split_custom_set_from_vertices(clarity_result)
    clarity_mesh.update()
    return len(clarity_result)


def clarity_transfer_foliage_normals(
        clarity_leaves,
        clarity_proxy,
        clarity_influence,
        clarity_upward_bias,
        clarity_up_axis,
        clarity_force_smooth):
    clarity_generator = clarity_transfer_foliage_normals_generator(
        clarity_leaves,
        clarity_proxy,
        clarity_influence,
        clarity_upward_bias,
        clarity_up_axis,
        clarity_force_smooth,
    )
    while True:
        try:
            next(clarity_generator)
        except StopIteration as clarity_stop:
            return clarity_stop.value


def clarity_restore_foliage_normals(clarity_leaves):
    if clarity_leaves is None or clarity_leaves.type != 'MESH':
        raise RuntimeError("Choose a Leaves mesh first.")
    clarity_mesh = clarity_leaves.data
    clarity_attribute = clarity_mesh.attributes.get(CLARITY_NORMAL_BACKUP)
    if clarity_attribute is None:
        raise RuntimeError("No stored original normals were found on the Leaves mesh.")
    clarity_values = [0.0] * (len(clarity_mesh.loops) * 3)
    clarity_attribute.data.foreach_get('vector', clarity_values)
    clarity_normals = [
        Vector(clarity_values[clarity_index:clarity_index + 3])
        for clarity_index in range(0, len(clarity_values), 3)
    ]
    clarity_smooth = clarity_mesh.attributes.get(CLARITY_SMOOTH_BACKUP)
    if clarity_smooth is not None:
        clarity_smooth_values = [False] * len(clarity_mesh.polygons)
        clarity_smooth.data.foreach_get('value', clarity_smooth_values)
        for clarity_polygon, clarity_use_smooth in zip(
                clarity_mesh.polygons, clarity_smooth_values):
            clarity_polygon.use_smooth = clarity_use_smooth
        clarity_mesh.attributes.remove(clarity_smooth)
    clarity_mesh.normals_split_custom_set(clarity_normals)
    clarity_mesh.attributes.remove(clarity_attribute)
    clarity_mesh.update()


def clarity_delete_foliage_proxy(clarity_proxy):
    if clarity_proxy is None:
        return
    if not clarity_proxy.get(CLARITY_PROXY_TAG):
        raise RuntimeError("The selected object is not a Clarity foliage proxy.")
    clarity_mesh = clarity_proxy.data
    bpy.data.objects.remove(clarity_proxy, do_unlink=True)
    if clarity_mesh is not None and clarity_mesh.users == 0:
        bpy.data.meshes.remove(clarity_mesh)
