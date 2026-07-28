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
    assert window_manager.keyconfigs.active.name == "Maya"
    assert os.path.basename(os.path.normpath(bpy.utils.user_resource('CONFIG'))) == (
        "maya_fork_config"
    )

    for object in bpy.data.objects:
        assert object.transform_model == 'BLENDER'
        assert object.custom_pivot is None


if __name__ == "__main__":
    main()
