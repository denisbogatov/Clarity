# SPDX-FileCopyrightText: 2009-2023 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

import bpy
import copy
import json
import os
import uuid
from bpy.props import (
    CollectionProperty,
    EnumProperty,
    FloatVectorProperty,
    IntProperty,
    StringProperty,
)
from bpy.types import Header, Menu, Operator, Panel, PropertyGroup, UIList

from bpy.app.translations import (
    pgettext_iface as iface_,
    contexts as i18n_contexts,
)


class TOPBAR_HT_upper_bar(Header):
    bl_space_type = 'TOPBAR'

    def draw(self, context):
        region = context.region

        if region.alignment == 'RIGHT':
            self.draw_right(context)
        else:
            self.draw_left(context)

    def draw_left(self, context):
        layout = self.layout

        window = context.window
        screen = context.screen

        TOPBAR_MT_editor_menus.draw_collapsible(context, layout)

        layout.separator(type='LINE')

        if not screen.show_fullscreen:
            layout.template_ID_tabs(window, "workspace", new="workspace.add", menu="TOPBAR_MT_workspace_menu")
        else:
            layout.operator("screen.back_to_previous", icon='SCREEN_BACK', text="Back to Previous")

    def draw_right(self, context):
        layout = self.layout

        window = context.window
        screen = context.screen
        scene = window.scene

        # If statusbar is hidden, still show messages at the top
        if not screen.show_statusbar:
            layout.template_reports_banner()
            layout.template_running_jobs()

        # Active workspace view-layer is retrieved through window, not through workspace.
        layout.template_ID(window, "scene", new="scene.new", unlink="scene.delete")

        row = layout.row(align=True)
        row.template_search(
            window, "view_layer",
            scene, "view_layers",
            new="scene.view_layer_add",
            unlink="scene.view_layer_remove",
        )


_MAYA_SHELF_TABS = (
    "Modeling",
    "Custom",
)

_MAYA_SHELF_LEGACY_TABS = {
    "Poly Modeling",
    "Modeling",
    "Curves",
    "Surfaces",
    "Sculpting",
    "Rigging",
    "Animation",
    "Rendering",
    "FX",
    "Motion Graphics",
    "XGen",
    "Arnold",
    "Custom",
}

_MAYA_SHELF_ITEMS = {
    "Modeling": (
        ("select_box", "Box Select", 'RESTRICT_SELECT_OFF'),
        ("move", "Move", 'ORIENTATION_GLOBAL'),
        ("rotate", "Rotate", 'DRIVER_ROTATIONAL_DIFFERENCE'),
        ("scale", "Scale", 'FULLSCREEN_ENTER'),
        None,
        ("plane", "Add Plane", 'MESH_PLANE'),
        ("cube", "Add Cube", 'MESH_CUBE'),
        ("sphere", "Add UV Sphere", 'MESH_UVSPHERE'),
        ("cylinder", "Add Cylinder", 'MESH_CYLINDER'),
        ("cone", "Add Cone", 'MESH_CONE'),
        ("torus", "Add Torus", 'MESH_TORUS'),
        None,
        ("edit_mode", "Toggle Edit Mode", 'EDITMODE_HLT'),
        ("extrude", "Extrude", 'MOD_SOLIDIFY'),
        ("inset", "Inset Faces", 'FACESEL'),
        ("bevel", "Bevel", 'MOD_BEVEL'),
        ("loop_cut", "Loop Cut", 'MOD_MULTIRES'),
        None,
        ("mirror", "Mirror Modifier", 'MOD_MIRROR'),
        ("array", "Array Modifier", 'MOD_ARRAY'),
        ("subsurf", "Subdivision Surface", 'MOD_SUBSURF'),
    ),
    "Curves": (
        ("bezier", "Add Bezier Curve", 'CURVE_BEZCURVE'),
        ("bezier_circle", "Add Bezier Circle", 'CURVE_BEZCIRCLE'),
        ("nurbs", "Add NURBS Curve", 'CURVE_NCURVE'),
        ("nurbs_circle", "Add NURBS Circle", 'CURVE_NCIRCLE'),
        ("path", "Add Path", 'CURVE_PATH'),
        None,
        ("move", "Move", 'ORIENTATION_GLOBAL'),
        ("rotate", "Rotate", 'DRIVER_ROTATIONAL_DIFFERENCE'),
        ("scale", "Scale", 'FULLSCREEN_ENTER'),
        ("edit_mode", "Toggle Edit Mode", 'EDITMODE_HLT'),
        ("extrude", "Extrude", 'MOD_SOLIDIFY'),
        ("bevel", "Bevel", 'MOD_BEVEL'),
    ),
    "Sculpting": (
        ("sculpt_mode", "Sculpt Mode", 'SCULPTMODE_HLT'),
        ("sculpt_draw", "Draw Brush", 'BRUSH_DATA'),
        ("sculpt_smooth", "Smooth Brush", 'SMOOTHCURVE'),
        ("sculpt_grab", "Grab Brush", 'HAND'),
        None,
        ("subsurf", "Subdivision Surface", 'MOD_SUBSURF'),
        ("multires", "Multiresolution Modifier", 'MOD_MULTIRES'),
    ),
    "Rigging": (
        ("armature", "Add Armature", 'ARMATURE_DATA'),
        ("edit_mode", "Toggle Edit Mode", 'EDITMODE_HLT'),
        ("pose_mode", "Pose Mode", 'POSE_HLT'),
        None,
        ("parent", "Parent", 'CONSTRAINT_BONE'),
        ("clear_parent", "Clear Parent", 'UNLINKED'),
        ("constraint", "Add Copy Transforms Constraint", 'CONSTRAINT'),
    ),
    "Animation": (
        ("keyframe", "Insert LocRotScale Keyframe", 'KEY_HLT'),
        ("delete_keyframe", "Delete Keyframe", 'KEY_DEHLT'),
        None,
        ("first_frame", "Jump to First Frame", 'REW'),
        ("play", "Play Animation", 'PLAY'),
        ("last_frame", "Jump to Last Frame", 'FF'),
        None,
        ("graph_editor", "Graph Editor", 'GRAPH'),
        ("dope_sheet", "Dope Sheet", 'ACTION'),
        ("nla_editor", "NLA Editor", 'NLA'),
    ),
    "Rendering": (
        ("camera", "Add Camera", 'CAMERA_DATA'),
        ("point_light", "Add Point Light", 'LIGHT'),
        ("area_light", "Add Area Light", 'LIGHT_AREA'),
        ("sun_light", "Add Sun", 'LIGHT_SUN'),
        None,
        ("material", "New Material", 'MATERIAL'),
        ("render", "Render Image", 'RENDER_STILL'),
        ("render_animation", "Render Animation", 'RENDER_ANIMATION'),
    ),
    "FX": (
        ("quick_smoke", "Quick Smoke", 'MOD_FLUIDSIM'),
        ("quick_fur", "Quick Fur", 'PARTICLES'),
        ("explode", "Explode Modifier", 'MOD_EXPLODE'),
        None,
        ("wind", "Add Wind Force", 'FORCE_WIND'),
        ("turbulence", "Add Turbulence Force", 'FORCE_TURBULENCE'),
    ),
    "Custom": (
        ("save", "Save File", 'FILE_TICK'),
        ("preferences", "Preferences", 'PREFERENCES'),
        None,
        ("cube", "Add Cube", 'MESH_CUBE'),
        ("material", "New Material", 'MATERIAL'),
        ("render", "Render Image", 'RENDER_STILL'),
    ),
}

_MAYA_SHELF_ITEMS["Surfaces"] = _MAYA_SHELF_ITEMS["Curves"]
_MAYA_SHELF_ITEMS["Motion Graphics"] = _MAYA_SHELF_ITEMS["Animation"]
_MAYA_SHELF_ITEMS["XGen"] = _MAYA_SHELF_ITEMS["FX"]
_MAYA_SHELF_ITEMS["Arnold"] = _MAYA_SHELF_ITEMS["Rendering"]

_MAYA_SHELF_EXTRA_ACTIONS = (
    ("select_all", "Selection: Select All", 'RESTRICT_SELECT_OFF'),
    ("select_none", "Selection: Deselect All", 'SELECT_SUBTRACT'),
    ("select_inverse", "Selection: Invert", 'ARROW_LEFTRIGHT'),
    ("delete_object", "Object: Delete", 'TRASH'),
    ("duplicate", "Object: Duplicate", 'DUPLICATE'),
    ("duplicate_linked", "Object: Duplicate Linked", 'LINKED'),
    ("join_objects", "Object: Join", 'AUTOMERGE_ON'),
    ("separate_selection", "Object: Separate Selection", 'UNLINKED'),
    ("apply_transforms", "Object: Apply All Transforms", 'CHECKMARK'),
    ("origin_geometry", "Object: Origin to Geometry", 'OBJECT_ORIGIN'),
    ("shade_smooth", "Object: Shade Smooth", 'MOD_SMOOTH'),
    ("shade_flat", "Object: Shade Flat", 'MESH_CUBE'),
    ("hide_selected", "Object: Hide Selected", 'HIDE_ON'),
    ("unhide_all", "Object: Unhide All", 'HIDE_OFF'),
    ("empty", "Object: Add Empty", 'EMPTY_AXIS'),
    ("clear_location", "Object: Clear Location", 'OBJECT_ORIGIN'),
    ("clear_rotation", "Object: Clear Rotation", 'DRIVER_ROTATIONAL_DIFFERENCE'),
    ("clear_scale", "Object: Clear Scale", 'FULLSCREEN_ENTER'),
    ("origin_cursor", "Object: Origin to 3D Cursor", 'PIVOT_CURSOR'),
    ("apply_active_modifier", "Object: Apply Active Modifier", 'CHECKMARK'),
    ("frame_selected", "View: Frame Selected", 'VIEWZOOM'),
    ("frame_all", "View: Frame All", 'HOME'),
    ("camera_view", "View: Camera View", 'CAMERA_DATA'),
    ("camera_to_view", "View: Align Camera to View", 'CAMERA_DATA'),
    ("perspective_toggle", "View: Perspective / Orthographic", 'VIEW_PERSPECTIVE'),
    ("isolate_selected", "View: Toggle Local View", 'HIDE_OFF'),
    ("toggle_overlays", "View: Toggle Overlays", 'OVERLAY'),
    ("view_wireframe", "View: Wireframe", 'SHADING_WIRE'),
    ("view_solid", "View: Solid", 'SHADING_SOLID'),
    ("view_material", "View: Material Preview", 'SHADING_TEXTURE'),
    ("view_rendered", "View: Rendered", 'SHADING_RENDERED'),
    ("xray_toggle", "View: Toggle X-Ray", 'XRAY'),
    ("merge_by_distance", "Mesh: Merge by Distance", 'AUTOMERGE_ON'),
    ("recalc_normals", "Mesh: Recalculate Normals", 'NORMALS_FACE'),
    ("bridge_loops", "Mesh: Bridge Edge Loops", 'MOD_EDGESPLIT'),
    ("subdivide_mesh", "Mesh: Subdivide", 'MOD_SUBSURF'),
    ("triangulate", "Mesh: Triangulate Faces", 'MOD_TRIANGULATE'),
    ("tris_to_quads", "Mesh: Tris to Quads", 'MESH_GRID'),
    ("fill_faces", "Mesh: Fill", 'FACESEL'),
    ("delete_loose", "Mesh: Delete Loose", 'TRASH'),
    ("flip_normals", "Mesh: Flip Normals", 'NORMALS_FACE'),
    ("select_more", "Mesh: Select More", 'ADD'),
    ("select_less", "Mesh: Select Less", 'REMOVE'),
    ("mark_seam", "Mesh: Mark Seam", 'UV_EDGESEL'),
    ("clear_seam", "Mesh: Clear Seam", 'X'),
    ("unwrap", "UV: Unwrap", 'UV'),
    ("smart_uv", "UV: Smart UV Project", 'MOD_UVPROJECT'),
    ("average_islands", "UV: Average Island Scale", 'UV'),
    ("pack_islands", "UV: Pack Islands", 'UV'),
    ("reset_uv", "UV: Reset", 'LOOP_BACK'),
    ("cursor_to_selected", "Snap: Cursor to Selected", 'PIVOT_CURSOR'),
    ("cursor_to_origin", "Snap: Cursor to World Origin", 'PIVOT_CURSOR'),
    ("selected_to_cursor", "Snap: Selection to Cursor", 'PIVOT_CURSOR'),
    ("selected_to_grid", "Snap: Selection to Grid", 'SNAP_GRID'),
    ("solidify_modifier", "Modifier: Solidify", 'MOD_SOLIDIFY'),
    ("bevel_modifier", "Modifier: Bevel", 'MOD_BEVEL'),
    ("boolean_modifier", "Modifier: Boolean", 'MOD_BOOLEAN'),
    ("weld_modifier", "Modifier: Weld", 'AUTOMERGE_ON'),
    ("decimate_modifier", "Modifier: Decimate", 'MOD_DECIM'),
    ("auto_key_toggle", "Animation: Toggle Auto Key", 'REC'),
    ("knife", "Mesh: Knife", 'MOD_BOOLEAN'),
    ("bisect", "Mesh: Bisect", 'MOD_BOOLEAN'),
    ("rip", "Mesh: Rip", 'UNLINKED'),
    ("rip_fill", "Mesh: Rip Fill", 'UNLINKED'),
    ("spin", "Mesh: Spin", 'FORCE_VORTEX'),
    ("screw_mesh", "Mesh: Screw", 'MOD_SCREW'),
    ("shrink_fatten", "Mesh: Shrink / Fatten", 'FULLSCREEN_ENTER'),
    ("extrude_normals", "Mesh: Extrude Along Normals", 'MOD_SOLIDIFY'),
    ("extrude_individual", "Mesh: Extrude Individual Faces", 'FACESEL'),
    ("grid_fill", "Mesh: Grid Fill", 'MESH_GRID'),
    ("fill_holes", "Mesh: Fill Holes", 'FACESEL'),
    ("dissolve_vertices", "Mesh: Dissolve Vertices", 'VERTEXSEL'),
    ("dissolve_edges", "Mesh: Dissolve Edges", 'EDGESEL'),
    ("dissolve_faces", "Mesh: Dissolve Faces", 'FACESEL'),
    ("edge_slide", "Mesh: Edge Slide", 'EDGESEL'),
    ("vertex_slide", "Mesh: Vertex Slide", 'VERTEXSEL'),
    ("loop_select", "Mesh: Select Loop", 'MOD_MULTIRES'),
    ("select_linked", "Mesh: Select Linked", 'LINKED'),
    ("select_non_manifold", "Mesh: Select Non-Manifold", 'ERROR'),
    ("convert_mesh", "Object: Convert to Mesh", 'MESH_DATA'),
    ("apply_visual_transform", "Object: Apply Visual Transform", 'CHECKMARK'),
    ("apply_selected_modifiers", "Object: Apply Modifiers on Selected", 'CHECKMARK'),
    ("apply_all_modifiers", "Object: Apply All Modifiers", 'CHECKMARK'),
    ("link_to_collection", "Object: Add to Collection", 'OUTLINER_COLLECTION'),
    ("move_to_collection", "Object: Move to Collection", 'OUTLINER_COLLECTION'),
    ("link_object_data", "Object: Link Object Data", 'LINKED'),
    ("make_single_user", "Object: Make Single User", 'UNLINKED'),
    ("parent_bone", "Object: Parent to Bone", 'CONSTRAINT_BONE'),
    ("clear_constraints", "Object: Clear Constraints", 'X'),
    ("rename_object", "Object: Rename Active Object", 'GREASEPENCIL'),
    ("weighted_normal_modifier", "Modifier: Weighted Normal", 'NORMALS_FACE'),
    ("geometry_nodes_modifier", "Modifier: Geometry Nodes", 'GEOMETRY_NODES'),
    ("lattice_modifier", "Modifier: Lattice", 'MOD_LATTICE'),
    ("shrinkwrap_modifier", "Modifier: Shrinkwrap", 'MOD_SHRINKWRAP'),
    ("simple_deform_modifier", "Modifier: Simple Deform", 'MOD_SIMPLEDEFORM'),
    ("skin_modifier", "Modifier: Skin", 'MOD_SKIN'),
    ("remesh_modifier", "Modifier: Remesh", 'MOD_REMESH'),
    ("screw_modifier", "Modifier: Screw", 'MOD_SCREW'),
    ("copy_modifiers", "Modifier: Copy to Selected", 'DUPLICATE'),
    ("view_front", "View: Front", 'AXIS_FRONT'),
    ("view_back", "View: Back", 'AXIS_FRONT'),
    ("view_left", "View: Left", 'AXIS_SIDE'),
    ("view_right", "View: Right", 'AXIS_SIDE'),
    ("view_top", "View: Top", 'AXIS_TOP'),
    ("view_bottom", "View: Bottom", 'AXIS_TOP'),
    ("orbit_left", "View: Orbit Left 15 Degrees", 'LOOP_BACK'),
    ("orbit_right", "View: Orbit Right 15 Degrees", 'LOOP_FORWARDS'),
    ("toggle_grid", "View: Toggle Grid", 'SNAP_GRID'),
    ("toggle_wire_overlay", "View: Toggle Wire Overlay", 'SHADING_WIRE'),
    ("toggle_face_orientation", "View: Toggle Face Orientation", 'NORMALS_FACE'),
    ("toggle_statistics", "View: Toggle Statistics", 'INFO'),
    ("toggle_gizmos", "View: Toggle Gizmos", 'GIZMO'),
    ("toggle_camera_lock", "View: Toggle Camera Lock", 'LOCKED'),
    ("viewport_screenshot", "View: Screenshot Viewport", 'IMAGE_DATA'),
    ("uv_cube_project", "UV: Cube Projection", 'MESH_CUBE'),
    ("uv_cylinder_project", "UV: Cylinder Projection", 'MESH_CYLINDER'),
    ("uv_sphere_project", "UV: Sphere Projection", 'MESH_UVSPHERE'),
    ("uv_project_view", "UV: Project from View", 'VIEW_PERSPECTIVE'),
    ("uv_minimize_stretch", "UV: Minimize Stretch", 'FULLSCREEN_ENTER'),
    ("uv_stitch", "UV: Stitch", 'AUTOMERGE_ON'),
    ("uv_align", "UV: Align", 'ALIGN_JUSTIFY'),
    ("uv_pin", "UV: Pin", 'PINNED'),
    ("uv_unpin", "UV: Unpin", 'UNPINNED'),
    ("uv_select_overlap", "UV: Select Overlap", 'SELECT_INTERSECT'),
    ("keyframe_location", "Animation: Insert Location Keyframe", 'KEY_HLT'),
    ("keyframe_rotation", "Animation: Insert Rotation Keyframe", 'KEY_HLT'),
    ("keyframe_scale", "Animation: Insert Scale Keyframe", 'KEY_HLT'),
    ("clear_keyframes", "Animation: Clear Keyframes", 'KEY_DEHLT'),
    ("duplicate_keyframes", "Animation: Duplicate Keyframes", 'DUPLICATE'),
    ("interpolation_constant", "Animation: Constant Interpolation", 'IPO_CONSTANT'),
    ("interpolation_linear", "Animation: Linear Interpolation", 'IPO_LINEAR'),
    ("interpolation_bezier", "Animation: Bezier Interpolation", 'IPO_BEZIER'),
    ("previous_keyframe", "Animation: Previous Keyframe", 'PREV_KEYFRAME'),
    ("next_keyframe", "Animation: Next Keyframe", 'NEXT_KEYFRAME'),
    ("create_pose_asset", "Animation: Create Pose Asset", 'ASSET_MANAGER'),
    ("bake_action", "Animation: Bake Action", 'ACTION'),
    ("toggle_motion_paths", "Animation: Toggle Motion Paths", 'ANIM_DATA'),
    ("set_preview_range", "Animation: Set Preview Range", 'PREVIEW_RANGE'),
    ("ik_constraint", "Rigging: Add IK Constraint", 'CONSTRAINT_BONE'),
    ("child_of_constraint", "Rigging: Add Child Of Constraint", 'CONSTRAINT'),
    ("track_to_constraint", "Rigging: Add Track To Constraint", 'CONSTRAINT'),
    ("limit_rotation_constraint", "Rigging: Add Limit Rotation Constraint", 'CONSTRAINT'),
    ("parent_auto_weights", "Rigging: Parent with Automatic Weights", 'ARMATURE_DATA'),
    ("clear_pose", "Rigging: Clear Pose", 'LOOP_BACK'),
    ("pose_as_rest", "Rigging: Apply Pose as Rest Pose", 'ARMATURE_DATA'),
    ("symmetrize_bones", "Rigging: Symmetrize Bones", 'MOD_MIRROR'),
    ("subdivide_bone", "Rigging: Subdivide Bone", 'MOD_SUBSURF'),
    ("calculate_bone_roll", "Rigging: Calculate Bone Roll", 'DRIVER_ROTATIONAL_DIFFERENCE'),
    ("voxel_remesh", "Sculpt: Voxel Remesh", 'MOD_REMESH'),
    ("mask_all", "Sculpt: Mask All", 'MOD_MASK'),
    ("mask_clear", "Sculpt: Clear Mask", 'X'),
    ("mask_invert", "Sculpt: Invert Mask", 'ARROW_LEFTRIGHT'),
    ("hide_masked", "Sculpt: Hide Masked", 'HIDE_ON'),
    ("face_sets_visible", "Sculpt: Face Sets from Visible", 'FACESEL'),
    ("dyntopo_toggle", "Sculpt: Toggle Dyntopo", 'SCULPTMODE_HLT'),
    ("multires_subdivide", "Sculpt: Multires Subdivide", 'MOD_MULTIRES'),
    ("smooth_mesh", "Sculpt: Smooth Mesh", 'MOD_SMOOTH'),
    ("open_file", "File: Open", 'FILE_FOLDER'),
    ("save_as", "File: Save As", 'FILE_TICK'),
    ("incremental_save", "File: Incremental Save", 'FILE_TICK'),
    ("append_file", "File: Append", 'APPEND_BLEND'),
    ("link_file", "File: Link", 'LINK_BLEND'),
    ("pack_resources", "File: Pack Resources", 'PACKAGE'),
    ("render_viewport", "Render: Viewport", 'RENDER_STILL'),
    ("render_selected", "Render: Selected Objects", 'RENDER_STILL'),
    ("open_render_result", "Render: Open Render Result", 'IMAGE_DATA'),
    ("purge_orphans", "File: Purge Orphan Data", 'TRASH'),
)

