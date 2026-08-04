# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

import os

import bpy


def main():
    bpy.ops.wm.read_factory_settings(use_empty=False)
    preferences = bpy.context.preferences
    assert preferences.inputs.interaction_preset == 'CLARITY'
    assert preferences.keymap.active_keyconfig == "Clarity"

    window_manager = bpy.context.window_manager
    assert window_manager.clarity_interaction_enabled

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


if __name__ == "__main__":
    main()
