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
    # Double click selects the edge loop and `Shift` double click the path between the previous
    # component and this one, in every component mode. The Maya interaction model dispatches those
    # gestures itself, before any keymap runs, so the base bindings can only act where the dispatcher
    # passes through: `Alt` double click used to still select an edge ring there, while `Alt` belongs
    # to viewport navigation.
    return (
        item[0] in {"mesh.loop_select", "mesh.edgering_select"}
        and item[1].get("value") == 'DOUBLE_CLICK'
    )


def remove_maya_key_conflicts(keyconfig_data):
    """Drop base bindings that occupy gestures the Maya interaction model owns itself.

    A leftover binding never wins the event, so what it costs is a second entry in the keymap editor
    and a surprise in the contexts the dispatcher declines to handle.
    """
    for _keymap_name, _keymap_args, keymap_content in keyconfig_data:
        items = keymap_content["items"]
        items[:] = [
            item for item in items
            if not (_is_edit_pivot_conflict(item) or _is_topology_selection_conflict(item))
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

    if platform == "darwin":
        from bl_keymap_utils.platform_helpers import keyconfig_data_oskey_from_ctrl_for_macos
        keyconfig_data = keyconfig_data_oskey_from_ctrl_for_macos(keyconfig_data)

    keyconfig_init_from_data(kc, keyconfig_data)


if __name__ == "__main__":
    load()