_MAYA_SHELF_DISCOVERED_OPERATOR_MODULES = (
    "mesh",
    "uv",
    "object",
    "transform",
    "view3d",
    "curve",
    "curves",
    "sculpt",
    "paint",
    "armature",
    "pose",
)


def _maya_shelf_operator_icon(module_name, operator_name):
    name = operator_name.lower()
    icon_rules = (
        (("delete", "remove", "dissolve"), 'TRASH'),
        (("select",), 'RESTRICT_SELECT_OFF'),
        (("extrude", "solidify"), 'MOD_SOLIDIFY'),
        (("bevel",), 'MOD_BEVEL'),
        (("subdiv",), 'MOD_SUBSURF'),
        (("mirror", "symmetr"), 'MOD_MIRROR'),
        (("unwrap", "project", "uv"), 'UV'),
        (("rotate", "spin"), 'DRIVER_ROTATIONAL_DIFFERENCE'),
        (("scale", "shrink", "fatten"), 'FULLSCREEN_ENTER'),
        (("move", "translate", "slide"), 'ORIENTATION_GLOBAL'),
        (("duplicate",), 'DUPLICATE'),
        (("join", "merge", "weld"), 'AUTOMERGE_ON'),
        (("hide",), 'HIDE_ON'),
        (("reveal", "show"), 'HIDE_OFF'),
        (("normal",), 'NORMALS_FACE'),
        (("parent",), 'CONSTRAINT_BONE'),
        (("constraint",), 'CONSTRAINT'),
        (("camera",), 'CAMERA_DATA'),
        (("render",), 'RENDER_STILL'),
        (("smooth",), 'MOD_SMOOTH'),
    )
    for keywords, icon in icon_rules:
        if any(keyword in name for keyword in keywords):
            return icon
    return {
        "mesh": 'MESH_DATA',
        "uv": 'UV',
        "object": 'OBJECT_DATA',
        "transform": 'ORIENTATION_GLOBAL',
        "view3d": 'VIEW3D',
        "curve": 'CURVE_DATA',
        "curves": 'CURVES_DATA',
        "sculpt": 'SCULPTMODE_HLT',
        "paint": 'BRUSH_DATA',
        "armature": 'ARMATURE_DATA',
        "pose": 'POSE_HLT',
    }.get(module_name, 'NONE')


def _maya_shelf_discovered_action_items():
    items = []
    for module_name in _MAYA_SHELF_DISCOVERED_OPERATOR_MODULES:
        module = getattr(bpy.ops, module_name)
        for operator_name in dir(module):
            if operator_name.startswith("_"):
                continue
            operator = getattr(module, operator_name)
            try:
                rna_type = operator.get_rna_type()
            except (AttributeError, RuntimeError):
                continue
            action = f"operator__{module_name}__{operator_name}"
            category = module_name.replace("_", " ").title()
            label = f"{category} (All): {rna_type.name}"
            icon = _maya_shelf_operator_icon(module_name, operator_name)
            items.append((action, label, icon))
    return tuple(items)


_MAYA_SHELF_DISCOVERED_ACTIONS = _maya_shelf_discovered_action_items()


def _maya_shelf_builtin_action_items():
    items = []
    seen = set()
    action_groups = list(_MAYA_SHELF_ITEMS.values()) + [
        _MAYA_SHELF_EXTRA_ACTIONS,
        _MAYA_SHELF_DISCOVERED_ACTIONS,
    ]
    for shelf_items in action_groups:
        for shelf_item in shelf_items:
            if shelf_item is None:
                continue
            action, label, icon = shelf_item
            if action in seen:
                continue
            seen.add(action)
            items.append((action, label, f"Run {label}", icon, len(items)))
    return tuple(items)


_MAYA_SHELF_BUILTIN_ACTIONS = _maya_shelf_builtin_action_items()
_MAYA_SHELF_BUILTIN_ACTION_LABELS = {
    action: label
    for action, label, _description, _icon, _index in _MAYA_SHELF_BUILTIN_ACTIONS
}
_MAYA_SHELF_BUILTIN_ACTION_ICONS = {
    action: icon
    for action, _label, _description, icon, _index in _MAYA_SHELF_BUILTIN_ACTIONS
}


def _maya_shelf_blender_icon_items():
    enum_items = bpy.types.UILayout.bl_rna.functions["operator"].parameters["icon"].enum_items
    return tuple(
        (
            enum_item.identifier,
            enum_item.name or enum_item.identifier,
            enum_item.description,
            enum_item.value,
            index,
        )
        for index, enum_item in enumerate(enum_items)
    )


_MAYA_SHELF_BLENDER_ICONS = _maya_shelf_blender_icon_items()
_MAYA_SHELF_BLENDER_ICON_VALUES = {
    identifier: icon_value
    for identifier, _name, _description, icon_value, _index in _MAYA_SHELF_BLENDER_ICONS
}

_MAYA_SHELF_COMMAND_TYPES = (
    ('BUILTIN', "Built-in Action", "Choose a ready-to-use shelf action"),
    ('OPERATOR', "Blender Operator", "Run a Blender operator"),
    ('PYTHON', "Python Script", "Run custom Python code"),
)

_MAYA_SHELF_SCRIPT_SOURCES = (
    ('INLINE', "Inline Code", "Run code stored in this shelf button"),
    ('TEXT', "Text Block", "Run a Blender Text Editor text block"),
    ('FILE', "Python File", "Run an external Python file"),
)

_MAYA_SHELF_ACTION_CATEGORIES = (
    ('ALL', "All Categories", "Show actions from every category"),
    ('MESH', "Mesh", "Mesh modeling actions"),
    ('UV', "UV", "UV editing actions"),
    ('OBJECT', "Object", "Object actions"),
    ('TRANSFORM', "Transform", "Transform actions"),
    ('VIEW', "View", "Viewport actions"),
    ('CURVE', "Curve", "Curve and Curves actions"),
    ('SCULPT', "Sculpt", "Sculpting actions"),
    ('PAINT', "Paint", "Painting actions"),
    ('RIGGING', "Rigging", "Armature and pose actions"),
    ('ANIMATION', "Animation", "Animation actions"),
    ('MODIFIER', "Modifier", "Modifier actions"),
    ('SELECTION', "Selection", "Selection actions"),
    ('SNAP', "Snap", "Snapping actions"),
    ('FILE', "File", "File actions"),
    ('RENDER', "Render", "Rendering actions"),
    ('FX', "FX", "Simulation and effects actions"),
    ('OTHER', "Other", "Uncategorized actions"),
)

_MAYA_SHELF_ACTION_SORT_MODES = (
    ('CATEGORY', "Category", "Group actions by category, then sort by name"),
    ('NAME', "Name", "Sort all visible actions by name"),
    ('ORIGINAL', "Original", "Keep the catalog order"),
)

_MAYA_SHELF_ACTION_CATEGORY_ORDER = {
    identifier: index
    for index, (identifier, _name, _description) in enumerate(
        _MAYA_SHELF_ACTION_CATEGORIES
    )
}


def _maya_shelf_action_category(action, label):
    category_map = {
        "mesh": 'MESH',
        "uv": 'UV',
        "object": 'OBJECT',
        "transform": 'TRANSFORM',
        "view3d": 'VIEW',
        "view": 'VIEW',
        "curve": 'CURVE',
        "curves": 'CURVE',
        "sculpt": 'SCULPT',
        "paint": 'PAINT',
        "armature": 'RIGGING',
        "pose": 'RIGGING',
        "rigging": 'RIGGING',
        "animation": 'ANIMATION',
        "modifier": 'MODIFIER',
        "selection": 'SELECTION',
        "snap": 'SNAP',
        "file": 'FILE',
        "render": 'RENDER',
        "fx": 'FX',
    }
    if action.startswith("operator__"):
        _prefix, module_name, _operator_name = action.split("__", 2)
        return category_map.get(module_name, 'OTHER')
    if ":" in label:
        prefix = label.split(":", 1)[0].replace(" (All)", "").lower()
        if prefix in category_map:
            return category_map[prefix]
    for tab_name, shelf_items in _MAYA_SHELF_ITEMS.items():
        if any(item is not None and item[0] == action for item in shelf_items):
            return {
                "Modeling": 'MESH',
                "Curves": 'CURVE',
                "Surfaces": 'CURVE',
                "Sculpting": 'SCULPT',
                "Rigging": 'RIGGING',
                "Animation": 'ANIMATION',
                "Rendering": 'RENDER',
                "FX": 'FX',
                "Motion Graphics": 'ANIMATION',
                "XGen": 'FX',
                "Arnold": 'RENDER',
                "Custom": 'OTHER',
            }.get(tab_name, 'OTHER')
    return 'OTHER'


_maya_shelf_config_cache = None
_maya_shelf_active_scope = "TOPBAR"
_maya_shelf_save_timer_pending = False
_maya_shelf_drag_state = None
_maya_shelf_previews = None
_maya_shelf_layout_revision = 0
_maya_shelf_row_cache = {}

_MAYA_SHELF_LEFT_MARGIN = 4.0
_MAYA_SHELF_BUTTON_SIZE = 20.0
_MAYA_SHELF_SLOT_WIDTH = 35.0
_MAYA_SHELF_SEPARATOR_WIDTH = 13.2


def unregister_runtime():
    global _maya_shelf_previews
    global _maya_shelf_drag_state
    if _maya_shelf_previews is not None:
        bpy.utils.previews.remove(_maya_shelf_previews)
        _maya_shelf_previews = None
    _maya_shelf_drag_state = None
    _maya_shelf_row_cache.clear()


def _maya_shelf_item_slot_width(_item):
    return _MAYA_SHELF_SLOT_WIDTH


def _maya_shelf_preview_icon(name, filename):
    global _maya_shelf_previews
    if _maya_shelf_previews is None:
        import bpy.utils.previews

        _maya_shelf_previews = bpy.utils.previews.new()
    if name not in _maya_shelf_previews:
        filepath = os.path.join(
            os.path.dirname(__file__),
            "assets",
            filename,
        )
        preview = _maya_shelf_previews.load(name, filepath, 'IMAGE')
        # Load the tiny SVG before the first frame using it is drawn.
        _ = preview.icon_size
    return _maya_shelf_previews[name].icon_id


def _maya_shelf_marker_icon():
    return _maya_shelf_preview_icon("maya_shelf_drop_marker", "maya_shelf_drop.svg")


def _maya_shelf_custom_icon(filepath):
    if not filepath:
        return 0
    absolute_path = os.path.abspath(bpy.path.abspath(filepath))
    if not os.path.isfile(absolute_path):
        return 0
    preview_name = "maya_shelf_custom_" + uuid.uuid5(
        uuid.NAMESPACE_URL,
        os.path.normcase(absolute_path),
    ).hex
    try:
        return _maya_shelf_preview_icon(preview_name, absolute_path)
    except Exception:
        return 0


def _maya_shelf_script_settings(operator):
    source = operator.script_source
    settings = {
        "script_source": source,
        "script_code": "",
        "script_text": "",
        "script_file": "",
    }
    if source == 'INLINE':
        code = operator.script_code.strip()
        if not code:
            return None, "Enter Python code"
        settings["script_code"] = code
    elif source == 'TEXT':
        text_name = operator.script_text.strip()
        if not text_name or bpy.data.texts.get(text_name) is None:
            return None, "Select an existing Blender text block"
        settings["script_text"] = text_name
    else:
        filepath = os.path.abspath(bpy.path.abspath(operator.script_file.strip()))
        if not os.path.isfile(filepath):
            return None, "Python script file does not exist"
        settings["script_file"] = filepath
    return settings, ""


class TOPBAR_PG_maya_shelf_icon(PropertyGroup):
    identifier: StringProperty()


class TOPBAR_PG_maya_shelf_action(PropertyGroup):
    identifier: StringProperty()
    label: StringProperty()
    icon: StringProperty()
    category: StringProperty()


class TOPBAR_UL_maya_shelf_icons(UIList):
    def draw_item(
            self,
            _context,
            layout,
            _data,
            item,
            _icon,
            _active_data,
            _active_property,
            _index,
    ):
        layout.label(text=item.identifier, icon=item.identifier)


class TOPBAR_UL_maya_shelf_actions(UIList):
    def filter_items(self, _context, data, property_name):
        actions = getattr(data, property_name)
        flags = []
        if self.filter_name:
            flags = bpy.types.UI_UL_list.filter_items_by_name(
                self.filter_name,
                self.bitflag_filter_item,
                actions,
                "label",
                reverse=self.use_filter_invert,
            )
        if not flags:
            flags = [self.bitflag_filter_item] * len(actions)
        category = getattr(data, "action_category", 'ALL')
        if category != 'ALL':
            for index, action in enumerate(actions):
                if action.category != category:
                    flags[index] = 0

        sort_mode = getattr(data, "action_sort", 'CATEGORY')
        if sort_mode == 'CATEGORY':
            sort_data = [
                (
                    index,
                    _MAYA_SHELF_ACTION_CATEGORY_ORDER.get(
                        action.category,
                        len(_MAYA_SHELF_ACTION_CATEGORY_ORDER),
                    ),
                    action.label.casefold(),
                )
                for index, action in enumerate(actions)
            ]
            indices = bpy.types.UI_UL_list.sort_items_helper(
                sort_data,
                lambda entry: (entry[1], entry[2]),
            )
        elif sort_mode == 'NAME' or self.use_filter_sort_alpha:
            indices = bpy.types.UI_UL_list.sort_items_by_name(actions, "label")
        else:
            indices = list(range(len(actions)))
        return flags, indices

    def draw_item(
            self,
            _context,
            layout,
            _data,
            item,
            _icon,
            _active_data,
            _active_property,
            _index,
    ):
        layout.label(text=item.label, icon=item.icon)


def _maya_shelf_icon_list_fill(operator, selected_icon):
    operator.icons.clear()
    selected_index = 0
    for index, enum_item in enumerate(_MAYA_SHELF_BLENDER_ICONS):
        icon = operator.icons.add()
        icon.identifier = enum_item[0]
        if icon.identifier == selected_icon:
            selected_index = index
    operator.icon_index = selected_index


def _maya_shelf_action_list_fill(operator, selected_action):
    operator.actions.clear()
    selected_index = 0
    for index, enum_item in enumerate(_MAYA_SHELF_BUILTIN_ACTIONS):
        action = operator.actions.add()
        action.identifier = enum_item[0]
        action.label = enum_item[1]
        action.icon = enum_item[3]
        action.category = _maya_shelf_action_category(
            action.identifier,
            action.label,
        )
        if action.identifier == selected_action:
            selected_index = index
    operator.action_index = selected_index


def _maya_shelf_selected_action(operator):
    if operator.actions and 0 <= operator.action_index < len(operator.actions):
        return operator.actions[operator.action_index].identifier
    return operator.builtin_action


def _maya_shelf_action_index_update(operator, _context):
    action = _maya_shelf_selected_action(operator)
    label = _MAYA_SHELF_BUILTIN_ACTION_LABELS.get(action, "")
    if label:
        operator.label = label.split(":", 1)[-1].strip()
    icon_identifier = _MAYA_SHELF_BUILTIN_ACTION_ICONS.get(action)
    if not icon_identifier:
        return
    for index, icon in enumerate(operator.icons):
        if icon.identifier == icon_identifier:
            operator.icon_index = index
            operator.custom_icon = ""
            break


