# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

import os

import bpy
from bpy_extras.io_utils import axis_conversion
from mathutils import Vector


def evaluated_geometry_node_mesh(node_type, configure=None):
    mesh = bpy.data.meshes.new(f"{node_type} Source")
    obj = bpy.data.objects.new(f"{node_type} Object", mesh)
    bpy.context.scene.collection.objects.link(obj)

    node_tree = bpy.data.node_groups.new(f"{node_type} Test", 'GeometryNodeTree')
    node_tree.interface.new_socket(
        name="Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry'
    )
    output = node_tree.nodes.new("NodeGroupOutput")
    primitive = node_tree.nodes.new(node_type)
    if configure is not None:
        configure(primitive)
    node_tree.links.new(primitive.outputs["Mesh"], output.inputs["Geometry"])

    modifier = obj.modifiers.new(name="Primitive", type='NODES')
    modifier.node_group = node_tree
    bpy.context.view_layer.update()

    evaluated_object = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    evaluated_mesh = evaluated_object.to_mesh()
    try:
        positions = [vertex.co.copy() for vertex in evaluated_mesh.vertices]
        normals = [polygon.normal.copy() for polygon in evaluated_mesh.polygons]
    finally:
        evaluated_object.to_mesh_clear()

    bpy.data.objects.remove(obj, do_unlink=True)
    bpy.data.node_groups.remove(node_tree)
    bpy.data.meshes.remove(mesh)
    return positions, normals


def evaluated_curve_fill_mesh():
    mesh = bpy.data.meshes.new("Curve Fill Source")
    obj = bpy.data.objects.new("Curve Fill Object", mesh)
    bpy.context.scene.collection.objects.link(obj)

    node_tree = bpy.data.node_groups.new("Curve Fill Test", 'GeometryNodeTree')
    node_tree.interface.new_socket(
        name="Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry'
    )
    output = node_tree.nodes.new("NodeGroupOutput")
    circle = node_tree.nodes.new("GeometryNodeCurvePrimitiveCircle")
    fill = node_tree.nodes.new("GeometryNodeFillCurve")
    node_tree.links.new(circle.outputs["Curve"], fill.inputs["Curve"])
    node_tree.links.new(fill.outputs["Mesh"], output.inputs["Geometry"])

    modifier = obj.modifiers.new(name="Curve Fill", type='NODES')
    modifier.node_group = node_tree
    bpy.context.view_layer.update()

    evaluated_object = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    evaluated_mesh = evaluated_object.to_mesh()
    try:
        positions = [vertex.co.copy() for vertex in evaluated_mesh.vertices]
        normals = [polygon.normal.copy() for polygon in evaluated_mesh.polygons]
    finally:
        evaluated_object.to_mesh_clear()

    bpy.data.objects.remove(obj, do_unlink=True)
    bpy.data.node_groups.remove(node_tree)
    bpy.data.meshes.remove(mesh)
    return positions, normals


