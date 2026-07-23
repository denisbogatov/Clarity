# SPDX-FileCopyrightText: 2009-2023 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

import bpy
import json
import os
import uuid
from bpy.props import IntProperty, StringProperty
from bpy.types import Header, Menu, Operator, Panel

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

_maya_shelf_config_cache = None
_maya_shelf_save_timer_pending = False
_maya_shelf_drag_state = None
_maya_shelf_previews = None

_MAYA_SHELF_LEFT_MARGIN = 4.0
_MAYA_SHELF_BUTTON_SIZE = 24.0
_MAYA_SHELF_SLOT_WIDTH = 27.0
_MAYA_SHELF_SEPARATOR_WIDTH = 13.2


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
    return {"version": 2, "active": "Modeling", "tabs": tabs}


def _maya_shelf_config():
    global _maya_shelf_config_cache
    if _maya_shelf_config_cache is not None:
        return _maya_shelf_config_cache
    save_migrated_config = False
    try:
        with open(_maya_shelf_config_path(), "r", encoding="utf-8") as handle:
            config = json.load(handle)
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
        _maya_shelf_config_cache = config
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        _maya_shelf_config_cache = _maya_shelf_default_config()
    if save_migrated_config:
        _maya_shelf_save()
    return _maya_shelf_config_cache


def _maya_shelf_save():
    path = _maya_shelf_config_path()
    temp_path = path + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(_maya_shelf_config(), handle, ensure_ascii=False, indent=2)
    os.replace(temp_path, path)


def _maya_shelf_save_deferred():
    global _maya_shelf_save_timer_pending
    if _maya_shelf_save_timer_pending:
        return
    _maya_shelf_save_timer_pending = True

    def save_after_redraw():
        global _maya_shelf_save_timer_pending
        _maya_shelf_save_timer_pending = False
        _maya_shelf_save()
        return None

    bpy.app.timers.register(save_after_redraw, first_interval=0.25)


def _maya_shelf_active_tab():
    config = _maya_shelf_config()
    active = config.get("active")
    tab = next((tab for tab in config["tabs"] if tab["name"] == active), None)
    if tab is None:
        tab = config["tabs"][0]
        config["active"] = tab["name"]
    return tab


def _maya_shelf_redraw(context):
    area = getattr(context, "area", None)
    if area is not None and area.type == 'TOPBAR':
        area.tag_redraw()

    # Regular screen areas do not contain global Top Bar areas. Keep this fallback for
    # non-global/custom screens, while the context area above handles the normal case.
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'TOPBAR':
                area.tag_redraw()


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
    target_index = min(max(target_index, 0), len(rows[target_row]))
    separators = tab.setdefault("separators", [])
    for separator in separators:
        column = separator.get("column", 0)
        if separator.get("row", 0) == source_row and source_index < column:
            separator["column"] = column - 1
    for separator in separators:
        column = separator.get("column", 0)
        if separator.get("row", 0) == target_row and target_index <= column:
            separator["column"] = column + 1
    item["row"] = target_row
    rows[target_row].insert(target_index, item)
    tab["items"] = rows[0] + rows[1]
    return True


class TOPBAR_OT_maya_shelf_tab(Operator):
    bl_idname = "topbar.maya_shelf_tab"
    bl_label = "Maya Shelf Tab"
    bl_options = {'INTERNAL'}

    tab: StringProperty()

    def execute(self, context):
        config = _maya_shelf_config()
        if any(tab["name"] == self.tab for tab in config["tabs"]):
            config["active"] = self.tab
            _maya_shelf_save_deferred()
        _maya_shelf_redraw(context)
        return {'FINISHED'}