def _maya_shelf_draw_icon_preview(layout, operator):
    icon_value = _maya_shelf_custom_icon(operator.custom_icon)
    icon_identifier = ""
    if not icon_value and operator.icons and 0 <= operator.icon_index < len(operator.icons):
        icon_identifier = operator.icons[operator.icon_index].identifier
        icon_value = _MAYA_SHELF_BLENDER_ICON_VALUES.get(icon_identifier, 0)

    preview = layout.box()
    preview.label(text="Icon Preview")
    icon_row = preview.row()
    icon_row.alignment = 'CENTER'
    preview_button = icon_row.row(align=True)
    preview_button.scale_x = 3.0
    preview_button.scale_y = 3.0
    preview_button.context_string_set(
        "maya_shelf_background_color",
        ",".join(f"{component:.6f}" for component in operator.background_color),
    )
    preview_button.context_string_set(
        "maya_shelf_icon_color",
        ",".join(
            f"{component:.6f}"
            for component in (
                (1.0, 1.0, 1.0, operator.icon_color[3])
                if operator.custom_icon
                else operator.icon_color
            )
        ),
    )
    operator_args = {"text": "", "emboss": True}
    if icon_value:
        operator_args["icon_value"] = icon_value
    preview_button.operator("topbar.maya_shelf_preview", **operator_args)
    if operator.custom_icon:
        preview.label(text=os.path.basename(operator.custom_icon))
    elif icon_identifier:
        preview.label(text=icon_identifier)


def _maya_shelf_config_path():
    config_dir = bpy.utils.user_resource('CONFIG', create=True)
    return os.path.join(config_dir, "maya_shelf.json")


def _maya_shelf_default_config():
    tabs = []
    for tab_name in _MAYA_SHELF_TABS:
        source_items = [item for item in _MAYA_SHELF_ITEMS.get(tab_name, ()) if item is not None]
        split = (len(source_items) + 1) // 2
        items = []
        for index, (action, label, icon) in enumerate(source_items):
            items.append({
                "id": uuid.uuid4().hex,
                "label": label,
                "icon": icon,
                "action": action,
                "operator": "",
                "row": 0 if index < split else 1,
            })
        tabs.append({"name": tab_name, "items": items, "separators": []})
    return {"version": 3, "active": "Modeling", "tabs": tabs}


def _maya_shelf_config_clone(source):
    config = copy.deepcopy(source)
    for tab in config["tabs"]:
        for item in tab["items"]:
            item["id"] = uuid.uuid4().hex
        for separator in tab.setdefault("separators", []):
            separator["id"] = uuid.uuid4().hex
    config["selected"] = ""
    return config


def _maya_shelf_layout_scope_key(context, area=None):
    if area is None:
        area = getattr(context, "area", None)
    screen = getattr(context, "screen", None)
    workspace = getattr(context, "workspace", None)
    area_index = 0
    if screen is not None:
        area_index = next(
            (
                index
                for index, candidate in enumerate(screen.areas)
                if candidate == area
            ),
            0,
        )
    return "SHELF:{}:{}:{}".format(
        getattr(workspace, "name", "Workspace"),
        getattr(screen, "name", "Screen"),
        area_index,
    )


def _maya_shelf_uuid_scope_key(context):
    area = getattr(context, "area", None)
    if area is None or area.type != 'SHELF':
        return None
    shelf_id = getattr(getattr(context, "space_data", None), "shelf_id", "")
    return "SHELF:" + shelf_id if shelf_id else None


def _maya_shelf_scope_key(context):
    area = getattr(context, "area", None) if context is not None else None
    if area is None or area.type != 'SHELF':
        return "TOPBAR"
    return _maya_shelf_layout_scope_key(context, area)


def _maya_shelf_config(context=None):
    global _maya_shelf_active_scope
    global _maya_shelf_config_cache
    if context is not None:
        _maya_shelf_active_scope = _maya_shelf_scope_key(context)
    uuid_scope = (
        _maya_shelf_uuid_scope_key(context)
        if context is not None and getattr(context, "area", None) is not None and
        context.area.type == 'SHELF'
        else None
    )
    if _maya_shelf_config_cache is not None:
        shelves = _maya_shelf_config_cache["shelves"]
        if (
            _maya_shelf_active_scope not in shelves and
            uuid_scope in shelves
        ):
            shelves[_maya_shelf_active_scope] = shelves.pop(uuid_scope)
            _maya_shelf_save_deferred()
        if _maya_shelf_active_scope not in shelves:
            source = shelves.get("TOPBAR")
            shelves[_maya_shelf_active_scope] = (
                _maya_shelf_config_clone(source)
                if source is not None
                else _maya_shelf_default_config()
            )
            shelves[_maya_shelf_active_scope]["selected"] = ""
            _maya_shelf_save_deferred()
        return shelves[_maya_shelf_active_scope]

    save_migrated_config = False
    try:
        with open(_maya_shelf_config_path(), "r", encoding="utf-8") as handle:
            stored_config = json.load(handle)
        if "shelves" in stored_config:
            shelves = stored_config["shelves"]
            if not isinstance(shelves, dict):
                raise ValueError("Shelf storage is invalid")
            config = shelves.get("TOPBAR")
            if config is None:
                raise ValueError("Top Bar shelf is missing")
            _maya_shelf_config_cache = stored_config
        else:
            config = stored_config
            _maya_shelf_config_cache = {
                "storage_version": 1,
                "shelves": {"TOPBAR": config},
            }
            save_migrated_config = True
        if not config.get("tabs"):
            raise ValueError("Shelf has no tabs")
        if config.get("version", 1) < 2:
            modeling = next(
                (
                    tab for tab in config["tabs"]
                    if tab["name"] in {"Modeling", "Poly Modeling"}
                ),
                None,
            )
            custom = next(
                (tab for tab in config["tabs"] if tab["name"] == "Custom"),
                None,
            )
            if modeling is None:
                modeling = _maya_shelf_default_config()["tabs"][0]
            modeling["name"] = "Modeling"
            if custom is None:
                custom = {"name": "Custom", "items": [], "separators": []}
            user_tabs = [
                tab for tab in config["tabs"]
                if tab["name"] not in _MAYA_SHELF_LEGACY_TABS
            ]
            retained_tabs = [modeling, custom] + user_tabs
            for tab in retained_tabs:
                for separator in tab.setdefault("separators", []):
                    separator.setdefault("row", 0)
            config["tabs"] = retained_tabs
            config["active"] = (
                config.get("active")
                if config.get("active") in {"Modeling", "Custom"}
                else "Modeling"
            )
            config["version"] = 2
            save_migrated_config = True
        if config.get("version", 1) < 3:
            for tab in config["tabs"]:
                for item in tab["items"]:
                    background_color = item.get("background_color")
                    if (
                        background_color and
                        len(background_color) == 4 and
                        background_color[3] == 0.0
                    ):
                        item["background_color"] = [
                            background_color[0],
                            background_color[1],
                            background_color[2],
                            1.0,
                        ]
                    icon_color = item.get("icon_color")
                    if icon_color and len(icon_color) == 4 and icon_color[3] == 0.0:
                        item["icon_color"] = [icon_color[0], icon_color[1], icon_color[2], 1.0]
            config["version"] = 3
            save_migrated_config = True
    except (OSError, AttributeError, ValueError, TypeError, json.JSONDecodeError):
        _maya_shelf_config_cache = {
            "storage_version": 1,
            "shelves": {"TOPBAR": _maya_shelf_default_config()},
        }
    if save_migrated_config:
        _maya_shelf_save()
    shelves = _maya_shelf_config_cache["shelves"]
    if (
        _maya_shelf_active_scope not in shelves and
        uuid_scope in shelves
    ):
        shelves[_maya_shelf_active_scope] = shelves.pop(uuid_scope)
        _maya_shelf_save_deferred()
    if _maya_shelf_active_scope not in shelves:
        source = shelves.get("TOPBAR")
        shelves[_maya_shelf_active_scope] = (
            _maya_shelf_config_clone(source)
            if source is not None
            else _maya_shelf_default_config()
        )
        shelves[_maya_shelf_active_scope]["selected"] = ""
        _maya_shelf_save_deferred()
    return shelves[_maya_shelf_active_scope]


def _maya_shelf_save():
    path = _maya_shelf_config_path()
    temp_path = path + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        _maya_shelf_config()
        json.dump(_maya_shelf_config_cache, handle, ensure_ascii=False, indent=2)
    os.replace(temp_path, path)


def _maya_shelf_save_deferred():
    global _maya_shelf_save_timer_pending
    if _maya_shelf_save_timer_pending:
        return
    _maya_shelf_save_timer_pending = True
    try:
        _maya_shelf_save()
    finally:
        _maya_shelf_save_timer_pending = False


def _maya_shelf_active_tab(context=None):
    config = _maya_shelf_config(context)
    active = config.get("active")
    tab = next((tab for tab in config["tabs"] if tab["name"] == active), None)
    if tab is None:
        tab = config["tabs"][0]
        config["active"] = tab["name"]
    return tab


def _maya_shelf_config_for_scope(scope):
    shelves = _maya_shelf_config_cache["shelves"]
    if scope not in shelves:
        shelves[scope] = _maya_shelf_config_clone(shelves["TOPBAR"])
    return shelves[scope]


def _maya_shelf_active_tab_for_scope(scope):
    config = _maya_shelf_config_for_scope(scope)
    active = config.get("active")
    tab = next((tab for tab in config["tabs"] if tab["name"] == active), None)
    if tab is None:
        tab = config["tabs"][0]
        config["active"] = tab["name"]
    return tab


def _maya_shelf_area_scope(context, area):
    return _maya_shelf_layout_scope_key(context, area)


def _maya_shelf_redraw(context):
    global _maya_shelf_layout_revision
    _maya_shelf_layout_revision += 1
    _maya_shelf_row_cache.clear()

    area = getattr(context, "area", None)
    if area is not None and area.type in {'TOPBAR', 'SHELF'}:
        area.tag_redraw()

    # Regular screen areas do not contain global Top Bar areas. Keep this fallback for
    # non-global/custom screens, while the context area above handles the normal case.
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type in {'TOPBAR', 'SHELF'}:
                area.tag_redraw()
    if hasattr(bpy.ops.topbar, "shelf_global_redraw"):
        bpy.ops.topbar.shelf_global_redraw()


def _maya_shelf_reorder(item_id, target_row, target_index):
    tab = _maya_shelf_active_tab()
    item = next((item for item in tab["items"] if item["id"] == item_id), None)
    if item is None:
        return False
    source_row = item.get("row", 0)
    source_items = [
        candidate for candidate in tab["items"]
        if candidate.get("row", 0) == source_row
    ]
    source_index = source_items.index(item)
    rows = {
        0: [candidate for candidate in tab["items"] if candidate is not item and candidate.get("row", 0) == 0],
        1: [candidate for candidate in tab["items"] if candidate is not item and candidate.get("row", 0) == 1],
    }
    requested_target_index = max(target_index, 0)
    insert_index = min(requested_target_index, len(rows[target_row]))
    separators = tab.setdefault("separators", [])
    for separator in separators:
        column = separator.get("column", 0)
        if separator.get("row", 0) == source_row and source_index < column:
            separator["column"] = column - 1
    for separator in separators:
        column = separator.get("column", 0)
        if (
            separator.get("row", 0) == target_row and
            requested_target_index <= column
        ):
            separator["column"] = column + 1
    item["row"] = target_row
    rows[target_row].insert(insert_index, item)
    tab["items"] = rows[0] + rows[1]
    return True


def _maya_shelf_reorder_adaptive(item_id, target_index):
    tab = _maya_shelf_active_tab()
    entries = _maya_shelf_adaptive_entries(tab)
    source_index = next(
        (
            index
            for index, (_entry_type, entry) in enumerate(entries)
            if entry["id"] == item_id
        ),
        None,
    )
    if source_index is None:
        return False

    entry = entries.pop(source_index)
    if source_index < target_index:
        target_index -= 1
    entries.insert(min(max(target_index, 0), len(entries)), entry)

    tab["items"] = [
        item
        for entry_type, item in entries
        if entry_type == "ITEM"
    ]
    item_column = 0
    separators = []
    for entry_type, item in entries:
        if entry_type == "ITEM":
            item["row"] = 0
            item_column += 1
        else:
            item["row"] = 0
            item["column"] = item_column
            separators.append(item)
    tab["separators"] = separators
    return True


def _maya_shelf_entry_remove(tab, item_id):
    item = next((item for item in tab["items"] if item["id"] == item_id), None)
    if item is not None:
        row = item.get("row", 0)
        row_items = [
            candidate for candidate in tab["items"]
            if candidate.get("row", 0) == row
        ]
        index = row_items.index(item)
        tab["items"].remove(item)
        for separator in tab.setdefault("separators", []):
            if separator.get("row", 0) == row and separator.get("column", 0) > index:
                separator["column"] -= 1
        return "ITEM", item

    separator = next(
        (
            separator for separator in tab.setdefault("separators", [])
            if separator["id"] == item_id
        ),
        None,
    )
    if separator is not None:
        tab["separators"].remove(separator)
        return "SEPARATOR", separator
    return None, None


def _maya_shelf_entry_insert_row(tab, entry_type, entry, row, index):
    row = min(max(row, 0), 1)
    if entry_type == "SEPARATOR":
        entry["row"] = row
        entry["column"] = max(index, 0)
        tab.setdefault("separators", []).append(entry)
        tab["separators"].sort(
            key=lambda candidate: (
                candidate.get("row", 0),
                candidate.get("column", 0),
            )
        )
        return

    rows = {
        row_index: [
            item for item in tab["items"]
            if item.get("row", 0) == row_index
        ]
        for row_index in (0, 1)
    }
    insert_index = min(max(index, 0), len(rows[row]))
    for separator in tab.setdefault("separators", []):
        if separator.get("row", 0) == row and separator.get("column", 0) >= insert_index:
            separator["column"] += 1
    entry["row"] = row
    rows[row].insert(insert_index, entry)
    tab["items"] = rows[0] + rows[1]


def _maya_shelf_entry_insert_adaptive(tab, entry_type, entry, index):
    entries = _maya_shelf_adaptive_entries(tab)
    entries.insert(min(max(index, 0), len(entries)), (entry_type, entry))
    tab["items"] = []
    tab["separators"] = []
    item_column = 0
    for candidate_type, candidate in entries:
        candidate["row"] = 0
        if candidate_type == "ITEM":
            tab["items"].append(candidate)
            item_column += 1
        else:
            candidate["column"] = item_column
            tab["separators"].append(candidate)


class TOPBAR_OT_maya_shelf_tab(Operator):
    bl_idname = "topbar.maya_shelf_tab"
    bl_label = "Maya Shelf Tab"
    bl_options = {'INTERNAL'}

    tab: StringProperty()

    def execute(self, context):
        config = _maya_shelf_config(context)
        if any(tab["name"] == self.tab for tab in config["tabs"]):
            config["active"] = self.tab
            _maya_shelf_save()
        _maya_shelf_redraw(context)
        return {'FINISHED'}


class TOPBAR_OT_maya_shelf_tab_add(Operator):
    bl_idname = "topbar.maya_shelf_tab_add"
    bl_label = "Add Shelf Tab"

    name: StringProperty(name="Name", default="New Shelf")

    def invoke(self, context, _event):
        _maya_shelf_config(context)
        return context.window_manager.invoke_props_dialog(self, width=320)

    def execute(self, context):
        name = self.name.strip()
        config = _maya_shelf_config(context)
        if not name or any(tab["name"] == name for tab in config["tabs"]):
            self.report({'WARNING'}, "Enter a unique shelf name")
            return {'CANCELLED'}
        config["tabs"].append({"name": name, "items": [], "separators": []})
        config["active"] = name
        _maya_shelf_save()
        _maya_shelf_redraw(context)
        return {'FINISHED'}


class TOPBAR_OT_maya_shelf_tab_rename(Operator):
    bl_idname = "topbar.maya_shelf_tab_rename"
    bl_label = "Rename Shelf Tab"

    name: StringProperty(name="Name")

    def invoke(self, context, _event):
        self.name = _maya_shelf_active_tab(context)["name"]
        return context.window_manager.invoke_props_dialog(self, width=320)

    def execute(self, context):
        name = self.name.strip()
        config = _maya_shelf_config(context)
        tab = _maya_shelf_active_tab()
        if not name or any(item is not tab and item["name"] == name for item in config["tabs"]):
            self.report({'WARNING'}, "Enter a unique shelf name")
            return {'CANCELLED'}
        tab["name"] = name
        config["active"] = name
        _maya_shelf_save()
        _maya_shelf_redraw(context)
        return {'FINISHED'}


class TOPBAR_OT_maya_shelf_tab_remove(Operator):
    bl_idname = "topbar.maya_shelf_tab_remove"
    bl_label = "Remove Shelf Tab"

    def execute(self, context):
        config = _maya_shelf_config(context)
        if len(config["tabs"]) == 1:
            self.report({'WARNING'}, "At least one shelf tab is required")
            return {'CANCELLED'}
        tab = _maya_shelf_active_tab()
        config["tabs"].remove(tab)
        config["active"] = config["tabs"][0]["name"]
        _maya_shelf_save()
        _maya_shelf_redraw(context)
        return {'FINISHED'}