def main():
    assert axis_conversion(from_forward='Z', from_up='Y').is_identity

    rotate_axis = bpy.ops.transform.rotate.get_rna_type().properties["orient_axis"]
    assert rotate_axis.default == "Y"

    # Every ViewCube corner has its own three-axis preset. The gizmo maps these in the same
    # -/+X, -/+Y, -/+Z order as its corner geometry.
    view_axis_items = bpy.ops.view3d.view_axis.get_rna_type().properties["type"].enum_items
    expected_corner_views = {
        "LEFT_BOTTOM_BACK": 112,
        "LEFT_BOTTOM_FRONT": 113,
        "LEFT_TOP_BACK": 114,
        "LEFT_TOP_FRONT": 115,
        "RIGHT_BOTTOM_BACK": 116,
        "RIGHT_BOTTOM_FRONT": 117,
        "RIGHT_TOP_BACK": 118,
        "RIGHT_TOP_FRONT": 119,
    }
    corner_views = {
        item.identifier: item.value
        for item in view_axis_items
        if item.identifier in expected_corner_views
    }
    assert corner_views == expected_corner_views

    for operator in (bpy.ops.wm.obj_export, bpy.ops.wm.obj_import, bpy.ops.wm.stl_export,
                     bpy.ops.wm.stl_import):
        operator_properties = operator.get_rna_type().properties
        assert operator_properties["forward_axis"].default == "Z"
        assert operator_properties["up_axis"].default == "Y"
    usd_export_properties = bpy.ops.wm.usd_export.get_rna_type().properties
    assert usd_export_properties["export_global_forward_selection"].default == "Z"
    assert usd_export_properties["export_global_up_selection"].default == "Y"

    bpy.ops.wm.read_factory_settings(use_empty=False)
    preferences = bpy.context.preferences
    assert preferences.inputs.interaction_preset == 'CLARITY'
    assert preferences.inputs.view_rotate_method == 'TURNTABLE'
    assert not preferences.view.show_splash
    assert preferences.keymap.active_keyconfig == "Clarity"
    assert all(
        abs(actual - expected) < 1.0e-6
        for actual, expected in zip(bpy.context.scene.gravity, (0.0, -9.81, 0.0))
    )
    view_3d_spaces = [
        area.spaces.active
        for screen in bpy.data.screens
        for area in screen.areas
        if area.type == 'VIEW_3D'
    ]
    assert view_3d_spaces
    for space in view_3d_spaces:
        assert space.overlay.show_floor
        assert space.overlay.show_ortho_grid
        assert space.overlay.show_axis_x
        assert not space.overlay.show_axis_y
        assert space.overlay.show_axis_z
        assert all(abs(value) < 1.0e-6 for value in space.region_3d.view_location)

    view_theme = preferences.themes[0].view_3d
    assert all(
        abs(actual - expected) < 1.0e-6
        for actual, expected in zip(view_theme.object_active, (0.0, 1.0, 0.0))
    )
    assert all(abs(value - 1.0) < 1.0e-6 for value in view_theme.object_selected)

    window_manager = bpy.context.window_manager
    assert window_manager.clarity_interaction_enabled
    assert window_manager.clarity_symmetry_mode == 'OFF'
    assert window_manager.clarity_symmetry_axis == 'X'
    assert abs(window_manager.clarity_symmetry_tolerance - 0.001) < 1.0e-8
    assert window_manager.clarity_symmetry_preserve_seam
    assert abs(window_manager.clarity_symmetry_seam_tolerance - 0.001) < 1.0e-8
    assert window_manager.clarity_symmetry_allow_partial

    # The window manager runs the keyconfig preset only when there is a UI: WM_keyconfig_reload()
    # returns early on `G.background`, so nothing has executed Clarity.py at this point and the only
    # key configurations present are the built-in ones. Running the same entry point the UI runs is
    # what lets the rest of this test check the preset rather than the preference that names it.
    bpy.utils.keyconfig_init()
    assert window_manager.keyconfigs.active.name == "Clarity"
    mesh_keymap = window_manager.keyconfigs.active.keymaps["Mesh"]
    bridge_items = [
        item for item in mesh_keymap.keymap_items
        if item.type == 'B' and item.value == 'PRESS' and item.ctrl and item.shift
    ]
    assert len(bridge_items) == 1
    assert bridge_items[0].idname == "mesh.bridge_edge_loops"
    extrude_items = [
        item for item in mesh_keymap.keymap_items
        if item.type == 'E' and item.value == 'PRESS' and item.ctrl
        and not item.shift and not item.alt and not item.oskey
    ]
    assert len(extrude_items) == 1
    assert extrude_items[0].idname == "mesh.extrude_context_move"

    for keymap_name in ("Object Mode", "Mesh"):
        keymap = window_manager.keyconfigs.active.keymaps[keymap_name]
        soft_selection_items = [
            item for item in keymap.keymap_items
            if item.type == 'B' and item.value == 'PRESS'
            and not item.ctrl and not item.shift and not item.alt and not item.oskey
        ]
        assert len(soft_selection_items) == 1
        assert soft_selection_items[0].idname == "view3d.soft_selection_hotkey"

    knife_modal_keymap = window_manager.keyconfigs.active.keymaps["Knife Tool Modal Map"]
    left_mouse_items = [
        item for item in knife_modal_keymap.keymap_items
        if item.type == 'LEFTMOUSE' and item.value == 'ANY'
    ]
    assert len(left_mouse_items) == 1
    assert left_mouse_items[0].propvalue == 'ADD_CUT'
    undo_items = [
        item for item in knife_modal_keymap.keymap_items
        if item.type == 'Z' and item.value == 'PRESS' and not item.shift
    ]
    redo_items = [
        item for item in knife_modal_keymap.keymap_items
        if item.type == 'Z' and item.value == 'PRESS' and item.shift
    ]
    assert {(item.ctrl, item.propvalue) for item in undo_items} == {
        (False, 'UNDO'),
        (True, 'UNDO'),
    }
    assert {(item.ctrl, item.propvalue) for item in redo_items} == {
        (False, 'REDO'),
        (True, 'REDO'),
    }
    object_xray_items = [
        item for item in knife_modal_keymap.keymap_items
        if item.type == 'TWO' and item.value == 'PRESS' and item.ctrl
        and not item.shift and not item.alt and not item.oskey
    ]
    view_xray_items = [
        item for item in knife_modal_keymap.keymap_items
        if item.type == 'THREE' and item.value == 'PRESS' and item.ctrl
        and not item.shift and not item.alt and not item.oskey
    ]
    assert [item.propvalue for item in object_xray_items] == ['OBJECT_XRAY_TOGGLE']
    assert [item.propvalue for item in view_xray_items] == ['VIEW_XRAY_TOGGLE']
    subdivision_items = [
        item for item in knife_modal_keymap.keymap_items
        if item.type in {'ONE', 'TWO', 'THREE'} and item.value == 'PRESS'
        and not item.ctrl and not item.shift and not item.alt and not item.oskey
    ]
    assert {(item.type, item.propvalue) for item in subdivision_items} == {
        ('ONE', 'SUBDIVISION_PREVIEW_OFF'),
        ('TWO', 'SUBDIVISION_PREVIEW_ON'),
        ('THREE', 'SUBDIVISION_PREVIEW_SURFACE'),
    }
    assert os.path.basename(os.path.normpath(bpy.utils.user_resource('CONFIG'))) == (
        "clarity_fork_config"
    )

    for object in bpy.data.objects:
        assert object.transform_model == 'BLENDER'
        assert object.custom_pivot is None

    assert all(abs(value) < 1.0e-6 for value in bpy.context.scene.cursor.location)
    assert bpy.context.scene.tool_settings.statvis.overhang_axis == 'NEG_Y'

    camera = bpy.data.objects.get("Camera")
    assert camera is not None
    assert camera.track_axis == 'NEG_Z'
    assert camera.up_axis == 'Y'
    camera_rotation = camera.matrix_world.to_quaternion()
    camera_forward = camera_rotation @ Vector((0.0, 0.0, -1.0))
    direction_to_origin = -camera.matrix_world.translation
    direction_to_origin.normalize()
    assert camera_forward.dot(direction_to_origin) > 0.999
    camera_up = camera_rotation @ Vector((0.0, 1.0, 0.0))
    assert camera_up.dot(Vector((0.0, 1.0, 0.0))) > 0.5

    bpy.ops.mesh.primitive_plane_add(align='WORLD')
    plane = bpy.context.object
    assert all(abs(value) < 1.0e-6 for value in plane.location)
    assert all(abs(angle) < 1.0e-6 for angle in plane.rotation_euler)
    assert all(abs(vertex.co.y) < 1.0e-6 for vertex in plane.data.vertices)
    assert plane.track_axis == 'POS_Z'
    assert plane.up_axis == 'Y'

    floor_constraint = plane.constraints.new(type='FLOOR')
    assert floor_constraint.floor_location == 'FLOOR_Y'

    follow_path_constraint = plane.constraints.new(type='FOLLOW_PATH')
    assert follow_path_constraint.forward_axis == 'FORWARD_Z'
    assert follow_path_constraint.up_axis == 'UP_Y'

    locked_track_constraint = plane.constraints.new(type='LOCKED_TRACK')
    assert locked_track_constraint.track_axis == 'TRACK_Z'
    assert locked_track_constraint.lock_axis == 'LOCK_Y'

    damped_track_constraint = plane.constraints.new(type='DAMPED_TRACK')
    assert damped_track_constraint.track_axis == 'TRACK_Z'

    shrinkwrap_constraint = plane.constraints.new(type='SHRINKWRAP')
    assert shrinkwrap_constraint.project_axis == 'POS_Y'

    screw_modifier = plane.modifiers.new(name="Y-Up Screw", type='SCREW')
    assert screw_modifier.axis == 'Y'
    plane.modifiers.remove(screw_modifier)

    mesh_cache_modifier = plane.modifiers.new(name="Y-Up Mesh Cache", type='MESH_CACHE')
    assert mesh_cache_modifier.forward_axis == 'POS_Z'
    assert mesh_cache_modifier.up_axis == 'POS_Y'
    plane.modifiers.remove(mesh_cache_modifier)

    wave_modifier = plane.modifiers.new(name="Y-Up Wave", type='WAVE')
    wave_modifier.use_cyclic = False
    wave_modifier.speed = 0.0
    wave_modifier.height = 1.0
    wave_modifier.width = 10.0
    wave_modifier.narrowness = 1.0
    bpy.context.view_layer.update()
    evaluated_plane = plane.evaluated_get(bpy.context.evaluated_depsgraph_get())
    evaluated_wave_mesh = evaluated_plane.to_mesh()
    try:
        for source, evaluated in zip(plane.data.vertices, evaluated_wave_mesh.vertices):
            assert abs(evaluated.co.x - source.co.x) < 1.0e-6
            assert abs(evaluated.co.z - source.co.z) < 1.0e-6
            assert evaluated.co.y > 0.0
    finally:
        evaluated_plane.to_mesh_clear()
    plane.modifiers.remove(wave_modifier)

    shader_tree = bpy.data.node_groups.new("Y-Up Shader Defaults", 'ShaderNodeTree')
    vector_rotate = shader_tree.nodes.new("ShaderNodeVectorRotate")
    assert tuple(vector_rotate.inputs["Axis"].default_value) == (0.0, 1.0, 0.0)
    shader_normal = shader_tree.nodes.new("ShaderNodeNormal")
    assert tuple(shader_normal.inputs["Normal"].default_value) == (0.0, 1.0, 0.0)
    assert tuple(shader_normal.outputs["Normal"].default_value) == (0.0, 1.0, 0.0)
    bpy.data.node_groups.remove(shader_tree)

    function_tree = bpy.data.node_groups.new("Y-Up Function Defaults", 'GeometryNodeTree')
    axes_to_rotation = function_tree.nodes.new("FunctionNodeAxesToRotation")
    assert tuple(axes_to_rotation.inputs["Primary Axis"].default_value) == (0.0, 1.0, 0.0)
    assert axes_to_rotation.primary_axis == 'Y'
    assert axes_to_rotation.secondary_axis == 'X'
    axis_angle = function_tree.nodes.new("FunctionNodeAxisAngleToRotation")
    assert tuple(axis_angle.inputs["Axis"].default_value) == (0.0, 1.0, 0.0)
    align_rotation = function_tree.nodes.new("FunctionNodeAlignRotationToVector")
    assert tuple(align_rotation.inputs["Vector"].default_value) == (0.0, 1.0, 0.0)
    assert align_rotation.axis == 'Y'
    align_euler = function_tree.nodes.new("FunctionNodeAlignEulerToVector")
    assert tuple(align_euler.inputs["Vector"].default_value) == (0.0, 1.0, 0.0)
    rotate_euler = function_tree.nodes.new("FunctionNodeRotateEuler")
    rotate_euler.rotation_type = 'AXIS_ANGLE'
    assert tuple(rotate_euler.inputs["Axis"].default_value) == (0.0, 1.0, 0.0)
    bpy.data.node_groups.remove(function_tree)

    compositor_tree = bpy.data.node_groups.new("Y-Up Compositor Defaults", 'CompositorNodeTree')
    compositor_normal = compositor_tree.nodes.new("CompositorNodeNormal")
    assert tuple(compositor_normal.outputs["Normal"].default_value) == (0.0, 1.0, 0.0)
    bpy.data.node_groups.remove(compositor_tree)

    curve_defaults_tree = bpy.data.node_groups.new("Y-Up Curve Defaults", 'GeometryNodeTree')
    bezier_segment = curve_defaults_tree.nodes.new("GeometryNodeCurvePrimitiveBezierSegment")
    assert tuple(bezier_segment.inputs["Start Handle"].default_value) == (-0.5, 0.0, -0.5)
    quadratic_bezier = curve_defaults_tree.nodes.new("GeometryNodeCurveQuadraticBezier")
    assert tuple(quadratic_bezier.inputs["Middle"].default_value) == (0.0, 0.0, -2.0)
    bpy.data.node_groups.remove(curve_defaults_tree)

    # Canonical Geometry Nodes primitives share the same Y-up basis as editor-created geometry.
    def configure_grid(node):
        assert "Size Z" in node.inputs and "Vertices Z" in node.inputs
        assert "Size Y" not in node.inputs and "Vertices Y" not in node.inputs

    grid_positions, grid_normals = evaluated_geometry_node_mesh(
        "GeometryNodeMeshGrid", configure_grid
    )
    assert grid_positions
    assert all(abs(position.y) < 1.0e-6 for position in grid_positions)
    assert max(abs(position.z) for position in grid_positions) > 0.0
    assert grid_normals and all(normal.y > 0.999 for normal in grid_normals)

    def configure_cylinder(node):
        node.inputs["Radius"].default_value = 1.0
        node.inputs["Depth"].default_value = 2.0

    cylinder_positions, _ = evaluated_geometry_node_mesh(
        "GeometryNodeMeshCylinder", configure_cylinder
    )
    assert abs(min(position.y for position in cylinder_positions) + 1.0) < 1.0e-5
    assert abs(max(position.y for position in cylinder_positions) - 1.0) < 1.0e-5
    assert max(abs(position.z) for position in cylinder_positions) > 0.9

    def configure_cone(node):
        node.inputs["Depth"].default_value = 2.0

    cone_positions, _ = evaluated_geometry_node_mesh("GeometryNodeMeshCone", configure_cone)
    assert abs(min(position.y for position in cone_positions)) < 1.0e-5
    assert abs(max(position.y for position in cone_positions) - 2.0) < 1.0e-5

    fill_positions, fill_normals = evaluated_curve_fill_mesh()
    assert fill_positions and fill_normals
    assert all(abs(position.y) < 1.0e-6 for position in fill_positions)
    assert max(abs(position.z) for position in fill_positions) > 0.9
    assert all(normal.y > 0.999 for normal in fill_normals)

    # Built-in Maya-style shelf primitives create at world zero, independently of Blender's cursor.
    bpy.context.scene.cursor.location = (7.0, 8.0, 9.0)
    assert bpy.ops.topbar.clarity_shelf_action(action='cube') == {'FINISHED'}
    shelf_cube = bpy.context.object
    assert shelf_cube is not None and shelf_cube.type == 'MESH'
    assert all(abs(value) < 1.0e-6 for value in shelf_cube.location)
    assert all(abs(angle) < 1.0e-6 for angle in shelf_cube.rotation_euler)

    assert bpy.ops.topbar.clarity_shelf_action(action='bezier_circle') == {'FINISHED'}
    shelf_circle = bpy.context.object
    assert shelf_circle is not None and shelf_circle.type == 'CURVE'
    assert all(abs(value) < 1.0e-6 for value in shelf_circle.location)
    assert all(abs(angle) < 1.0e-6 for angle in shelf_circle.rotation_euler)
    assert shelf_circle.data.dimensions == '3D'
    circle_points = shelf_circle.data.splines[0].bezier_points
    assert all(abs(point.co.y) < 1.0e-6 for point in circle_points)
    assert max(abs(point.co.z) for point in circle_points) > 0.9

    assert bpy.ops.topbar.clarity_shelf_action(action='armature') == {'FINISHED'}
    shelf_armature = bpy.context.object
    assert shelf_armature is not None and shelf_armature.type == 'ARMATURE'
    assert all(abs(value) < 1.0e-6 for value in shelf_armature.location)
    shelf_bone = shelf_armature.data.bones[0]
    assert all(abs(value) < 1.0e-6 for value in shelf_bone.head)
    assert abs(shelf_bone.tail.x) < 1.0e-6
    assert shelf_bone.tail.y > 0.0
    assert abs(shelf_bone.tail.z) < 1.0e-6

    bpy.context.scene.cursor.location = (0.0, 0.0, 0.0)
    bpy.context.view_layer.objects.active = shelf_armature
    shelf_armature.select_set(True)
    assert bpy.ops.object.mode_set(mode='EDIT') == {'FINISHED'}
    assert bpy.ops.armature.bone_primitive_add(
        align='UP', space='OBJECT', length=2.0
    ) == {'FINISHED'}
    added_bone = shelf_armature.data.edit_bones.active
    added_direction = added_bone.tail - added_bone.head
    assert abs(added_direction.x) < 1.0e-6
    assert added_direction.y > 1.999
    assert abs(added_direction.z) < 1.0e-6

    # Bone side naming follows the native Maya-style world semantics too.
    # The add operator intentionally selects only the tip for immediate extension; auto-name
    # operates on fully selected edit bones, so make that precondition explicit here.
    added_bone.select = True
    added_bone.select_head = True
    added_bone.select_tail = True
    added_bone.name = "AxisBone"
    added_bone.head = (0.0, 1.0, 0.0)
    added_bone.tail = (0.0, 2.0, 0.0)
    assert bpy.ops.armature.autoside_names(type='YAXIS') == {'FINISHED'}
    assert added_bone.name.endswith(".Top")

    added_bone.name = "AxisBone"
    added_bone.head = (0.0, 0.0, 1.0)
    added_bone.tail = (0.0, 0.0, 2.0)
    assert bpy.ops.armature.autoside_names(type='ZAXIS') == {'FINISHED'}
    assert added_bone.name.endswith(".Fr")
    assert bpy.ops.object.mode_set(mode='OBJECT') == {'FINISHED'}


if __name__ == "__main__":
    main()
