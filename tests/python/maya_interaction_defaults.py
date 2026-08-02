# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

import os

import bpy


def main():
    bpy.ops.wm.read_factory_settings(use_empty=False)
    preferences = bpy.context.preferences
    assert preferences.inputs.interaction_preset == 'MAYA'
    assert preferences.keymap.active_keyconfig == "Maya"

    window_manager = bpy.context.window_manager
    assert window_manager.maya_interaction_enabled

    # The window manager runs the keyconfig preset only when there is a UI: WM_keyconfig_reload()
    # returns early on `G.background`, so nothing has executed Maya.py at this point and the only
    # key configurations present are the built-in ones. Running the same entry point the UI runs is
    # what lets the rest of this test check the preset rather than the preference that names it.
    bpy.utils.keyconfig_init()
    assert window_manager.keyconfigs.active.name == "Maya"
    mesh_keymap = window_manager.keyconfigs.active.keymaps["Mesh"]
    bridge_items = [
        item for item in mesh_keymap.keymap_items
        if item.type == 'B' and item.value == 'PRESS' and item.ctrl and item.shift
    ]
    assert len(bridge_items) == 1
    assert bridge_items[0].idname == "mesh.bridge_edge_loops"
    assert os.path.basename(os.path.normpath(bpy.utils.user_resource('CONFIG'))) == (
        "maya_fork_config"
    )

    for object in bpy.data.objects:
        assert object.transform_model == 'BLENDER'
        assert object.custom_pivot is None


if __name__ == "__main__":
    main()