class TOPBAR_OT_maya_shelf_item_add(Operator):
    bl_idname = "topbar.maya_shelf_item_add"
    bl_label = "Add Shelf Icon"

    label: StringProperty(name="Tooltip", default="New Command")
    command_type: EnumProperty(
        name="Action",
        items=_MAYA_SHELF_COMMAND_TYPES,
        default='BUILTIN',
    )
    builtin_action: EnumProperty(
        name="Built-in Action",
        items=_MAYA_SHELF_BUILTIN_ACTIONS,
        default='cube',
    )
    actions: CollectionProperty(type=TOPBAR_PG_maya_shelf_action)
    action_index: IntProperty(
        name="Built-in Action",
        default=0,
        update=_maya_shelf_action_index_update,
    )
    action_category: EnumProperty(
        name="Category",
        items=_MAYA_SHELF_ACTION_CATEGORIES,
        default='ALL',
    )
    action_sort: EnumProperty(
        name="Sort",
        items=_MAYA_SHELF_ACTION_SORT_MODES,
        default='CATEGORY',
    )
    operator_id: StringProperty(name="Operator", default="mesh.primitive_cube_add")
    script_source: EnumProperty(
        name="Script Source",
        items=_MAYA_SHELF_SCRIPT_SOURCES,
        default='INLINE',
    )
    script_code: StringProperty(name="Python Code")
    script_text: StringProperty(name="Text Block")
    script_file: StringProperty(name="Python File", subtype='FILE_PATH')
    icons: CollectionProperty(type=TOPBAR_PG_maya_shelf_icon)
    icon_index: IntProperty(name="Blender Icon", default=0)
    custom_icon: StringProperty(name="Custom Icon", subtype='FILE_PATH')
    background_color: FloatVectorProperty(
        name="Background Color",
        description="Button background color and opacity",
        subtype='COLOR',
        size=4,
        min=0.0,
        max=1.0,
        default=(0.18, 0.18, 0.18, 1.0),
    )
    icon_color: FloatVectorProperty(
        name="Icon Color",
        description="Icon tint and opacity",
        subtype='COLOR',
        size=4,
        min=0.0,
        max=1.0,
        default=(1.0, 1.0, 1.0, 1.0),
    )
    short_text: StringProperty(
        name="Short Text",
        description="Short label shown next to the icon",
        maxlen=5,
    )
    row: IntProperty(name="Row", default=0, min=0, max=1)

    def invoke(self, context, _event):
        _maya_shelf_config(context)
        _maya_shelf_action_list_fill(self, "cube")
        _maya_shelf_icon_list_fill(self, "MESH_CUBE")
        return context.window_manager.invoke_props_dialog(self, width=600)

    def draw(self, _context):
        layout = self.layout
        layout.prop(self, "label")
        layout.prop(self, "command_type")
        if self.command_type == 'BUILTIN':
            layout.label(text="Built-in Action")
            filters = layout.row(align=True)
            filters.prop(self, "action_category", text="")
            filters.prop(self, "action_sort", text="")
            layout.template_list(
                "TOPBAR_UL_maya_shelf_actions",
                "",
                self,
                "actions",
                self,
                "action_index",
                rows=9,
                maxrows=9,
            )
        elif self.command_type == 'OPERATOR':
            layout.prop(self, "operator_id")
        else:
            layout.prop(self, "script_source")
            if self.script_source == 'INLINE':
                layout.textbox(
                    self,
                    "script_code",
                    initial_visible_lines=8,
                    placeholder="Enter Python code stored in this shelf icon",
                )
            elif self.script_source == 'TEXT':
                layout.prop_search(self, "script_text", bpy.data, "texts")
            else:
                layout.prop(self, "script_file")
        layout.label(text="Blender Icon")
        layout.template_list(
            "TOPBAR_UL_maya_shelf_icons",
            "",
            self,
            "icons",
            self,
            "icon_index",
            rows=8,
            maxrows=8,
        )
        layout.prop(self, "custom_icon")
        _maya_shelf_draw_icon_preview(layout, self)
        layout.prop(self, "background_color")
        layout.prop(self, "icon_color")
        layout.prop(self, "short_text")
        layout.prop(self, "row")

    def execute(self, context):
        _maya_shelf_config(context)
        operator_id = self.operator_id.strip()
        script_settings = {
            "script_source": "",
            "script_code": "",
            "script_text": "",
            "script_file": "",
        }
        if self.command_type == 'BUILTIN':
            pass
        elif self.command_type == 'OPERATOR':
            try:
                module, name = operator_id.split(".", 1)
                getattr(getattr(bpy.ops, module), name)
            except (ValueError, AttributeError):
                self.report({'WARNING'}, "Unknown Blender operator")
                return {'CANCELLED'}
        else:
            script_settings, error = _maya_shelf_script_settings(self)
            if error:
                self.report({'WARNING'}, error)
                return {'CANCELLED'}

        if not self.icons or not 0 <= self.icon_index < len(self.icons):
            self.report({'WARNING'}, "Select a Blender icon")
            return {'CANCELLED'}
        icon = self.icons[self.icon_index].identifier
        custom_icon = self.custom_icon.strip()
        if custom_icon:
            custom_icon = os.path.abspath(bpy.path.abspath(custom_icon))
            if not os.path.isfile(custom_icon):
                self.report({'WARNING'}, "Custom icon file does not exist")
                return {'CANCELLED'}
            if not _maya_shelf_custom_icon(custom_icon):
                self.report({'WARNING'}, "Unsupported custom icon image")
                return {'CANCELLED'}

        label = self.label.strip()
        if not label or label == "New Command":
            if self.command_type == 'BUILTIN':
                label = _MAYA_SHELF_BUILTIN_ACTION_LABELS[
                    _maya_shelf_selected_action(self)
                ]
            elif self.command_type == 'OPERATOR':
                label = operator_id
            else:
                label = "Python Script"

        _maya_shelf_active_tab()["items"].append({
            "id": uuid.uuid4().hex,
            "label": label,
            "icon": icon,
            "action": (
                _maya_shelf_selected_action(self)
                if self.command_type == 'BUILTIN' else ""
            ),
            "operator": operator_id if self.command_type == 'OPERATOR' else "",
            "command_type": self.command_type,
            "custom_icon": custom_icon,
            "background_color": list(self.background_color),
            "icon_color": list(self.icon_color),
            "short_text": self.short_text.strip(),
            "row": self.row,
            **script_settings,
        })
        _maya_shelf_save()
        _maya_shelf_redraw(context)
        return {'FINISHED'}


class TOPBAR_OT_maya_shelf_item_edit(Operator):
    bl_idname = "topbar.maya_shelf_item_edit"
    bl_label = "Edit Shelf Icon"

    item_id: StringProperty(options={'SKIP_SAVE'})
    label: StringProperty(name="Tooltip")
    command_type: EnumProperty(
        name="Action",
        items=_MAYA_SHELF_COMMAND_TYPES,
        default='BUILTIN',
    )
    builtin_action: EnumProperty(
        name="Built-in Action",
        items=_MAYA_SHELF_BUILTIN_ACTIONS,
        default='select_box',
    )
    actions: CollectionProperty(type=TOPBAR_PG_maya_shelf_action)
    action_index: IntProperty(
        name="Built-in Action",
        default=0,
        update=_maya_shelf_action_index_update,
    )
    action_category: EnumProperty(
        name="Category",
        items=_MAYA_SHELF_ACTION_CATEGORIES,
        default='ALL',
    )
    action_sort: EnumProperty(
        name="Sort",
        items=_MAYA_SHELF_ACTION_SORT_MODES,
        default='CATEGORY',
    )
    operator_id: StringProperty(name="Operator")
    script_source: EnumProperty(
        name="Script Source",
        items=_MAYA_SHELF_SCRIPT_SOURCES,
        default='INLINE',
    )
    script_code: StringProperty(name="Python Code")
    script_text: StringProperty(name="Text Block")
    script_file: StringProperty(name="Python File", subtype='FILE_PATH')
    icons: CollectionProperty(type=TOPBAR_PG_maya_shelf_icon)
    icon_index: IntProperty(name="Blender Icon", default=0)
    custom_icon: StringProperty(name="Custom Icon", subtype='FILE_PATH')
    background_color: FloatVectorProperty(
        name="Background Color",
        description="Button background color and opacity",
        subtype='COLOR',
        size=4,
        min=0.0,
        max=1.0,
        default=(0.18, 0.18, 0.18, 1.0),
    )
    icon_color: FloatVectorProperty(
        name="Icon Color",
        description="Icon tint and opacity",
        subtype='COLOR',
        size=4,
        min=0.0,
        max=1.0,
        default=(1.0, 1.0, 1.0, 1.0),
    )
    short_text: StringProperty(
        name="Short Text",
        description="Short label shown next to the icon",
        maxlen=5,
    )

    def invoke(self, context, _event):
        _maya_shelf_config(context)
        item = next(
            (
                item for item in _maya_shelf_active_tab()["items"]
                if item["id"] == self.item_id
            ),
            None,
        )
        if item is None:
            return {'CANCELLED'}
        self.operator_id = item.get("operator", "")
        self.command_type = item.get(
            "command_type",
            'OPERATOR' if self.operator_id else 'BUILTIN',
        )
        if item.get("action") in {
            enum_item[0] for enum_item in _MAYA_SHELF_BUILTIN_ACTIONS
        }:
            self.builtin_action = item["action"]
        _maya_shelf_action_list_fill(self, self.builtin_action)
        self.label = item.get("label", "")
        self.script_source = item.get("script_source", "INLINE") or 'INLINE'
        self.script_code = item.get("script_code", "")
        self.script_text = item.get("script_text", "")
        self.script_file = item.get("script_file", "")
        _maya_shelf_icon_list_fill(self, item.get("icon", "NONE"))
        self.custom_icon = item.get("custom_icon", "")
        self.background_color = item.get(
            "background_color",
            (0.18, 0.18, 0.18, 1.0),
        )
        self.icon_color = item.get("icon_color", (1.0, 1.0, 1.0, 1.0))
        self.short_text = item.get("short_text", "")
        return context.window_manager.invoke_props_dialog(self, width=600)

    def draw(self, _context):
        layout = self.layout
        layout.prop(self, "label")
        layout.prop(self, "command_type")
        if self.command_type == 'BUILTIN':
            layout.label(text="Built-in Action")
            filters = layout.row(align=True)
            filters.prop(self, "action_category", text="")
            filters.prop(self, "action_sort", text="")
            layout.template_list(
                "TOPBAR_UL_maya_shelf_actions",
                "",
                self,
                "actions",
                self,
                "action_index",
                rows=9,
                maxrows=9,
            )
        elif self.command_type == 'OPERATOR':
            layout.prop(self, "operator_id")
        elif self.command_type == 'PYTHON':
            layout.prop(self, "script_source")
            if self.script_source == 'INLINE':
                layout.textbox(
                    self,
                    "script_code",
                    initial_visible_lines=8,
                    placeholder="Enter Python code stored in this shelf icon",
                )
            elif self.script_source == 'TEXT':
                layout.prop_search(self, "script_text", bpy.data, "texts")
            else:
                layout.prop(self, "script_file")
        layout.label(text="Blender Icon")
        layout.template_list(
            "TOPBAR_UL_maya_shelf_icons",
            "",
            self,
            "icons",
            self,
            "icon_index",
            rows=8,
            maxrows=8,
        )
        layout.prop(self, "custom_icon")
        _maya_shelf_draw_icon_preview(layout, self)
        layout.prop(self, "background_color")
        layout.prop(self, "icon_color")
        layout.prop(self, "short_text")

    def execute(self, context):
        _maya_shelf_config(context)
        item = next(
            (
                item for item in _maya_shelf_active_tab()["items"]
                if item["id"] == self.item_id
            ),
            None,
        )
        if item is None:
            return {'CANCELLED'}

        operator_id = self.operator_id.strip()
        if self.command_type == 'OPERATOR':
            try:
                module, name = operator_id.split(".", 1)
                getattr(getattr(bpy.ops, module), name)
            except (ValueError, AttributeError):
                self.report({'WARNING'}, "Unknown Blender operator")
                return {'CANCELLED'}
        script_settings = None
        if self.command_type == 'PYTHON':
            script_settings, error = _maya_shelf_script_settings(self)
            if error:
                self.report({'WARNING'}, error)
                return {'CANCELLED'}

        if not self.icons or not 0 <= self.icon_index < len(self.icons):
            self.report({'WARNING'}, "Select a Blender icon")
            return {'CANCELLED'}
        icon = self.icons[self.icon_index].identifier

        custom_icon = self.custom_icon.strip()
        if custom_icon:
            custom_icon = os.path.abspath(bpy.path.abspath(custom_icon))
            if not os.path.isfile(custom_icon):
                self.report({'WARNING'}, "Custom icon file does not exist")
                return {'CANCELLED'}
            if not _maya_shelf_custom_icon(custom_icon):
                self.report({'WARNING'}, "Unsupported custom icon image")
                return {'CANCELLED'}

        item["label"] = self.label.strip() or item.get("label", "Shelf Command")
        item["icon"] = icon
        item["custom_icon"] = custom_icon
        item["background_color"] = list(self.background_color)
        item["icon_color"] = list(self.icon_color)
        item["short_text"] = self.short_text.strip()
        if self.command_type == 'BUILTIN':
            item["action"] = _maya_shelf_selected_action(self)
            item["operator"] = ""
            item["command_type"] = 'BUILTIN'
            item["script_source"] = ""
            item["script_code"] = ""
            item["script_text"] = ""
            item["script_file"] = ""
        elif self.command_type == 'OPERATOR':
            item["action"] = ""
            item["operator"] = operator_id
            item["command_type"] = 'OPERATOR'
            item["script_source"] = ""
            item["script_code"] = ""
            item["script_text"] = ""
            item["script_file"] = ""
        elif self.command_type == 'PYTHON':
            item["action"] = ""
            item["operator"] = ""
            item["command_type"] = 'PYTHON'
            item.update(script_settings)
        _maya_shelf_save()
        _maya_shelf_redraw(context)
        return {'FINISHED'}


class TOPBAR_OT_maya_shelf_item_remove_id(Operator):
    bl_idname = "topbar.maya_shelf_item_remove_id"
    bl_label = "Remove from Shelf"
    bl_options = {'UNDO'}

    item_id: StringProperty()

    def execute(self, context):
        _maya_shelf_config(context)
        tab = _maya_shelf_active_tab()
        separator = next(
            (
                separator for separator in tab.setdefault("separators", [])
                if separator["id"] == self.item_id
            ),
            None,
        )
        if separator is not None:
            tab["separators"].remove(separator)
            _maya_shelf_save()
            _maya_shelf_redraw(context)
            return {'FINISHED'}

        item = next((item for item in tab["items"] if item["id"] == self.item_id), None)
        if item is None:
            return {'CANCELLED'}
        tab["items"].remove(item)
        _maya_shelf_save()
        _maya_shelf_redraw(context)
        return {'FINISHED'}


class TOPBAR_OT_maya_shelf_separator_add(Operator):
    bl_idname = "topbar.maya_shelf_separator_add"
    bl_label = "Add Shelf Separator"
    bl_options = {'UNDO'}

    column: IntProperty(default=-1, min=-1, options={'SKIP_SAVE'})
    row: IntProperty(default=0, min=0, max=1, options={'SKIP_SAVE'})

    def execute(self, context):
        _maya_shelf_config(context)
        tab = _maya_shelf_active_tab()
        row_lengths = [
            sum(1 for item in tab["items"] if item.get("row", 0) == row)
            for row in (0, 1)
        ]
        column = self.column if self.column >= 0 else row_lengths[self.row]
        separators = tab.setdefault("separators", [])
        separators.append({
            "id": uuid.uuid4().hex,
            "column": column,
            "row": self.row,
        })
        separators.sort(
            key=lambda separator: (
                separator.get("row", 0),
                separator.get("column", 0),
            )
        )
        _maya_shelf_save()
        _maya_shelf_redraw(context)
        return {'FINISHED'}


class TOPBAR_OT_maya_shelf_context_menu(Operator):
    bl_idname = "topbar.maya_shelf_context_menu"
    bl_label = "Shelf Context Menu"
    bl_options = {'INTERNAL'}

    item_id: StringProperty(options={'SKIP_SAVE'})
    row: IntProperty(default=0, min=0, max=1, options={'SKIP_SAVE'})

    def invoke(self, context, _event):
        _maya_shelf_config(context)
        context.window_manager.popup_menu(self.draw_menu, title="Shelf")
        return {'FINISHED'}

    def draw_menu(self, menu, context):
        _maya_shelf_config(context)
        layout = menu.layout
        layout.operator_context = 'INVOKE_DEFAULT'
        tab = _maya_shelf_active_tab()
        item = next(
            (item for item in tab["items"] if item["id"] == self.item_id),
            None,
        )
        separator = next(
            (
                separator for separator in tab.setdefault("separators", [])
                if separator["id"] == self.item_id
            ),
            None,
        )
        if not self.item_id:
            config = _maya_shelf_config()
            layout.label(text="Shelf Tabs")
            for shelf_tab in config["tabs"]:
                props = layout.operator(
                    "topbar.maya_shelf_tab",
                    text=shelf_tab["name"],
                    icon='CHECKMARK' if shelf_tab is tab else 'BLANK1',
                )
                props.tab = shelf_tab["name"]
            layout.separator()
            layout.operator(
                "topbar.maya_shelf_tab_add",
                text="Add Shelf Tab",
                icon='ADD',
            )
            layout.operator(
                "topbar.maya_shelf_tab_rename",
                text="Rename Active Tab",
                icon='GREASEPENCIL',
            )
            layout.operator(
                "topbar.maya_shelf_tab_remove",
                text="Remove Active Tab",
                icon='X',
            )
            layout.separator()

        props = layout.operator(
            "topbar.maya_shelf_item_add",
            text="Add Shelf Icon",
            icon='ADD',
        )
        props.row = self.row

        if item is not None:
            row_items = [
                candidate for candidate in tab["items"]
                if candidate.get("row", 0) == item.get("row", 0)
            ]
            separator_column = row_items.index(item) + 1
        elif separator is not None:
            separator_column = separator.get("column", 0) + 1
        else:
            separator_column = sum(
                1 for candidate in tab["items"]
                if candidate.get("row", 0) == self.row
            )
        props = layout.operator(
            "topbar.maya_shelf_separator_add",
            text="Add Separator",
            icon='SPLIT_VERTICAL',
        )
        props.column = separator_column
        props.row = separator.get("row", self.row) if separator is not None else self.row

        if self.item_id:
            layout.separator()
            if item is not None:
                props = layout.operator(
                    "topbar.maya_shelf_item_edit",
                    text="Edit Shelf Icon",
                    icon='GREASEPENCIL',
                )
                props.item_id = item["id"]
            props = layout.operator(
                "topbar.maya_shelf_item_remove_id",
                text="Remove Separator" if separator is not None else "Remove from Shelf",
                icon='TRASH',
            )
            props.item_id = self.item_id


