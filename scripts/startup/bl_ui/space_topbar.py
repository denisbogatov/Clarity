# SPDX-FileCopyrightText: 2009-2023 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

import bpy
import copy
import json
import math
import os
import sys
import tempfile
import time
import tokenize
import traceback
import uuid
from bpy.props import (
    BoolProperty,
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


_CLARITY_SHELF_TABS = (
    "Modeling",
    "Custom",
)

_CLARITY_SHELF_LEGACY_TABS = {
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

_CLARITY_SHELF_ITEMS = {
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

_CLARITY_SHELF_ITEMS["Surfaces"] = _CLARITY_SHELF_ITEMS["Curves"]
_CLARITY_SHELF_ITEMS["Motion Graphics"] = _CLARITY_SHELF_ITEMS["Animation"]
_CLARITY_SHELF_ITEMS["XGen"] = _CLARITY_SHELF_ITEMS["FX"]
_CLARITY_SHELF_ITEMS["Arnold"] = _CLARITY_SHELF_ITEMS["Rendering"]

_CLARITY_SHELF_EXTRA_ACTIONS = (
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

_CLARITY_SHELF_DISCOVERED_OPERATOR_MODULES = (
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


def _clarity_shelf_operator_icon(module_name, operator_name):
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


def _clarity_shelf_discovered_action_items():
    items = []
    for module_name in _CLARITY_SHELF_DISCOVERED_OPERATOR_MODULES:
        module = getattr(bpy.ops, module_name)
        for operator_name in dir(module):
            if operator_name.startswith("_"):
                continue
            operator = getattr(module, operator_name)
            try:
                rna_type = operator.get_rna_type()
            except (AttributeError, KeyError, RuntimeError, TypeError):
                continue
            action = f"operator__{module_name}__{operator_name}"
            category = module_name.replace("_", " ").title()
            label = f"{category} (All): {rna_type.name}"
            icon = _clarity_shelf_operator_icon(module_name, operator_name)
            items.append((action, label, icon))
    return tuple(items)


# Walking every `bpy.ops` module and the whole icon enum costs far more than the
# shelf needs at startup: the catalogs are only read when an Add/Edit dialog is
# open. Build them on first use and keep the result here instead.
_clarity_shelf_catalog_cache = {}


def _clarity_shelf_refresh_action_catalog():
    """Invalidate discovered actions after add-ons register or remove operators."""
    signature = tuple(
        (
            module_name,
            tuple(
                name for name in dir(getattr(bpy.ops, module_name))
                if not name.startswith("_")
            ),
        )
        for module_name in _CLARITY_SHELF_DISCOVERED_OPERATOR_MODULES
    )
    if _clarity_shelf_catalog_cache.get("operator_signature") == signature:
        return
    for key in tuple(_clarity_shelf_catalog_cache):
        if key in {"actions", "action_labels", "action_icons", "action_rows"}:
            del _clarity_shelf_catalog_cache[key]
        elif isinstance(key, tuple) and key[:1] == ("action_order",):
            del _clarity_shelf_catalog_cache[key]
    _clarity_shelf_catalog_cache["operator_signature"] = signature


def _clarity_shelf_builtin_actions():
    actions = _clarity_shelf_catalog_cache.get("actions")
    if actions is not None:
        return actions
    items = []
    seen = set()
    action_groups = list(_CLARITY_SHELF_ITEMS.values()) + [
        _CLARITY_SHELF_EXTRA_ACTIONS,
        _clarity_shelf_discovered_action_items(),
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
    actions = tuple(items)
    _clarity_shelf_catalog_cache["actions"] = actions
    return actions


def _clarity_shelf_builtin_action_labels():
    labels = _clarity_shelf_catalog_cache.get("action_labels")
    if labels is None:
        labels = {
            action: label
            for action, label, _description, _icon, _index in _clarity_shelf_builtin_actions()
        }
        _clarity_shelf_catalog_cache["action_labels"] = labels
    return labels


def _clarity_shelf_builtin_action_icons():
    icons = _clarity_shelf_catalog_cache.get("action_icons")
    if icons is None:
        icons = {
            action: icon
            for action, _label, _description, icon, _index in _clarity_shelf_builtin_actions()
        }
        _clarity_shelf_catalog_cache["action_icons"] = icons
    return icons


def _clarity_shelf_blender_icons():
    icons = _clarity_shelf_catalog_cache.get("icons")
    if icons is not None:
        return icons
    enum_items = bpy.types.UILayout.bl_rna.functions["operator"].parameters["icon"].enum_items
    icons = tuple(
        (
            enum_item.identifier,
            enum_item.name or enum_item.identifier,
            enum_item.description,
            enum_item.value,
            index,
        )
        for index, enum_item in enumerate(enum_items)
    )
    _clarity_shelf_catalog_cache["icons"] = icons
    return icons


def _clarity_shelf_blender_icon_values():
    values = _clarity_shelf_catalog_cache.get("icon_values")
    if values is None:
        values = {
            identifier: icon_value
            for identifier, _name, _description, icon_value, _index in _clarity_shelf_blender_icons()
        }
        _clarity_shelf_catalog_cache["icon_values"] = values
    return values


_CLARITY_SHELF_COMMAND_TYPES = (
    ('BUILTIN', "Built-in Action", "Choose a ready-to-use shelf action"),
    ('OPERATOR', "Blender Operator", "Run a Blender operator"),
    ('PYTHON', "Python Script", "Run custom Python code"),
)

_CLARITY_SHELF_SCRIPT_SOURCES = (
    ('INLINE', "Inline Code", "Run code stored in this shelf button"),
    ('TEXT', "Text Block", "Run a Blender Text Editor text block"),
    ('FILE', "Python File", "Run an external Python file"),
)

_CLARITY_SHELF_ACTION_CATEGORIES = (
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

_CLARITY_SHELF_ACTION_SORT_MODES = (
    ('CATEGORY', "Category", "Group actions by category, then sort by name"),
    ('NAME', "Name", "Sort all visible actions by name"),
    ('ORIGINAL', "Original", "Keep the catalog order"),
)

_CLARITY_SHELF_ACTION_CATEGORY_ORDER = {
    identifier: index
    for index, (identifier, _name, _description) in enumerate(
        _CLARITY_SHELF_ACTION_CATEGORIES
    )
}


_CLARITY_SHELF_CATEGORY_BY_PREFIX = {
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
_CLARITY_SHELF_CATEGORY_BY_ACTION = {
    "select_box": 'SELECTION',
    "select_all": 'SELECTION',
    "select_none": 'SELECTION',
    "select_inverse": 'SELECTION',
    "move": 'TRANSFORM',
    "rotate": 'TRANSFORM',
    "scale": 'TRANSFORM',
    "apply_transforms": 'TRANSFORM',
    "clear_location": 'TRANSFORM',
    "clear_rotation": 'TRANSFORM',
    "clear_scale": 'TRANSFORM',
    "save": 'FILE',
    "save_as": 'FILE',
    "incremental_save": 'FILE',
    "open_file": 'FILE',
    "append_file": 'FILE',
    "link_file": 'FILE',
    "render": 'RENDER',
    "render_animation": 'RENDER',
    "render_selected": 'RENDER',
    "open_render_result": 'RENDER',
}

_CLARITY_SHELF_CATEGORY_BY_TAB = {
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
}


def _clarity_shelf_category_by_tab_action():
    """Category of every action that appears in a built-in tab, first tab wins."""
    categories = _clarity_shelf_catalog_cache.get("tab_categories")
    if categories is None:
        categories = {}
        for tab_name, shelf_items in _CLARITY_SHELF_ITEMS.items():
            category = _CLARITY_SHELF_CATEGORY_BY_TAB.get(tab_name, 'OTHER')
            for shelf_item in shelf_items:
                if shelf_item is not None:
                    categories.setdefault(shelf_item[0], category)
        _clarity_shelf_catalog_cache["tab_categories"] = categories
    return categories


def _clarity_shelf_action_category(action, label):
    category = _CLARITY_SHELF_CATEGORY_BY_ACTION.get(action)
    if category is not None:
        return category
    if action.startswith("operator__"):
        _prefix, module_name, _operator_name = action.split("__", 2)
        return _CLARITY_SHELF_CATEGORY_BY_PREFIX.get(module_name, 'OTHER')
    if ":" in label:
        prefix = label.split(":", 1)[0].replace(" (All)", "").lower()
        category = _CLARITY_SHELF_CATEGORY_BY_PREFIX.get(prefix)
        if category is not None:
            return category
    return _clarity_shelf_category_by_tab_action().get(action, 'OTHER')


def _clarity_shelf_action_rows():
    """Picker rows: (identifier, label, icon, category, sort_key).

    Precomputed because the action picker is refilled from scratch every time a dialog
    opens, and `sort_key` keeps the per-redraw sort in `TOPBAR_UL_clarity_shelf_actions`
    down to one string compare per entry instead of a category lookup plus a casefold.
    """
    rows = _clarity_shelf_catalog_cache.get("action_rows")
    if rows is not None:
        return rows
    unknown_order = len(_CLARITY_SHELF_ACTION_CATEGORY_ORDER)
    rows = []
    for action, label, _description, icon, _index in _clarity_shelf_builtin_actions():
        category = _clarity_shelf_action_category(action, label)
        order = _CLARITY_SHELF_ACTION_CATEGORY_ORDER.get(category, unknown_order)
        rows.append((action, label, icon, category, "{:02d}{:s}".format(order, label.casefold())))
    rows = tuple(rows)
    _clarity_shelf_catalog_cache["action_rows"] = rows
    return rows


def _clarity_shelf_action_order(sort_mode, reverse=False):
    """Cached UIList mapping from catalog index to displayed index."""
    cache_key = ("action_order", sort_mode, reverse)
    order = _clarity_shelf_catalog_cache.get(cache_key)
    if order is not None:
        return list(order)

    rows = _clarity_shelf_action_rows()
    if sort_mode == 'CATEGORY':
        sorted_indices = sorted(
            range(len(rows)),
            key=lambda index: rows[index][4],
            reverse=reverse,
        )
    elif sort_mode == 'NAME':
        sorted_indices = sorted(
            range(len(rows)),
            key=lambda index: rows[index][1].casefold(),
            reverse=reverse,
        )
    elif reverse:
        sorted_indices = list(reversed(range(len(rows))))
    else:
        return []

    order = [0] * len(sorted_indices)
    for displayed_index, catalog_index in enumerate(sorted_indices):
        order[catalog_index] = displayed_index
    order = tuple(order)
    _clarity_shelf_catalog_cache[cache_key] = order
    return list(order)


_CLARITY_SHELF_INVALID_STORAGE_BASELINE = object()

_clarity_shelf_config_cache = None
_clarity_shelf_active_scope = "TOPBAR"
_clarity_shelf_drag_state = None
# Entry under the cursor, pushed in by the C++ shelf region handler while a drag runs.
_clarity_shelf_drag_hover = None
_clarity_shelf_previews = None
_clarity_shelf_row_cache = {}
_clarity_shelf_custom_icon_cache = {}
_clarity_shelf_future_scope_storage = {}
_clarity_shelf_future_storage = None
_clarity_shelf_scope_baselines = {}
_clarity_shelf_storage_baseline_content = None
_clarity_shelf_pending_scopes = set()

_CLARITY_SHELF_ROW_COUNT = 2

# Schema version of a single shelf config, see `_clarity_shelf_migrate_config`.
_CLARITY_SHELF_VERSION = 3
_CLARITY_SHELF_STORAGE_VERSION = 1
_CLARITY_SHELF_DEFAULT_BACKGROUND_COLOR = (0.18, 0.18, 0.18, 1.0)
_CLARITY_SHELF_DEFAULT_ICON_COLOR = (1.0, 1.0, 1.0, 1.0)
_CLARITY_SHELF_DRAG_SOURCE_COLOR = (0.08, 0.32, 0.68, 1.0)
_CLARITY_SHELF_CUSTOM_ICON_RECHECK_SECONDS = 1.0
_CLARITY_SHELF_SAVE_LOCK_TIMEOUT = 0.75
_CLARITY_SHELF_STALE_LOCK_SECONDS = 30.0


def unregister_runtime():
    global _clarity_shelf_previews
    global _clarity_shelf_drag_state
    global _clarity_shelf_drag_hover
    global _clarity_shelf_config_cache
    global _clarity_shelf_future_storage
    global _clarity_shelf_storage_baseline_content
    if _clarity_shelf_previews is not None:
        bpy.utils.previews.remove(_clarity_shelf_previews)
        _clarity_shelf_previews = None
    _clarity_shelf_drag_state = None
    _clarity_shelf_drag_hover = None
    # The config is written out on every change, so dropping it here only forces
    # a reload. Icon ids belong to the previews collection freed above.
    _clarity_shelf_config_cache = None
    _clarity_shelf_future_storage = None
    _clarity_shelf_storage_baseline_content = None
    _clarity_shelf_custom_icon_cache.clear()
    _clarity_shelf_catalog_cache.clear()
    _clarity_shelf_row_cache.clear()
    _clarity_shelf_future_scope_storage.clear()
    _clarity_shelf_scope_baselines.clear()
    _clarity_shelf_pending_scopes.clear()


def _clarity_shelf_preview_icon(name, filename, *, force_reload=False):
    global _clarity_shelf_previews
    if _clarity_shelf_previews is None:
        import bpy.utils.previews

        _clarity_shelf_previews = bpy.utils.previews.new()
    if force_reload and name in _clarity_shelf_previews:
        del _clarity_shelf_previews[name]
    if name not in _clarity_shelf_previews:
        filepath = os.path.join(
            os.path.dirname(__file__),
            "assets",
            filename,
        )
        try:
            preview = _clarity_shelf_previews.load(name, filepath, 'IMAGE')
            # Force the image to load before the first frame using it is drawn.
            icon_size = preview.icon_size
            if not icon_size[0] or not icon_size[1]:
                del _clarity_shelf_previews[name]
                return 0
        except Exception:
            if name in _clarity_shelf_previews:
                del _clarity_shelf_previews[name]
            return 0
    return _clarity_shelf_previews[name].icon_id


def _clarity_shelf_custom_icon(filepath, *, force_reload=False):
    """Preview id for a user image, refreshed after the file changes.

    Draw calls only stat each distinct path once per second. This keeps missing paths
    off the hot redraw loop while still noticing replacements, deletions and a `//`
    path resolving differently after another blend-file is opened.
    """
    if not filepath:
        return 0
    absolute_path = os.path.abspath(bpy.path.abspath(filepath))
    cache_key = os.path.normcase(absolute_path)
    now = time.monotonic()
    cached = _clarity_shelf_custom_icon_cache.get(cache_key)
    if not force_reload and cached is not None and now < cached["recheck_at"]:
        return cached["icon_id"]

    try:
        stat = os.stat(absolute_path)
        fingerprint = (stat.st_mtime_ns, stat.st_size)
    except OSError:
        if cached is not None and cached["preview_name"] and _clarity_shelf_previews is not None:
            if cached["preview_name"] in _clarity_shelf_previews:
                del _clarity_shelf_previews[cached["preview_name"]]
        _clarity_shelf_custom_icon_cache[cache_key] = {
            "fingerprint": None,
            "icon_id": 0,
            "preview_name": "",
            "recheck_at": now + _CLARITY_SHELF_CUSTOM_ICON_RECHECK_SECONDS,
        }
        return 0

    if not force_reload and cached is not None and cached["fingerprint"] == fingerprint:
        cached["recheck_at"] = now + _CLARITY_SHELF_CUSTOM_ICON_RECHECK_SECONDS
        return cached["icon_id"]
    if cached is not None and cached["preview_name"] and _clarity_shelf_previews is not None:
        if cached["preview_name"] in _clarity_shelf_previews:
            del _clarity_shelf_previews[cached["preview_name"]]

    preview_name = "clarity_shelf_custom_" + uuid.uuid5(
        uuid.NAMESPACE_URL,
        "{:s}:{:d}:{:d}".format(cache_key, fingerprint[0], fingerprint[1]),
    ).hex
    icon_id = _clarity_shelf_preview_icon(
        preview_name,
        absolute_path,
        force_reload=force_reload,
    )
    _clarity_shelf_custom_icon_cache[cache_key] = {
        "fingerprint": fingerprint,
        "icon_id": icon_id,
        "preview_name": preview_name if icon_id else "",
        "recheck_at": now + _CLARITY_SHELF_CUSTOM_ICON_RECHECK_SECONDS,
    }
    return icon_id


def _clarity_shelf_script_settings(operator):
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


class TOPBAR_PG_clarity_shelf_icon(PropertyGroup):
    identifier: StringProperty()


class TOPBAR_PG_clarity_shelf_action(PropertyGroup):
    identifier: StringProperty()
    label: StringProperty()
    icon: StringProperty()
    category: StringProperty()
    # Category order and lowercased label, joined so sorting is a plain string compare.
    sort_key: StringProperty()


class TOPBAR_UL_clarity_shelf_icons(UIList):
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


class TOPBAR_UL_clarity_shelf_actions(UIList):
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
        category = getattr(data, "action_category", 'ALL')
        if category != 'ALL':
            if not flags:
                flags = [self.bitflag_filter_item] * len(actions)
            for index, action in enumerate(actions):
                if action.category != category:
                    flags[index] = 0

        sort_mode = getattr(data, "action_sort", 'CATEGORY')
        if self.use_filter_sort_alpha:
            sort_mode = 'NAME'
        if len(actions) == len(_clarity_shelf_action_rows()):
            indices = _clarity_shelf_action_order(
                sort_mode,
                reverse=self.use_filter_sort_reverse,
            )
        elif sort_mode == 'ORIGINAL':
            indices = (
                [len(actions) - index - 1 for index in range(len(actions))]
                if self.use_filter_sort_reverse
                else []
            )
        else:
            key_property = "sort_key" if sort_mode == 'CATEGORY' else "label"
            indices = bpy.types.UI_UL_list.sort_items_helper(
                [
                    (index, getattr(action, key_property).casefold())
                    for index, action in enumerate(actions)
                ],
                lambda entry: entry[1],
                reverse=self.use_filter_sort_reverse,
            )
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


def _clarity_shelf_color_string(color):
    return ",".join(f"{component:.6f}" for component in color)


def _clarity_shelf_icon_list_fill(operator, selected_icon):
    operator.icons.clear()
    selected_index = 0
    for index, enum_item in enumerate(_clarity_shelf_blender_icons()):
        icon = operator.icons.add()
        icon.identifier = enum_item[0]
        # The built-in UIList name filter reads the inherited PropertyGroup name.
        icon.name = icon.identifier
        if icon.identifier == selected_icon:
            selected_index = index
    operator.icon_index = selected_index


def _clarity_shelf_action_list_fill(operator, selected_action):
    _clarity_shelf_refresh_action_catalog()
    operator.actions.clear()
    selected_index = 0
    selected_found = False
    for index, row in enumerate(_clarity_shelf_action_rows()):
        identifier, label, icon, category, sort_key = row
        action = operator.actions.add()
        action.identifier = identifier
        action.label = label
        action.icon = icon
        action.category = category
        action.sort_key = sort_key
        if identifier == selected_action:
            selected_index = index
            selected_found = True
    if selected_action and not selected_found:
        action = operator.actions.add()
        action.identifier = selected_action
        action.label = "Missing Action: {:s}".format(selected_action)
        action.icon = 'ERROR'
        action.category = 'OTHER'
        action.sort_key = "{:02d}{:s}".format(
            _CLARITY_SHELF_ACTION_CATEGORY_ORDER['OTHER'],
            action.label.casefold(),
        )
        selected_index = len(operator.actions) - 1
    operator.action_index = selected_index


def _clarity_shelf_selected_action(operator):
    if operator.actions and 0 <= operator.action_index < len(operator.actions):
        return operator.actions[operator.action_index].identifier
    return operator.builtin_action


def _clarity_shelf_action_index_update(operator, _context):
    action = _clarity_shelf_selected_action(operator)
    label = _clarity_shelf_builtin_action_labels().get(action, "")
    if label:
        operator.label = label.split(":", 1)[-1].strip()
    icon_identifier = _clarity_shelf_builtin_action_icons().get(action)
    if not icon_identifier:
        return
    for index, icon in enumerate(operator.icons):
        if icon.identifier == icon_identifier:
            operator.icon_index = index
            operator.custom_icon = ""
            break


def _clarity_shelf_draw_icon_preview(layout, operator):
    custom_icon_value = _clarity_shelf_custom_icon(operator.custom_icon)
    icon_value = custom_icon_value
    icon_identifier = ""
    if not icon_value and operator.icons and 0 <= operator.icon_index < len(operator.icons):
        icon_identifier = operator.icons[operator.icon_index].identifier
        icon_value = _clarity_shelf_blender_icon_values().get(icon_identifier, 0)

    preview = layout.box()
    preview.label(text="Icon Preview")
    icon_row = preview.row()
    icon_row.alignment = 'CENTER'
    preview_button = icon_row.row(align=True)
    preview_button.scale_x = 3.0
    preview_button.scale_y = 3.0
    preview_button.context_string_set(
        "clarity_shelf_background_color",
        _clarity_shelf_color_string(operator.background_color),
    )
    preview_button.context_string_set(
        "clarity_shelf_icon_color",
        _clarity_shelf_color_string(
            (1.0, 1.0, 1.0, operator.icon_color[3])
            if custom_icon_value
            else operator.icon_color
        ),
    )
    operator_args = {"text": "", "emboss": True}
    if icon_value:
        operator_args["icon_value"] = icon_value
    preview_button.operator("topbar.clarity_shelf_preview", **operator_args)
    if operator.custom_icon:
        preview.label(text=os.path.basename(operator.custom_icon))
    elif icon_identifier:
        preview.label(text=icon_identifier)


def _clarity_shelf_config_path():
    config_dir = bpy.utils.user_resource('CONFIG', create=True)
    return os.path.join(config_dir, "clarity_shelf.json")


def _clarity_shelf_legacy_config_path():
    config_dir = bpy.utils.user_resource('CONFIG')
    return os.path.join(config_dir, "maya_shelf.json")


def _clarity_shelf_reject_json_constant(value):
    raise ValueError("Invalid JSON number: {:s}".format(value))


def _clarity_shelf_json_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("JSON number is outside the supported range")
    return number


def _clarity_shelf_default_config():
    tabs = []
    for tab_name in _CLARITY_SHELF_TABS:
        source_items = [item for item in _CLARITY_SHELF_ITEMS.get(tab_name, ()) if item is not None]
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
    return {"version": _CLARITY_SHELF_VERSION, "active": "Modeling", "tabs": tabs}


def _clarity_shelf_config_clone(source):
    config = copy.deepcopy(source)
    for tab in config["tabs"]:
        for item in tab["items"]:
            item["id"] = uuid.uuid4().hex
        for separator in tab["separators"]:
            separator["id"] = uuid.uuid4().hex
    return config


def _clarity_shelf_clamped_int(value, minimum, maximum):
    try:
        number = int(value)
    except (OverflowError, TypeError, ValueError):
        return minimum
    return min(max(number, minimum), maximum)


def _clarity_shelf_version(value):
    try:
        return max(int(value), 1)
    except (OverflowError, TypeError, ValueError):
        return 1


def _clarity_shelf_assign(mapping, key, value):
    """Assign a normalized value and report whether the JSON graph changed."""
    sentinel = object()
    if mapping.get(key, sentinel) == value:
        return False
    mapping[key] = value
    return True


def _clarity_shelf_ui_string(value, default="", *, strip=False, max_length=None):
    if value is None:
        value = default
    elif not isinstance(value, str):
        value = str(value)
    if strip:
        value = value.strip()
    if max_length is not None:
        value = value[:max_length]
    return value


def _clarity_shelf_color(value, default):
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return list(default)
    try:
        color = [float(component) for component in value]
    except (OverflowError, TypeError, ValueError):
        return list(default)
    if not all(math.isfinite(component) for component in color):
        return list(default)
    return [min(max(component, 0.0), 1.0) for component in color]


def _clarity_shelf_unique_id(value, used_ids):
    identifier = value.strip() if isinstance(value, str) else ""
    if not identifier or identifier in used_ids:
        identifier = uuid.uuid4().hex
    used_ids.add(identifier)
    return identifier


def _clarity_shelf_normalize_tab(tab):
    """Fill in every key the draw and edit code indexes with `[]`.

    The config is a plain JSON file users can hand-edit, so nothing about its shape
    can be assumed. Normalizing once on load keeps the rest of the shelf free of
    defensive `setdefault` calls, and clamping `row` stops out-of-range items from
    being silently dropped by the row-based reorder code.
    """
    if not isinstance(tab, dict):
        raise ValueError("Shelf tab is invalid")
    changed = False
    discarded = False
    name = _clarity_shelf_ui_string(tab.get("name"), "Shelf", strip=True) or "Shelf"
    discarded |= "name" in tab and tab.get("name") != name
    changed |= _clarity_shelf_assign(tab, "name", name)

    items = tab.get("items")
    if isinstance(items, list):
        normalized_items = [item for item in items if isinstance(item, dict)]
        discarded |= len(normalized_items) != len(items)
    else:
        normalized_items = []
        changed = True
        discarded |= items not in (None, [])
    changed |= _clarity_shelf_assign(tab, "items", normalized_items)

    separators = tab.get("separators")
    if isinstance(separators, list):
        normalized_separators = [
            separator for separator in separators if isinstance(separator, dict)
        ]
        discarded |= len(normalized_separators) != len(separators)
    else:
        normalized_separators = []
        changed = True
        discarded |= separators not in (None, [])
    changed |= _clarity_shelf_assign(tab, "separators", normalized_separators)

    last_row = _CLARITY_SHELF_ROW_COUNT - 1
    used_ids = set()
    for item in tab["items"]:
        identifier = _clarity_shelf_unique_id(item.get("id"), used_ids)
        discarded |= bool(item.get("id")) and item.get("id") != identifier
        changed |= _clarity_shelf_assign(
            item,
            "id",
            identifier,
        )
        changed |= _clarity_shelf_assign(
            item,
            "label",
            _clarity_shelf_ui_string(item.get("label"), "Shelf Command"),
        )
        icon = _clarity_shelf_ui_string(item.get("icon"), 'NONE') or 'NONE'
        changed |= _clarity_shelf_assign(item, "icon", icon)
        row = _clarity_shelf_clamped_int(item.get("row", 0), 0, last_row)
        discarded |= "row" in item and item.get("row") != row
        changed |= _clarity_shelf_assign(item, "row", row)

        for key in (
                "action",
                "operator",
                "custom_icon",
                "script_code",
                "script_text",
                "script_file",
        ):
            if key in item:
                value = _clarity_shelf_ui_string(item.get(key))
                discarded |= item.get(key) != value
                changed |= _clarity_shelf_assign(item, key, value)
        if "short_text" in item:
            short_text = _clarity_shelf_ui_string(
                item.get("short_text"),
                max_length=5,
            )
            discarded |= item.get("short_text") != short_text
            changed |= _clarity_shelf_assign(item, "short_text", short_text)
        if "command_type" in item:
            command_type = item.get("command_type")
            if command_type not in {'BUILTIN', 'OPERATOR', 'PYTHON'}:
                command_type = (
                    'PYTHON' if any(item.get(key) for key in (
                        "script_code", "script_text", "script_file",
                    ))
                    else 'OPERATOR' if item.get("operator")
                    else 'BUILTIN'
                )
            discarded |= item.get("command_type") != command_type
            changed |= _clarity_shelf_assign(item, "command_type", command_type)
        if "script_source" in item:
            script_source = item.get("script_source")
            if script_source not in {'INLINE', 'TEXT', 'FILE'}:
                script_source = 'INLINE'
            discarded |= item.get("script_source") != script_source
            changed |= _clarity_shelf_assign(item, "script_source", script_source)
        for key, default in (
                ("background_color", _CLARITY_SHELF_DEFAULT_BACKGROUND_COLOR),
                ("icon_color", _CLARITY_SHELF_DEFAULT_ICON_COLOR),
        ):
            if key in item:
                color = _clarity_shelf_color(item.get(key), default)
                discarded |= item.get(key) != color
                changed |= _clarity_shelf_assign(item, key, color)

    row_lengths = {
        row_index: len(_clarity_shelf_row_items(tab, row_index))
        for row_index in range(_CLARITY_SHELF_ROW_COUNT)
    }
    for separator in tab["separators"]:
        identifier = _clarity_shelf_unique_id(separator.get("id"), used_ids)
        discarded |= bool(separator.get("id")) and separator.get("id") != identifier
        changed |= _clarity_shelf_assign(
            separator,
            "id",
            identifier,
        )
        row = _clarity_shelf_clamped_int(separator.get("row", 0), 0, last_row)
        discarded |= "row" in separator and separator.get("row") != row
        changed |= _clarity_shelf_assign(separator, "row", row)
        column = _clarity_shelf_clamped_int(
            separator.get("column", 0), 0, row_lengths[row],
        )
        discarded |= "column" in separator and separator.get("column") != column
        changed |= _clarity_shelf_assign(
            separator,
            "column",
            column,
        )
    sorted_separators = sorted(
        tab["separators"],
        key=lambda separator: (separator["row"], separator["column"]),
    )
    changed |= _clarity_shelf_assign(tab, "separators", sorted_separators)
    return changed, discarded


def _clarity_shelf_normalize_config(config):
    if not isinstance(config, dict):
        raise ValueError("Shelf config is invalid")
    tabs = config.get("tabs")
    if not isinstance(tabs, list) or not tabs:
        raise ValueError("Shelf has no tabs")
    normalized_tabs = [tab for tab in tabs if isinstance(tab, dict)]
    if not normalized_tabs:
        raise ValueError("Shelf has no valid tabs")

    changed = len(normalized_tabs) != len(tabs)
    discarded = changed
    active_name = config.get("active")
    active_tab_name = None
    used_names = set()
    for tab in normalized_tabs:
        original_name = _clarity_shelf_ui_string(tab.get("name"), "Shelf", strip=True) or "Shelf"
        tab_changed, tab_discarded = _clarity_shelf_normalize_tab(tab)
        changed |= tab_changed
        discarded |= tab_discarded

        base_name = tab["name"]
        unique_name = base_name
        suffix = 2
        while unique_name in used_names:
            unique_name = "{:s} {:d}".format(base_name, suffix)
            suffix += 1
        used_names.add(unique_name)
        discarded |= unique_name != base_name
        changed |= _clarity_shelf_assign(tab, "name", unique_name)
        if active_tab_name is None and active_name == original_name:
            active_tab_name = unique_name

    changed |= _clarity_shelf_assign(config, "tabs", normalized_tabs)
    if active_tab_name is None:
        active_tab_name = normalized_tabs[0]["name"]
    changed |= _clarity_shelf_assign(config, "active", active_tab_name)
    return changed, discarded


def _clarity_shelf_layout_scope_key(context, area=None):
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


def _clarity_shelf_uuid_scope_key(context):
    area = getattr(context, "area", None)
    if area is None or area.type != 'SHELF':
        return None
    shelf_id = getattr(getattr(context, "space_data", None), "shelf_id", "")
    return "SHELF:" + shelf_id if shelf_id else None


def _clarity_shelf_scope_key(context):
    area = getattr(context, "area", None) if context is not None else None
    if area is None or area.type != 'SHELF':
        return "TOPBAR"
    return _clarity_shelf_layout_scope_key(context, area)


def _clarity_shelf_tab_is_unmodified_builtin(tab):
    """Whether a legacy tab still matches the generated v1 contents.

    UUIDs are intentionally ignored. Any visual customization, separator, command
    change or reorder makes the tab user data and therefore keeps it during v2
    migration.
    """
    tab_name = tab["name"]
    source_name = "Modeling" if tab_name == "Poly Modeling" else tab_name
    source_items = [
        item for item in _CLARITY_SHELF_ITEMS.get(source_name, ()) if item is not None
    ]
    if tab["separators"] or len(tab["items"]) != len(source_items):
        return False

    split = (len(source_items) + 1) // 2
    optional_keys = {
        "background_color",
        "icon_color",
        "custom_icon",
        "short_text",
        "command_type",
        "script_source",
        "script_code",
        "script_text",
        "script_file",
    }
    for index, (item, source_item) in enumerate(zip(tab["items"], source_items)):
        action, label, icon = source_item
        if (
            item.get("action", "") != action or
            item.get("label", "") != label or
            item.get("icon", 'NONE') != icon or
            item.get("operator", "") or
            item.get("row", 0) != (0 if index < split else 1) or
            any(key in item for key in optional_keys)
        ):
            return False
    return True


def _clarity_shelf_migrate_config(config):
    """Bring one shelf config up to the current version. Returns True when changed."""
    migrated = False
    version = _clarity_shelf_version(config.get("version", 1))
    if version > _CLARITY_SHELF_VERSION:
        # Never downgrade data written by a newer Blender. Known fields were
        # normalized for safe drawing, but the schema marker and unknown fields stay.
        return False
    if version < 2:
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
            modeling = _clarity_shelf_default_config()["tabs"][0]
        modeling["name"] = "Modeling"
        if custom is None:
            custom = {"name": "Custom", "items": [], "separators": []}
        user_tabs = [
            tab for tab in config["tabs"]
            if (
                tab is not modeling and
                tab is not custom and
                (
                    tab["name"] not in _CLARITY_SHELF_LEGACY_TABS or
                    not _clarity_shelf_tab_is_unmodified_builtin(tab)
                )
            )
        ]
        config["tabs"] = [modeling, custom] + user_tabs
        tab_names = {tab["name"] for tab in config["tabs"]}
        active = config.get("active")
        if active == "Poly Modeling":
            active = "Modeling"
        config["active"] = active if active in tab_names else "Modeling"
        config["version"] = 2
        migrated = True
    if version < 3:
        # Alpha 0 used to mean "no override"; opaque is what those items meant.
        for tab in config["tabs"]:
            for item in tab["items"]:
                for key in ("background_color", "icon_color"):
                    color = item.get(key)
                    if color and len(color) == 4 and color[3] == 0.0:
                        item[key] = [color[0], color[1], color[2], 1.0]
        config["version"] = 3
        migrated = True
    if config.get("version") != _CLARITY_SHELF_VERSION:
        config["version"] = _CLARITY_SHELF_VERSION
        migrated = True
    return migrated


def _clarity_shelf_backup_broken_config(error, expected_content):
    """Keep an unreadable config around, the next save would overwrite it."""
    path = _clarity_shelf_config_path()
    if expected_content is None:
        print("Clarity shelf: unable to verify the unreadable config before backing it up")
        return False
    backup_path = path + ".bak"
    lock_path = ""
    try:
        lock_path = _clarity_shelf_save_lock_acquire(path)
        with open(path, "rb") as handle:
            if handle.read() != expected_content:
                print(
                    "Clarity shelf: config changed in another Blender process; "
                    "left the newer file untouched"
                )
                return False
        os.replace(path, backup_path)
    except OSError as ex:
        print("Clarity shelf: unable to back up {:s}: {:s}".format(path, str(ex)))
        return False
    finally:
        if lock_path:
            try:
                os.remove(lock_path)
            except OSError:
                pass
    print(
        "Clarity shelf: {:s} could not be read ({:s}), "
        "kept as {:s} and reset to defaults".format(path, str(error), backup_path)
    )
    return True


def _clarity_shelf_backup_repaired_config(reason, original_content):
    """Copy a partly recoverable config before destructive local repairs."""
    path = _clarity_shelf_config_path()
    if original_content is None:
        return
    backup_path = path + ".bak"
    temp_path = ""
    try:
        with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=os.path.dirname(path),
                prefix=os.path.basename(backup_path) + ".",
                suffix=".tmp",
                delete=False,
        ) as handle:
            temp_path = handle.name
            handle.write(original_content)
        os.replace(temp_path, backup_path)
    except OSError as ex:
        print("Clarity shelf: unable to back up {:s}: {:s}".format(path, str(ex)))
        return
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
    print(
        "Clarity shelf: repaired unreadable data ({:s}); original kept as {:s}".format(
            reason,
            backup_path,
        )
    )


def _clarity_shelf_load():
    """Read the shelf storage into `_clarity_shelf_config_cache`, defaults on failure."""
    global _clarity_shelf_config_cache
    global _clarity_shelf_future_storage
    global _clarity_shelf_storage_baseline_content
    config_path = _clarity_shelf_config_path()
    legacy_config_path = _clarity_shelf_legacy_config_path()
    migrate_legacy_config = not os.path.exists(config_path) and os.path.isfile(legacy_config_path)
    read_path = legacy_config_path if migrate_legacy_config else config_path
    migrated = migrate_legacy_config
    destructive_repair = False
    repair_reasons = []
    raw_storage_content = None
    _clarity_shelf_future_scope_storage.clear()
    _clarity_shelf_scope_baselines.clear()
    _clarity_shelf_pending_scopes.clear()
    _clarity_shelf_future_storage = None
    _clarity_shelf_storage_baseline_content = None
    try:
        with open(read_path, "rb") as handle:
            raw_storage_content = handle.read()
        stored_config = json.loads(
            raw_storage_content.decode("utf-8"),
            parse_constant=_clarity_shelf_reject_json_constant,
            parse_float=_clarity_shelf_json_float,
        )
        if not isinstance(stored_config, dict):
            raise ValueError("Shelf storage is invalid")
        _clarity_shelf_storage_baseline_content = raw_storage_content
        declared_storage_version = _clarity_shelf_version(
            stored_config.get("storage_version", 1),
        )
        raw_shelves = stored_config.get("shelves")
        if isinstance(raw_shelves, dict):
            _clarity_shelf_scope_baselines.update(copy.deepcopy(raw_shelves))
        elif "shelves" not in stored_config and declared_storage_version <= _CLARITY_SHELF_STORAGE_VERSION:
            # Storage version 0 held the Top Bar shelf directly at the top level.
            _clarity_shelf_scope_baselines["TOPBAR"] = copy.deepcopy(stored_config)
        if declared_storage_version > _CLARITY_SHELF_STORAGE_VERSION:
            _clarity_shelf_future_storage = copy.deepcopy(stored_config)
        if (
            _clarity_shelf_future_storage is not None and
            not isinstance(stored_config.get("shelves"), dict)
        ):
            # A future storage schema may rename `shelves`; never reinterpret its
            # top-level graph as the legacy single-shelf format.
            storage = {
                "storage_version": declared_storage_version,
                "shelves": {"TOPBAR": _clarity_shelf_default_config()},
            }
        elif "shelves" in stored_config:
            shelves = stored_config["shelves"]
            if not isinstance(shelves, dict):
                raise ValueError("Shelf storage is invalid")
            storage = stored_config
            if declared_storage_version <= _CLARITY_SHELF_STORAGE_VERSION:
                if storage.get("storage_version") != _CLARITY_SHELF_STORAGE_VERSION:
                    storage["storage_version"] = _CLARITY_SHELF_STORAGE_VERSION
                    migrated = True
        else:
            # Storage version 0 held a single Top Bar shelf at the top level.
            storage = {
                "storage_version": _CLARITY_SHELF_STORAGE_VERSION,
                "shelves": {"TOPBAR": stored_config},
            }
            migrated = True
        if "TOPBAR" not in storage["shelves"]:
            # Every other scope is cloned from the Top Bar shelf, so it has to exist.
            storage["shelves"]["TOPBAR"] = _clarity_shelf_default_config()
            migrated = True
        # Repair one scope at a time: a single unreadable shelf must not cost the user
        # every other shelf they set up.
        for scope in list(storage["shelves"]):
            try:
                config = storage["shelves"][scope]
                future_schema = (
                    isinstance(config, dict) and
                    _clarity_shelf_version(config.get("version", 1)) > _CLARITY_SHELF_VERSION
                )
                if future_schema:
                    # Keep the exact future-schema graph for unrelated saves. A safe
                    # normalized copy is still used at runtime so drawing cannot fail.
                    _clarity_shelf_future_scope_storage[scope] = copy.deepcopy(config)
                normalized, discarded = _clarity_shelf_normalize_config(config)
                if not future_schema:
                    migrated |= normalized
                if discarded and not future_schema:
                    destructive_repair = True
                    repair_reasons.append("discarded invalid entries in {:s}".format(scope))
                migrated |= _clarity_shelf_migrate_config(config)
            except (AttributeError, OverflowError, ValueError, TypeError) as ex:
                print("Clarity shelf: resetting unreadable shelf {:s}: {:s}".format(
                    scope, str(ex)))
                if scope in _clarity_shelf_future_scope_storage:
                    # The raw graph remains the source of truth until the user edits
                    # this scope explicitly.
                    future_schema = True
                storage["shelves"][scope] = _clarity_shelf_default_config()
                if not future_schema:
                    migrated = True
                    destructive_repair = True
                    repair_reasons.append("reset {:s}".format(scope))
        _clarity_shelf_config_cache = storage
    except (OSError, AttributeError, UnicodeError, ValueError, TypeError, json.JSONDecodeError) as ex:
        if not isinstance(ex, FileNotFoundError) and not migrate_legacy_config:
            _clarity_shelf_backup_broken_config(ex, raw_storage_content)
        _clarity_shelf_storage_baseline_content = None
        _clarity_shelf_scope_baselines.clear()
        _clarity_shelf_config_cache = {
            "storage_version": _CLARITY_SHELF_STORAGE_VERSION,
            "shelves": {"TOPBAR": _clarity_shelf_default_config()},
        }
        migrated = True
    _clarity_shelf_invalidate_layout()
    if migrated and _clarity_shelf_future_storage is None:
        if migrate_legacy_config:
            # The legacy file remains a read-only fallback. The migrated graph is written only to
            # `clarity_shelf.json`, so future edits never make the old path authoritative again.
            _clarity_shelf_storage_baseline_content = None
        if destructive_repair:
            _clarity_shelf_backup_repaired_config(
                "; ".join(repair_reasons),
                raw_storage_content,
            )
        _clarity_shelf_save()


def _clarity_shelf_scope_config(scope, uuid_scope=None):
    """Config for `scope`, created from the Top Bar shelf when it does not exist yet.

    Returns the config and whether the storage had to be changed to produce it.
    """
    if _clarity_shelf_config_cache is None:
        _clarity_shelf_load()
    shelves = _clarity_shelf_config_cache["shelves"]
    if scope in shelves:
        return shelves[scope], False
    if uuid_scope is not None and uuid_scope in shelves:
        # Shelf areas used to be keyed by their `shelf_id`; adopt that config.
        shelves[scope] = shelves.pop(uuid_scope)
        if uuid_scope in _clarity_shelf_future_scope_storage:
            _clarity_shelf_future_scope_storage[scope] = (
                _clarity_shelf_future_scope_storage.pop(uuid_scope)
            )
    else:
        source = shelves.get("TOPBAR")
        shelves[scope] = (
            _clarity_shelf_config_clone(source)
            if source is not None
            else _clarity_shelf_default_config()
        )
    _clarity_shelf_invalidate_layout()
    return shelves[scope], True


def _clarity_shelf_config(context=None):
    """Config of the shelf `context` belongs to, or of the last one that was used.

    Passing a context re-points the module-wide active scope, so any code that
    later calls this without one keeps operating on the same shelf.
    """
    global _clarity_shelf_active_scope
    if context is not None:
        _clarity_shelf_active_scope = _clarity_shelf_scope_key(context)
        uuid_scope = _clarity_shelf_uuid_scope_key(context)
    else:
        uuid_scope = None
    config, created = _clarity_shelf_scope_config(_clarity_shelf_active_scope, uuid_scope)
    if created:
        changed_scopes = {_clarity_shelf_active_scope}
        if uuid_scope is not None:
            changed_scopes.add(uuid_scope)
        if _clarity_shelf_save(changed_scopes):
            _clarity_shelf_pending_scopes.update(changed_scopes)
    return config


def _clarity_shelf_save_lock_acquire(path):
    """Acquire the small cross-process lock guarding read/merge/replace."""
    lock_path = path + ".lock"
    deadline = time.monotonic() + _CLARITY_SHELF_SAVE_LOCK_TIMEOUT
    while True:
        try:
            descriptor = os.open(
                lock_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            )
        except FileExistsError:
            try:
                lock_age = time.time() - os.path.getmtime(lock_path)
                if lock_age > _CLARITY_SHELF_STALE_LOCK_SECONDS:
                    os.remove(lock_path)
                    continue
            except FileNotFoundError:
                continue
            if time.monotonic() >= deadline:
                raise OSError("another Blender process is saving the shelf")
            time.sleep(0.025)
            continue
        try:
            try:
                os.write(descriptor, "{:d}\n".format(os.getpid()).encode("ascii"))
            finally:
                os.close(descriptor)
        except OSError:
            try:
                os.remove(lock_path)
            except OSError:
                pass
            raise
        return lock_path


def _clarity_shelf_merge_disk_storage(storage, changed_scopes, path):
    """Preserve external scopes and return whether the whole-file baseline stayed valid."""
    try:
        with open(path, "rb") as handle:
            disk_content = handle.read()
        disk_storage = json.loads(
            disk_content.decode("utf-8"),
            parse_constant=_clarity_shelf_reject_json_constant,
            parse_float=_clarity_shelf_json_float,
        )
    except FileNotFoundError:
        if _clarity_shelf_storage_baseline_content is None:
            return storage, True
        raise OSError(
            "shelf storage was removed by another process; restart Blender before editing it"
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as ex:
        raise OSError(
            "shelf storage changed and can no longer be merged safely: {:s}".format(str(ex))
        )

    if not changed_scopes:
        if disk_content != _clarity_shelf_storage_baseline_content:
            raise OSError(
                "shelf storage changed in another Blender process during migration; "
                "restart Blender before editing it"
            )
        return storage, True
    if isinstance(disk_storage, dict):
        disk_storage_version = _clarity_shelf_version(
            disk_storage.get("storage_version", 1),
        )
        if _clarity_shelf_future_storage is None:
            if disk_storage_version > _CLARITY_SHELF_STORAGE_VERSION:
                raise OSError(
                    "shelf storage was upgraded by another Blender process; "
                    "restart Blender before editing it"
                )
        else:
            loaded_storage_version = _clarity_shelf_version(
                _clarity_shelf_future_storage.get("storage_version", 1),
            )
            if disk_storage_version != loaded_storage_version:
                raise OSError(
                    "shelf storage schema changed in another Blender process; "
                    "restart Blender before editing it"
                )
    if (
        not isinstance(disk_storage, dict) or
        not isinstance(disk_storage.get("shelves"), dict)
    ):
        if disk_content == _clarity_shelf_storage_baseline_content:
            return storage, True
        raise OSError(
            "shelf storage uses a schema written by another Blender process; "
            "restart Blender before editing it"
        )

    merged = disk_storage
    merged_shelves = merged["shelves"]
    source_shelves = storage["shelves"]
    disk_unchanged = disk_content == _clarity_shelf_storage_baseline_content
    missing = object()
    for scope in changed_scopes:
        baseline_scope = _clarity_shelf_scope_baselines.get(scope, missing)
        disk_scope = merged_shelves.get(scope, missing)
        source_scope = source_shelves.get(scope, missing)
        if (
            not disk_unchanged and
            disk_scope != baseline_scope and
            source_scope != disk_scope
        ):
            raise OSError(
                "shelf {:s} changed in another Blender process; "
                "restart Blender before editing it".format(scope)
            )
        if scope in source_shelves:
            merged_shelves[scope] = source_shelves[scope]
        else:
            merged_shelves.pop(scope, None)
    return merged, disk_unchanged


def _clarity_shelf_save(changed_scopes=None):
    """Atomically write the whole shelf storage. Returns an empty string on success."""
    global _clarity_shelf_future_storage
    global _clarity_shelf_storage_baseline_content
    if _clarity_shelf_config_cache is None:
        return ""
    if changed_scopes is not None:
        changed_scopes = set(changed_scopes)
        changed_scopes.update(_clarity_shelf_pending_scopes)
    if _clarity_shelf_future_storage is not None and not changed_scopes:
        # Automatic normalization and migration must never rewrite a storage schema
        # this Blender does not understand.
        return ""
    path = _clarity_shelf_config_path()
    temp_path = ""
    lock_path = ""
    try:
        lock_path = _clarity_shelf_save_lock_acquire(path)
        source_storage = _clarity_shelf_config_cache
        if _clarity_shelf_future_scope_storage:
            source_storage = copy.deepcopy(source_storage)
            source_storage["shelves"].update(_clarity_shelf_future_scope_storage)
        if _clarity_shelf_future_storage is not None:
            storage = copy.deepcopy(_clarity_shelf_future_storage)
            storage_shelves = storage.setdefault("shelves", {})
            for scope in changed_scopes:
                if scope in source_storage["shelves"]:
                    storage_shelves[scope] = source_storage["shelves"][scope]
                else:
                    storage_shelves.pop(scope, None)
        else:
            storage = source_storage
        storage, refresh_whole_baseline = _clarity_shelf_merge_disk_storage(
            storage,
            changed_scopes,
            path,
        )
        with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=os.path.dirname(path),
                prefix=os.path.basename(path) + ".",
                suffix=".tmp",
                delete=False,
        ) as handle:
            temp_path = handle.name
            json.dump(
                storage,
                handle,
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            )
        with open(temp_path, "rb") as handle:
            written_content = handle.read()
        os.replace(temp_path, path)
        storage_shelves = storage.get("shelves", {})
        if changed_scopes:
            for scope in changed_scopes:
                if scope in storage_shelves:
                    _clarity_shelf_scope_baselines[scope] = copy.deepcopy(
                        storage_shelves[scope],
                    )
                else:
                    _clarity_shelf_scope_baselines.pop(scope, None)
            _clarity_shelf_pending_scopes.difference_update(changed_scopes)
        else:
            _clarity_shelf_scope_baselines.clear()
            if isinstance(storage_shelves, dict):
                _clarity_shelf_scope_baselines.update(copy.deepcopy(storage_shelves))
            _clarity_shelf_pending_scopes.clear()
        if refresh_whole_baseline:
            _clarity_shelf_storage_baseline_content = written_content
        else:
            # Runtime scopes not touched by this save may still be older than the
            # merged disk graph. Never use a historical whole-file snapshot as a
            # fast-path marker after that happens.
            _clarity_shelf_storage_baseline_content = _CLARITY_SHELF_INVALID_STORAGE_BASELINE
        if _clarity_shelf_future_storage is not None:
            _clarity_shelf_future_storage = copy.deepcopy(storage)
        return ""
    except (OSError, TypeError, ValueError) as ex:
        error = "Unable to save shelf config: {:s}".format(str(ex))
        print("Clarity shelf: {:s} ({:s})".format(error, path))
        return error
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
        if lock_path:
            try:
                os.remove(lock_path)
            except OSError:
                pass


def _clarity_shelf_active_tab(context=None):
    return _clarity_shelf_tab_for_config(_clarity_shelf_config(context))


def _clarity_shelf_tab_for_config(config):
    active = config.get("active")
    tab = next((tab for tab in config["tabs"] if tab["name"] == active), None)
    if tab is None:
        tab = config["tabs"][0]
        config["active"] = tab["name"]
    return tab


def _clarity_shelf_config_for_scope(scope):
    config, created = _clarity_shelf_scope_config(scope)
    if created:
        changed_scopes = {scope}
        if _clarity_shelf_save(changed_scopes):
            _clarity_shelf_pending_scopes.update(changed_scopes)
    return config


def _clarity_shelf_active_tab_for_scope(scope):
    return _clarity_shelf_tab_for_config(_clarity_shelf_config_for_scope(scope))


def _clarity_shelf_find_item(tab, item_id):
    if not item_id:
        return None
    return next((item for item in tab["items"] if item["id"] == item_id), None)


def _clarity_shelf_find_separator(tab, item_id):
    if not item_id:
        return None
    return next(
        (separator for separator in tab["separators"] if separator["id"] == item_id),
        None,
    )


def _clarity_shelf_row_items(tab, row_index):
    return [item for item in tab["items"] if item.get("row", 0) == row_index]


def _clarity_shelf_row_entries(tab, row_index, scope=None):
    """Visual entries of one Top Bar row, including every separator."""
    if scope is None:
        scope = _clarity_shelf_active_scope
    cache_key = (scope, tab["name"], row_index)
    cached = _clarity_shelf_row_cache.get(cache_key)
    if cached is not None:
        return cached

    items = _clarity_shelf_row_items(tab, row_index)
    separators_by_column = {}
    for separator in tab["separators"]:
        if separator.get("row", 0) != row_index:
            continue
        column = min(max(separator.get("column", 0), 0), len(items))
        separators_by_column.setdefault(column, []).append(separator)

    entries = []
    for column in range(len(items) + 1):
        entries.extend(
            ("SEPARATOR", separator)
            for separator in separators_by_column.get(column, ())
        )
        if column < len(items):
            entries.append(("ITEM", items[column]))
    cached = tuple(entries)
    _clarity_shelf_row_cache[cache_key] = cached
    return cached


def _clarity_shelf_sort_separators(tab):
    tab["separators"].sort(
        key=lambda separator: (separator.get("row", 0), separator.get("column", 0)),
    )


def _clarity_shelf_invalidate_layout():
    """Drop cached row grouping after the config object graph changes."""
    _clarity_shelf_row_cache.clear()


def _clarity_shelf_redraw(context, *, layout_changed=False):
    if layout_changed:
        _clarity_shelf_invalidate_layout()

    context_area = getattr(context, "area", None)
    if context_area is not None and context_area.type in {'TOPBAR', 'SHELF'}:
        context_area.tag_redraw()

    # Regular screen areas do not contain global Top Bar areas. Keep this fallback for
    # non-global/custom screens, while the context area above handles the normal case.
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type in {'TOPBAR', 'SHELF'}:
                area.tag_redraw()
    if hasattr(bpy.ops.topbar, "shelf_global_redraw"):
        bpy.ops.topbar.shelf_global_redraw()


def _clarity_shelf_commit(
        context,
        operator=None,
        *,
        layout_changed=True,
        changed_scopes=None,
        retry_on_error=True,
):
    """Persist a shelf mutation, report failures and refresh every visible shelf."""
    if changed_scopes is None:
        changed_scopes = {_clarity_shelf_active_scope}
    else:
        changed_scopes = set(changed_scopes)
    future_scopes = {}
    for scope in changed_scopes:
        future_scope = _clarity_shelf_future_scope_storage.pop(scope, None)
        if future_scope is not None:
            future_scopes[scope] = future_scope
    error = _clarity_shelf_save(changed_scopes)
    if error:
        if retry_on_error:
            _clarity_shelf_pending_scopes.update(changed_scopes)
        else:
            _clarity_shelf_future_scope_storage.update(future_scopes)
    _clarity_shelf_redraw(context, layout_changed=layout_changed)
    if error and operator is not None:
        operator.report({'ERROR'}, error)
    return not error


def _clarity_shelf_apply_row_entries(tab, row_index, entries):
    """Write a flat visual row back to the item/column JSON representation."""
    rows = {
        candidate_row: (
            [] if candidate_row == row_index
            else _clarity_shelf_row_items(tab, candidate_row)
        )
        for candidate_row in range(_CLARITY_SHELF_ROW_COUNT)
    }
    separators = [
        separator for separator in tab["separators"]
        if separator.get("row", 0) != row_index
    ]
    for entry_type, entry in entries:
        entry["row"] = row_index
        if entry_type == "ITEM":
            rows[row_index].append(entry)
        else:
            entry["column"] = len(rows[row_index])
            separators.append(entry)
    tab["items"] = [
        item for candidate_row in range(_CLARITY_SHELF_ROW_COUNT)
        for item in rows[candidate_row]
    ]
    tab["separators"] = separators
    _clarity_shelf_sort_separators(tab)


def _clarity_shelf_reorder(item_id, target_row, target_index):
    """Move an icon or separator by visual insertion index."""
    tab = _clarity_shelf_active_tab()
    entry = _clarity_shelf_find_item(tab, item_id)
    if entry is None:
        entry = _clarity_shelf_find_separator(tab, item_id)
    if entry is None:
        return False

    target_row = min(max(target_row, 0), _CLARITY_SHELF_ROW_COUNT - 1)
    source_row = entry.get("row", 0)
    source_entries = list(_clarity_shelf_row_entries(tab, source_row))
    source_index = next(
        (
            index for index, (_entry_type, candidate) in enumerate(source_entries)
            if candidate is entry
        ),
        None,
    )
    if source_index is None:
        return False

    moved_entry = source_entries.pop(source_index)
    if source_row == target_row:
        if source_index < target_index:
            target_index -= 1
        insert_index = min(max(target_index, 0), len(source_entries))
        if insert_index == source_index:
            return False
        source_entries.insert(insert_index, moved_entry)
        _clarity_shelf_apply_row_entries(tab, source_row, source_entries)
        return True

    target_entries = list(_clarity_shelf_row_entries(tab, target_row))
    insert_index = min(max(target_index, 0), len(target_entries))
    target_entries.insert(insert_index, moved_entry)
    _clarity_shelf_apply_row_entries(tab, source_row, source_entries)
    _clarity_shelf_apply_row_entries(tab, target_row, target_entries)
    return True


def _clarity_shelf_apply_adaptive_entries(tab, entries):
    """Rewrite a tab from a flat entry list, the shape the shelf editor works in."""
    tab["items"] = []
    tab["separators"] = []
    item_column = 0
    for entry_type, entry in entries:
        entry["row"] = 0
        if entry_type == "ITEM":
            tab["items"].append(entry)
            item_column += 1
        else:
            entry["column"] = item_column
            tab["separators"].append(entry)


def _clarity_shelf_reorder_adaptive(item_id, target_index):
    tab = _clarity_shelf_active_tab()
    entries = _clarity_shelf_adaptive_entries(tab)
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
    target_index = min(max(target_index, 0), len(entries))
    if target_index == source_index:
        return False
    entries.insert(target_index, entry)
    _clarity_shelf_apply_adaptive_entries(tab, entries)
    return True


def _clarity_shelf_entry_remove(tab, item_id):
    item = _clarity_shelf_find_item(tab, item_id)
    if item is not None:
        row = item.get("row", 0)
        index = _clarity_shelf_row_items(tab, row).index(item)
        tab["items"].remove(item)
        for separator in tab["separators"]:
            if separator.get("row", 0) == row and separator.get("column", 0) > index:
                separator["column"] -= 1
        return "ITEM", item

    separator = _clarity_shelf_find_separator(tab, item_id)
    if separator is not None:
        tab["separators"].remove(separator)
        return "SEPARATOR", separator
    return None, None


def _clarity_shelf_entry_insert_row(tab, entry_type, entry, row, index, scope=None):
    row = min(max(row, 0), _CLARITY_SHELF_ROW_COUNT - 1)
    entries = list(_clarity_shelf_row_entries(tab, row, scope))
    entries.insert(min(max(index, 0), len(entries)), (entry_type, entry))
    _clarity_shelf_apply_row_entries(tab, row, entries)


def _clarity_shelf_entry_insert_adaptive(tab, entry_type, entry, index, scope=None):
    entries = _clarity_shelf_adaptive_entries(tab, scope)
    entries.insert(min(max(index, 0), len(entries)), (entry_type, entry))
    _clarity_shelf_apply_adaptive_entries(tab, entries)


class TOPBAR_OT_clarity_shelf_tab(Operator):
    bl_idname = "topbar.clarity_shelf_tab"
    bl_label = "Clarity Shelf Tab"
    bl_options = {'INTERNAL'}

    tab: StringProperty()

    def execute(self, context):
        config = _clarity_shelf_config(context)
        if any(tab["name"] == self.tab for tab in config["tabs"]):
            config["active"] = self.tab
            if not _clarity_shelf_commit(context, self, layout_changed=False):
                return {'CANCELLED'}
        else:
            _clarity_shelf_redraw(context)
        return {'FINISHED'}


class TOPBAR_OT_clarity_shelf_tab_add(Operator):
    bl_idname = "topbar.clarity_shelf_tab_add"
    bl_label = "Add Shelf Tab"

    name: StringProperty(name="Name", default="New Shelf")

    def invoke(self, context, _event):
        _clarity_shelf_config(context)
        return context.window_manager.invoke_props_dialog(self, width=320)

    def execute(self, context):
        name = self.name.strip()
        config = _clarity_shelf_config(context)
        if not name or any(tab["name"] == name for tab in config["tabs"]):
            self.report({'WARNING'}, "Enter a unique shelf name")
            return {'CANCELLED'}
        config["tabs"].append({"name": name, "items": [], "separators": []})
        config["active"] = name
        return {'FINISHED'} if _clarity_shelf_commit(context, self) else {'CANCELLED'}


class TOPBAR_OT_clarity_shelf_tab_rename(Operator):
    bl_idname = "topbar.clarity_shelf_tab_rename"
    bl_label = "Rename Shelf Tab"

    name: StringProperty(name="Name")

    def invoke(self, context, _event):
        self.name = _clarity_shelf_active_tab(context)["name"]
        return context.window_manager.invoke_props_dialog(self, width=320)

    def execute(self, context):
        name = self.name.strip()
        config = _clarity_shelf_config(context)
        tab = _clarity_shelf_tab_for_config(config)
        if not name or any(item is not tab and item["name"] == name for item in config["tabs"]):
            self.report({'WARNING'}, "Enter a unique shelf name")
            return {'CANCELLED'}
        tab["name"] = name
        config["active"] = name
        return {'FINISHED'} if _clarity_shelf_commit(context, self) else {'CANCELLED'}


class TOPBAR_OT_clarity_shelf_tab_remove(Operator):
    bl_idname = "topbar.clarity_shelf_tab_remove"
    bl_label = "Remove Shelf Tab"

    def execute(self, context):
        config = _clarity_shelf_config(context)
        if len(config["tabs"]) == 1:
            self.report({'WARNING'}, "At least one shelf tab is required")
            return {'CANCELLED'}
        tab = _clarity_shelf_tab_for_config(config)
        config["tabs"].remove(tab)
        config["active"] = config["tabs"][0]["name"]
        return {'FINISHED'} if _clarity_shelf_commit(context, self) else {'CANCELLED'}


class _ClarityShelfItemDialog:
    """Shared properties, layout and validation of the Add/Edit shelf icon dialogs.

    Blender collects property annotations from non-RNA base classes, so keeping them
    here means the two dialogs cannot drift apart.
    """

    label: StringProperty(name="Tooltip")
    command_type: EnumProperty(
        name="Action",
        items=_CLARITY_SHELF_COMMAND_TYPES,
        default='BUILTIN',
    )
    # Fallback for the selected action when `actions` was never filled, which happens
    # when the operator runs without its dialog. The catalog is too large to expose as
    # an enum: building it would cost every startup, dialog or not.
    builtin_action: StringProperty(default="cube", options={'HIDDEN', 'SKIP_SAVE'})
    actions: CollectionProperty(type=TOPBAR_PG_clarity_shelf_action)
    action_index: IntProperty(
        name="Built-in Action",
        default=0,
        update=_clarity_shelf_action_index_update,
    )
    action_category: EnumProperty(
        name="Category",
        items=_CLARITY_SHELF_ACTION_CATEGORIES,
        default='ALL',
    )
    action_sort: EnumProperty(
        name="Sort",
        items=_CLARITY_SHELF_ACTION_SORT_MODES,
        default='CATEGORY',
    )
    operator_id: StringProperty(name="Operator", default="mesh.primitive_cube_add")
    script_source: EnumProperty(
        name="Script Source",
        items=_CLARITY_SHELF_SCRIPT_SOURCES,
        default='INLINE',
    )
    script_code: StringProperty(name="Python Code")
    script_text: StringProperty(name="Text Block")
    script_file: StringProperty(name="Python File", subtype='FILE_PATH')
    icons: CollectionProperty(type=TOPBAR_PG_clarity_shelf_icon)
    icon_index: IntProperty(name="Blender Icon", default=0)
    custom_icon: StringProperty(name="Custom Icon", subtype='FILE_PATH')
    background_color: FloatVectorProperty(
        name="Background Color",
        description="Button background color and opacity",
        subtype='COLOR',
        size=4,
        min=0.0,
        max=1.0,
        default=_CLARITY_SHELF_DEFAULT_BACKGROUND_COLOR,
    )
    icon_color: FloatVectorProperty(
        name="Icon Color",
        description="Icon tint and opacity",
        subtype='COLOR',
        size=4,
        min=0.0,
        max=1.0,
        default=_CLARITY_SHELF_DEFAULT_ICON_COLOR,
    )
    short_text: StringProperty(
        name="Short Text",
        description="Short label shown next to the icon",
        maxlen=5,
    )

    # Set by subclasses that let the user pick a Top Bar row.
    draw_row_property = False

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
                "TOPBAR_UL_clarity_shelf_actions",
                "",
                self,
                "actions",
                self,
                "action_index",
                rows=9,
                maxrows=9,
                sort_lock=True,
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
            "TOPBAR_UL_clarity_shelf_icons",
            "",
            self,
            "icons",
            self,
            "icon_index",
            rows=8,
            maxrows=8,
        )
        layout.prop(self, "custom_icon")
        _clarity_shelf_draw_icon_preview(layout, self)
        layout.prop(self, "background_color")
        layout.prop(self, "icon_color")
        layout.prop(self, "short_text")
        if self.draw_row_property:
            layout.prop(self, "row")

    def _validated_command(self):
        """Return (command values, error). `command` holds the keys of a shelf item."""
        operator_id = self.operator_id.strip()
        command = {
            "action": "",
            "operator": "",
            "command_type": self.command_type,
            "script_source": "",
            "script_code": "",
            "script_text": "",
            "script_file": "",
        }
        if self.command_type == 'OPERATOR':
            try:
                _clarity_shelf_operator(operator_id)
            except RuntimeError:
                return None, "Unknown Blender operator"
            command["operator"] = operator_id
        elif self.command_type == 'PYTHON':
            script_settings, error = _clarity_shelf_script_settings(self)
            if error:
                return None, error
            command.update(script_settings)
        else:
            command["action"] = _clarity_shelf_selected_action(self)
        return command, ""

    def _validated_appearance(self, command):
        """Return (appearance values, error) for the icon and color properties."""
        if self.icons and 0 <= self.icon_index < len(self.icons):
            icon = self.icons[self.icon_index].identifier
        else:
            # Run without its dialog, so the icon list was never filled. A built-in
            # action still knows which icon it wants.
            icon = _clarity_shelf_builtin_action_icons().get(command["action"], "")
        if not icon:
            return None, "Select a Blender icon"

        custom_icon = self.custom_icon.strip()
        if custom_icon:
            custom_icon = os.path.abspath(bpy.path.abspath(custom_icon))
            if not os.path.isfile(custom_icon):
                return None, "Custom icon file does not exist"
            if not _clarity_shelf_custom_icon(custom_icon, force_reload=True):
                return None, "Unsupported custom icon image"
        return {
            "icon": icon,
            "custom_icon": custom_icon,
            "background_color": list(self.background_color),
            "icon_color": list(self.icon_color),
            "short_text": self.short_text.strip(),
        }, ""

    def _default_label(self, command):
        if command["command_type"] == 'BUILTIN':
            return _clarity_shelf_builtin_action_labels().get(
                command["action"], "Shelf Command",
            )
        if command["command_type"] == 'OPERATOR':
            return command["operator"]
        return "Python Script"


class TOPBAR_OT_clarity_shelf_item_add(_ClarityShelfItemDialog, Operator):
    bl_idname = "topbar.clarity_shelf_item_add"
    bl_label = "Add Shelf Icon"

    row: IntProperty(name="Row", default=0, min=0, max=_CLARITY_SHELF_ROW_COUNT - 1)

    draw_row_property = True

    def invoke(self, context, _event):
        _clarity_shelf_config(context)
        # Operator properties are remembered between runs, so the sentinel the
        # auto-label in `execute` looks for has to be restored explicitly.
        self.label = "New Command"
        _clarity_shelf_action_list_fill(self, "cube")
        _clarity_shelf_icon_list_fill(self, "MESH_CUBE")
        return context.window_manager.invoke_props_dialog(self, width=600)

    def execute(self, context):
        tab = _clarity_shelf_active_tab(context)
        command, error = self._validated_command()
        if error:
            self.report({'WARNING'}, error)
            return {'CANCELLED'}
        appearance, error = self._validated_appearance(command)
        if error:
            self.report({'WARNING'}, error)
            return {'CANCELLED'}

        label = self.label.strip()
        if not label or label == "New Command":
            label = self._default_label(command)

        tab["items"].append({
            "id": uuid.uuid4().hex,
            "label": label,
            "row": self.row,
            **command,
            **appearance,
        })
        return {'FINISHED'} if _clarity_shelf_commit(context, self) else {'CANCELLED'}


class TOPBAR_OT_clarity_shelf_item_edit(_ClarityShelfItemDialog, Operator):
    bl_idname = "topbar.clarity_shelf_item_edit"
    bl_label = "Edit Shelf Icon"

    item_id: StringProperty(options={'SKIP_SAVE'})

    def invoke(self, context, _event):
        item = _clarity_shelf_find_item(_clarity_shelf_active_tab(context), self.item_id)
        if item is None:
            return {'CANCELLED'}
        self.operator_id = item.get("operator", "")
        self.command_type = item.get(
            "command_type",
            'OPERATOR' if self.operator_id else 'BUILTIN',
        )
        action = item.get("action", "")
        self.builtin_action = action or "select_box"
        _clarity_shelf_action_list_fill(self, self.builtin_action)
        self.label = item.get("label", "")
        self.script_source = item.get("script_source", "INLINE") or 'INLINE'
        self.script_code = item.get("script_code", "")
        self.script_text = item.get("script_text", "")
        self.script_file = item.get("script_file", "")
        _clarity_shelf_icon_list_fill(self, item.get("icon", 'NONE'))
        self.custom_icon = item.get("custom_icon", "")
        self.background_color = item.get(
            "background_color", _CLARITY_SHELF_DEFAULT_BACKGROUND_COLOR,
        )
        self.icon_color = item.get("icon_color", _CLARITY_SHELF_DEFAULT_ICON_COLOR)
        self.short_text = item.get("short_text", "")
        return context.window_manager.invoke_props_dialog(self, width=600)

    def execute(self, context):
        item = _clarity_shelf_find_item(_clarity_shelf_active_tab(context), self.item_id)
        if item is None:
            return {'CANCELLED'}

        command, error = self._validated_command()
        if error:
            self.report({'WARNING'}, error)
            return {'CANCELLED'}
        appearance, error = self._validated_appearance(command)
        if error:
            self.report({'WARNING'}, error)
            return {'CANCELLED'}

        item["label"] = self.label.strip() or item.get("label", "Shelf Command")
        item.update(command)
        item.update(appearance)
        return (
            {'FINISHED'}
            if _clarity_shelf_commit(context, self, layout_changed=False)
            else {'CANCELLED'}
        )


class TOPBAR_OT_clarity_shelf_item_remove_id(Operator):
    bl_idname = "topbar.clarity_shelf_item_remove_id"
    bl_label = "Remove from Shelf"
    # No 'UNDO': the shelf lives in its own config file, not in the undo stack.
    bl_options = {'INTERNAL'}

    item_id: StringProperty()

    def execute(self, context):
        tab = _clarity_shelf_active_tab(context)
        entry_type, _entry = _clarity_shelf_entry_remove(tab, self.item_id)
        if entry_type is None:
            return {'CANCELLED'}
        return {'FINISHED'} if _clarity_shelf_commit(context, self) else {'CANCELLED'}


class TOPBAR_OT_clarity_shelf_separator_add(Operator):
    bl_idname = "topbar.clarity_shelf_separator_add"
    bl_label = "Add Shelf Separator"
    bl_options = {'INTERNAL'}

    column: IntProperty(default=-1, min=-1, options={'SKIP_SAVE'})
    row: IntProperty(
        default=0, min=0, max=_CLARITY_SHELF_ROW_COUNT - 1, options={'SKIP_SAVE'},
    )

    def execute(self, context):
        tab = _clarity_shelf_active_tab(context)
        column = self.column
        if column < 0:
            column = len(_clarity_shelf_row_items(tab, self.row))
        tab["separators"].append({
            "id": uuid.uuid4().hex,
            "column": column,
            "row": self.row,
        })
        _clarity_shelf_sort_separators(tab)
        return {'FINISHED'} if _clarity_shelf_commit(context, self) else {'CANCELLED'}


def _clarity_shelf_separator_insert_column(tab, item, separator, fallback_row):
    """Column a new separator should take when added next to an existing entry."""
    if item is not None:
        return _clarity_shelf_row_items(tab, item.get("row", 0)).index(item) + 1
    if separator is not None:
        return separator.get("column", 0)
    return len(_clarity_shelf_row_items(tab, fallback_row))


class TOPBAR_OT_clarity_shelf_context_menu(Operator):
    bl_idname = "topbar.clarity_shelf_context_menu"
    bl_label = "Shelf Context Menu"
    bl_options = {'INTERNAL'}

    item_id: StringProperty(options={'SKIP_SAVE'})
    row: IntProperty(
        default=0, min=0, max=_CLARITY_SHELF_ROW_COUNT - 1, options={'SKIP_SAVE'},
    )

    def invoke(self, context, _event):
        _clarity_shelf_config(context)
        context.window_manager.popup_menu(self.draw_menu, title="Shelf")
        return {'FINISHED'}

    def draw_menu(self, menu, context):
        config = _clarity_shelf_config(context)
        layout = menu.layout
        layout.operator_context = 'INVOKE_DEFAULT'
        tab = _clarity_shelf_tab_for_config(config)
        item = _clarity_shelf_find_item(tab, self.item_id)
        separator = _clarity_shelf_find_separator(tab, self.item_id)
        entry_row = (
            item.get("row", self.row) if item is not None
            else separator.get("row", self.row) if separator is not None
            else self.row
        )
        if not self.item_id:
            layout.label(text="Shelf Tabs")
            for shelf_tab in config["tabs"]:
                props = layout.operator(
                    "topbar.clarity_shelf_tab",
                    text=shelf_tab["name"],
                    icon='CHECKMARK' if shelf_tab is tab else 'BLANK1',
                )
                props.tab = shelf_tab["name"]
            layout.separator()
            layout.operator(
                "topbar.clarity_shelf_tab_add",
                text="Add Shelf Tab",
                icon='ADD',
            )
            layout.operator(
                "topbar.clarity_shelf_tab_rename",
                text="Rename Active Tab",
                icon='GREASEPENCIL',
            )
            layout.operator(
                "topbar.clarity_shelf_tab_remove",
                text="Remove Active Tab",
                icon='X',
            )
            layout.separator()

        props = layout.operator(
            "topbar.clarity_shelf_item_add",
            text="Add Shelf Icon",
            icon='ADD',
        )
        props.row = entry_row

        props = layout.operator(
            "topbar.clarity_shelf_separator_add",
            text="Add Separator",
            icon='SPLIT_VERTICAL',
        )
        props.column = _clarity_shelf_separator_insert_column(
            tab, item, separator, entry_row,
        )
        props.row = entry_row

        if self.item_id:
            layout.separator()
            if item is not None:
                props = layout.operator(
                    "topbar.clarity_shelf_item_edit",
                    text="Edit Shelf Icon",
                    icon='GREASEPENCIL',
                )
                props.item_id = item["id"]
            props = layout.operator(
                "topbar.clarity_shelf_item_remove_id",
                text="Remove Separator" if separator is not None else "Remove from Shelf",
                icon='TRASH',
            )
            props.item_id = self.item_id


class TOPBAR_OT_clarity_shelf_drag(Operator):
    bl_idname = "topbar.clarity_shelf_drag"
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
    def _probe():
        """Refresh `_clarity_shelf_drag_hover` from the real button layout.

        The hit test has to live in C++, because only it can see the rectangles the layout
        engine produced, and it has to be pulled from here rather than pushed from a shelf
        region handler: a modal operator returning `PASS_THROUGH` still yields
        `WM_HANDLER_BREAK`, and `wm_event_do_handlers` then skips every region handler.
        """
        bpy.ops.topbar.clarity_shelf_drag_probe()

    def _drop_target(self, context, _event):
        """Where the dragged entry would land: (scope, adaptive, row, index).

        Scope is None when the cursor is over no shelf. Everything is derived from the
        last probe, so the drop cannot disagree with the marker the user sees.
        """
        hover = _clarity_shelf_drag_hover
        if hover is None:
            return None, None, None, None

        scope = hover["scope"]
        adaptive = hover["adaptive"]
        row = hover["row"]
        tab = _clarity_shelf_active_tab_for_scope(scope)
        if adaptive:
            entries = _clarity_shelf_adaptive_entries(tab, scope)
        else:
            entries = _clarity_shelf_row_entries(tab, row, scope)

        index = next(
            (
                entry_index
                for entry_index, (_entry_type, entry) in enumerate(entries)
                if entry["id"] == hover["item_id"]
            ),
            None,
        )
        if index is None:
            # An empty shelf reports no entry, so append. On the source surface that cannot
            # happen, and staying put is the safe answer there.
            if (
                scope == self._source_scope and
                adaptive == self._adaptive and
                row == self._source_row
            ):
                return scope, adaptive, row, self._source_index
            return scope, adaptive, row, len(entries)
        return scope, adaptive, row, index + (1 if hover["after"] else 0)

    def _preview_begin(self, context):
        global _clarity_shelf_drag_state
        global _clarity_shelf_drag_hover
        self._preview_active = True
        _clarity_shelf_drag_hover = None
        _clarity_shelf_drag_state = {
            "kind": "separator" if self._drag_separator else "icon",
            "item_id": self.item_id,
            "source_scope": self._source_scope,
            "source_row": self._source_row,
            "source_index": self._source_index,
        }

    def _preview_end(self, context):
        global _clarity_shelf_drag_state
        global _clarity_shelf_drag_hover
        if not getattr(self, "_preview_active", False):
            return
        self._preview_active = False
        _clarity_shelf_drag_state = None
        _clarity_shelf_drag_hover = None
        # Stops the C++ side from hit testing and drawing the insertion marker.
        if hasattr(bpy.ops.topbar, "clarity_shelf_drag_end"):
            bpy.ops.topbar.clarity_shelf_drag_end()

    def invoke(self, context, _event):
        if not hasattr(bpy.ops.topbar, "clarity_shelf_drag_probe"):
            # Without the hit test there is no way to tell where the icon would land, and a
            # silent no-op would look like a broken shelf.
            self.report(
                {'ERROR'},
                "Shelf drag needs a rebuilt Blender: topbar.clarity_shelf_drag_probe is missing",
            )
            return {'CANCELLED'}

        tab = _clarity_shelf_active_tab(context)
        self._source_scope = _clarity_shelf_active_scope
        self._adaptive = context.area.type == 'SHELF'
        source_separator = _clarity_shelf_find_separator(tab, self.item_id)
        self._drag_separator = source_separator is not None
        source_entry = source_separator
        if source_entry is None:
            source_entry = _clarity_shelf_find_item(tab, self.item_id)
        if source_entry is None:
            return {'CANCELLED'}
        row = source_entry.get("row", 0)

        if self._adaptive:
            entries = _clarity_shelf_adaptive_entries(tab, self._source_scope)
        else:
            entries = _clarity_shelf_row_entries(tab, row, self._source_scope)
        index = next(
            (
                entry_index
                for entry_index, (_entry_type, entry) in enumerate(entries)
                if entry is source_entry
            ),
            None,
        )
        if index is None:
            return {'CANCELLED'}

        if self._adaptive:
            row = 0

        self._source_row = row
        self._source_index = index
        self._preview_begin(context)
        context.window_manager.modal_handler_add(self)
        _clarity_shelf_redraw(context)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        _clarity_shelf_config(context)
        if event.type == 'MOUSEMOVE':
            # The probe also tags the redraw that moves the insertion marker, but only when
            # the target boundary actually changes.
            self._probe()
            return {'RUNNING_MODAL', 'PASS_THROUGH'}

        if event.type == 'MIDDLEMOUSE' and event.value == 'RELEASE':
            # Probe again so the drop never depends on the last motion event having arrived.
            self._probe()
            scope, adaptive, row, index = self._drop_target(context, event)
            if scope is None:
                self._preview_end(context)
                _clarity_shelf_redraw(context)
                return {'CANCELLED', 'PASS_THROUGH'}

            affected_scopes = {self._source_scope, scope}
            scope_configs = {
                affected_scope: _clarity_shelf_config_for_scope(affected_scope)
                for affected_scope in affected_scopes
            }
            config_backups = {
                affected_scope: copy.deepcopy(config)
                for affected_scope, config in scope_configs.items()
            }
            changed = False
            if scope != self._source_scope:
                source_tab = _clarity_shelf_tab_for_config(
                    scope_configs[self._source_scope],
                )
                target_tab = _clarity_shelf_tab_for_config(scope_configs[scope])
                entry_type, entry = _clarity_shelf_entry_remove(source_tab, self.item_id)
                if entry is not None:
                    target_ids = {
                        candidate["id"]
                        for candidate in target_tab["items"] + target_tab["separators"]
                    }
                    if entry["id"] in target_ids:
                        entry["id"] = uuid.uuid4().hex
                    if adaptive:
                        _clarity_shelf_entry_insert_adaptive(
                            target_tab,
                            entry_type,
                            entry,
                            index,
                            scope,
                        )
                    else:
                        _clarity_shelf_entry_insert_row(
                            target_tab,
                            entry_type,
                            entry,
                            row,
                            index,
                            scope,
                        )
                    changed = True
            elif adaptive:
                changed = _clarity_shelf_reorder_adaptive(self.item_id, index)
            else:
                changed = _clarity_shelf_reorder(self.item_id, row, index)
            self._preview_end(context)
            if changed:
                saved = _clarity_shelf_commit(
                    context,
                    self,
                    changed_scopes=affected_scopes,
                    retry_on_error=False,
                )
                if not saved:
                    for affected_scope, backup in config_backups.items():
                        config = scope_configs[affected_scope]
                        config.clear()
                        config.update(backup)
                    _clarity_shelf_redraw(context, layout_changed=True)
                    return {'CANCELLED', 'PASS_THROUGH'}
            else:
                _clarity_shelf_redraw(context)
            return {'FINISHED', 'PASS_THROUGH'}

        if event.type in {'ESC', 'RIGHTMOUSE', 'WINDOW_DEACTIVATE'}:
            self._preview_end(context)
            _clarity_shelf_redraw(context)
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}

    def cancel(self, context):
        self._preview_end(context)
        _clarity_shelf_redraw(context)


class TOPBAR_OT_clarity_shelf_drag_hover(Operator):
    """Record which shelf entry the drag cursor is over.

    Called by `topbar.clarity_shelf_drag_probe`, which owns the hit test because only C++ can
    see the button rectangles the layout engine produced. It runs this with the hovered
    shelf pushed into the context, so the scope and row are read from there.
    """
    bl_idname = "topbar.clarity_shelf_drag_hover"
    bl_label = "Shelf Drag Hover"
    bl_options = {'INTERNAL'}

    found: BoolProperty(default=True)
    item_id: StringProperty()
    after: BoolProperty(default=False)

    def execute(self, context):
        global _clarity_shelf_drag_hover
        area = getattr(context, "area", None)
        region = getattr(context, "region", None)
        if not self.found or area is None or area.type not in {'TOPBAR', 'SHELF'}:
            _clarity_shelf_drag_hover = None
            return {'CANCELLED'}

        if area.type == 'SHELF':
            scope = _clarity_shelf_layout_scope_key(context, area)
            adaptive = True
            row = 0
        else:
            scope = "TOPBAR"
            adaptive = False
            row = 0 if (region is not None and region.type == 'FOOTER') else 1
        if not scope:
            _clarity_shelf_drag_hover = None
            return {'CANCELLED'}

        _clarity_shelf_drag_hover = {
            "scope": scope,
            "adaptive": adaptive,
            "row": row,
            "item_id": self.item_id,
            "after": self.after,
        }
        return {'FINISHED'}


_CLARITY_SHELF_EDITOR_AREA_TYPES = {
    "graph_editor": 'GRAPH_EDITOR',
    "dope_sheet": 'DOPESHEET_EDITOR',
    "nla_editor": 'NLA_EDITOR',
}

_CLARITY_SHELF_SELECT_ACTIONS = {
    "select_all": 'SELECT',
    "select_none": 'DESELECT',
    "select_inverse": 'INVERT',
}
_CLARITY_SHELF_SELECT_OPERATOR_BY_MODE = {
    'EDIT_ARMATURE': "armature.select_all",
    'EDIT_CURVE': "curve.select_all",
    'EDIT_CURVES': "curves.select_all",
    'EDIT_GREASE_PENCIL': "grease_pencil.select_all",
    'EDIT_LATTICE': "lattice.select_all",
    'EDIT_MESH': "mesh.select_all",
    'EDIT_METABALL': "mball.select_all",
    'EDIT_POINTCLOUD': "pointcloud.select_all",
    'EDIT_SURFACE': "curve.select_all",
    'PARTICLE': "particle.select_all",
    'POSE': "pose.select_all",
    'SCULPT_CURVES': "curves.select_all",
}

_CLARITY_SHELF_SHADING_TYPES = {
    "view_wireframe": 'WIREFRAME',
    "view_solid": 'SOLID',
    "view_material": 'MATERIAL',
    "view_rendered": 'RENDERED',
}

_CLARITY_SHELF_OVERLAY_TOGGLES = {
    "toggle_overlays": "show_overlays",
    "toggle_grid": "show_floor",
    "toggle_wire_overlay": "show_wireframes",
    "toggle_face_orientation": "show_face_orientation",
    "toggle_statistics": "show_stats",
}

_CLARITY_SHELF_SPACE_TOGGLES = {
    "toggle_gizmos": "show_gizmo",
    "toggle_camera_lock": "lock_camera",
}

_CLARITY_SHELF_INTERPOLATION_TYPES = {
    "interpolation_constant": 'CONSTANT',
    "interpolation_linear": 'LINEAR',
    "interpolation_bezier": 'BEZIER',
}

# Actions that want a keyframe editor rather than the 3D Viewport.
_CLARITY_SHELF_ANIMATION_EDITOR_ACTIONS = frozenset({
    "duplicate_keyframes",
    "interpolation_constant",
    "interpolation_linear",
    "interpolation_bezier",
})
_CLARITY_SHELF_VIEW3D_CONTEXT_ACTIONS = frozenset({
    "rename_object",
    "viewport_screenshot",
})
_CLARITY_SHELF_CONTEXT_FREE_ACTIONS = frozenset({
    "append_file",
    "auto_key_toggle",
    "incremental_save",
    "link_file",
    "open_file",
    "open_render_result",
    "preferences",
    "purge_orphans",
    "render",
    "render_animation",
    "render_selected",
    "save",
    "save_as",
})
_CLARITY_SHELF_OPERATOR_AREA_PREFERENCES = {
    "action": ('DOPESHEET_EDITOR', 'GRAPH_EDITOR'),
    "anim": (
        'VIEW_3D',
        'DOPESHEET_EDITOR',
        'GRAPH_EDITOR',
        'NLA_EDITOR',
        'SEQUENCE_EDITOR',
    ),
    "armature": ('VIEW_3D',),
    "curve": ('VIEW_3D',),
    "curves": ('VIEW_3D',),
    "geometry": ('VIEW_3D',),
    "grease_pencil": ('VIEW_3D',),
    "lattice": ('VIEW_3D',),
    "mball": ('VIEW_3D',),
    "mesh": ('VIEW_3D',),
    "nla": ('VIEW_3D', 'NLA_EDITOR'),
    "node": ('NODE_EDITOR',),
    "object": ('VIEW_3D',),
    "paint": ('VIEW_3D', 'IMAGE_EDITOR'),
    "particle": ('VIEW_3D',),
    "pointcloud": ('VIEW_3D',),
    "poselib": ('VIEW_3D',),
    "pose": ('VIEW_3D',),
    "sculpt": ('VIEW_3D',),
    "sculpt_curves": ('VIEW_3D',),
    "transform": (
        'VIEW_3D',
        'GRAPH_EDITOR',
        'DOPESHEET_EDITOR',
        'NLA_EDITOR',
        'NODE_EDITOR',
        'IMAGE_EDITOR',
        'SEQUENCE_EDITOR',
        'CLIP_EDITOR',
    ),
    "uv": ('IMAGE_EDITOR', 'VIEW_3D'),
    "view3d": ('VIEW_3D',),
}


def _clarity_shelf_operator(idname):
    """Resolve and validate a `bpy.ops` idname."""
    try:
        module_name, operator_name = idname.split(".", 1)
        if not module_name or not operator_name:
            raise ValueError
        operator = getattr(getattr(bpy.ops, module_name), operator_name)
        operator.get_rna_type()
    except (AttributeError, KeyError, RuntimeError, TypeError, ValueError) as ex:
        raise RuntimeError("Unknown Blender operator: {:s}".format(idname)) from ex
    return operator


def _clarity_shelf_operator_context(context, idname):
    """Find an area/region where a custom operator actually polls."""
    operator = _clarity_shelf_operator(idname)
    module_name = idname.split(".", 1)[0]
    preferred_area_types = _CLARITY_SHELF_OPERATOR_AREA_PREFERENCES.get(
        module_name,
        (),
    )
    candidates = []
    if (
        context.area is not None and
        context.region is not None and
        context.area.type not in {'TOPBAR', 'SHELF'} and
        (
            not preferred_area_types or
            context.area.type in preferred_area_types
        )
    ):
        candidates.append((context.area, context.region))
    areas = list(context.screen.areas)
    areas.sort(
        key=lambda area: (
            preferred_area_types.index(area.type)
            if area.type in preferred_area_types
            else len(preferred_area_types)
        ),
    )
    for area in areas:
        if (
            area is context.area or
            area.type == 'SHELF' or
            (preferred_area_types and area.type not in preferred_area_types)
        ):
            continue
        region = next(
            (candidate for candidate in area.regions if candidate.type == 'WINDOW'),
            None,
        )
        if region is not None:
            candidates.append((area, region))
    if (
        context.area is not None and
        context.region is not None and
        not preferred_area_types and
        (context.area, context.region) not in candidates
    ):
        # Global WindowManager operators can legitimately poll in the shelf itself,
        # but editor-neutral poll callbacks must not make it the first choice.
        candidates.append((context.area, context.region))

    for area, region in candidates:
        try:
            with context.temp_override(
                    window=context.window,
                    screen=context.screen,
                    area=area,
                    region=region,
                    space_data=area.spaces.active,
            ):
                if operator.poll():
                    return area, region
        except (RuntimeError, TypeError):
            continue
    return None, None


def _clarity_shelf_action_context(context, action, operator_id):
    """Area and region used by one shelf command."""
    if action == "set_preview_range":
        return _clarity_shelf_operator_context(context, "anim.previewrange_set")
    if action in _CLARITY_SHELF_VIEW3D_CONTEXT_ACTIONS:
        area = next(
            (area for area in context.screen.areas if area.type == 'VIEW_3D'),
            None,
        )
        region = next(
            (region for region in area.regions if region.type == 'WINDOW'),
            None,
        ) if area is not None else None
        return area, region
    discovered_operator = ""
    if action.startswith("operator__"):
        parts = action.split("__", 2)
        if len(parts) == 3 and all(parts[1:]):
            discovered_operator = "{:s}.{:s}".format(parts[1], parts[2])
    if operator_id or discovered_operator:
        return _clarity_shelf_operator_context(
            context, operator_id or discovered_operator,
        )
    if action in _CLARITY_SHELF_CONTEXT_FREE_ACTIONS:
        return context.area, context.region
    if action in _CLARITY_SHELF_ANIMATION_EDITOR_ACTIONS:
        area = next(
            (
                area for area in context.screen.areas
                if area.type in {'GRAPH_EDITOR', 'DOPESHEET_EDITOR'}
            ),
            None,
        )
        if area is not None:
            region = next(
                (region for region in area.regions if region.type == 'WINDOW'),
                None,
            )
            return area, region
    area = next(
        (area for area in context.screen.areas if area.type == 'VIEW_3D'),
        None,
    )
    region = next(
        (region for region in area.regions if region.type == 'WINDOW'),
        None,
    ) if area is not None else None
    return area, region


def _clarity_shelf_call_operator(idname, properties, invoke=False):
    operator = _clarity_shelf_operator(idname)
    if invoke:
        status = operator('INVOKE_DEFAULT', **properties)
    else:
        status = operator(**properties)
    if status and 'CANCELLED' in status:
        raise RuntimeError("Blender operator cancelled: {:s}".format(idname))
    return status


def _clarity_shelf_run_script(context, item):
    """Run a Python shelf button. Returns an error message, empty when it succeeded."""
    source = item.get("script_source", "INLINE")
    filename = "<Shelf Button>"
    script_directory = ""
    path_inserted = False
    try:
        if source == 'TEXT':
            text_name = item.get("script_text", "")
            text = bpy.data.texts.get(text_name)
            if text is None:
                raise RuntimeError("Shelf text block was not found")
            code = text.as_string()
            filename = f"<Text:{text_name}>"
        elif source == 'FILE':
            filename = os.path.abspath(bpy.path.abspath(item.get("script_file", "")))
            script_directory = os.path.dirname(filename)
            with tokenize.open(filename) as handle:
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
        if script_directory and script_directory not in sys.path:
            sys.path.insert(0, script_directory)
            path_inserted = True
        area = next(
            (area for area in context.screen.areas if area.type == 'VIEW_3D'),
            None,
        )
        region = next(
            (region for region in area.regions if region.type == 'WINDOW'),
            None,
        ) if area is not None else None
        if area is not None and region is not None:
            with context.temp_override(area=area, region=region):
                namespace["context"] = bpy.context
                exec(compiled, namespace, namespace)
        else:
            exec(compiled, namespace, namespace)
    except Exception as ex:
        traceback.print_exc()
        return f"Shelf script failed: {ex}"
    finally:
        if path_inserted:
            try:
                sys.path.remove(script_directory)
            except ValueError:
                pass
    return ""


# Built-in actions that need more than a single operator call. Every handler takes
# (context, area, action) and raises with a user-facing message when it cannot run.

def _clarity_shelf_new_material(context, _area, _action):
    obj = context.active_object
    materials = getattr(getattr(obj, "data", None), "materials", None)
    if materials is None:
        raise RuntimeError("Select an object that supports materials")
    material = bpy.data.materials.new(name="Material")
    try:
        materials.append(material)
    except Exception:
        try:
            bpy.data.materials.remove(material)
        except Exception:
            pass
        raise


def _clarity_shelf_switch_editor(_context, area, action):
    area.type = _CLARITY_SHELF_EDITOR_AREA_TYPES[action]


def _clarity_shelf_select(context, _area, action):
    select_action = _CLARITY_SHELF_SELECT_ACTIONS[action]
    if context.mode == 'EDIT_TEXT':
        if select_action != 'SELECT':
            raise RuntimeError("Text Edit mode only supports Select All")
        _clarity_shelf_call_operator("font.select_all", {})
        return
    operator_id = _CLARITY_SHELF_SELECT_OPERATOR_BY_MODE.get(
        context.mode,
        "object.select_all",
    )
    _clarity_shelf_call_operator(operator_id, {"action": select_action})


def _clarity_shelf_set_shading(_context, area, action):
    area.spaces.active.shading.type = _CLARITY_SHELF_SHADING_TYPES[action]


def _clarity_shelf_toggle_xray(_context, area, _action):
    shading = area.spaces.active.shading
    shading.show_xray = not shading.show_xray


def _clarity_shelf_toggle_overlay(_context, area, action):
    overlay = area.spaces.active.overlay
    attribute = _CLARITY_SHELF_OVERLAY_TOGGLES[action]
    setattr(overlay, attribute, not getattr(overlay, attribute))


def _clarity_shelf_toggle_space(_context, area, action):
    space = area.spaces.active
    attribute = _CLARITY_SHELF_SPACE_TOGGLES[action]
    setattr(space, attribute, not getattr(space, attribute))


def _clarity_shelf_apply_active_modifier(context, _area, _action):
    obj = context.active_object
    if obj is None or not obj.modifiers:
        raise RuntimeError("The active object has no modifiers")
    modifier = obj.modifiers.active or obj.modifiers[-1]
    _clarity_shelf_call_operator(
        "object.modifier_apply",
        {"modifier": modifier.name},
    )


def _clarity_shelf_apply_all_modifiers(context, _area, _action):
    obj = context.active_object
    if obj is None or not obj.modifiers:
        raise RuntimeError("The active object has no modifiers")
    while obj.modifiers:
        _clarity_shelf_call_operator(
            "object.modifier_apply",
            {"modifier": obj.modifiers[0].name},
        )


def _clarity_shelf_apply_selected_modifiers(context, _area, _action):
    objects = [obj for obj in context.selected_editable_objects if obj.modifiers]
    if not objects:
        raise RuntimeError("Selected objects have no modifiers")
    active_object = context.view_layer.objects.active
    try:
        for obj in objects:
            context.view_layer.objects.active = obj
            while obj.modifiers:
                _clarity_shelf_call_operator(
                    "object.modifier_apply",
                    {"modifier": obj.modifiers[0].name},
                )
    finally:
        context.view_layer.objects.active = active_object


def _clarity_shelf_clear_constraints(context, _area, _action):
    obj = context.active_object
    if obj is None:
        raise RuntimeError("Select an object first")
    if obj.mode == 'POSE' and context.active_pose_bone is not None:
        context.active_pose_bone.constraints.clear()
    else:
        obj.constraints.clear()


def _clarity_shelf_edit_keyframes(_context, area, action):
    if area.type == 'GRAPH_EDITOR':
        module_name = "graph"
    elif area.type == 'DOPESHEET_EDITOR':
        module_name = "action"
    else:
        raise RuntimeError("Open a Dope Sheet or Graph Editor first")
    if action == "duplicate_keyframes":
        _clarity_shelf_call_operator(
            module_name + ".duplicate_move",
            {},
            invoke=True,
        )
    else:
        _clarity_shelf_call_operator(
            module_name + ".interpolation_type",
            {"type": _CLARITY_SHELF_INTERPOLATION_TYPES[action]},
        )


def _clarity_shelf_toggle_motion_paths(context, _area, _action):
    obj = context.active_object
    if obj is None:
        raise RuntimeError("Select an object first")
    if context.mode == 'POSE':
        pose_bones = context.selected_pose_bones or ()
        if not pose_bones:
            raise RuntimeError("Select at least one pose bone")
        if any(pose_bone.motion_path is not None for pose_bone in pose_bones):
            _clarity_shelf_call_operator("pose.paths_clear", {})
        else:
            _clarity_shelf_call_operator("pose.paths_calculate", {})
    elif obj.motion_path is None:
        _clarity_shelf_call_operator("object.paths_calculate", {})
    else:
        _clarity_shelf_call_operator(
            "object.paths_clear",
            {"only_selected": False},
        )


def _clarity_shelf_set_preview_range(_context, _area, _action):
    _clarity_shelf_call_operator("anim.previewrange_set", {}, invoke=True)


def _clarity_shelf_multires_subdivide(context, _area, _action):
    obj = context.active_object
    modifier = next(
        (modifier for modifier in obj.modifiers if modifier.type == 'MULTIRES'),
        None,
    ) if obj is not None else None
    if modifier is None:
        raise RuntimeError("Add a Multires modifier first")
    _clarity_shelf_call_operator(
        "object.multires_subdivide",
        {"modifier": modifier.name, "mode": 'CATMULL_CLARK'},
    )


def _clarity_shelf_incremental_save(_context, _area, _action):
    if not bpy.data.filepath:
        _clarity_shelf_call_operator(
            "wm.save_as_mainfile",
            {"show_save_modified_images_dialog": True},
            invoke=True,
        )
    else:
        _clarity_shelf_call_operator(
            "wm.save_mainfile",
            {
                "incremental": True,
                "show_save_modified_images_dialog": True,
            },
            invoke=True,
        )


def _clarity_shelf_render_selected(context, _area, _action):
    selected = set(context.selected_objects)
    if not selected:
        raise RuntimeError("Select at least one object")
    render_states = {obj: obj.hide_render for obj in context.scene.objects}
    try:
        for obj in context.scene.objects:
            obj.hide_render = obj not in selected
        _clarity_shelf_call_operator("render.render", {})
    finally:
        for obj, hide_render in render_states.items():
            obj.hide_render = hide_render


def _clarity_shelf_open_render_result(_context, _area, _action):
    image = bpy.data.images.get("Render Result")
    if image is None:
        raise RuntimeError("No Render Result is available")
    _clarity_shelf_call_operator("render.view_show", {}, invoke=True)


def _clarity_shelf_purge_orphans(_context, _area, _action):
    bpy.data.orphans_purge(do_recursive=True)


def _clarity_shelf_toggle_auto_key(context, _area, _action):
    tool_settings = context.scene.tool_settings
    tool_settings.use_keyframe_insert_auto = not tool_settings.use_keyframe_insert_auto


_CLARITY_SHELF_ACTION_HANDLERS = {
    "material": _clarity_shelf_new_material,
    "xray_toggle": _clarity_shelf_toggle_xray,
    "apply_active_modifier": _clarity_shelf_apply_active_modifier,
    "apply_all_modifiers": _clarity_shelf_apply_all_modifiers,
    "apply_selected_modifiers": _clarity_shelf_apply_selected_modifiers,
    "clear_constraints": _clarity_shelf_clear_constraints,
    "duplicate_keyframes": _clarity_shelf_edit_keyframes,
    "toggle_motion_paths": _clarity_shelf_toggle_motion_paths,
    "set_preview_range": _clarity_shelf_set_preview_range,
    "multires_subdivide": _clarity_shelf_multires_subdivide,
    "incremental_save": _clarity_shelf_incremental_save,
    "render_selected": _clarity_shelf_render_selected,
    "open_render_result": _clarity_shelf_open_render_result,
    "purge_orphans": _clarity_shelf_purge_orphans,
    "auto_key_toggle": _clarity_shelf_toggle_auto_key,
}
for _actions, _handler in (
        (_CLARITY_SHELF_EDITOR_AREA_TYPES, _clarity_shelf_switch_editor),
        (_CLARITY_SHELF_SELECT_ACTIONS, _clarity_shelf_select),
        (_CLARITY_SHELF_SHADING_TYPES, _clarity_shelf_set_shading),
        (_CLARITY_SHELF_OVERLAY_TOGGLES, _clarity_shelf_toggle_overlay),
        (_CLARITY_SHELF_SPACE_TOGGLES, _clarity_shelf_toggle_space),
        (_CLARITY_SHELF_INTERPOLATION_TYPES, _clarity_shelf_edit_keyframes),
):
    _CLARITY_SHELF_ACTION_HANDLERS.update(dict.fromkeys(_actions, _handler))
del _actions, _handler


_CLARITY_SHELF_OUTER_UNDO_ACTIONS = frozenset({
    "material",
    "clear_constraints",
    "purge_orphans",
})


class _ClarityShelfAction:
    """Shared dispatcher for regular actions and the few direct-data undo actions."""

    _outer_undo = False

    action: StringProperty()
    operator_id: StringProperty()
    item_id: StringProperty()
    tooltip: StringProperty(options={'SKIP_SAVE'})

    @classmethod
    def description(cls, _context, properties):
        return properties.tooltip

    def execute(self, context):
        tab = _clarity_shelf_active_tab(context)
        if _clarity_shelf_find_separator(tab, self.item_id) is not None:
            return {'CANCELLED'}

        action = self.action
        operator_id = self.operator_id
        command_type = 'BUILTIN' if action else 'OPERATOR' if operator_id else 'BUILTIN'
        item = None
        if self.item_id:
            item = _clarity_shelf_find_item(tab, self.item_id)
            if item is None:
                self.report({'WARNING'}, "Shelf item no longer exists")
                return {'CANCELLED'}
            command_type = item.get(
                "command_type",
                'OPERATOR' if item.get("operator") else 'BUILTIN',
            )
            if command_type == 'OPERATOR':
                action = ""
                operator_id = item.get("operator", "")
            else:
                action = item.get("action", "")
                operator_id = ""

        needs_outer_undo = (
            command_type == 'BUILTIN' and
            action in _CLARITY_SHELF_OUTER_UNDO_ACTIONS
        )
        if needs_outer_undo != self._outer_undo:
            self.report({'WARNING'}, "Shelf action changed; try again")
            return {'CANCELLED'}

        if command_type == 'PYTHON':
            if item is None:
                self.report({'WARNING'}, "Shelf script no longer exists")
                return {'CANCELLED'}
            error = _clarity_shelf_run_script(context, item)
            if error:
                self.report({'ERROR'}, error)
                return {'CANCELLED'}
            return {'FINISHED'}

        try:
            context_operator_id = operator_id
            if not context_operator_id and action not in _CLARITY_SHELF_ACTION_HANDLERS:
                _, operators, invoke_operators = self._action_tables()
                if action in invoke_operators:
                    context_operator_id = invoke_operators[action][0]
                elif action in operators:
                    context_operator_id = operators[action][0]
            area, region = _clarity_shelf_action_context(
                context,
                action,
                context_operator_id,
            )
            if area is None or region is None:
                self.report({'WARNING'}, "No compatible editor is available")
                return {'CANCELLED'}
            with context.temp_override(
                    window=context.window,
                    screen=context.screen,
                    area=area,
                    region=region,
                    space_data=area.spaces.active,
            ):
                self._run_action(context, area, action, operator_id)
        except Exception as ex:
            self.report({'WARNING'}, str(ex))
            return {'CANCELLED'}
        return {'FINISHED'}

    def _run_action(self, context, area, action, operator_id):
        """Dispatch one built-in action. Raises with a user-facing message on failure.

        The order matters: a tool wins over a handler, a handler over a plain operator
        call, and an explicit `operator_id` only applies when there is no action at all.
        """
        tool_actions, operators, invoke_operators = self._action_tables()

        tool = tool_actions.get(action)
        if tool is not None:
            _clarity_shelf_call_operator("wm.tool_set_by_id", {"name": tool})
            return

        handler = _CLARITY_SHELF_ACTION_HANDLERS.get(action)
        if handler is not None:
            handler(context, area, action)
            return

        entry = invoke_operators.get(action)
        if entry is not None:
            _clarity_shelf_call_operator(entry[0], entry[1], invoke=True)
            return

        if action.startswith("operator__"):
            parts = action.split("__", 2)
            if len(parts) != 3 or not all(parts[1:]):
                raise RuntimeError("Malformed shelf operator: {:s}".format(action))
            _clarity_shelf_call_operator(
                "{:s}.{:s}".format(parts[1], parts[2]), {}, invoke=True,
            )
            return

        if operator_id:
            _clarity_shelf_call_operator(operator_id, {}, invoke=True)
            return

        entry = operators.get(action)
        if entry is None:
            raise RuntimeError(
                "Unknown shelf action: {:s}".format(action or "(none)"))
        _clarity_shelf_call_operator(entry[0], entry[1])

    @staticmethod
    def _action_tables():
        """Action id to operator mappings. Built once, they are only read here."""
        tables = _clarity_shelf_catalog_cache.get("action_tables")
        if tables is not None:
            return tables

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
            "save": (
                "wm.save_mainfile",
                {"show_save_modified_images_dialog": True},
            ),
            "save_as": (
                "wm.save_as_mainfile",
                {"show_save_modified_images_dialog": True},
            ),
            "append_file": ("wm.append", {}),
            "link_file": ("wm.link", {}),
        }

        tables = (tool_actions, operators, invoke_operators)
        _clarity_shelf_catalog_cache["action_tables"] = tables
        return tables


class TOPBAR_OT_clarity_shelf_action(_ClarityShelfAction, Operator):
    bl_idname = "topbar.clarity_shelf_action"
    bl_label = "Clarity Shelf Action"
    bl_options = {'INTERNAL'}

    @classmethod
    def description(cls, context, properties):
        return _ClarityShelfAction.description(context, properties)

    def execute(self, context):
        return _ClarityShelfAction.execute(self, context)


class TOPBAR_OT_clarity_shelf_action_undo(_ClarityShelfAction, Operator):
    bl_idname = "topbar.clarity_shelf_action_undo"
    bl_label = "Clarity Shelf Action"
    bl_options = {'INTERNAL', 'UNDO'}

    _outer_undo = True

    @classmethod
    def description(cls, context, properties):
        return _ClarityShelfAction.description(context, properties)

    def execute(self, context):
        return _ClarityShelfAction.execute(self, context)


class TOPBAR_OT_clarity_shelf_preview(Operator):
    bl_idname = "topbar.clarity_shelf_preview"
    bl_label = "Icon Preview"
    bl_options = {'INTERNAL'}

    def execute(self, _context):
        return {'FINISHED'}


class WM_MT_button_context(Menu):
    """Shelf entries appended to the right-click menu of any button.

    `bl_ui.__init__` draws the contents of this legacy class inside the regular
    button context menu, so the shelf items are only added for shelf buttons.
    """

    bl_label = "Button Context Menu"

    def draw(self, context):
        button_operator = getattr(context, "button_operator", None)
        operator_rna = getattr(button_operator, "bl_rna", None)
        operator_identifier = getattr(operator_rna, "identifier", "")
        if operator_identifier not in {
            "TOPBAR_OT_clarity_shelf_action",
            "TOPBAR_OT_clarity_shelf_action_undo",
        }:
            return
        item_id = getattr(button_operator, "item_id", "")
        if not isinstance(item_id, str) or not item_id:
            return

        layout = self.layout
        tab = _clarity_shelf_active_tab(context)
        item = _clarity_shelf_find_item(tab, item_id)
        separator = _clarity_shelf_find_separator(tab, item_id)
        if item is None and separator is None:
            return
        row = (
            item.get("row", 0) if item is not None
            else separator.get("row", 0) if separator is not None
            else 0
        )

        layout.separator()
        props = layout.operator(
            "topbar.clarity_shelf_item_add",
            text="Add Shelf Icon",
            icon='ADD',
        )
        props.row = row
        props = layout.operator(
            "topbar.clarity_shelf_separator_add",
            text="Add Separator",
            icon='SPLIT_VERTICAL',
        )
        props.column = _clarity_shelf_separator_insert_column(tab, item, separator, row)
        props.row = row
        props = layout.operator(
            "topbar.clarity_shelf_item_remove_id",
            text="Remove Separator" if separator is not None else "Remove from Shelf",
            icon='TRASH',
        )
        props.item_id = item_id


def _clarity_shelf_is_drag_source(item_id):
    return (
        _clarity_shelf_drag_state is not None and
        _clarity_shelf_drag_state.get("kind") == "icon" and
        _clarity_shelf_drag_state.get("source_scope") == _clarity_shelf_active_scope and
        _clarity_shelf_drag_state.get("item_id") == item_id
    )


def _clarity_shelf_action_operator_id(item):
    command_type = item.get(
        "command_type",
        'OPERATOR' if item.get("operator") else 'BUILTIN',
    )
    if (
        command_type == 'BUILTIN' and
        item.get("action", "") in _CLARITY_SHELF_OUTER_UNDO_ACTIONS
    ):
        return "topbar.clarity_shelf_action_undo"
    return "topbar.clarity_shelf_action"


def _clarity_shelf_draw_separator_button(
        container,
        separator,
        *,
        units_x=None,
        scale_y=None,
        enabled=True,
):
    divider = container.row(align=True)
    if units_x is not None:
        divider.ui_units_x = units_x
    if scale_y is not None:
        divider.alignment = 'CENTER'
        divider.scale_y = scale_y
    divider.context_string_set("clarity_shelf_item_id", separator["id"])
    divider.context_string_set("clarity_shelf_separator", "1")
    divider.context_string_set(
        "clarity_shelf_background_color",
        _clarity_shelf_color_string((0.0, 0.0, 0.0, 0.0)),
    )
    divider.enabled = enabled
    props = divider.operator("topbar.clarity_shelf_action", text="|", emboss=False)
    props.item_id = separator["id"]


def _clarity_shelf_draw_item_button(
        cell,
        item,
        *,
        button_units_x,
        icon_scale_y,
        label_scale_y,
):
    """Draw one shelf icon plus its short label into `cell`.

    The colors travel to the C++ widget code as button context strings, which
    `topbar_shelf_button_colors_apply` reads back when laying the region out.
    """
    icon_line = cell.row(align=True)
    icon_line.alignment = 'CENTER'
    icon_line.scale_y = icon_scale_y
    button = icon_line.row(align=True)
    button.ui_units_x = button_units_x

    custom_icon = _clarity_shelf_custom_icon(item.get("custom_icon", ""))
    background_color = item.get(
        "background_color", _CLARITY_SHELF_DEFAULT_BACKGROUND_COLOR,
    )
    icon_color = item.get("icon_color", _CLARITY_SHELF_DEFAULT_ICON_COLOR)
    is_drag_source = _clarity_shelf_is_drag_source(item["id"])
    if is_drag_source:
        background_color = _CLARITY_SHELF_DRAG_SOURCE_COLOR
    if custom_icon:
        # A user image carries its own colors, only its opacity is configurable.
        icon_color = (1.0, 1.0, 1.0, icon_color[3])
    button.context_string_set(
        "clarity_shelf_drag_source", "1" if is_drag_source else "0",
    )
    button.context_string_set(
        "clarity_shelf_background_color", _clarity_shelf_color_string(background_color),
    )
    button.context_string_set(
        "clarity_shelf_icon_color", _clarity_shelf_color_string(icon_color),
    )

    operator_args = {"text": "", "emboss": True}
    if custom_icon:
        operator_args["icon_value"] = custom_icon
    else:
        operator_args["icon"] = item.get("icon", 'NONE')
    props = button.operator(_clarity_shelf_action_operator_id(item), **operator_args)
    props.action = item.get("action", "")
    props.operator_id = item.get("operator", "")
    props.item_id = item["id"]
    props.tooltip = item.get("label", "Shelf Command")

    label_line = cell.row(align=True)
    label_line.alignment = 'CENTER'
    label_line.scale_y = label_scale_y
    label_line.label(text=item.get("short_text", ""))


def _clarity_shelf_draw_icon_row(layout, row_index, context):
    tab = _clarity_shelf_active_tab(context)
    row = layout.row(align=False)
    row.alignment = 'LEFT'
    row.scale_x = 1.2
    row.scale_y = 1.0

    entries = _clarity_shelf_row_entries(tab, row_index)
    for entry_type, entry in entries:
        if entry_type == "SEPARATOR":
            _clarity_shelf_draw_separator_button(
                row,
                entry,
                units_x=0.55,
                enabled=False,
            )
            continue

        item_column = row.column(align=True)
        item_column.ui_units_x = 1.45
        item_column.context_string_set("clarity_shelf_item_id", entry["id"])
        _clarity_shelf_draw_item_button(
            item_column,
            entry,
            button_units_x=0.85,
            icon_scale_y=0.82,
            label_scale_y=0.68,
        )

    if entries and entries[-1][0] == "SEPARATOR":
        tail = row.row(align=True)
        tail.ui_units_x = 0.2
        tail.label(text="")


class TOPBAR_HT_clarity_shelf_upper(Header):
    bl_space_type = 'TOPBAR'
    bl_region_type = 'FOOTER'

    def draw(self, context):
        _clarity_shelf_draw_icon_row(self.layout, 0, context)


class TOPBAR_HT_clarity_shelf_lower(Header):
    bl_space_type = 'TOPBAR'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        _clarity_shelf_draw_icon_row(self.layout, 1, context)


def _clarity_shelf_adaptive_entries(tab, scope=None):
    """Flatten a tab into the single ordered list the Shelf editor lays out."""
    entries = []
    for row_index in range(_CLARITY_SHELF_ROW_COUNT):
        entries.extend(_clarity_shelf_row_entries(tab, row_index, scope))
    return entries


def _clarity_shelf_draw_adaptive(layout, context):
    tab = _clarity_shelf_active_tab(context)
    flow = layout.grid_flow(
        row_major=True,
        columns=0,
        even_columns=True,
        even_rows=True,
        align=True,
    )
    flow.scale_x = 1.05
    flow.scale_y = 1.0

    for entry_type, entry in _clarity_shelf_adaptive_entries(tab):
        cell = flow.column(align=True)
        cell.ui_units_x = 1.55

        cell.context_string_set("clarity_shelf_item_id", entry["id"])
        if entry_type == "SEPARATOR":
            _clarity_shelf_draw_separator_button(
                cell,
                entry,
                scale_y=1.6,
            )
            continue

        _clarity_shelf_draw_item_button(
            cell,
            entry,
            button_units_x=0.95,
            icon_scale_y=0.9,
            label_scale_y=0.7,
        )


class SHELF_MT_tabs(Menu):
    bl_label = "Shelf Tabs"

    def draw(self, context):
        layout = self.layout
        config = _clarity_shelf_config(context)
        active_tab = _clarity_shelf_tab_for_config(config)
        for tab in config["tabs"]:
            props = layout.operator(
                "topbar.clarity_shelf_tab",
                text=tab["name"],
                icon='CHECKMARK' if tab is active_tab else 'BLANK1',
            )
            props.tab = tab["name"]
        layout.separator()
        layout.operator("topbar.clarity_shelf_tab_add", text="Add Shelf Tab", icon='ADD')
        layout.operator(
            "topbar.clarity_shelf_tab_rename",
            text="Rename Active Tab",
            icon='GREASEPENCIL',
        )
        layout.operator("topbar.clarity_shelf_tab_remove", text="Remove Active Tab", icon='X')


class SHELF_HT_header(Header):
    bl_space_type = 'SHELF'

    def draw(self, context):
        layout = self.layout
        layout.template_header()
        layout.menu("SHELF_MT_tabs", text=_clarity_shelf_active_tab(context)["name"])


class SHELF_PT_main(Panel):
    bl_space_type = 'SHELF'
    bl_region_type = 'WINDOW'
    bl_label = "Shelf"
    bl_options = {'HIDE_HEADER'}

    def draw(self, context):
        _clarity_shelf_draw_adaptive(self.layout, context)


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
            layout.menu("TOPBAR_MT_blender", text="Clarity")

        layout.menu("TOPBAR_MT_file")
        layout.menu("TOPBAR_MT_edit")

        layout.menu("TOPBAR_MT_render")

        layout.menu("TOPBAR_MT_window")
        layout.menu("TOPBAR_MT_help")


class TOPBAR_MT_blender(Menu):
    bl_label = "Clarity"

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


def _clarity_shelf_legacy_operator_alias(base):
    """Hidden forwarding class for external scripts using a former operator identifier."""
    namespace = {
        "__module__": __name__,
        "bl_idname": base.bl_idname.replace(".clarity_", ".maya_"),
        "bl_options": set(getattr(base, "bl_options", set())) | {'INTERNAL'},
    }
    for name, value in base.__dict__.items():
        if name.startswith("__") or name in {"bl_idname", "bl_options", "bl_rna"}:
            continue
        namespace[name] = value
    annotations = {}
    for owner in reversed(base.__mro__):
        annotations.update(getattr(owner, "__annotations__", {}))
    if annotations:
        namespace["__annotations__"] = annotations
    for callback in ("poll", "description", "check", "draw", "invoke", "execute", "modal", "cancel"):
        for owner in base.__mro__:
            if callback in owner.__dict__:
                namespace[callback] = owner.__dict__[callback]
                break
    # Never inherit from a registered operator class: Blender would reuse its StructRNA and replace
    # the primary Clarity callback owner. Recreate the class on the same unregistered mixins instead.
    return type(base.__name__.replace("_clarity_", "_maya_"), base.__bases__, namespace)


_CLARITY_SHELF_LEGACY_OPERATOR_CLASSES = tuple(
    _clarity_shelf_legacy_operator_alias(base)
    for base in (
        TOPBAR_OT_clarity_shelf_tab,
        TOPBAR_OT_clarity_shelf_tab_add,
        TOPBAR_OT_clarity_shelf_tab_rename,
        TOPBAR_OT_clarity_shelf_tab_remove,
        TOPBAR_OT_clarity_shelf_item_add,
        TOPBAR_OT_clarity_shelf_item_edit,
        TOPBAR_OT_clarity_shelf_item_remove_id,
        TOPBAR_OT_clarity_shelf_separator_add,
        TOPBAR_OT_clarity_shelf_context_menu,
        TOPBAR_OT_clarity_shelf_drag,
        TOPBAR_OT_clarity_shelf_drag_hover,
        TOPBAR_OT_clarity_shelf_action,
        TOPBAR_OT_clarity_shelf_action_undo,
        TOPBAR_OT_clarity_shelf_preview,
    )
)


classes = (
    TOPBAR_PG_clarity_shelf_icon,
    TOPBAR_PG_clarity_shelf_action,
    TOPBAR_UL_clarity_shelf_icons,
    TOPBAR_UL_clarity_shelf_actions,
    TOPBAR_HT_upper_bar,
    TOPBAR_OT_clarity_shelf_tab,
    TOPBAR_OT_clarity_shelf_tab_add,
    TOPBAR_OT_clarity_shelf_tab_rename,
    TOPBAR_OT_clarity_shelf_tab_remove,
    TOPBAR_OT_clarity_shelf_item_add,
    TOPBAR_OT_clarity_shelf_item_edit,
    TOPBAR_OT_clarity_shelf_item_remove_id,
    TOPBAR_OT_clarity_shelf_separator_add,
    TOPBAR_OT_clarity_shelf_context_menu,
    TOPBAR_OT_clarity_shelf_drag,
    TOPBAR_OT_clarity_shelf_drag_hover,
    TOPBAR_OT_clarity_shelf_action,
    TOPBAR_OT_clarity_shelf_action_undo,
    TOPBAR_OT_clarity_shelf_preview,
    *_CLARITY_SHELF_LEGACY_OPERATOR_CLASSES,
    WM_MT_button_context,
    TOPBAR_HT_clarity_shelf_upper,
    TOPBAR_HT_clarity_shelf_lower,
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
