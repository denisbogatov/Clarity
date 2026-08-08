# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Walks the pointer out along each pivot axis and lets the manipulator say what it would grab.

This is the automated form of the walk the Edit Pivot divergence was measured by hand with, and it
presses nothing. A press is a state change - at a distance where no handle answers, the release
becomes a click, and in Edit Pivot a click aims the pivot, so the next reading is taken from a
centre that moved. Highlighting needs only a motion, and the `pick:` line in
`gizmo_find_intersected_3d_intern` reports what the select buffer answered for it. So the probe
moves, and the trace does the measuring.

Both halves go to `stderr`: this file writes one `PROBE` marker per stop, and the gizmo trace writes
its `pick:` lines right after it. Read the pairs.

    set BLENDER_CLARITY_GIZMO_TRACE=1
    blender --factory-startup -p 0 0 1280 900 --enable-event-simulate \\
        --python tests/python/ui_simulate/run_blender_setup.py -- \\
        --tests probe_clarity_pivot_handles.walk_the_axes 2> gztrace.txt

It is deliberately not in `tests/python/CMakeLists.txt`: it asserts nothing, so it is not a test.
"""

import sys

import modules.ui_test_utils as ui

from test_clarity_pivot import _object_origin_pixel, _view3d_area_region

#: Where to stop, in pixels from the manipulator centre. The bands being separated are the centre
#: handle (about 15 px), the trackball disc (about 75 px) and the view ring (about 90 px).
DISTANCES = tuple(range(5, 131, 5))

AXES = (("X", (1.0, 0.0, 0.0)), ("Y", (0.0, 1.0, 0.0)), ("Z", (0.0, 0.0, 1.0)))

#: Steps to burn after a pass changes the mode, before its readings are taken.
SETTLE_FRAMES = 10


def _mark(text):
    sys.stderr.write("PROBE {:s}\n".format(text))
    sys.stderr.flush()


def _axis_screen_direction(object, region, region_3d, axis):
    """
    The direction one pivot axis runs in on screen, as a unit 2D vector.

    World axes, because that is the frame a freshly loaded cube's pivot has; an authored orientation
    would have to be read from the pivot instead.
    """
    from bpy_extras.view3d_utils import location_3d_to_region_2d
    from mathutils import Vector

    origin = object.matrix_world.translation
    here = location_3d_to_region_2d(region, region_3d, origin)
    there = location_3d_to_region_2d(region, region_3d, origin + Vector(axis))
    if here is None or there is None:
        return None
    direction = there - here
    if direction.length < 1.0:
        # Pointing at the camera: every stop along it would land on the same pixel.
        return None
    return direction.normalized()


def walk_the_axes():
    import bpy
    from mathutils import Euler

    e, t, window = ui.test_window()

    bpy.context.preferences.inputs.interaction_preset = 'CLARITY'
    yield

    area, region = _view3d_area_region(window)
    region_3d = area.spaces[0].region_3d
    object = bpy.data.objects["Cube"]
    with bpy.context.temp_override(window=window, area=area, region=region):
        bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.object.select_all(action='DESELECT')
        bpy.context.view_layer.objects.active = object
        object.select_set(True)
    yield

    centre = _object_origin_pixel(object, region, region_3d)
    _mark("centre window=({:d} {:d}) region_offset=({:d} {:d}) gizmo_size={:d}".format(
        centre[0], centre[1], region.x, region.y,
        bpy.context.preferences.view.gizmo_size,
    ))

    gizmo_size = bpy.context.preferences.view.gizmo_size
    view_distance = region_3d.view_distance
    overlay = area.spaces[0].overlay

    # Everything before `W` fails and everything after it answers, with the same gizmo objects at
    # the same addresses, the same eleven offered to the pick, the same geometry drawn into the
    # buffer and the same cursor. Leaving and re-entering the mode does not help, so it is not the
    # first entry either. `W` does three things that outlive it - it sets `gizmo_show_object`, it
    # activates a Clarity tool, and it forces the Blender tool to Box Select - and these four cold
    # passes take them one at a time, before anything else in the session has happened.
    passes = [
        ("pivot-cold", AXES[:1], {"pivot": True, "show_object": False}),
        ("pivot-cold-wire-no-floor", AXES[:1],
         {"pivot": True, "show_object": False, "display": 'WIRE', "floor": False}),
        ("pivot-cold-gizmo-150", AXES[:1], {"pivot": True, "show_object": False, "gizmo_size": 150}),
        ("pivot-cold-redraw", AXES[:1], {"pivot": True, "show_object": False, "redraw": True}),
        ("pivot-cold-view-nudge", AXES[:1], {"pivot": True, "show_object": False, "nudge": True}),
        ("pivot-cold-show-object", AXES[:1], {"pivot": True, "show_object": True}),
        ("pivot-cold-box-select", AXES[:1],
         {"pivot": True, "show_object": False, "blender_tool": "builtin.select_box"}),
        ("pivot-cold-select-tool", AXES[:1], {"pivot": True, "show_object": False, "tool": "q"}),
        ("move", AXES, {"tool": "w"}),
        ("pivot", AXES, {"pivot": True}),
        # Kept because they are the controls that are already answered: moving the view without
        # changing the manipulator's size on screen, and taking the cube's surface and the ground
        # plane out of the depth buffer the pick reads. None of the three changes anything.
        ("move-view-0.5x", AXES[:1], {"zoom": 0.5}),
        ("move-wire", AXES[:1], {"display": 'WIRE'}),
        ("move-no-floor", AXES[:1], {"floor": False}),
        ("move-wire-no-floor", AXES[:1], {"display": 'WIRE', "floor": False}),
    ]

    space = area.spaces[0]
    pivot_on = False
    for mode, axes, options in passes:
        if "show_object" in options:
            space.show_gizmo_object_translate = bool(options["show_object"])
        if options.get("blender_tool"):
            with bpy.context.temp_override(window=window, area=area, region=region):
                bpy.ops.wm.tool_set_by_id(name=options["blender_tool"])
        if options.get("tool"):
            yield getattr(e, options["tool"])()
        bpy.context.preferences.view.gizmo_size = options.get("gizmo_size", gizmo_size)
        if options.get("redraw"):
            region.tag_redraw()
        if options.get("nudge"):
            # A real view change, which is the one thing that certainly redraws the whole region.
            region_3d.view_rotation.rotate(Euler((0.0, 0.0, 0.02)))
        region_3d.view_distance = view_distance * options.get("zoom", 1.0)
        object.display_type = options.get("display", 'TEXTURED')
        # Not `show_overlays`: that would take the gizmos with it. Only the ground plane, which is
        # what the pick's depth buffer holds under an arrow lying along a world axis.
        overlay.show_floor = options.get("floor", True)
        overlay.show_axis_x = options.get("floor", True)
        overlay.show_axis_y = options.get("floor", True)
        yield

        e.cursor_position_set(*centre, move=True)
        yield
        if bool(options.get("pivot")) != pivot_on:
            yield e.d()
            pivot_on = not pivot_on
        # A manipulator that has just appeared is not pickable on the next event: the first walk of
        # a run answered nothing at all while every later one answered, with the same eleven handles
        # drawn into the buffer at the same places. Frames, not state - so the probe waits for some.
        for _ in range(SETTLE_FRAMES):
            yield
        _mark("mode {:s} view_distance={:.3f} display={:s} floor={:d}".format(
            mode, region_3d.view_distance, object.display_type, int(overlay.show_floor)))

        # The centre moves with the view distance only if the view target is not the pivot, so it is
        # re-read rather than assumed.
        centre = _object_origin_pixel(object, region, region_3d)

        for name, axis in axes:
            direction = _axis_screen_direction(object, region, region_3d, axis)
            if direction is None:
                _mark("axis {:s} skipped, it points along the view".format(name))
                continue
            _mark("mode {:s} axis {:s} screen_direction=({:.3f} {:.3f}) centre=({:d} {:d})".format(
                mode, name, direction.x, direction.y, centre[0], centre[1]))
            for distance in DISTANCES:
                x = int(round(centre[0] + direction.x * distance))
                y = int(round(centre[1] + direction.y * distance))
                _mark("mode={:s} axis={:s} distance={:d} at=({:d} {:d})".format(
                    mode, name, distance, x, y))
                e.cursor_position_set(x, y, move=True)
                yield
                # A second motion on the same pixel: the first one can be swallowed while the
                # region redraws, and a highlight test that never ran leaves no `pick:` line.
                e.cursor_position_set(x, y, move=True)
                yield

        # Marked before the next pass touches anything, or its setup lands in the last stop's
        # readings.
        _mark("leaving {:s}".format(mode))
        e.cursor_position_set(*centre, move=True)
        yield

    if pivot_on:
        yield e.d()
    _mark("done")