class TOPBAR_OT_maya_shelf_drag(Operator):
    bl_idname = "topbar.maya_shelf_drag"
    bl_label = "Move Shelf Icon"
    bl_options = {'INTERNAL'}

    item_id: StringProperty()

    @classmethod
    def poll(cls, context):
        return (
            context.area is not None and
            context.area.type in {'TOPBAR', 'SHELF'} and
            context.region is not None and
            context.region.type in {'WINDOW', 'FOOTER'}
        )

    @staticmethod
    def _source_row_and_index(context, event):
        region = context.region
        if region is None or region.type not in {'WINDOW', 'FOOTER'}:
            return None, None

        ui_scale = getattr(context.preferences.system, "ui_scale", 1.0)
        left_margin = _MAYA_SHELF_LEFT_MARGIN * ui_scale
        button_width = _MAYA_SHELF_BUTTON_SIZE * ui_scale
        slot_width = _MAYA_SHELF_SLOT_WIDTH * ui_scale
        mouse_region_x = event.mouse_x - region.x
        if mouse_region_x < left_margin:
            return None, None

        row = 0 if region.type == 'FOOTER' else 1
        relative_x = mouse_region_x - left_margin
        index = int(((relative_x - button_width * 0.5) / slot_width) + 0.5)
        items = [
            item
            for item in _maya_shelf_active_tab()["items"]
            if item.get("row", 0) == row
        ]
        if not items or index < 0 or index > len(items):
            return None, None
        if index == len(items):
            index -= 1
        return row, index

    @staticmethod
    def _adaptive_target_index(context, event, region, tab):
        entries = _maya_shelf_adaptive_entries(tab)
        ui_scale = getattr(context.preferences.system, "ui_scale", 1.0)
        margin = 8.0 * ui_scale
        cell_width = 32.5 * ui_scale
        cell_height = 36.0 * ui_scale
        content_width = max(region.width - margin * 2.0, cell_width)
        columns = max(int(content_width / cell_width), 1)
        actual_cell_width = content_width / columns
        mouse_x = min(max(event.mouse_x - region.x - margin, 0.0), content_width)
        mouse_y = max(region.y + region.height - event.mouse_y - margin, 0.0)
        column = min(int(mouse_x / actual_cell_width), columns - 1)
        row = max(int(mouse_y / cell_height), 0)
        index = row * columns + column
        if mouse_x - column * actual_cell_width > actual_cell_width * 0.5:
            index += 1
        return min(max(index, 0), len(entries))

    @staticmethod
    def _row_target_index(context, event, bounds, row, tab):
        ui_scale = getattr(context.preferences.system, "ui_scale", 1.0)
        relative_x = event.mouse_x - bounds[0] - _MAYA_SHELF_LEFT_MARGIN * ui_scale
        separator_width = _MAYA_SHELF_SEPARATOR_WIDTH * ui_scale
        row_items = [
            item for item in tab["items"]
            if item.get("row", 0) == row
        ]
        separator_counts = {}
        for separator in tab.setdefault("separators", []):
            if separator.get("row", 0) == row:
                column = max(separator.get("column", 0), 0)
                separator_counts[column] = separator_counts.get(column, 0) + 1

        positions = []
        position = 0.0
        for column in range(len(row_items) + 1):
            positions.append((position, column))
            position += separator_counts.get(column, 0) * separator_width
            if column < len(row_items):
                position += _maya_shelf_item_slot_width(row_items[column]) * ui_scale
        return min(positions, key=lambda candidate: abs(relative_x - candidate[0]))[1]

    def _drop_target(self, context, event):
        for area in context.screen.areas:
            if area.type != 'SHELF':
                continue
            region = next(
                (candidate for candidate in area.regions if candidate.type == 'WINDOW'),
                None,
            )
            if (
                region is None or
                not region.x <= event.mouse_x < region.x + region.width or
                not region.y <= event.mouse_y < region.y + region.height
            ):
                continue
            scope = _maya_shelf_area_scope(context, area)
            if not scope:
                continue
            tab = _maya_shelf_active_tab_for_scope(scope)
            index = self._adaptive_target_index(context, event, region, tab)
            return scope, True, 0, index

        topbar_bounds = self._topbar_region_bounds
        if not topbar_bounds:
            ui_scale = getattr(context.preferences.system, "ui_scale", 1.0)
            screen_top = max(
                (area.y + area.height for area in context.screen.areas),
                default=0,
            )
            row_height = 24.0 * ui_scale
            window_width = max(
                (area.x + area.width for area in context.screen.areas),
                default=0,
            )
            topbar_bounds = {
                1: (0, screen_top, window_width, row_height),
                0: (0, screen_top + row_height, window_width, row_height),
            }

        for row, bounds in topbar_bounds.items():
            if (
                bounds[0] <= event.mouse_x < bounds[0] + bounds[2] and
                bounds[1] <= event.mouse_y < bounds[1] + bounds[3]
            ):
                tab = _maya_shelf_active_tab_for_scope("TOPBAR")
                index = self._row_target_index(context, event, bounds, row, tab)
                return "TOPBAR", False, row, index
        return None, None, None, None

    def _drop_row_and_index(self, context, event):
        if self._adaptive:
            region = context.region
            entries = _maya_shelf_adaptive_entries(_maya_shelf_active_tab())
            ui_scale = getattr(context.preferences.system, "ui_scale", 1.0)
            margin = 8.0 * ui_scale
            cell_width = 32.5 * ui_scale
            cell_height = 36.0 * ui_scale
            content_width = max(region.width - margin * 2.0, cell_width)
            columns = max(int(content_width / cell_width), 1)
            actual_cell_width = content_width / columns
            mouse_x = min(max(event.mouse_x - region.x - margin, 0.0), content_width)
            mouse_y = max(region.y + region.height - event.mouse_y - margin, 0.0)
            column = min(int(mouse_x / actual_cell_width), columns - 1)
            row = max(int(mouse_y / cell_height), 0)
            index = row * columns + column
            if mouse_x - column * actual_cell_width > actual_cell_width * 0.5:
                index += 1
            return 0, min(max(index, 0), len(entries))

        if not self._region_bounds:
            return None, None

        row, bounds = min(
            self._region_bounds.items(),
            key=lambda item: abs(event.mouse_y - (item[1][1] + item[1][3] * 0.5)),
        )
        icon_band_min = min(item[1] for item in self._region_bounds.values())
        icon_band_max = max(item[1] + item[3] for item in self._region_bounds.values())
        if not icon_band_min <= event.mouse_y < icon_band_max:
            return None, None

        mouse_region_x = event.mouse_x - bounds[0]
        ui_scale = getattr(context.preferences.system, "ui_scale", 1.0)
        left_margin = _MAYA_SHELF_LEFT_MARGIN * ui_scale
        separator_width = _MAYA_SHELF_SEPARATOR_WIDTH * ui_scale
        relative_x = mouse_region_x - left_margin
        tab = _maya_shelf_active_tab()
        row_items = [
            item for item in tab["items"]
            if item.get("row", 0) == row
        ]
        separator_counts = {}
        for separator in tab.setdefault("separators", []):
            if separator.get("row", 0) == row:
                column = max(separator.get("column", 0), 0)
                separator_counts[column] = separator_counts.get(column, 0) + 1

        boundary_positions = []
        boundary_indices = []
        position = 0.0
        for column in range(len(row_items) + 1):
            boundary_positions.append(position)
            boundary_indices.append(column)
            position += separator_counts.get(column, 0) * separator_width
            if column < len(row_items):
                position += _maya_shelf_item_slot_width(row_items[column]) * ui_scale
        if (
            not self._drag_separator and
            separator_counts.get(len(row_items), 0)
        ):
            boundary_positions.append(position)
            boundary_indices.append(len(row_items) + 1)

        boundary_index = min(
            range(len(boundary_positions)),
            key=lambda candidate: abs(relative_x - boundary_positions[candidate]),
        )
        visual_index = boundary_indices[boundary_index]
        index = visual_index
        if (
            not self._drag_separator and
            row == self._source_row and
            self._source_index < visual_index
        ):
            index -= 1
        item_count = len(row_items) - (
            1 if not self._drag_separator and row == self._source_row else 0
        )
        max_index = item_count
        if (
            not self._drag_separator and
            separator_counts.get(len(row_items), 0)
        ):
            max_index += 1
        return row, min(max(index, 0), max_index)

    def _preview_begin(self, context):
        global _maya_shelf_drag_state
        self._preview_active = True
        _maya_shelf_drag_state = {
            "kind": "separator" if self._drag_separator else "icon",
            "item_id": self.item_id,
            "source_scope": self._source_scope,
            "source_row": self._source_row,
            "source_index": self._source_index,
            "target_row": self._target_row,
            "target_index": self._target_index,
            "target_scope": self._target_scope,
            "adaptive": self._target_adaptive,
        }

    def _preview_update(self):
        if _maya_shelf_drag_state is not None:
            _maya_shelf_drag_state["target_row"] = self._target_row
            _maya_shelf_drag_state["target_index"] = self._target_index
            _maya_shelf_drag_state["target_scope"] = self._target_scope
            _maya_shelf_drag_state["adaptive"] = self._target_adaptive

    def _preview_end(self, context):
        global _maya_shelf_drag_state
        if not getattr(self, "_preview_active", False):
            return
        self._preview_active = False
        _maya_shelf_drag_state = None

    def invoke(self, context, event):
        _maya_shelf_config(context)
        self._source_scope = _maya_shelf_scope_key(context)
        self._adaptive = context.area.type == 'SHELF'
        tab = _maya_shelf_active_tab()
        source_separator = next(
            (
                separator for separator in tab.setdefault("separators", [])
                if separator["id"] == self.item_id
            ),
            None,
        )
        self._drag_separator = source_separator is not None
        if source_separator is not None:
            row = source_separator.get("row", 0)
            index = max(source_separator.get("column", 0), 0)
        else:
            source_item = next(
                (item for item in tab["items"] if item["id"] == self.item_id),
                None,
            )
            if source_item is not None:
                row = source_item.get("row", 0)
                items = [
                    item for item in tab["items"]
                    if item.get("row", 0) == row
                ]
                index = items.index(source_item)
            else:
                row, index = self._source_row_and_index(context, event)
                if row is None:
                    return {'CANCELLED'}
                items = [
                    item for item in tab["items"]
                    if item.get("row", 0) == row
                ]
                if index >= len(items):
                    return {'CANCELLED'}
                self.item_id = items[index]["id"]

        if self._adaptive:
            index = next(
                (
                    entry_index
                    for entry_index, (_entry_type, entry) in enumerate(
                        _maya_shelf_adaptive_entries(tab)
                    )
                    if entry["id"] == self.item_id
                ),
                None,
            )
            if index is None:
                return {'CANCELLED'}
            row = 0

        self._source_row = row
        self._source_index = index
        self._target_row = row
        self._target_index = index
        self._target_scope = self._source_scope
        self._target_adaptive = self._adaptive
        self._region_bounds = {
            0 if region.type == 'FOOTER' else 1: (
                region.x,
                region.y,
                region.width,
                region.height,
            )
            for region in context.area.regions
            if region.type in {'WINDOW', 'FOOTER'}
        }
        self._topbar_region_bounds = (
            self._region_bounds.copy()
            if context.area.type == 'TOPBAR'
            else {}
        )
        _maya_shelf_config()["selected"] = ""
        self._preview_begin(context)
        context.window_manager.modal_handler_add(self)
        _maya_shelf_redraw(context)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        _maya_shelf_config(context)
        if event.type == 'MOUSEMOVE':
            scope, adaptive, row, index = self._drop_target(context, event)
            target = (scope, adaptive, row, index)
            current = (
                self._target_scope,
                self._target_adaptive,
                self._target_row,
                self._target_index,
            )
            if scope is not None and target != current:
                self._target_scope = scope
                self._target_adaptive = adaptive
                self._target_row = row
                self._target_index = index
                self._preview_update()
                _maya_shelf_redraw(context)
            return {'RUNNING_MODAL', 'PASS_THROUGH'}

        if event.type == 'MIDDLEMOUSE' and event.value == 'RELEASE':
            scope, adaptive, row, index = self._drop_target(context, event)
            if scope is None:
                scope = self._target_scope
                adaptive = self._target_adaptive
                row = self._target_row
                index = self._target_index

            if scope != self._source_scope:
                source_tab = _maya_shelf_active_tab_for_scope(self._source_scope)
                target_tab = _maya_shelf_active_tab_for_scope(scope)
                entry_type, entry = _maya_shelf_entry_remove(source_tab, self.item_id)
                if entry is not None:
                    target_ids = {
                        candidate["id"]
                        for candidate in target_tab["items"] +
                        target_tab.setdefault("separators", [])
                    }
                    if entry["id"] in target_ids:
                        entry["id"] = uuid.uuid4().hex
                    if adaptive:
                        _maya_shelf_entry_insert_adaptive(
                            target_tab,
                            entry_type,
                            entry,
                            index,
                        )
                    else:
                        _maya_shelf_entry_insert_row(
                            target_tab,
                            entry_type,
                            entry,
                            row,
                            index,
                        )
            elif adaptive:
                _maya_shelf_reorder_adaptive(self.item_id, index)
            elif self._drag_separator:
                tab = _maya_shelf_active_tab()
                separator = next(
                    (
                        separator for separator in tab.setdefault("separators", [])
                        if separator["id"] == self.item_id
                    ),
                    None,
                )
                if separator is not None:
                    separator["column"] = index
                    separator["row"] = row
                    tab["separators"].sort(
                        key=lambda candidate: (
                            candidate.get("row", 0),
                            candidate.get("column", 0),
                        )
                    )
            else:
                if row == self._source_row and self._source_index < index:
                    index -= 1
                _maya_shelf_reorder(self.item_id, row, index)
            _maya_shelf_config()["selected"] = ""
            self._preview_end(context)
            _maya_shelf_save()
            _maya_shelf_redraw(context)
            return {'FINISHED', 'PASS_THROUGH'}

        if event.type in {'ESC', 'RIGHTMOUSE'}:
            _maya_shelf_config()["selected"] = ""
            self._preview_end(context)
            _maya_shelf_redraw(context)
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}

    def cancel(self, context):
        _maya_shelf_config(context)
        _maya_shelf_config()["selected"] = ""
        self._preview_end(context)
        _maya_shelf_redraw(context)