class TOPBAR_OT_maya_shelf_tab_add(Operator):
    bl_idname = "topbar.maya_shelf_tab_add"
    bl_label = "Add Shelf Tab"

    name: StringProperty(name="Name", default="New Shelf")

    def invoke(self, context, _event):
        return context.window_manager.invoke_props_dialog(self, width=320)

    def execute(self, context):
        name = self.name.strip()
        config = _maya_shelf_config()
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
        self.name = _maya_shelf_active_tab()["name"]
        return context.window_manager.invoke_props_dialog(self, width=320)

    def execute(self, context):
        name = self.name.strip()
        config = _maya_shelf_config()
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
        config = _maya_shelf_config()
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
    operator_id: StringProperty(name="Operator", default="mesh.primitive_cube_add")
    icon: StringProperty(name="Icon", default="MESH_CUBE")
    row: IntProperty(name="Row", default=0, min=0, max=1)

    def invoke(self, context, _event):
        return context.window_manager.invoke_props_dialog(self, width=380)

    def draw(self, _context):
        layout = self.layout
        layout.prop(self, "label")
        layout.prop(self, "operator_id")
        layout.prop(self, "icon")
        layout.prop(self, "row")

    def execute(self, context):
        try:
            module, name = self.operator_id.strip().split(".", 1)
            getattr(getattr(bpy.ops, module), name)
        except (ValueError, AttributeError):
            self.report({'WARNING'}, "Unknown Blender operator")
            return {'CANCELLED'}

        icon_names = {
            item.identifier
            for item in bpy.types.UILayout.bl_rna.functions["operator"].parameters["icon"].enum_items
        }
        icon = self.icon.strip().upper()
        if icon not in icon_names:
            self.report({'WARNING'}, "Unknown Blender icon")
            return {'CANCELLED'}

        _maya_shelf_active_tab()["items"].append({
            "id": uuid.uuid4().hex,
            "label": self.label.strip() or self.operator_id,
            "icon": icon,
            "action": "",
            "operator": self.operator_id.strip(),
            "row": self.row,
        })
        _maya_shelf_save()
        _maya_shelf_redraw(context)
        return {'FINISHED'}


class TOPBAR_OT_maya_shelf_item_remove_id(Operator):
    bl_idname = "topbar.maya_shelf_item_remove_id"
    bl_label = "Remove from Shelf"
    bl_options = {'UNDO'}

    item_id: StringProperty()

    def execute(self, context):
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
        context.window_manager.popup_menu(self.draw_menu, title="Shelf")
        return {'FINISHED'}

    def draw_menu(self, menu, _context):
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
            context.area.type == 'TOPBAR' and
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

    def _drop_row_and_index(self, context, event):
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
        slot_width = _MAYA_SHELF_SLOT_WIDTH * ui_scale
        separator_width = _MAYA_SHELF_SEPARATOR_WIDTH * ui_scale
        relative_x = mouse_region_x - left_margin
        separator_offset = 0.0
        for separator in sorted(
            (
                separator
                for separator in _maya_shelf_active_tab().setdefault("separators", [])
                if separator.get("row", 0) == row
            ),
            key=lambda candidate: candidate.get("column", 0),
        ):
            separator_x = (
                separator.get("column", 0) * slot_width +
                separator_offset
            )
            if relative_x < separator_x + separator_width * 0.5:
                break
            separator_offset += separator_width
        relative_x -= separator_offset
        index = max(0, int((relative_x + slot_width * 0.5) / slot_width))
        item_count = sum(
            1
            for item in _maya_shelf_active_tab()["items"]
            if (
                (self._drag_separator or item["id"] != self.item_id) and
                item.get("row", 0) == row
            )
        )
        return row, min(index, item_count)

    def _preview_begin(self, context):
        global _maya_shelf_drag_state
        self._preview_active = True
        _maya_shelf_drag_state = {
            "kind": "separator" if self._drag_separator else "icon",
            "source_row": self._source_row,
            "source_index": self._source_index,
            "target_row": self._target_row,
            "target_index": self._target_index,
        }

    def _preview_update(self):
        if _maya_shelf_drag_state is not None:
            _maya_shelf_drag_state["target_row"] = self._target_row
            _maya_shelf_drag_state["target_index"] = self._target_index

    def _preview_end(self, context):
        global _maya_shelf_drag_state
        if not getattr(self, "_preview_active", False):
            return
        self._preview_active = False
        _maya_shelf_drag_state = None

    def invoke(self, context, event):
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

        self._source_row = row
        self._source_index = index
        self._target_row = row
        self._target_index = index
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
        _maya_shelf_config()["selected"] = self.item_id
        self._preview_begin(context)
        context.window_manager.modal_handler_add(self)
        _maya_shelf_redraw(context)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type == 'MOUSEMOVE':
            row, index = self._drop_row_and_index(context, event)
            if row is not None and (row, index) != (self._target_row, self._target_index):
                self._target_row = row
                self._target_index = index
                self._preview_update()
                _maya_shelf_redraw(context)
            return {'RUNNING_MODAL', 'PASS_THROUGH'}

        if event.type == 'MIDDLEMOUSE' and event.value == 'RELEASE':
            row, index = self._drop_row_and_index(context, event)
            if row is None:
                row, index = self._target_row, self._target_index
            if self._drag_separator:
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
        if any(
            separator["id"] == self.item_id
            for separator in _maya_shelf_active_tab().setdefault("separators", [])
        ):
            return {'CANCELLED'}
        area = next((area for area in context.screen.areas if area.type == 'VIEW_3D'), None)
        if area is None:
            self.report({'WARNING'}, "No 3D View available")
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


