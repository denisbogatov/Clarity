# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

import os
import bpy


DIRNAME, FILENAME = os.path.split(__file__)
IDNAME = os.path.splitext(FILENAME)[0]


def update_fn(_self, _context):
    load()


industry_compatible = bpy.utils.execfile(
    os.path.join(DIRNAME, "keymap_data", "industry_compatible_data.py")
)


def _is_edit_pivot_conflict(item):
    # `D` toggles Edit Pivot, so it cannot also pick the annotate tool.
    return (
        item[0] == "wm.tool_set_by_id"
        and item[1].get("type") == 'D'
        and not any(
            item[1].get(modifier, False)
            for modifier in ("shift", "ctrl", "alt", "oskey")
        )
        and ("name", "builtin.annotate") in (item[2] or {}).get("properties", ())
    )


def _is_topology_selection_conflict(item):
    # Double click performs the component-mode-specific topology selection. `Shift` double click
    # adds a face loop when two faces are neighbors, or a path between non-neighboring components.
    # The Maya interaction model dispatches those gestures itself, before any keymap runs, so the
    # base bindings can only act where the dispatcher passes through: `Alt` double click used to
    # still select an edge ring there, while `Alt` belongs to viewport navigation.
    return (
        item[0] in {"mesh.loop_select", "mesh.edgering_select"}
        and item[1].get("value") == 'DOUBLE_CLICK'
    )


def _is_shortest_path_conflict(item):
    # `mesh.shortest_path_pick` sits on `Ctrl Shift` LMB *press*. A press always resolves before the
    # double click built on top of it, so that binding fires first and the topology gesture the
    # dispatcher would have run - the edge loop, the face loop - never happens: the redo panel shows
    # "Pick Shortest Path" and one component gets selected. The dispatcher offers the path itself,
    # for the component pairs Maya walks a path between, so the base binding only stands in the way.
    return (
        item[0].endswith(".shortest_path_pick")
        and item[1].get("value") == 'PRESS'
        and item[1].get("ctrl", False)
        and item[1].get("shift", False)
    )


_SELECT_ALL_OPERATORS = {
    "object.select_all",
    "mesh.select_all",
    "curve.select_all",
    "armature.select_all",
    "mball.select_all",
    "lattice.select_all",
    "pose.select_all",
    "particle.select_all",
}


def _keymap_item_action(item):
    return dict((item[2] or {}).get("properties", ())).get("action")


def apply_maya_selection_shortcuts(keyconfig_data):
    """Move the three selection-wide commands onto the keys Maya uses for them.

    Industry Compatible puts them on `Ctrl A`, `Ctrl Shift A` and `Ctrl I`; Maya uses
    `Ctrl Shift A`, `Alt D` and `Ctrl Shift I`. Only the editors that select 3D components or
    objects are touched, so the Outliner, the UV editor and the text editor keep their own.
    """
    for _keymap_name, _keymap_args, keymap_content in keyconfig_data:
        for item in keymap_content["items"]:
            if item[0] not in _SELECT_ALL_OPERATORS:
                continue
            properties = item[1]
            if properties.get("value") != 'PRESS':
                continue
            action = _keymap_item_action(item)
            if action == 'SELECT' and properties.get("type") == 'A':
                properties["shift"] = True
            elif action == 'DESELECT' and properties.get("type") == 'A':
                # Maya deselects everything with `Alt D`, and leaves `A` to selecting.
                properties.clear()
                properties.update({"type": 'D', "value": 'PRESS', "alt": True})
            elif action == 'INVERT' and properties.get("type") == 'I':
                properties["shift"] = True


def allow_modifiers_on_gizmo_tweak(keyconfig_data):
    """Let a held modifier reach the manipulator.

    The Industry Compatible binding takes no modifiers at all, and a gizmo whose keymap does not
    accept the held one is dropped from the hit test entirely (see
    `wm_gizmo_keymap_uses_event_modifier`): the manipulator stays on screen but stops answering the
    moment `Shift` goes down, which is what kept Shift Extrude from ever starting. `Alt` is left
    out because it belongs to viewport navigation.
    """
    for _keymap_name, _keymap_args, keymap_content in keyconfig_data:
        for item in keymap_content["items"]:
            if item[0] != "gizmogroup.gizmo_tweak":
                continue
            # -1 is "any" for a key-map modifier.
            item[1].update({"ctrl": -1, "shift": -1, "oskey": -1})


def remove_maya_key_conflicts(keyconfig_data):
    """Drop base bindings that occupy gestures the Maya interaction model owns itself.

    A leftover binding never wins the event, so what it costs is a second entry in the keymap editor
    and a surprise in the contexts the dispatcher declines to handle.
    """
    for _keymap_name, _keymap_args, keymap_content in keyconfig_data:
        items = keymap_content["items"]
        items[:] = [
            item for item in items
            if not (
                _is_edit_pivot_conflict(item)
                or _is_topology_selection_conflict(item)
                or _is_shortest_path_conflict(item)
            )
        ]


def load():
    from sys import platform
    from bl_keymap_utils.io import keyconfig_init_from_data

    prefs = bpy.context.preferences
    kc = bpy.context.window_manager.keyconfigs.new(IDNAME)
    params = industry_compatible.Params(
        use_mouse_emulate_3_button=prefs.inputs.use_mouse_emulate_3_button
    )
    keyconfig_data = industry_compatible.generate_keymaps(params)
    remove_maya_key_conflicts(keyconfig_data)
    allow_modifiers_on_gizmo_tweak(keyconfig_data)
    apply_maya_selection_shortcuts(keyconfig_data)

    if platform == "darwin":
        from bl_keymap_utils.platform_helpers import keyconfig_data_oskey_from_ctrl_for_macos
        keyconfig_data = keyconfig_data_oskey_from_ctrl_for_macos(keyconfig_data)

    keyconfig_init_from_data(kc, keyconfig_data)


if __name__ == "__main__":
    load()