class TOPBAR_OT_maya_shelf_action(Operator):
    bl_idname = "topbar.maya_shelf_action"
    bl_label = "Maya Shelf Action"
    bl_options = {'REGISTER', 'UNDO'}

    action: StringProperty()
    operator_id: StringProperty()
    item_id: StringProperty()
    tooltip: StringProperty(options={'SKIP_SAVE'})

    @classmethod
    def description(cls, _context, properties):
        return properties.tooltip

    def execute(self, context):
        _maya_shelf_config(context)
        tab = _maya_shelf_active_tab()
        if any(
            separator["id"] == self.item_id
            for separator in tab.setdefault("separators", [])
        ):
            return {'CANCELLED'}
        item = next(
            (item for item in tab["items"] if item["id"] == self.item_id),
            None,
        )
        if item is not None and item.get("command_type") == 'PYTHON':
            source = item.get("script_source", "INLINE")
            filename = "<Shelf Button>"
            try:
                if source == 'TEXT':
                    text_name = item.get("script_text", "")
                    text = bpy.data.texts.get(text_name)
                    if text is None:
                        raise RuntimeError("Shelf text block was not found")
                    code = text.as_string()
                    filename = f"<Text:{text_name}>"
                elif source == 'FILE':
                    filename = item.get("script_file", "")
                    with open(filename, "r", encoding="utf-8-sig") as handle:
                        code = handle.read()
                else:
                    code = item.get("script_code", "")
                namespace = {
                    "__name__": "__main__",
                    "__file__": filename,
                    "bpy": bpy,
                    "context": context,
                }
                compiled = compile(code, filename, "exec")
                area = next(
                    (area for area in context.screen.areas if area.type == 'VIEW_3D'),
                    None,
                )
                region = next(
                    (
                        region for region in area.regions
                        if region.type == 'WINDOW'
                    ),
                    None,
                ) if area is not None else None
                if area is not None and region is not None:
                    with context.temp_override(area=area, region=region):
                        namespace["context"] = bpy.context
                        exec(compiled, namespace, namespace)
                else:
                    exec(compiled, namespace, namespace)
            except Exception as ex:
                self.report({'ERROR'}, f"Shelf script failed: {ex}")
                return {'CANCELLED'}
            return {'FINISHED'}

        animation_editor_actions = {
            "duplicate_keyframes",
            "interpolation_constant",
            "interpolation_linear",
            "interpolation_bezier",
            "set_preview_range",
        }
        if self.action in animation_editor_actions:
            area = next(
                (
                    area for area in context.screen.areas
                    if area.type in {'GRAPH_EDITOR', 'DOPESHEET_EDITOR'}
                ),
                None,
            )
        else:
            area = None
        if area is None:
            area = next(
                (area for area in context.screen.areas if area.type == 'VIEW_3D'),
                None,
            )
        if area is None:
            self.report({'WARNING'}, "No compatible editor is available")
            return {'CANCELLED'}
        region = next((region for region in area.regions if region.type == 'WINDOW'), None)
        override = {
            "window": context.window,
            "screen": context.screen,
            "area": area,
            "region": region,
            "space_data": area.spaces.active,
        }

        tool_actions = {
            "select_box": "builtin.select_box",
            "move": "builtin.move",
            "rotate": "builtin.rotate",
            "scale": "builtin.scale",
            "sculpt_draw": "builtin_brush.Draw",
            "sculpt_smooth": "builtin_brush.Smooth",
            "sculpt_grab": "builtin_brush.Grab",
            "spin": "builtin.spin",
        }
        operators = {
            "plane": ("mesh.primitive_plane_add", {}),
            "cube": ("mesh.primitive_cube_add", {}),
            "sphere": ("mesh.primitive_uv_sphere_add", {}),
            "cylinder": ("mesh.primitive_cylinder_add", {}),
            "cone": ("mesh.primitive_cone_add", {}),
            "torus": ("mesh.primitive_torus_add", {}),
            "bezier": ("curve.primitive_bezier_curve_add", {}),
            "bezier_circle": ("curve.primitive_bezier_circle_add", {}),
            "nurbs": ("curve.primitive_nurbs_curve_add", {}),
            "nurbs_circle": ("curve.primitive_nurbs_circle_add", {}),
            "path": ("curve.primitive_nurbs_path_add", {}),
            "edit_mode": ("object.editmode_toggle", {}),
            "pose_mode": ("object.posemode_toggle", {}),
            "sculpt_mode": ("object.mode_set", {"mode": 'SCULPT'}),
            "extrude": ("mesh.extrude_region_move", {}),
            "inset": ("mesh.inset", {}),
            "bevel": ("mesh.bevel", {}),
            "loop_cut": ("mesh.loopcut_slide", {}),
            "mirror": ("object.modifier_add", {"type": 'MIRROR'}),
            "array": ("object.modifier_add", {"type": 'ARRAY'}),
            "subsurf": ("object.modifier_add", {"type": 'SUBSURF'}),
            "multires": ("object.modifier_add", {"type": 'MULTIRES'}),
            "armature": ("object.armature_add", {}),
            "parent": ("object.parent_set", {"type": 'OBJECT'}),
            "clear_parent": ("object.parent_clear", {"type": 'CLEAR_KEEP_TRANSFORM'}),
            "constraint": ("object.constraint_add", {"type": 'COPY_TRANSFORMS'}),
            "keyframe": ("anim.keyframe_insert_menu", {"type": 'LocRotScale'}),
            "delete_keyframe": ("anim.keyframe_delete_v3d", {}),
            "first_frame": ("screen.frame_jump", {"end": False}),
            "play": ("screen.animation_play", {}),
            "last_frame": ("screen.frame_jump", {"end": True}),
            "camera": ("object.camera_add", {}),
            "point_light": ("object.light_add", {"type": 'POINT'}),
            "area_light": ("object.light_add", {"type": 'AREA'}),
            "sun_light": ("object.light_add", {"type": 'SUN'}),
            "render": ("render.render", {}),
            "render_animation": ("render.render", {"animation": True}),
            "quick_smoke": ("object.quick_smoke", {}),
            "quick_fur": ("object.quick_fur", {}),
            "explode": ("object.modifier_add", {"type": 'EXPLODE'}),
            "wind": ("object.effector_add", {"type": 'WIND'}),
            "turbulence": ("object.effector_add", {"type": 'TURBULENCE'}),
            "save": ("wm.save_mainfile", {}),
            "preferences": ("screen.userpref_show", {}),
            "delete_object": ("object.delete", {"use_global": False, "confirm": False}),
            "duplicate": ("object.duplicate_move", {}),
            "duplicate_linked": ("object.duplicate_move_linked", {}),
            "join_objects": ("object.join", {}),
            "separate_selection": ("mesh.separate", {"type": 'SELECTED'}),
            "apply_transforms": (
                "object.transform_apply",
                {"location": True, "rotation": True, "scale": True},
            ),
            "origin_geometry": (
                "object.origin_set",
                {"type": 'ORIGIN_GEOMETRY', "center": 'MEDIAN'},
            ),
            "shade_smooth": ("object.shade_smooth", {}),
            "shade_flat": ("object.shade_flat", {}),
            "hide_selected": ("object.hide_view_set", {"unselected": False}),
            "unhide_all": ("object.hide_view_clear", {}),
            "empty": ("object.empty_add", {"type": 'PLAIN_AXES'}),
            "clear_location": ("object.location_clear", {"clear_delta": False}),
            "clear_rotation": ("object.rotation_clear", {"clear_delta": False}),
            "clear_scale": ("object.scale_clear", {"clear_delta": False}),
            "origin_cursor": ("object.origin_set", {"type": 'ORIGIN_CURSOR'}),
            "frame_selected": ("view3d.view_selected", {"use_all_regions": False}),
            "frame_all": ("view3d.view_all", {"center": False}),
            "camera_view": ("view3d.view_camera", {}),
            "camera_to_view": ("view3d.camera_to_view", {}),
            "perspective_toggle": ("view3d.view_persportho", {}),
            "isolate_selected": ("view3d.localview", {"frame_selected": False}),
            "merge_by_distance": ("mesh.remove_doubles", {}),
            "recalc_normals": ("mesh.normals_make_consistent", {"inside": False}),
            "bridge_loops": ("mesh.bridge_edge_loops", {}),
            "subdivide_mesh": ("mesh.subdivide", {}),
            "triangulate": ("mesh.quads_convert_to_tris", {}),
            "tris_to_quads": ("mesh.tris_convert_to_quads", {}),
            "fill_faces": ("mesh.fill", {}),
            "delete_loose": ("mesh.delete_loose", {}),
            "flip_normals": ("mesh.flip_normals", {}),
            "select_more": ("mesh.select_more", {}),
            "select_less": ("mesh.select_less", {}),
            "mark_seam": ("mesh.mark_seam", {"clear": False}),
            "clear_seam": ("mesh.mark_seam", {"clear": True}),
            "unwrap": ("uv.unwrap", {}),
            "smart_uv": ("uv.smart_project", {}),
            "average_islands": ("uv.average_islands_scale", {}),
            "pack_islands": ("uv.pack_islands", {}),
            "reset_uv": ("uv.reset", {}),
            "cursor_to_selected": ("view3d.snap_cursor_to_selected", {}),
            "cursor_to_origin": ("view3d.snap_cursor_to_center", {}),
            "selected_to_cursor": (
                "view3d.snap_selected_to_cursor",
                {"use_offset": False},
            ),
            "selected_to_grid": ("view3d.snap_selected_to_grid", {}),
            "solidify_modifier": ("object.modifier_add", {"type": 'SOLIDIFY'}),
            "bevel_modifier": ("object.modifier_add", {"type": 'BEVEL'}),
            "boolean_modifier": ("object.modifier_add", {"type": 'BOOLEAN'}),
            "weld_modifier": ("object.modifier_add", {"type": 'WELD'}),
            "decimate_modifier": ("object.modifier_add", {"type": 'DECIMATE'}),
            "grid_fill": ("mesh.fill_grid", {}),
            "fill_holes": ("mesh.fill_holes", {}),
            "dissolve_vertices": ("mesh.dissolve_verts", {}),
            "dissolve_edges": ("mesh.dissolve_edges", {}),
            "dissolve_faces": ("mesh.dissolve_faces", {}),
            "loop_select": ("mesh.loop_multi_select", {"ring": False}),
            "select_linked": ("mesh.select_linked", {}),
            "select_non_manifold": ("mesh.select_non_manifold", {}),
            "convert_mesh": ("object.convert", {"target": 'MESH'}),
            "apply_visual_transform": ("object.visual_transform_apply", {}),
            "link_object_data": ("object.make_links_data", {"type": 'OBDATA'}),
            "make_single_user": (
                "object.make_single_user",
                {
                    "type": 'SELECTED_OBJECTS',
                    "object": True,
                    "obdata": True,
                    "material": False,
                    "animation": False,
                },
            ),
            "parent_bone": ("object.parent_set", {"type": 'BONE'}),
            "weighted_normal_modifier": (
                "object.modifier_add",
                {"type": 'WEIGHTED_NORMAL'},
            ),
            "geometry_nodes_modifier": ("object.modifier_add", {"type": 'NODES'}),
            "lattice_modifier": ("object.modifier_add", {"type": 'LATTICE'}),
            "shrinkwrap_modifier": ("object.modifier_add", {"type": 'SHRINKWRAP'}),
            "simple_deform_modifier": (
                "object.modifier_add",
                {"type": 'SIMPLE_DEFORM'},
            ),
            "skin_modifier": ("object.modifier_add", {"type": 'SKIN'}),
            "remesh_modifier": ("object.modifier_add", {"type": 'REMESH'}),
            "screw_modifier": ("object.modifier_add", {"type": 'SCREW'}),
            "copy_modifiers": ("object.modifiers_copy_to_selected", {}),
            "view_front": ("view3d.view_axis", {"type": 'FRONT'}),
            "view_back": ("view3d.view_axis", {"type": 'BACK'}),
            "view_left": ("view3d.view_axis", {"type": 'LEFT'}),
            "view_right": ("view3d.view_axis", {"type": 'RIGHT'}),
            "view_top": ("view3d.view_axis", {"type": 'TOP'}),
            "view_bottom": ("view3d.view_axis", {"type": 'BOTTOM'}),
            "orbit_left": (
                "view3d.view_orbit",
                {"type": 'ORBITLEFT', "angle": 0.261799},
            ),
            "orbit_right": (
                "view3d.view_orbit",
                {"type": 'ORBITRIGHT', "angle": 0.261799},
            ),
            "uv_cube_project": ("uv.cube_project", {}),
            "uv_cylinder_project": ("uv.cylinder_project", {}),
            "uv_sphere_project": ("uv.sphere_project", {}),
            "uv_project_view": ("uv.project_from_view", {}),
            "uv_align": ("uv.align", {"axis": 'ALIGN_AUTO'}),
            "uv_pin": ("uv.pin", {"clear": False}),
            "uv_unpin": ("uv.pin", {"clear": True}),
            "uv_select_overlap": ("uv.select_overlap", {}),
            "keyframe_location": (
                "anim.keyframe_insert_menu",
                {"type": 'Location'},
            ),
            "keyframe_rotation": (
                "anim.keyframe_insert_menu",
                {"type": 'Rotation'},
            ),
            "keyframe_scale": ("anim.keyframe_insert_menu", {"type": 'Scaling'}),
            "clear_keyframes": ("anim.keyframe_clear_v3d", {}),
            "previous_keyframe": ("screen.keyframe_jump", {"next": False}),
            "next_keyframe": ("screen.keyframe_jump", {"next": True}),
            "ik_constraint": ("pose.constraint_add", {"type": 'IK'}),
            "child_of_constraint": (
                "object.constraint_add",
                {"type": 'CHILD_OF'},
            ),
            "track_to_constraint": (
                "object.constraint_add",
                {"type": 'TRACK_TO'},
            ),
            "limit_rotation_constraint": (
                "object.constraint_add",
                {"type": 'LIMIT_ROTATION'},
            ),
            "parent_auto_weights": (
                "object.parent_set",
                {"type": 'ARMATURE_AUTO'},
            ),
            "clear_pose": ("pose.transforms_clear", {}),
            "pose_as_rest": ("pose.armature_apply", {}),
            "symmetrize_bones": ("armature.symmetrize", {}),
            "subdivide_bone": ("armature.subdivide", {}),
            "calculate_bone_roll": (
                "armature.calculate_roll",
                {"type": 'POS_X'},
            ),
            "voxel_remesh": ("object.voxel_remesh", {}),
            "mask_all": (
                "paint.mask_flood_fill",
                {"mode": 'VALUE', "value": 1.0},
            ),
            "mask_clear": (
                "paint.mask_flood_fill",
                {"mode": 'VALUE', "value": 0.0},
            ),
            "mask_invert": ("paint.mask_flood_fill", {"mode": 'INVERT'}),
            "hide_masked": ("paint.hide_show_masked", {"action": 'HIDE'}),
            "face_sets_visible": (
                "sculpt.face_sets_create",
                {"mode": 'VISIBLE'},
            ),
            "dyntopo_toggle": ("sculpt.dynamic_topology_toggle", {}),
            "smooth_mesh": ("sculpt.mesh_filter", {"type": 'SMOOTH'}),
            "pack_resources": ("file.pack_all", {}),
            "render_viewport": ("render.opengl", {"view_context": True}),
        }

        invoke_operators = {
            "knife": ("mesh.knife_tool", {}),
            "bisect": ("mesh.bisect", {}),
            "rip": (
                "mesh.rip_move",
                {"MESH_OT_rip": {"use_fill": False}},
            ),
            "rip_fill": (
                "mesh.rip_move",
                {"MESH_OT_rip": {"use_fill": True}},
            ),
            "screw_mesh": ("mesh.screw", {}),
            "shrink_fatten": ("transform.shrink_fatten", {}),
            "extrude_normals": ("mesh.extrude_region_shrink_fatten", {}),
            "extrude_individual": ("mesh.extrude_faces_move", {}),
            "edge_slide": ("transform.edge_slide", {}),
            "vertex_slide": ("transform.vert_slide", {}),
            "link_to_collection": ("object.link_to_collection", {}),
            "move_to_collection": ("object.move_to_collection", {}),
            "rename_object": ("wm.call_panel", {"name": "TOPBAR_PT_name"}),
            "viewport_screenshot": ("screen.screenshot_area", {}),
            "uv_minimize_stretch": ("uv.minimize_stretch", {}),
            "uv_stitch": ("uv.stitch", {}),
            "create_pose_asset": ("poselib.create_pose_asset", {}),
            "bake_action": ("nla.bake", {}),
            "open_file": ("wm.open_mainfile", {}),
            "save_as": ("wm.save_as_mainfile", {}),
            "append_file": ("wm.append", {}),
            "link_file": ("wm.link", {}),
        }

        try:
            with context.temp_override(**override):
                if self.action in tool_actions:
                    bpy.ops.wm.tool_set_by_id(name=tool_actions[self.action])
                elif self.action == "material":
                    obj = context.active_object
                    if obj is None:
                        raise RuntimeError("Select an object first")
                    material = bpy.data.materials.new(name="Material")
                    obj.data.materials.append(material)
                elif self.action in {"graph_editor", "dope_sheet", "nla_editor"}:
                    area.type = {
                        "graph_editor": 'GRAPH_EDITOR',
                        "dope_sheet": 'DOPESHEET_EDITOR',
                        "nla_editor": 'NLA_EDITOR',
                    }[self.action]
                elif self.action in {"select_all", "select_none", "select_inverse"}:
                    selection_action = {
                        "select_all": 'SELECT',
                        "select_none": 'DESELECT',
                        "select_inverse": 'INVERT',
                    }[self.action]
                    obj = context.active_object
                    if obj is not None and obj.type == 'MESH' and obj.mode == 'EDIT':
                        bpy.ops.mesh.select_all(action=selection_action)
                    else:
                        bpy.ops.object.select_all(action=selection_action)
                elif self.action in {
                    "view_wireframe",
                    "view_solid",
                    "view_material",
                    "view_rendered",
                }:
                    area.spaces.active.shading.type = {
                        "view_wireframe": 'WIREFRAME',
                        "view_solid": 'SOLID',
                        "view_material": 'MATERIAL',
                        "view_rendered": 'RENDERED',
                    }[self.action]
                elif self.action == "xray_toggle":
                    shading = area.spaces.active.shading
                    shading.show_xray = not shading.show_xray
                elif self.action == "toggle_overlays":
                    overlay = area.spaces.active.overlay
                    overlay.show_overlays = not overlay.show_overlays
                elif self.action == "toggle_grid":
                    overlay = area.spaces.active.overlay
                    overlay.show_floor = not overlay.show_floor
                elif self.action == "toggle_wire_overlay":
                    overlay = area.spaces.active.overlay
                    overlay.show_wireframes = not overlay.show_wireframes
                elif self.action == "toggle_face_orientation":
                    overlay = area.spaces.active.overlay
                    overlay.show_face_orientation = not overlay.show_face_orientation
                elif self.action == "toggle_statistics":
                    overlay = area.spaces.active.overlay
                    overlay.show_stats = not overlay.show_stats
                elif self.action == "toggle_gizmos":
                    space = area.spaces.active
                    space.show_gizmo = not space.show_gizmo
                elif self.action == "toggle_camera_lock":
                    space = area.spaces.active
                    space.lock_camera = not space.lock_camera
                elif self.action == "apply_active_modifier":
                    obj = context.active_object
                    if obj is None or not obj.modifiers:
                        raise RuntimeError("The active object has no modifiers")
                    modifier = obj.modifiers.active or obj.modifiers[-1]
                    bpy.ops.object.modifier_apply(modifier=modifier.name)
                elif self.action == "apply_all_modifiers":
                    obj = context.active_object
                    if obj is None or not obj.modifiers:
                        raise RuntimeError("The active object has no modifiers")
                    while obj.modifiers:
                        bpy.ops.object.modifier_apply(modifier=obj.modifiers[0].name)
                elif self.action == "apply_selected_modifiers":
                    objects = [
                        obj for obj in context.selected_editable_objects
                        if obj.modifiers
                    ]
                    if not objects:
                        raise RuntimeError("Selected objects have no modifiers")
                    active_object = context.view_layer.objects.active
                    try:
                        for obj in objects:
                            context.view_layer.objects.active = obj
                            while obj.modifiers:
                                bpy.ops.object.modifier_apply(
                                    modifier=obj.modifiers[0].name
                                )
                    finally:
                        context.view_layer.objects.active = active_object
                elif self.action == "clear_constraints":
                    obj = context.active_object
                    if obj is None:
                        raise RuntimeError("Select an object first")
                    if obj.mode == 'POSE' and context.active_pose_bone is not None:
                        context.active_pose_bone.constraints.clear()
                    else:
                        obj.constraints.clear()
                elif self.action in {
                    "duplicate_keyframes",
                    "interpolation_constant",
                    "interpolation_linear",
                    "interpolation_bezier",
                }:
                    if area.type == 'GRAPH_EDITOR':
                        module = bpy.ops.graph
                    elif area.type == 'DOPESHEET_EDITOR':
                        module = bpy.ops.action
                    else:
                        raise RuntimeError("Open a Dope Sheet or Graph Editor first")
                    if self.action == "duplicate_keyframes":
                        module.duplicate_move('INVOKE_DEFAULT')
                    else:
                        interpolation = {
                            "interpolation_constant": 'CONSTANT',
                            "interpolation_linear": 'LINEAR',
                            "interpolation_bezier": 'BEZIER',
                        }[self.action]
                        module.interpolation_type(type=interpolation)
                elif self.action == "toggle_motion_paths":
                    obj = context.active_object
                    if obj is None:
                        raise RuntimeError("Select an object first")
                    if obj.motion_path is None:
                        bpy.ops.object.paths_calculate()
                    else:
                        bpy.ops.object.paths_clear(only_selected=False)
                elif self.action == "set_preview_range":
                    bpy.ops.anim.previewrange_set('INVOKE_DEFAULT')
                elif self.action == "multires_subdivide":
                    obj = context.active_object
                    modifier = next(
                        (
                            modifier for modifier in obj.modifiers
                            if modifier.type == 'MULTIRES'
                        ),
                        None,
                    ) if obj is not None else None
                    if modifier is None:
                        raise RuntimeError("Add a Multires modifier first")
                    bpy.ops.object.multires_subdivide(
                        modifier=modifier.name,
                        mode='CATMULL_CLARK',
                    )
                elif self.action == "incremental_save":
                    if not bpy.data.filepath:
                        bpy.ops.wm.save_as_mainfile('INVOKE_DEFAULT')
                    else:
                        bpy.ops.wm.save_mainfile(incremental=True)
                elif self.action == "render_selected":
                    selected = set(context.selected_objects)
                    if not selected:
                        raise RuntimeError("Select at least one object")
                    render_states = {
                        obj: obj.hide_render for obj in context.scene.objects
                    }
                    try:
                        for obj in context.scene.objects:
                            obj.hide_render = obj not in selected
                        bpy.ops.render.render()
                    finally:
                        for obj, hide_render in render_states.items():
                            obj.hide_render = hide_render
                elif self.action == "open_render_result":
                    image = bpy.data.images.get("Render Result")
                    if image is None:
                        raise RuntimeError("No Render Result is available")
                    area.type = 'IMAGE_EDITOR'
                    area.spaces.active.image = image
                elif self.action == "purge_orphans":
                    bpy.data.orphans_purge(do_recursive=True)
                elif self.action == "auto_key_toggle":
                    tool_settings = context.scene.tool_settings
                    tool_settings.use_keyframe_insert_auto = (
                        not tool_settings.use_keyframe_insert_auto
                    )
                elif self.action in invoke_operators:
                    idname, properties = invoke_operators[self.action]
                    module, name = idname.split(".", 1)
                    getattr(getattr(bpy.ops, module), name)(
                        'INVOKE_DEFAULT',
                        **properties,
                    )
                elif self.action.startswith("operator__"):
                    _prefix, module, name = self.action.split("__", 2)
                    getattr(getattr(bpy.ops, module), name)('INVOKE_DEFAULT')
                elif self.operator_id:
                    module, name = self.operator_id.split(".", 1)
                    getattr(getattr(bpy.ops, module), name)()
                else:
                    idname, properties = operators[self.action]
                    module, name = idname.split(".", 1)
                    getattr(getattr(bpy.ops, module), name)(**properties)
        except Exception as ex:
            self.report({'WARNING'}, str(ex))
            return {'CANCELLED'}
        return {'FINISHED'}


class TOPBAR_OT_maya_shelf_preview(Operator):
    bl_idname = "topbar.maya_shelf_preview"
    bl_label = "Icon Preview"
    bl_options = {'INTERNAL'}

    def execute(self, _context):
        return {'FINISHED'}


class WM_MT_button_context(Menu):
    bl_label = "Button Context Menu"

    def draw(self, context):
        _maya_shelf_config(context)
        button_operator = getattr(context, "button_operator", None)
        item_id = getattr(button_operator, "item_id", "") if button_operator else ""
        if item_id:
            tab = _maya_shelf_active_tab()
            item = next(
                (
                    item for item in tab["items"]
                    if item["id"] == item_id
                ),
                None,
            )
            separator = next(
                (
                    separator for separator in tab.setdefault("separators", [])
                    if separator["id"] == item_id
                ),
                None,
            )
            self.layout.separator()
            props = self.layout.operator(
                "topbar.maya_shelf_item_add",
                text="Add Shelf Icon",
                icon='ADD',
            )
            props.row = item.get("row", 0) if item else 0
            props = self.layout.operator(
                "topbar.maya_shelf_separator_add",
                text="Add Separator",
                icon='SPLIT_VERTICAL',
            )
            if item is not None:
                row_items = [
                    candidate for candidate in tab["items"]
                    if candidate.get("row", 0) == item.get("row", 0)
                ]
                props.column = row_items.index(item) + 1
                props.row = item.get("row", 0)
            elif separator is not None:
                props.column = separator.get("column", 0) + 1
                props.row = separator.get("row", 0)
            props = self.layout.operator(
                "topbar.maya_shelf_item_remove_id",
                text="Remove Separator" if separator is not None else "Remove from Shelf",
                icon='TRASH',
            )
            props.item_id = item_id


