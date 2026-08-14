# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Real-event coverage for Maya's B soft-selection gesture."""

import modules.ui_test_utils as ui


def _view3d_window_center(window):
    area = ui.get_window_area_by_type(window, 'VIEW_3D')
    if area is None:
        raise Exception("no 3D viewport in the test window")
    for region in area.regions:
        if region.type == 'WINDOW':
            return (
                region.x + region.width // 2,
                region.y + region.height // 2,
            )
    raise Exception("the 3D viewport has no window region")


def soft_selection_b_tap_toggles_one_shared_state():
    import bpy

    e, t, window = ui.test_window()
    bpy.context.preferences.inputs.interaction_preset = 'CLARITY'
    yield

    tool_settings = bpy.context.scene.tool_settings
    tool_settings.use_proportional_edit = False
    tool_settings.use_proportional_edit_objects = False
    e.cursor_position_set(*_view3d_window_center(window), move=True)
    yield

    yield e.b()
    t.assertTrue(tool_settings.use_proportional_edit)
    t.assertTrue(tool_settings.use_proportional_edit_objects)

    yield e.b()
    t.assertFalse(tool_settings.use_proportional_edit)
    t.assertFalse(tool_settings.use_proportional_edit_objects)


def soft_selection_b_left_drag_is_relative_and_does_not_toggle():
    import bpy

    e, t, window = ui.test_window()
    bpy.context.preferences.inputs.interaction_preset = 'CLARITY'
    yield

    tool_settings = bpy.context.scene.tool_settings
    settings = tool_settings.soft_selection
    settings.radius = 5.0
    tool_settings.use_proportional_edit = False
    tool_settings.use_proportional_edit_objects = False
    x, y = _view3d_window_center(window)
    e.cursor_position_set(x, y, move=True)
    yield

    e.b.press()
    yield
    e.leftmouse.press()
    yield
    e.cursor_position_set(x + 120, y, move=True)
    yield
    e.leftmouse.release()
    yield
    e.b.release()
    yield

    t.assertGreater(settings.radius, 5.0)
    t.assertFalse(tool_settings.use_proportional_edit)
    t.assertFalse(tool_settings.use_proportional_edit_objects)


def soft_selection_b_middle_drag_is_absolute_from_zero():
    import bpy

    e, t, window = ui.test_window()
    bpy.context.preferences.inputs.interaction_preset = 'CLARITY'
    yield

    settings = bpy.context.scene.tool_settings.soft_selection
    x, y = _view3d_window_center(window)

    def absolute_drag(initial_radius, delta):
        settings.radius = initial_radius
        e.cursor_position_set(x, y, move=True)
        yield
        e.b.press()
        yield
        e.middlemouse.press()
        yield
        e.cursor_position_set(x + delta, y, move=True)
        yield
        e.middlemouse.release()
        yield
        e.b.release()
        yield
        return settings.radius

    radius_from_large_initial = yield from absolute_drag(500.0, 100)
    radius_from_small_initial = yield from absolute_drag(0.1, -100)

    t.assertGreater(radius_from_large_initial, 0.0)
    t.assertAlmostEqual(
        radius_from_large_initial,
        radius_from_small_initial,
        places=5,
        msg="B+MMB inherited the previous radius instead of starting at zero",
    )


def soft_selection_b_drag_cancel_restores_radius():
    import bpy

    e, t, window = ui.test_window()
    bpy.context.preferences.inputs.interaction_preset = 'CLARITY'
    yield

    settings = bpy.context.scene.tool_settings.soft_selection
    settings.radius = 7.0
    x, y = _view3d_window_center(window)
    e.cursor_position_set(x, y, move=True)
    yield

    e.b.press()
    yield
    e.leftmouse.press()
    yield
    e.cursor_position_set(x + 140, y, move=True)
    yield
    t.assertNotAlmostEqual(settings.radius, 7.0)
    yield e.esc()
    e.leftmouse.release()
    e.b.release()
    yield

    t.assertAlmostEqual(settings.radius, 7.0)