class WM_MT_button_context(Menu):
    bl_label = "Button Context Menu"

    def draw(self, context):
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


def _maya_shelf_draw_icon_row(layout, row_index):
    config = _maya_shelf_config()
    tab = _maya_shelf_active_tab()
    selected = config.get("selected", "")
    row = layout.row(align=True)
    row.scale_x = 1.2
    row.scale_y = 1.2

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
    marker_index = None
    if (
        _maya_shelf_drag_state is not None and
        _maya_shelf_drag_state["target_row"] == row_index
    ):
        marker_index = _maya_shelf_drag_state["target_index"]
        if (
            _maya_shelf_drag_state.get("kind") != "separator" and
            _maya_shelf_drag_state["source_row"] == row_index and
            _maya_shelf_drag_state["source_index"] < marker_index
        ):
            marker_index += 1
        marker_index = min(max(marker_index, 0), len(items))

    def draw_marker():
        marker = row.row(align=True)
        marker.ui_units_x = 0.55
        marker.label(text="", icon_value=_maya_shelf_marker_icon())

    def draw_separator(separator):
        divider = row.row(align=True)
        divider.ui_units_x = 0.55
        divider.context_string_set("maya_shelf_item_id", separator["id"])
        props = divider.operator(
            "topbar.maya_shelf_action",
            text="|",
            emboss=False,
        )
        props.item_id = separator["id"]
        props.tooltip = "Shelf Separator"

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
        if column < len(items):
            item = items[column]
            button = row.row(align=True)
            button.context_string_set("maya_shelf_item_id", item["id"])
            props = button.operator(
                "topbar.maya_shelf_action",
                text="",
                icon=item["icon"],
                emboss=True,
                depress=(item["id"] == selected),
            )
            props.action = item.get("action", "")
            props.operator_id = item.get("operator", "")
            props.item_id = item["id"]
            props.tooltip = item.get("label", "Shelf Command")
            # 24 px square button + a compact spacer at UI scale.
            row.separator(factor=0.4)
        elif column < last_column:
            placeholder = row.row(align=True)
            placeholder.ui_units_x = _MAYA_SHELF_SLOT_WIDTH / 20.0
            placeholder.label(text="")


class TOPBAR_HT_maya_shelf_upper(Header):
    bl_space_type = 'TOPBAR'
    bl_region_type = 'FOOTER'

    def draw(self, _context):
        _maya_shelf_draw_icon_row(self.layout, 0)


class TOPBAR_HT_maya_shelf_lower(Header):
    bl_space_type = 'TOPBAR'
    bl_region_type = 'WINDOW'

    def draw(self, _context):
        _maya_shelf_draw_icon_row(self.layout, 1)


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
            layout.menu("TOPBAR_MT_blender", text="Blender")

        layout.menu("TOPBAR_MT_file")
        layout.menu("TOPBAR_MT_edit")

        layout.menu("TOPBAR_MT_render")

        layout.menu("TOPBAR_MT_window")
        layout.menu("TOPBAR_MT_help")


class TOPBAR_MT_blender(Menu):
    bl_label = "Blender"

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
    TOPBAR_HT_upper_bar,
    TOPBAR_OT_maya_shelf_tab,
    TOPBAR_OT_maya_shelf_tab_add,
    TOPBAR_OT_maya_shelf_tab_rename,
    TOPBAR_OT_maya_shelf_tab_remove,
    TOPBAR_OT_maya_shelf_item_add,
    TOPBAR_OT_maya_shelf_item_remove_id,
    TOPBAR_OT_maya_shelf_separator_add,
    TOPBAR_OT_maya_shelf_context_menu,
    TOPBAR_OT_maya_shelf_drag,
    TOPBAR_OT_maya_shelf_action,
    WM_MT_button_context,
    TOPBAR_HT_maya_shelf_upper,
    TOPBAR_HT_maya_shelf_lower,
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