def _maya_shelf_row_data(tab, row_index):
    cache_key = (
        _maya_shelf_active_scope,
        id(tab),
        row_index,
        _maya_shelf_layout_revision,
    )
    cached = _maya_shelf_row_cache.get(cache_key)
    if cached is not None:
        return cached

    items = tuple(
        item
        for item in tab["items"]
        if item.get("row", 0) == row_index
    )
    separators_by_column = {}
    for separator in tab.setdefault("separators", []):
        if separator.get("row", 0) != row_index:
            continue
        column = max(separator.get("column", 0), 0)
        separators_by_column.setdefault(column, []).append(separator)
    separators_by_column = {
        column: tuple(separators)
        for column, separators in separators_by_column.items()
    }
    cached = (items, separators_by_column)
    _maya_shelf_row_cache[cache_key] = cached
    return cached


def _maya_shelf_draw_icon_row(layout, row_index, context):
    config = _maya_shelf_config(context)
    tab = _maya_shelf_active_tab()
    selected = config.get("selected", "")
    row = layout.row(align=True)
    row.alignment = 'LEFT'
    row.scale_x = 1.2
    row.scale_y = 1.0

    items, separators_by_column = _maya_shelf_row_data(tab, row_index)
    marker_index = None
    marker_after_end_separator = False
    if (
        _maya_shelf_drag_state is not None and
        _maya_shelf_drag_state.get("target_scope") == _maya_shelf_active_scope and
        _maya_shelf_drag_state["target_row"] == row_index
    ):
        marker_index = _maya_shelf_drag_state["target_index"]
        if marker_index > len(items):
            marker_after_end_separator = True
            marker_index = None
        else:
            marker_index = min(max(marker_index, 0), len(items))

    def draw_marker():
        marker = row.row(align=True)
        marker.ui_units_x = 0.55
        marker.label(text="", icon_value=_maya_shelf_marker_icon())

    def draw_separator(separator):
        divider = row.row(align=True)
        divider.ui_units_x = 0.55
        divider.context_string_set("maya_shelf_item_id", separator["id"])
        divider.context_string_set("maya_shelf_separator", "1")
        divider.context_string_set("maya_shelf_background_color", "0,0,0,0")
        divider.enabled = False
        props = divider.operator(
            "topbar.maya_shelf_action",
            text="|",
            emboss=False,
        )
        props.item_id = separator["id"]

    last_column = max(
        len(items),
        max(separators_by_column, default=-1),
        marker_index if marker_index is not None else -1,
    )
    for column in range(last_column + 1):
        if marker_index == column:
            draw_marker()
        for separator in separators_by_column.get(column, ()):
            draw_separator(separator)
        if marker_after_end_separator and column == len(items):
            draw_marker()
        if column < len(items):
            item = items[column]
            item_column = row.column(align=True)
            item_column.ui_units_x = 1.45
            item_column.context_string_set("maya_shelf_item_id", item["id"])
            icon_line = item_column.row(align=True)
            icon_line.alignment = 'CENTER'
            icon_line.scale_y = 0.82
            button = icon_line.row(align=True)
            button.ui_units_x = 0.85
            custom_icon = _maya_shelf_custom_icon(item.get("custom_icon", ""))
            background_color = item.get(
                "background_color",
                (0.18, 0.18, 0.18, 1.0),
            )
            icon_color = item.get("icon_color", (1.0, 1.0, 1.0, 1.0))
            is_drag_source = (
                _maya_shelf_drag_state is not None and
                _maya_shelf_drag_state.get("kind") == "icon" and
                _maya_shelf_drag_state.get("source_scope") == _maya_shelf_active_scope and
                _maya_shelf_drag_state.get("item_id") == item["id"]
            )
            if is_drag_source:
                background_color = (0.08, 0.32, 0.68, 1.0)
            button.context_string_set(
                "maya_shelf_drag_source",
                "1" if is_drag_source else "0",
            )
            if custom_icon:
                icon_color = (1.0, 1.0, 1.0, icon_color[3])
            button.context_string_set(
                "maya_shelf_background_color",
                ",".join(f"{component:.6f}" for component in background_color),
            )
            button.context_string_set(
                "maya_shelf_icon_color",
                ",".join(f"{component:.6f}" for component in icon_color),
            )
            operator_args = {
                "text": "",
                "emboss": True,
                "depress": item["id"] == selected,
            }
            if custom_icon:
                operator_args["icon_value"] = custom_icon
            else:
                operator_args["icon"] = item["icon"]
            props = button.operator("topbar.maya_shelf_action", **operator_args)
            props.action = item.get("action", "")
            props.operator_id = item.get("operator", "")
            props.item_id = item["id"]
            props.tooltip = item.get("label", "Shelf Command")
            label_line = item_column.row(align=True)
            label_line.alignment = 'CENTER'
            label_line.scale_y = 0.68
            label_line.label(text=item.get("short_text", ""))
        elif column < last_column:
            placeholder = row.row(align=True)
            placeholder.ui_units_x = _MAYA_SHELF_SLOT_WIDTH / 20.0
            placeholder.label(text="")
        elif separators_by_column.get(column):
            tail = row.row(align=True)
            tail.ui_units_x = 0.2
            tail.label(text="")


class TOPBAR_HT_maya_shelf_upper(Header):
    bl_space_type = 'TOPBAR'
    bl_region_type = 'FOOTER'

    def draw(self, context):
        _maya_shelf_draw_icon_row(self.layout, 0, context)


class TOPBAR_HT_maya_shelf_lower(Header):
    bl_space_type = 'TOPBAR'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        _maya_shelf_draw_icon_row(self.layout, 1, context)


def _maya_shelf_adaptive_entries(tab):
    entries = []
    for row_index in (0, 1):
        items = [
            item
            for item in tab["items"]
            if item.get("row", 0) == row_index
        ]
        separators_by_column = {}
        for separator in tab.setdefault("separators", []):
            if separator.get("row", 0) != row_index:
                continue
            column = max(separator.get("column", 0), 0)
            separators_by_column.setdefault(column, []).append(separator)

        last_column = max(len(items), max(separators_by_column, default=-1))
        for column in range(last_column + 1):
            for separator in separators_by_column.get(column, ()):
                entries.append(("SEPARATOR", separator))
            if column < len(items):
                entries.append(("ITEM", items[column]))
    return entries


def _maya_shelf_draw_adaptive(layout, context):
    config = _maya_shelf_config(context)
    tab = _maya_shelf_active_tab()
    selected = config.get("selected", "")
    flow = layout.grid_flow(
        row_major=True,
        columns=0,
        even_columns=True,
        even_rows=True,
        align=True,
    )
    flow.scale_x = 1.05
    flow.scale_y = 1.0

    entries = _maya_shelf_adaptive_entries(tab)
    if (
        _maya_shelf_drag_state is not None and
        _maya_shelf_drag_state.get("target_scope") == _maya_shelf_active_scope and
        _maya_shelf_drag_state.get("adaptive")
    ):
        marker_index = _maya_shelf_drag_state["target_index"]
        entries.insert(min(max(marker_index, 0), len(entries)), ("MARKER", None))

    for entry_type, entry in entries:
        cell = flow.column(align=True)
        cell.ui_units_x = 1.55
        if entry_type == "MARKER":
            marker = cell.row(align=True)
            marker.alignment = 'CENTER'
            marker.scale_y = 1.6
            marker.label(text="", icon_value=_maya_shelf_marker_icon())
            continue

        cell.context_string_set("maya_shelf_item_id", entry["id"])

        if entry_type == "SEPARATOR":
            divider = cell.row(align=True)
            divider.alignment = 'CENTER'
            divider.scale_y = 1.6
            divider.context_string_set("maya_shelf_separator", "1")
            divider.context_string_set("maya_shelf_background_color", "0,0,0,0")
            props = divider.operator(
                "topbar.maya_shelf_action",
                text="|",
                emboss=False,
            )
            props.item_id = entry["id"]
            continue

        icon_line = cell.row(align=True)
        icon_line.alignment = 'CENTER'
        icon_line.scale_y = 0.9
        button = icon_line.row(align=True)
        button.ui_units_x = 0.95
        custom_icon = _maya_shelf_custom_icon(entry.get("custom_icon", ""))
        background_color = entry.get(
            "background_color",
            (0.18, 0.18, 0.18, 1.0),
        )
        icon_color = entry.get("icon_color", (1.0, 1.0, 1.0, 1.0))
        is_drag_source = (
            _maya_shelf_drag_state is not None and
            _maya_shelf_drag_state.get("kind") == "icon" and
            _maya_shelf_drag_state.get("source_scope") == _maya_shelf_active_scope and
            _maya_shelf_drag_state.get("item_id") == entry["id"]
        )
        if is_drag_source:
            background_color = (0.08, 0.32, 0.68, 1.0)
        button.context_string_set(
            "maya_shelf_drag_source",
            "1" if is_drag_source else "0",
        )
        if custom_icon:
            icon_color = (1.0, 1.0, 1.0, icon_color[3])
        button.context_string_set(
            "maya_shelf_background_color",
            ",".join(f"{component:.6f}" for component in background_color),
        )
        button.context_string_set(
            "maya_shelf_icon_color",
            ",".join(f"{component:.6f}" for component in icon_color),
        )
        operator_args = {
            "text": "",
            "emboss": True,
            "depress": entry["id"] == selected,
        }
        if custom_icon:
            operator_args["icon_value"] = custom_icon
        else:
            operator_args["icon"] = entry["icon"]
        props = button.operator("topbar.maya_shelf_action", **operator_args)
        props.action = entry.get("action", "")
        props.operator_id = entry.get("operator", "")
        props.item_id = entry["id"]
        props.tooltip = entry.get("label", "Shelf Command")

        label_line = cell.row(align=True)
        label_line.alignment = 'CENTER'
        label_line.scale_y = 0.7
        label_line.label(text=entry.get("short_text", ""))


class SHELF_MT_tabs(Menu):
    bl_label = "Shelf Tabs"

    def draw(self, context):
        layout = self.layout
        config = _maya_shelf_config(context)
        active_tab = _maya_shelf_active_tab()
        for tab in config["tabs"]:
            props = layout.operator(
                "topbar.maya_shelf_tab",
                text=tab["name"],
                icon='CHECKMARK' if tab is active_tab else 'BLANK1',
            )
            props.tab = tab["name"]
        layout.separator()
        layout.operator("topbar.maya_shelf_tab_add", text="Add Shelf Tab", icon='ADD')
        layout.operator(
            "topbar.maya_shelf_tab_rename",
            text="Rename Active Tab",
            icon='GREASEPENCIL',
        )
        layout.operator("topbar.maya_shelf_tab_remove", text="Remove Active Tab", icon='X')


class SHELF_HT_header(Header):
    bl_space_type = 'SHELF'

    def draw(self, context):
        layout = self.layout
        layout.template_header()
        layout.menu("SHELF_MT_tabs", text=_maya_shelf_active_tab(context)["name"])


class SHELF_PT_main(Panel):
    bl_space_type = 'SHELF'
    bl_region_type = 'WINDOW'
    bl_label = "Shelf"
    bl_options = {'HIDE_HEADER'}

    def draw(self, context):
        _maya_shelf_draw_adaptive(self.layout, context)


class TOPBAR_PT_tool_settings_extra(Panel):
    """
    Popover panel for adding extra options that don't fit in the tool settings header
    """
    bl_idname = "TOPBAR_PT_tool_settings_extra"
    bl_region_type = 'HEADER'
    bl_space_type = 'TOPBAR'
    bl_label = "Extra Options"
    bl_description = "Extra options"

    def draw(self, context):
        from bl_ui.space_toolsystem_common import ToolSelectPanelHelper
        layout = self.layout

        # Get the active tool
        space_type, mode = ToolSelectPanelHelper._tool_key_from_context(context)
        cls = ToolSelectPanelHelper._tool_class_from_space_type(space_type)
        item, tool, _ = cls._tool_get_active(context, space_type, mode, with_icon=True)
        if item is None:
            return

        # Draw the extra settings
        item.draw_settings(context, layout, tool, extra=True)


class TOPBAR_PT_tool_fallback(Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'HEADER'
    bl_label = "Layers"
    bl_ui_units_x = 8

    def draw(self, context):
        from bl_ui.space_toolsystem_common import ToolSelectPanelHelper
        layout = self.layout

        tool_settings = context.tool_settings
        ToolSelectPanelHelper.draw_fallback_tool_items(layout, context)
        if tool_settings.workspace_tool_type == 'FALLBACK':
            tool = context.tool
            ToolSelectPanelHelper.draw_active_tool_fallback(context, layout, tool)


class TOPBAR_MT_editor_menus(Menu):
    bl_idname = "TOPBAR_MT_editor_menus"
    bl_label = ""

    def draw(self, context):
        layout = self.layout

        # Allow calling this menu directly (this might not be a header area).
        if getattr(context.area, "show_menus", False):
            layout.menu("TOPBAR_MT_blender", text="", icon='BLENDER')
        else:
            layout.menu("TOPBAR_MT_blender", text="Maya 2.0")

        layout.menu("TOPBAR_MT_file")
        layout.menu("TOPBAR_MT_edit")

        layout.menu("TOPBAR_MT_render")

        layout.menu("TOPBAR_MT_window")
        layout.menu("TOPBAR_MT_help")


class TOPBAR_MT_blender(Menu):
    bl_label = "Maya 2.0"

    def draw(self, _context):
        layout = self.layout

        layout.operator("wm.splash")
        layout.operator("wm.splash_about")

        layout.separator()

        layout.operator("preferences.app_template_install", text="Install Application Template...")

        layout.separator()

        layout.menu("TOPBAR_MT_blender_system")


class TOPBAR_MT_file_cleanup(Menu):
    bl_label = "Clean Up"

    def draw(self, _context):
        layout = self.layout
        layout.separator()

        layout.operator("outliner.orphans_purge", text="Purge Unused Data...")
        layout.operator("outliner.orphans_manage", text="Manage Unused Data...")


class TOPBAR_MT_file(Menu):
    bl_label = "File"

    def draw(self, context):
        layout = self.layout

        layout.operator_context = 'INVOKE_AREA'
        layout.menu("TOPBAR_MT_file_new", text="New", text_ctxt=i18n_contexts.id_windowmanager, icon='FILE_NEW')
        layout.operator("wm.open_mainfile", text="Open...", icon='FILE_FOLDER')
        layout.menu("TOPBAR_MT_file_open_recent")
        layout.operator("wm.revert_mainfile")
        layout.menu("TOPBAR_MT_file_recover")

        layout.separator()

        layout.operator_context = 'EXEC_AREA' if context.blend_data.is_saved else 'INVOKE_AREA'
        layout.operator("wm.save_mainfile", text="Save", icon='FILE_TICK').show_save_modified_images_dialog = True

        layout.operator_context = 'INVOKE_AREA'
        layout.operator("wm.save_as_mainfile", text="Save As...").show_save_modified_images_dialog = True
        layout.operator_context = 'INVOKE_AREA'
        save_copy = layout.operator("wm.save_as_mainfile", text="Save Copy...")
        save_copy.copy = True
        save_copy.show_save_modified_images_dialog = True

        sub = layout.row()
        sub.enabled = context.blend_data.is_saved
        sub.operator_context = 'EXEC_AREA'
        save_incremental = sub.operator("wm.save_mainfile", text="Save Incremental")
        save_incremental.incremental = True
        save_incremental.show_save_modified_images_dialog = True

        layout.separator()

        layout.operator_context = 'INVOKE_AREA'
        layout.operator("wm.link", text="Link...", icon='LINK_BLEND')
        layout.operator("wm.append", text="Append...", icon='APPEND_BLEND')
        layout.menu("TOPBAR_MT_file_previews")

        layout.separator()

        layout.menu("TOPBAR_MT_file_import", icon='IMPORT')
        layout.menu("TOPBAR_MT_file_export", icon='EXPORT')
        row = layout.row()
        row.operator("wm.collection_export_all")
        row.enabled = context.view_layer.has_export_collections

        layout.separator()

        layout.menu("TOPBAR_MT_file_external_data")
        layout.menu("TOPBAR_MT_file_cleanup")

        layout.separator()

        layout.menu("TOPBAR_MT_file_defaults")

        layout.separator()

        layout.operator("wm.quit_blender", text="Quit", icon='QUIT')


class TOPBAR_MT_file_new(Menu):
    bl_label = "New File"

    @staticmethod
    def app_template_paths():
        import os

        template_paths = bpy.utils.app_template_paths()

        # Expand template paths.

        # Use a set to avoid duplicate user/system templates.
        # This is a corner case, but users managed to do it! #76849.
        app_templates = set()
        for path in template_paths:
            for d in os.listdir(path):
                if d.startswith(("__", ".")):
                    continue
                template = os.path.join(path, d)
                if os.path.isdir(template):
                    app_templates.add(d)

        return sorted(app_templates)

    @staticmethod
    def draw_ex(layout, _context, *, use_splash=False, use_more=False):
        layout.operator_context = 'INVOKE_DEFAULT'

        # Limit number of templates in splash screen, spill over into more menu.
        paths = TOPBAR_MT_file_new.app_template_paths()
        splash_limit = 6

        if use_splash:
            show_more = len(paths) > (splash_limit - 1)
            if show_more:
                paths = paths[:splash_limit - 2]
        elif use_more:
            paths = paths[splash_limit - 2:]
            show_more = False
        else:
            show_more = False

        # Draw application templates.
        if not use_more:
            props = layout.operator("wm.read_homefile", text="General", icon='FILE_NEW')
            props.app_template = ""

        for d in paths:
            icon = 'FILE_NEW'
            # Set icon per template.
            if d == "2D_Animation":
                icon = 'GREASEPENCIL_LAYER_GROUP'
            elif d == "Sculpting":
                icon = 'SCULPTMODE_HLT'
            elif d == "Storyboarding":
                icon = 'GREASEPENCIL'
            elif d == "VFX":
                icon = 'TRACKER'
            elif d == "Video_Editing":
                icon = 'SEQUENCE'
            props = layout.operator("wm.read_homefile", text=bpy.path.display_name(iface_(d)), icon=icon)
            props.app_template = d

        layout.operator_context = 'EXEC_DEFAULT'

        if show_more:
            layout.menu("TOPBAR_MT_templates_more", text="More...")

    def draw(self, context):
        TOPBAR_MT_file_new.draw_ex(self.layout, context)


class TOPBAR_MT_file_recover(Menu):
    bl_label = "Recover"

    def draw(self, _context):
        layout = self.layout

        layout.operator("wm.recover_last_session", text="Last Session")
        layout.operator("wm.recover_auto_save", text="Auto Save...")


class TOPBAR_MT_file_defaults(Menu):
    bl_label = "Defaults"

    def draw(self, context):
        layout = self.layout
        prefs = context.preferences

        layout.operator_context = 'INVOKE_AREA'

        if any(bpy.utils.app_template_paths()):
            app_template = prefs.app_template
        else:
            app_template = None

        if app_template:
            layout.label(
                text=iface_(bpy.path.display_name(app_template, has_ext=False), i18n_contexts.id_workspace),
                translate=False,
            )

        layout.operator("wm.save_homefile")
        if app_template:
            display_name = bpy.path.display_name(iface_(app_template))
            props = layout.operator("wm.read_factory_settings", text="Load Factory Blender Settings")
            props.app_template = app_template
            props = layout.operator(
                "wm.read_factory_settings",
                text=iface_("Load Factory {:s} Settings", i18n_contexts.operator_default).format(display_name),
                translate=False,
            )
            props.app_template = app_template
            props.use_factory_startup_app_template_only = True
            del display_name
        else:
            layout.operator("wm.read_factory_settings")


# Include technical operators here which would otherwise have no way for users to access.
class TOPBAR_MT_blender_system(Menu):
    bl_label = "System"

    def draw(self, _context):
        layout = self.layout

        layout.operator("script.reload")

        layout.separator()

        layout.operator("wm.memory_statistics")
        layout.operator("wm.debug_menu")
        layout.operator_menu_enum("wm.redraw_timer", "type")

        layout.separator()

        layout.operator("screen.spacedata_cleanup")
        layout.operator("wm.operator_presets_cleanup")


class TOPBAR_MT_templates_more(Menu):
    bl_label = "Templates"

    def draw(self, context):
        bpy.types.TOPBAR_MT_file_new.draw_ex(self.layout, context, use_more=True)


class TOPBAR_MT_file_import(Menu):
    bl_idname = "TOPBAR_MT_file_import"
    bl_label = "Import"
    bl_owner_use_filter = False

    def draw(self, _context):
        if bpy.app.build_options.alembic:
            self.layout.operator("wm.alembic_import", text="Alembic (.abc)")
        if bpy.app.build_options.usd:
            self.layout.operator(
                "wm.usd_import", text="Universal Scene Description (.usd*)")

        if bpy.app.build_options.io_gpencil:
            self.layout.operator("wm.grease_pencil_import_svg", text="SVG as Grease Pencil")

        if bpy.app.build_options.io_wavefront_obj:
            self.layout.operator("wm.obj_import", text="Wavefront (.obj)")
        if bpy.app.build_options.io_ply:
            self.layout.operator("wm.ply_import", text="Stanford PLY (.ply)")
        if bpy.app.build_options.io_stl:
            self.layout.operator("wm.stl_import", text="STL (.stl)")

        if bpy.app.build_options.io_fbx:
            self.layout.operator("wm.fbx_import", text="FBX (.fbx)")


class TOPBAR_MT_file_export(Menu):
    bl_idname = "TOPBAR_MT_file_export"
    bl_label = "Export"
    bl_owner_use_filter = False

    def draw(self, _context):
        if bpy.app.build_options.alembic:
            self.layout.operator("wm.alembic_export", text="Alembic (.abc)")
        if bpy.app.build_options.usd:
            self.layout.operator(
                "wm.usd_export", text="Universal Scene Description (.usd*)")

        if bpy.app.build_options.io_gpencil:
            # PUGIXML library dependency.
            if bpy.app.build_options.pugixml:
                self.layout.operator("wm.grease_pencil_export_svg", text="Grease Pencil as SVG")
            # HARU library dependency.
            if bpy.app.build_options.haru:
                self.layout.operator("wm.grease_pencil_export_pdf", text="Grease Pencil as PDF")

        if bpy.app.build_options.io_wavefront_obj:
            self.layout.operator("wm.obj_export", text="Wavefront (.obj)")
        if bpy.app.build_options.io_ply:
            self.layout.operator("wm.ply_export", text="Stanford PLY (.ply)")
        if bpy.app.build_options.io_stl:
            self.layout.operator("wm.stl_export", text="STL (.stl)")


class TOPBAR_MT_file_external_data(Menu):
    bl_label = "External Data"

    def draw(self, _context):
        layout = self.layout

        icon = 'CHECKBOX_HLT' if bpy.data.use_autopack else 'CHECKBOX_DEHLT'
        layout.operator("file.autopack_toggle", icon=icon)

        pack_all = layout.row()
        pack_all.operator("file.pack_all")
        pack_all.active = not bpy.data.use_autopack

        unpack_all = layout.row()
        unpack_all.operator("file.unpack_all")
        unpack_all.active = not bpy.data.use_autopack

        layout.separator()

        layout.operator("file.pack_libraries")
        layout.operator("file.unpack_libraries")

        layout.separator()

        layout.operator("file.make_paths_relative")
        layout.operator("file.make_paths_absolute")

        layout.separator()

        layout.operator("file.report_missing_files")
        layout.operator("file.find_missing_files", text="Find Missing Files...")


class TOPBAR_MT_file_previews(Menu):
    bl_label = "Data Previews"

    def draw(self, _context):
        layout = self.layout

        layout.operator("wm.previews_ensure")
        layout.operator("wm.previews_batch_generate", text="Batch-Generate Previews...")

        layout.separator()

        layout.operator("wm.previews_clear", text="Clear Data-Block Previews...")
        layout.operator("wm.previews_batch_clear", text="Batch-Clear Previews...")


class TOPBAR_MT_render(Menu):
    bl_label = "Render"

    def draw(self, context):
        layout = self.layout

        rd = context.scene.render
        scene = context.scene
        seq_scene = context.sequencer_scene
        strips = getattr(context, "strips", ())

        can_render_seq = seq_scene and seq_scene.render.use_sequencer and strips

        layout.operator("render.render", text="Render Image", icon='RENDER_STILL').use_viewport = True
        props = layout.operator("render.render", text="Render Animation", icon='RENDER_ANIMATION')
        props.animation = True
        props.use_viewport = True

        layout.separator()

        if can_render_seq and (seq_scene != scene):
            props = layout.operator("render.render", text="Render Sequencer Image", icon='RENDER_STILL')
            props.use_viewport = True
            props.use_sequencer_scene = True

            props = layout.operator("render.render", text="Render Sequencer Animation", icon='RENDER_ANIMATION')
            props.animation = True
            props.use_viewport = True
            props.use_sequencer_scene = True

            layout.separator()

        layout.operator("sound.mixdown", text="Render Audio...")

        layout.separator()

        layout.operator("render.view_show", text="View Render")
        layout.operator("render.play_rendered_anim", text="View Animation")

        layout.separator()

        layout.prop(rd, "use_lock_interface", text="Lock Interface")


class TOPBAR_MT_edit(Menu):
    bl_label = "Edit"

    def draw(self, context):
        layout = self.layout

        show_developer = context.preferences.view.show_developer_ui

        layout.operator("ed.undo", icon='LOOP_BACK')
        layout.operator("ed.redo", icon='LOOP_FORWARDS')
        layout.menu("TOPBAR_MT_undo_history")

        layout.separator()

        layout.operator("screen.redo_last", text="Adjust Last Operation...")
        layout.operator("screen.repeat_last")
        layout.operator("screen.repeat_history", text="Repeat History...")

        layout.separator()

        layout.operator("wm.search_menu", text="Menu Search...", icon='VIEWZOOM')
        if show_developer:
            layout.operator("wm.search_operator", text="Operator Search...")

        layout.separator()

        # Mainly to expose shortcut since this depends on the context.
        props = layout.operator("wm.call_panel", text="Rename Active Item...")
        props.name = "TOPBAR_PT_name"
        props.keep_open = False

        layout.operator("wm.batch_rename", text="Batch Rename...")

        layout.separator()

        # Should move elsewhere (impacts outliner & 3D view).
        tool_settings = context.tool_settings
        layout.prop(tool_settings, "lock_object_mode")

        layout.separator()

        layout.operator("screen.userpref_show", text="Preferences...", icon='PREFERENCES')


class TOPBAR_MT_window(Menu):
    bl_label = "Window"

    def draw(self, context):
        import sys
        from _bl_ui_utils.layout import operator_context

        layout = self.layout

        layout.operator("wm.window_new")
        layout.operator("wm.window_new_main")

        layout.separator()

        layout.operator("wm.window_fullscreen_toggle", icon='FULLSCREEN_ENTER')

        layout.separator()

        layout.operator("screen.workspace_cycle", text="Next Workspace").direction = 'NEXT'
        layout.operator("screen.workspace_cycle", text="Previous Workspace").direction = 'PREV'

        layout.separator()

        layout.prop(context.screen, "show_statusbar")

        layout.separator()

        layout.operator("screen.screenshot", text="Save Screenshot...")

        # Showing the status in the area doesn't work well in this case.
        # - From the top-bar, the text replaces the file-menu (not so bad but strange).
        # - From menu-search it replaces the area that the user may want to screen-shot.
        # Setting the context to screen causes the status to show in the global status-bar.
        with operator_context(layout, 'INVOKE_SCREEN'):
            layout.operator("screen.screenshot_area", text="Save Screenshot (Editor)...")

        if sys.platform[:3] == "win":
            layout.separator()
            layout.operator("wm.console_toggle", icon='CONSOLE')

        if context.scene.render.use_multiview:
            layout.separator()
            layout.operator("wm.set_stereo_3d")


class TOPBAR_MT_help(Menu):
    bl_label = "Help"

    def draw(self, context):
        layout = self.layout

        show_developer = context.preferences.view.show_developer_ui

        layout.operator("wm.url_open_preset", text="Manual", icon='URL').type = 'MANUAL'
        layout.operator("wm.url_open", text="Support").url = "https://www.blender.org/support"
        layout.operator("wm.url_open", text="User Communities").url = "https://www.blender.org/community/"
        layout.operator("wm.url_open", text="Get Involved").url = "https://www.blender.org/get-involved/"
        layout.operator("wm.url_open_preset", text="Release Notes").type = 'RELEASE_NOTES'

        layout.separator()

        if show_developer:
            layout.operator(
                "wm.url_open",
                text="Developer Documentation",
                icon='URL',
            ).url = "https://developer.blender.org/docs/"
            layout.operator("wm.url_open", text="Developer Community").url = "https://devtalk.blender.org"
            layout.operator("wm.url_open_preset", text="Python API Reference").type = 'API'
            layout.operator("wm.operator_cheat_sheet", icon='TEXT')

        layout.separator()

        layout.operator("wm.url_open_preset", text="Report a Bug", icon='URL').type = 'BUG'
        layout.operator("wm.sysinfo")


class TOPBAR_MT_file_context_menu(Menu):
    bl_label = "File"

    def draw(self, _context):
        layout = self.layout

        layout.operator_context = 'INVOKE_AREA'
        layout.menu("TOPBAR_MT_file_new", text="New", text_ctxt=i18n_contexts.id_windowmanager, icon='FILE_NEW')
        layout.operator("wm.open_mainfile", text="Open...", icon='FILE_FOLDER')
        layout.menu("TOPBAR_MT_file_open_recent")

        layout.separator()

        layout.operator("wm.link", text="Link...", icon='LINK_BLEND')
        layout.operator("wm.append", text="Append...", icon='APPEND_BLEND')

        layout.separator()

        layout.menu("TOPBAR_MT_file_import", icon='IMPORT')
        layout.menu("TOPBAR_MT_file_export", icon='EXPORT')

        layout.separator()

        layout.operator("screen.userpref_show", text="Preferences...", icon='PREFERENCES')


class TOPBAR_MT_workspace_menu(Menu):
    bl_label = "Workspace"

    def draw(self, _context):
        layout = self.layout

        layout.operator("workspace.duplicate", text="Duplicate", icon='DUPLICATE')
        if len(bpy.data.workspaces) <= 1:
            return

        layout.operator("workspace.delete", text="Delete", icon='REMOVE')

        layout.separator()

        layout.operator("workspace.reorder_to_front", text="Reorder to Front", icon='TRIA_LEFT_BAR')
        layout.operator("workspace.reorder_to_back", text="Reorder to Back", icon='TRIA_RIGHT_BAR')

        layout.separator()

        # For key binding discoverability.
        props = layout.operator("screen.workspace_cycle", text="Previous Workspace")
        props.direction = 'PREV'
        props = layout.operator("screen.workspace_cycle", text="Next Workspace")
        props.direction = 'NEXT'

        layout.separator()

        layout.operator("workspace.delete_all_others")


# Grease Pencil Object - Primitive curve
class TOPBAR_PT_gpencil_primitive(Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'HEADER'
    bl_label = "Primitives"

    def draw(self, context):
        settings = context.tool_settings.gpencil_sculpt

        layout = self.layout
        # Curve
        layout.template_curve_mapping(settings, "thickness_primitive_curve", brush=True)


# Only a popover
class TOPBAR_PT_name(Panel):
    bl_space_type = 'TOPBAR'  # dummy
    bl_region_type = 'HEADER'
    bl_label = "Rename Active Item"
    bl_ui_units_x = 14

    def draw(self, context):
        layout = self.layout

        # Edit first editable button in popup
        def row_with_icon(layout, icon):
            row = layout.row()
            row.activate_init = True
            row.label(icon=icon)
            return row

        mode = context.mode
        space = context.space_data
        space_type = None if (space is None) else space.type
        found = False
        if space_type == 'SEQUENCE_EDITOR':
            layout.label(text="Sequence Strip Name")
            item = context.active_strip
            if item:
                row = row_with_icon(layout, 'SEQUENCE')
                row.prop(item, "name", text="")
                found = True
        elif space_type == 'NODE_EDITOR':
            layout.label(text="Node Label")
            item = context.active_node
            if item:
                row = row_with_icon(layout, 'NODE')
                row.prop(item, "label", text="")
                found = True
        elif space_type == 'NLA_EDITOR':
            layout.label(text="NLA Strip Name")
            item = next(
                (strip for strip in context.selected_nla_strips if strip.active), None)
            if item:
                row = row_with_icon(layout, 'NLA')
                row.prop(item, "name", text="")
                found = True
        else:
            if mode == 'POSE' or (mode == 'WEIGHT_PAINT' and context.pose_object):
                layout.label(text="Bone Name")
                item = context.active_pose_bone
                if item:
                    row = row_with_icon(layout, 'BONE_DATA')
                    row.prop(item, "name", text="")
                    found = True
            elif mode == 'EDIT_ARMATURE':
                layout.label(text="Bone Name")
                item = context.active_bone
                if item:
                    row = row_with_icon(layout, 'BONE_DATA')
                    row.prop(item, "name", text="")
                    found = True
            else:
                layout.label(text="Object Name")
                item = context.object
                if item:
                    row = row_with_icon(layout, 'OBJECT_DATA')
                    row.prop(item, "name", text="")
                    found = True

        if not found:
            row = row_with_icon(layout, 'ERROR')
            row.label(text="No active item")


class TOPBAR_PT_name_marker(Panel):
    bl_space_type = 'TOPBAR'  # dummy
    bl_region_type = 'HEADER'
    bl_label = "Rename Marker"
    bl_ui_units_x = 14

    @staticmethod
    def is_using_pose_markers(context):
        sd = context.space_data
        return (
            sd.type == 'DOPESHEET_EDITOR' and sd.mode in {'ACTION', 'SHAPEKEY'} and
            sd.show_pose_markers and context.active_action
        )

    @staticmethod
    def is_using_sequencer(context):
        sd = context.space_data
        return sd.type == 'SEQUENCE_EDITOR'

    @staticmethod
    def get_selected_marker(context):
        if TOPBAR_PT_name_marker.is_using_pose_markers(context):
            markers = context.active_action.pose_markers
        elif TOPBAR_PT_name_marker.is_using_sequencer(context):
            markers = context.sequencer_scene.timeline_markers
        else:
            markers = context.scene.timeline_markers

        for marker in markers:
            if marker.select:
                return marker
        return None

    @staticmethod
    def row_with_icon(layout, icon):
        row = layout.row()
        row.activate_init = True
        row.label(icon=icon)
        return row

    def draw(self, context):
        layout = self.layout

        layout.label(text="Marker Name")

        scene = context.scene
        if scene.tool_settings.lock_markers:
            row = self.row_with_icon(layout, 'ERROR')
            label = "Markers are locked"
            row.label(text=label)
            return

        marker = self.get_selected_marker(context)
        if marker is None:
            row = self.row_with_icon(layout, 'ERROR')
            row.label(text="No active marker")
            return

        icon = 'TIME'
        if marker.camera is not None:
            icon = 'CAMERA_DATA'
        elif self.is_using_pose_markers(context):
            icon = 'ARMATURE_DATA'
        row = self.row_with_icon(layout, icon)
        row.prop(marker, "name", text="")


class TOPBAR_PT_grease_pencil_layers(Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'HEADER'
    bl_label = "Layers"
    bl_ui_units_x = 14

    @classmethod
    def poll(cls, context):
        object = context.object
        if object is None:
            return False
        if object.type != 'GREASEPENCIL':
            return False

        return True

    def draw(self, context):
        from .properties_data_grease_pencil import DATA_PT_grease_pencil_layers

        layout = self.layout
        grease_pencil = context.object.data

        DATA_PT_grease_pencil_layers.draw_settings(layout, grease_pencil)


classes = (
    TOPBAR_PG_maya_shelf_icon,
    TOPBAR_PG_maya_shelf_action,
    TOPBAR_UL_maya_shelf_icons,
    TOPBAR_UL_maya_shelf_actions,
    TOPBAR_HT_upper_bar,
    TOPBAR_OT_maya_shelf_tab,
    TOPBAR_OT_maya_shelf_tab_add,
    TOPBAR_OT_maya_shelf_tab_rename,
    TOPBAR_OT_maya_shelf_tab_remove,
    TOPBAR_OT_maya_shelf_item_add,
    TOPBAR_OT_maya_shelf_item_edit,
    TOPBAR_OT_maya_shelf_item_remove_id,
    TOPBAR_OT_maya_shelf_separator_add,
    TOPBAR_OT_maya_shelf_context_menu,
    TOPBAR_OT_maya_shelf_drag,
    TOPBAR_OT_maya_shelf_action,
    TOPBAR_OT_maya_shelf_preview,
    WM_MT_button_context,
    TOPBAR_HT_maya_shelf_upper,
    TOPBAR_HT_maya_shelf_lower,
    SHELF_MT_tabs,
    SHELF_HT_header,
    SHELF_PT_main,
    TOPBAR_MT_file_context_menu,
    TOPBAR_MT_workspace_menu,
    TOPBAR_MT_editor_menus,
    TOPBAR_MT_blender,
    TOPBAR_MT_blender_system,
    TOPBAR_MT_file,
    TOPBAR_MT_file_new,
    TOPBAR_MT_file_recover,
    TOPBAR_MT_file_defaults,
    TOPBAR_MT_templates_more,
    TOPBAR_MT_file_import,
    TOPBAR_MT_file_export,
    TOPBAR_MT_file_external_data,
    TOPBAR_MT_file_cleanup,
    TOPBAR_MT_file_previews,
    TOPBAR_MT_edit,
    TOPBAR_MT_render,
    TOPBAR_MT_window,
    TOPBAR_MT_help,
    TOPBAR_PT_tool_fallback,
    TOPBAR_PT_tool_settings_extra,
    TOPBAR_PT_gpencil_primitive,
    TOPBAR_PT_name,
    TOPBAR_PT_name_marker,
    TOPBAR_PT_grease_pencil_layers,
)

if __name__ == "__main__":  # only for live edit.
    from bpy.utils import register_class
    for cls in classes:
        register_class(cls)
