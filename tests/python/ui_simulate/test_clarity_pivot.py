# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
This file does not run anything, its methods are accessed for tests by ``run_blender_setup.py``.

Edit Pivot reacts to a left button click, and that click is the one gesture the Clarity dispatcher
cannot be handed ready-made: Blender synthesizes ``KM_CLICK`` inside ``wm_handlers_do`` and undoes
the promotion before that call returns, so the dispatcher only ever sees the press and the release.
Driving the real events is therefore the only way to test the recognition - a unit test can check
the rule, but not that the rule is reached.

The click operator reports what it hit and what it applied there into the file
``BLENDER_CLARITY_SNAP_TRACE_FILE`` names, and that trace is what the assertions read. Setting the
variable points the trace somewhere readable; leaving it unset is fine, see ``_trace_path``.

One test per Blender: ``run_blender_setup.py`` takes several names, but ``easy_keys.run`` only
registers a timer and returns, so a second name runs a second generator whose events interleave with
this one's. ``run.py`` starts a process per test for that reason.

    blender --enable-event-simulate --factory-startup \\
        --python tests/python/ui_simulate/run_blender_setup.py -- \\
        --tests test_clarity_pivot.pivot_click_aligns_the_pivot_to_the_clicked_edge
"""

import math
import os
import tempfile

import modules.ui_test_utils as ui


def _trace_path():
    """
    Where the click writes its report.

    The operator reads the variable on every line it writes, so a test that was handed no
    environment of its own - which is how `ctest` runs these - can name the file itself. The process
    id is part of the name because those runs are parallel and each one truncates its trace.
    """
    path = os.environ.get("BLENDER_CLARITY_SNAP_TRACE_FILE")
    if not path:
        path = os.path.join(
            tempfile.gettempdir(), "clarity-uitest-trace-{:d}.log".format(os.getpid()),
        )
        os.environ["BLENDER_CLARITY_SNAP_TRACE_FILE"] = path
    return path


def _trace_reset():
    path = _trace_path()
    with open(path, "w", encoding="utf-8"):
        pass
    return path


def _trace_lines(prefix):
    with open(_trace_path(), "r", encoding="utf-8") as file:
        return [line.strip() for line in file if line.startswith(prefix)]


def _trace_fields(line):
    """`key=value` pairs of a trace line, with the parenthesized normal kept as one value."""
    fields = {}
    rest = line
    while "=" in rest:
        key, _, rest = rest.partition("=")
        key = key.split()[-1]
        if rest.startswith("("):
            value, _, rest = rest[1:].partition(")")
        else:
            value, _, rest = rest.partition(" ")
        fields[key] = value.strip()
    return fields


def _view3d_area_region(window):
    area = ui.get_window_area_by_type(window, 'VIEW_3D')
    if area is None:
        raise Exception("no 3D viewport in the test window")
    for region in area.regions:
        if region.type == 'WINDOW':
            return area, region
    raise Exception("the 3D viewport has no window region")


def viewcube_angled_presets_preserve_y_up_and_perspective():
    """All Maya-style edge and corner presets remain level and perspective."""
    import bpy
    from mathutils import Vector

    _, t, window = ui.test_window()
    preferences = bpy.context.preferences
    preferences.inputs.interaction_preset = 'CLARITY'
    yield

    area, region = _view3d_area_region(window)
    region_3d = area.spaces.active.region_3d
    view_axis_items = bpy.ops.view3d.view_axis.get_rna_type().properties["type"].enum_items
    angled_views = [
        item.identifier for item in view_axis_items if 100 <= item.value < 120
    ]
    t.assertEqual(len(angled_views), 20, "the ViewCube must expose 12 edge and 8 corner views")

    direction_by_name = {
        "LEFT": Vector((-1.0, 0.0, 0.0)),
        "RIGHT": Vector((1.0, 0.0, 0.0)),
        "BOTTOM": Vector((0.0, -1.0, 0.0)),
        "TOP": Vector((0.0, 1.0, 0.0)),
        "BACK": Vector((0.0, 0.0, -1.0)),
        "FRONT": Vector((0.0, 0.0, 1.0)),
    }
    smooth_view = preferences.view.smooth_view
    use_auto_perspective = preferences.inputs.use_auto_perspective
    preferences.view.smooth_view = 0
    preferences.inputs.use_auto_perspective = True
    try:
        with bpy.context.temp_override(window=window, area=area, region=region):
            for view_name in angled_views:
                expected_direction = sum(
                    (direction_by_name[name] for name in view_name.split("_")),
                    Vector((0.0, 0.0, 0.0)),
                ).normalized()
                expected_up = (
                    Vector((0.0, 1.0, 0.0))
                    - expected_direction * expected_direction.y
                ).normalized()

                # Reproduce the failure sequence: face views leave the viewport orthographic.
                region_3d.view_perspective = 'ORTHO'
                t.assertEqual(bpy.ops.view3d.view_axis(type=view_name), {'FINISHED'})

                camera_rotation = region_3d.view_rotation.inverted()
                actual_direction = camera_rotation @ Vector((0.0, 0.0, 1.0))
                actual_up = camera_rotation @ Vector((0.0, 1.0, 0.0))
                t.assertEqual(region_3d.view_perspective, 'PERSP', view_name)
                t.assertGreater(actual_direction.dot(expected_direction), 0.9999, view_name)
                t.assertGreater(actual_up.dot(expected_up), 0.9999, view_name)
    finally:
        preferences.view.smooth_view = smooth_view
        preferences.inputs.use_auto_perspective = use_auto_perspective
    yield


def _visible_edge_picks(object, region, region_3d):
    """
    The cube edges that face the viewer, best first, each with the alignment its click should
    produce.

    The two faces beside an edge decide the answer: Clarity aligns the pivot X axis with the
    *normal* of what was clicked, and an edge's normal is the mean of those two. Both faces are
    required to face the viewer so the occlusion test cannot reject the hit.

    Read in object mode: the mesh only carries the edit cage's geometry once edit mode is left.
    """
    from bpy_extras.view3d_utils import location_3d_to_region_2d
    from mathutils import Vector

    mesh = object.data
    matrix = object.matrix_world
    normal_matrix = matrix.inverted().transposed().to_3x3()
    view_direction = region_3d.view_rotation @ Vector((0.0, 0.0, 1.0))

    faces_of_edge = {}
    for polygon in mesh.polygons:
        for key in polygon.edge_keys:
            faces_of_edge.setdefault(key, []).append(polygon.index)
    edge_index_of_key = {edge.key: edge.index for edge in mesh.edges}

    candidates = []
    for key, polygon_indices in faces_of_edge.items():
        if len(polygon_indices) != 2:
            continue
        normals = [(normal_matrix @ mesh.polygons[i].normal).normalized() for i in polygon_indices]
        facing = min(normal.dot(view_direction) for normal in normals)
        if facing <= 0.2:
            continue
        vertices = [matrix @ mesh.vertices[i].co for i in key]
        midpoint = (vertices[0] + vertices[1]) / 2.0
        position_2d = location_3d_to_region_2d(region, region_3d, midpoint)
        if position_2d is None:
            continue
        if not (8 < position_2d.x < region.width - 8 and 8 < position_2d.y < region.height - 8):
            continue
        candidates.append(
            {
                "facing": facing,
                "edge_index": edge_index_of_key[key],
                "midpoint": midpoint,
                "normal": (normals[0] + normals[1]).normalized(),
                "direction": (vertices[1] - vertices[0]).normalized(),
                "window_xy": (
                    region.x + int(round(position_2d.x)),
                    region.y + int(round(position_2d.y)),
                ),
            }
        )
    if not candidates:
        raise Exception("no front facing edge found to click")
    candidates.sort(key=lambda candidate: candidate["facing"], reverse=True)
    return candidates


def _visible_edge_pick(object, region, region_3d):
    return _visible_edge_picks(object, region, region_3d)[0]


def pivot_click_aligns_the_pivot_to_the_clicked_edge():
    import bpy
    from mathutils import Vector

    e, t, window = ui.test_window()
    trace = _trace_reset()

    bpy.context.preferences.inputs.interaction_preset = 'CLARITY'
    yield

    area, region = _view3d_area_region(window)
    region_3d = area.spaces[0].region_3d

    object = bpy.data.objects["Cube"]
    pick = _visible_edge_pick(object, region, region_3d)
    with bpy.context.temp_override(window=window, area=area, region=region):
        bpy.context.view_layer.objects.active = object
        object.select_set(True)
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_mode(type='EDGE')
        bpy.ops.mesh.select_all(action='SELECT')
    yield

    e.cursor_position_set(*pick["window_xy"], move=True)
    yield

    # `D` toggles Edit Pivot. Without the mode the click below is an ordinary selection.
    yield e.d()

    e.leftmouse.press()
    yield
    e.leftmouse.release()
    yield

    hits = _trace_lines("pivot-click hit")
    applies = _trace_lines("pivot-click apply")
    t.assertTrue(hits, "the click never reached TRANSFORM_OT_clarity_pivot_click, see " + trace)
    t.assertTrue(applies, "the click reached the operator but applied nothing, see " + trace)

    fields = _trace_fields(hits[-1])
    t.assertEqual(fields["position"], "1")
    t.assertEqual(fields["orientation"], "1")

    normal = Vector([float(value) for value in fields["normal"].split()])
    t.assertAlmostEqual(normal.length, 1.0, places=2)

    # The rule under test: an edge aligns the pivot with the mean of the normals of the two faces
    # beside it, never with the edge's own direction. On a cube the two differ by 45 degrees, so a
    # fallback to `v1 - v0` cannot pass by accident.
    t.assertGreater(
        normal.dot(pick["normal"]), 0.99,
        "expected the mean of the adjacent face normals {!r}, got {!r}".format(
            tuple(round(value, 3) for value in pick["normal"]),
            tuple(round(value, 3) for value in normal),
        ),
    )
    t.assertLess(abs(normal.dot(pick["direction"])), 0.1, "the pivot aligned with the edge direction")

    # A click orients, it does not move: the capture shows the pivot centre holding still through
    # every click while the axes turn. Position is the drag's job, and `Shift`'s.
    applied = _trace_fields(applies[-1])
    t.assertEqual(applied["position"], "0", "a plain click moved the pivot instead of aiming it")
    t.assertEqual(applied["orientation"], "1")

    # `Shift + click` is the half that does move it, and it leaves the orientation alone.
    e.shift.leftmouse.press()
    yield
    e.shift.leftmouse.release()
    yield
    shifted = _trace_fields(_trace_lines("pivot-click apply")[-1])
    t.assertEqual(shifted["position"], "1", "Shift-click did not place the pivot")
    t.assertEqual(shifted["orientation"], "0", "Shift-click turned the pivot as well")


def _selected_edge_count():
    import bmesh
    import bpy

    mesh = bmesh.from_edit_mesh(bpy.context.active_object.data)
    return sum(1 for edge in mesh.edges if edge.select)


def _edit_pivot_over_an_edge(e, window, select_all=True):
    """Edit Pivot on, the cursor resting over a visible edge. Yields once per simulated step."""
    import bpy

    bpy.context.preferences.inputs.interaction_preset = 'CLARITY'
    yield

    area, region = _view3d_area_region(window)
    object = bpy.data.objects["Cube"]
    pick = _visible_edge_pick(object, region, area.spaces[0].region_3d)
    with bpy.context.temp_override(window=window, area=area, region=region):
        bpy.context.view_layer.objects.active = object
        object.select_set(True)
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_mode(type='EDGE')
        if select_all:
            bpy.ops.mesh.select_all(action='SELECT')
        else:
            # One edge: enough for the pivot to have a component to sit on, and little enough that
            # an edge loop is a visible change.
            import bmesh
            bpy.ops.mesh.select_all(action='DESELECT')
            mesh = bmesh.from_edit_mesh(object.data)
            mesh.edges.ensure_lookup_table()
            mesh.edges[pick["edge_index"]].select_set(True)
            bmesh.update_edit_mesh(object.data)
    yield

    e.cursor_position_set(*pick["window_xy"], move=True)
    yield
    # `D` toggles Edit Pivot. Without the mode the clicks below are ordinary selections.
    yield e.d()
    return pick


def pivot_click_leaves_a_drag_alone():
    """
    A drag past the threshold ends in a left button release like a click does, and it belongs to the
    manipulator or to the marquee. Only the release that stayed where the press was may place the
    pivot.
    """
    e, t, window = ui.test_window()
    _trace_reset()

    pick = yield from _edit_pivot_over_an_edge(e, window)
    x, y = pick["window_xy"]

    e.leftmouse.press()
    yield
    e.cursor_position_set(x + 120, y + 40, move=True)
    yield
    e.leftmouse.release()
    yield

    t.assertFalse(_trace_lines("pivot-click hit"), "a drag placed the pivot")


def _edit_pivot_setup(e, window, select_all=False):
    """Everything ``_edit_pivot_over_an_edge`` does except pressing the key."""
    import bmesh
    import bpy

    bpy.context.preferences.inputs.interaction_preset = 'CLARITY'
    yield

    area, region = _view3d_area_region(window)
    object = bpy.data.objects["Cube"]
    pick = _visible_edge_pick(object, region, area.spaces[0].region_3d)
    with bpy.context.temp_override(window=window, area=area, region=region):
        bpy.context.view_layer.objects.active = object
        object.select_set(True)
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_mode(type='EDGE')
        if select_all:
            bpy.ops.mesh.select_all(action='SELECT')
        else:
            bpy.ops.mesh.select_all(action='DESELECT')
            mesh = bmesh.from_edit_mesh(object.data)
            mesh.edges.ensure_lookup_table()
            mesh.edges[pick["edge_index"]].select_set(True)
            bmesh.update_edit_mesh(object.data)
    yield

    e.cursor_position_set(*pick["window_xy"], move=True)
    yield
    return pick


def pivot_edit_key_holds_momentarily_and_taps_toggle():
    """
    Maya offers the key both ways: "press and hold the D key to temporarily enter custom pivot
    editing mode" and release to leave, or "press D or Insert" to toggle a mode that stays.

    The harness cannot hold a key for a wall-clock duration, so the threshold is moved instead:
    ``pie_tap_timeout`` is the preference the rule reads, and driving it to both extremes picks the
    branch deterministically. Whether the mode is still on is read from the click - only a mode with
    a target reaches the operator.
    """
    import bpy

    e, t, window = ui.test_window()
    _trace_reset()

    yield from _edit_pivot_setup(e, window)

    # Every release counts as a hold: the mode must not survive it.
    bpy.context.preferences.view.pie_tap_timeout = 0
    e.d.press()
    yield
    e.d.release()
    yield
    e.leftmouse.press()
    yield
    e.leftmouse.release()
    yield
    t.assertFalse(_trace_lines("pivot-click hit"), "a held key left Edit Pivot on after its release")

    # Every release counts as a tap: the toggle stays on and the same click now lands.
    bpy.context.preferences.view.pie_tap_timeout = 1000
    e.d.press()
    yield
    e.d.release()
    yield
    e.leftmouse.press()
    yield
    e.leftmouse.release()
    yield
    t.assertEqual(len(_trace_lines("pivot-click hit")), 1, "a tapped key did not leave the mode on")

    # And pressing it again turns the toggle back off.
    yield e.d()
    e.leftmouse.press()
    yield
    e.leftmouse.release()
    yield
    t.assertEqual(len(_trace_lines("pivot-click hit")), 1, "the second tap did not leave the mode")


def pivot_click_does_not_change_the_selection():
    """
    Maya's behavior matrix, ``Ctrl-click`` row: "no selection operator is invoked". In Custom Pivot
    mode the whole left button belongs to the pivot, and ``view3d.select`` sits on the *press*, so
    the press has to be swallowed before any keymap sees it.
    """
    import bmesh
    import bpy

    e, t, window = ui.test_window()
    _trace_reset()

    # The manipulator sits on the selected edge, and a press on one of its highlighted handles is
    # the gizmo's by design - the operator asks about the highlight and lets that press through, the
    # same question the marquee drag asks. The reach is in pixels while the distance between two
    # edges of the cube is in scene units, so in the 800x600 window `ctest` opens the neighbouring
    # edge lands inside the default gizmo and in a large window it does not. Shrinking the gizmo
    # keeps the clicks below out of its reach wherever the test runs.
    bpy.context.preferences.view.gizmo_size = 10

    pick = yield from _edit_pivot_over_an_edge(e, window, select_all=False)

    object = bpy.data.objects["Cube"]

    def selected_edges():
        return sorted(edge.index for edge in bmesh.from_edit_mesh(object.data).edges if edge.select)

    before = selected_edges()
    t.assertEqual(before, [pick["edge_index"]])

    area, region = _view3d_area_region(window)
    picks = _visible_edge_picks(object, region, area.spaces[0].region_3d)
    others = [candidate for candidate in picks if candidate["edge_index"] != pick["edge_index"]]
    t.assertTrue(others, "the cube shows only one clickable edge")

    # A click leaves the pivot where it landed, so the next one is aimed at a different edge: a
    # plain press over the manipulator is a handle pick in Maya too, and this test is about the
    # clicks that are not.
    modifier_sets = ({}, {"ctrl": True}, {"shift": True}, {"ctrl": True, "shift": True})
    for index, modifiers in enumerate(modifier_sets):
        e.cursor_position_set(*others[index % len(others)]["window_xy"], move=True)
        yield
        hits_before = len(_trace_lines("pivot-click hit"))

        builder = e
        for name in modifiers:
            builder = getattr(builder, name)
        builder.leftmouse.press()
        yield
        builder.leftmouse.release()
        yield

        t.assertEqual(
            len(_trace_lines("pivot-click hit")), hits_before + 1,
            "the click with {!r} never reached the operator".format(modifiers),
        )
        t.assertEqual(
            selected_edges(), before,
            "the pivot click with {!r} changed the selection".format(modifiers),
        )


def pivot_click_outside_the_object_resets():
    """
    *Reset a component's custom pivot*: clicking "in the area outside of the object" resets, and the
    modifiers say how much - a plain click both, ``Ctrl`` the orientation alone, ``Ctrl + Shift``
    both back onto the reference frame of the selected components.

    ``Shift`` is deliberately absent: it places the pivot at the cursor instead, which is the newer
    *Change the pivot point* page and what the operator does above this branch.
    """
    import bpy

    e, t, window = ui.test_window()
    _trace_reset()

    pick = yield from _edit_pivot_over_an_edge(e, window, select_all=False)

    area, region = _view3d_area_region(window)
    object = bpy.data.objects["Cube"]
    picks = _visible_edge_picks(object, region, area.spaces[0].region_3d)
    # Not where the pivot already is: a press on a highlighted handle belongs to the manipulator.
    elsewhere = next(p for p in picks if p["edge_index"] != pick["edge_index"])["window_xy"]
    # Empty space, kept clear of the toolbar and sidebar that overlap the window region's edges.
    empty = (region.x + region.width - 30, region.y + 30)

    for modifiers in ({}, {"ctrl": True}, {"ctrl": True, "shift": True}):
        # Land the pivot somewhere first, so a reset has something to undo.
        e.cursor_position_set(*elsewhere, move=True)
        yield
        e.leftmouse.press()
        yield
        e.leftmouse.release()
        yield

        resets_before = len(_trace_lines("pivot-click reset"))
        e.cursor_position_set(*empty, move=True)
        yield
        builder = e
        for name in modifiers:
            builder = getattr(builder, name)
        builder.leftmouse.press()
        yield
        builder.leftmouse.release()
        yield

        t.assertEqual(
            len(_trace_lines("pivot-click reset")), resets_before + 1,
            "a click outside the object with {!r} did not reset the pivot".format(modifiers),
        )

    # Shift keeps its own meaning out here: it places, it does not reset.
    resets_before = len(_trace_lines("pivot-click reset"))
    hits_before = len(_trace_lines("pivot-click hit"))
    e.shift.leftmouse.press()
    yield
    e.shift.leftmouse.release()
    yield
    t.assertEqual(len(_trace_lines("pivot-click reset")), resets_before,
                  "Shift-click outside the object reset instead of placing the pivot")
    t.assertEqual(len(_trace_lines("pivot-click hit")), hits_before + 1)


def pivot_click_places_the_object_origin():
    """
    The same click in object mode, where the target is the object origin rather than a component
    pivot. Covers the branch that ``pivot_edit_click_handle_action`` used to carry a fallback for.
    """
    import bpy

    e, t, window = ui.test_window()
    _trace_reset()

    bpy.context.preferences.inputs.interaction_preset = 'CLARITY'
    yield

    area, region = _view3d_area_region(window)
    object = bpy.data.objects["Cube"]
    pick = _visible_edge_pick(object, region, area.spaces[0].region_3d)
    with bpy.context.temp_override(window=window, area=area, region=region):
        bpy.context.view_layer.objects.active = object
        object.select_set(True)
    yield

    e.cursor_position_set(*pick["window_xy"], move=True)
    yield
    yield e.d()

    e.leftmouse.press()
    yield
    e.leftmouse.release()
    yield

    hits = _trace_lines("pivot-click hit")
    t.assertTrue(hits, "the object mode click never reached the operator")
    t.assertTrue(_trace_lines("pivot-click apply"), "the object mode click applied nothing")
    t.assertEqual(_trace_fields(hits[-1])["position"], "1")


def pivot_click_repeats_on_a_second_click():
    """
    Two separate clicks place the pivot twice: the recognition is per press-release pair and keeps
    no state between them.

    The neighboring rule - that the release of a *double* click must not place the pivot a second
    time - cannot be driven from here. ``WM_event_add_simulate`` runs the state update with double
    click detection switched off, so no simulated press is ever promoted to ``KM_DBL_CLICK``. That
    rule is covered by ``clarity_input.ADoubleClickPressIsNotAClickPress`` instead.
    """
    e, t, window = ui.test_window()
    _trace_reset()

    yield from _edit_pivot_over_an_edge(e, window, select_all=False)

    e.leftmouse.press()
    yield
    e.leftmouse.release()
    yield
    t.assertEqual(len(_trace_lines("pivot-click hit")), 1)

    e.leftmouse.press()
    yield
    e.leftmouse.release()
    yield
    t.assertEqual(len(_trace_lines("pivot-click hit")), 2)


def pivot_click_selects_the_custom_axis_orientation():
    """
    Authoring a frame is what selects Clarity's `Custom axis orientation`, and it stays selected after
    the mode ends.

    `fixtures/maya_2025_pivot_debug.log` reads the Move context at every step of the same sequence:
    `2` after `ctxEditMode`, `6` once an orientation is authored, `6` still after leaving the mode.
    `wm.clarity_transform_orientation` is the same reading on this side - the resolved coordinate
    system of the active tool, `CUSTOM` included - and only a real click can reach it, because the
    selection happens inside the operator the click runs.
    """
    import bpy

    e, t, window = ui.test_window()
    _trace_reset()

    yield from _edit_pivot_setup(e, window, select_all=True)
    area, region = _view3d_area_region(window)
    window_manager = bpy.context.window_manager

    t.assertEqual(
        window_manager.clarity_transform_orientation,
        'WORLD',
        "the tool did not start in the coordinate system Blender defaults to",
    )

    yield e.d()
    t.assertEqual(
        window_manager.clarity_transform_orientation,
        'WORLD',
        "entering Edit Pivot selected a coordinate system by itself",
    )

    e.leftmouse.press()
    yield
    e.leftmouse.release()
    yield

    t.assertTrue(_trace_lines("pivot-click apply"), "the click applied nothing, see the trace")
    t.assertEqual(
        window_manager.clarity_transform_orientation,
        'CUSTOM',
        "authoring a frame did not select Custom",
    )

    # Leaving the mode is the point of the rule: Custom is a tool setting, not a mode's.
    yield e.d()
    t.assertEqual(
        window_manager.clarity_transform_orientation,
        'CUSTOM',
        "Custom was dropped when Edit Pivot ended",
    )

    # The operator polls for a viewport, so the override needs the area and the region as well.
    with bpy.context.temp_override(window=window, area=area, region=region):
        bpy.ops.clarity.transform_orientation_set(tool='MOVE', orientation='WORLD')
    yield
    t.assertEqual(
        window_manager.clarity_transform_orientation,
        'WORLD',
        "picking a coordinate system did not leave Custom",
    )
    t.assertFalse(
        bpy.data.objects["Cube"].custom_pivot is not None
        and bpy.data.objects["Cube"].custom_pivot.is_orientation_valid,
        "picking a coordinate system kept the authored frame",
    )


def pivot_frame_goes_with_the_selection():
    """
    The authored frame belongs to the selection it was aimed at: clearing that selection drops it, and
    the tool goes back to its own coordinate system.

    In Maya's debug log the same pair of steps reads `oriValid True -> False` and the Move context
    `6 -> 2`. This is the rule the state capture cannot see - it runs from the event dispatcher and
    from the manipulator refresh, and a scripted session with nothing selected has neither.
    """
    import bpy

    e, t, window = ui.test_window()
    _trace_reset()

    area, region = _view3d_area_region(window)

    bpy.context.preferences.inputs.interaction_preset = 'CLARITY'
    yield

    object = bpy.data.objects["Cube"]
    pick = _visible_edge_pick(object, region, area.spaces[0].region_3d)
    with bpy.context.temp_override(window=window, area=area, region=region):
        bpy.context.view_layer.objects.active = object
        object.select_set(True)
    yield

    e.cursor_position_set(*pick["window_xy"], move=True)
    yield
    yield e.d()

    e.leftmouse.press()
    yield
    e.leftmouse.release()
    yield

    t.assertTrue(_trace_lines("pivot-click apply"), "the object mode click applied nothing")
    t.assertTrue(object.custom_pivot.is_orientation_valid, "the click authored no frame")
    window_manager = bpy.context.window_manager
    t.assertEqual(window_manager.clarity_transform_orientation, 'CUSTOM')

    # Out of the mode first, then away from the selection: the mode owns the left button while it is
    # on, so the click that deselects can only arrive after it is off - which is how a user gets here.
    yield e.d()
    with bpy.context.temp_override(window=window, area=area, region=region):
        bpy.ops.object.select_all(action='DESELECT')
    yield

    # An event has to follow. The rule runs from the event dispatcher and from the manipulator
    # refresh, and an empty selection has no manipulator to refresh - in use the deselect *is* a click
    # and the motion after it carries the rule, which is what this move stands in for.
    e.cursor_position_set(region.x + 4, region.y + 4, move=True)
    yield

    t.assertFalse(
        object.custom_pivot is not None and object.custom_pivot.is_orientation_valid,
        "the frame survived the selection it was aimed at",
    )
    t.assertEqual(
        window_manager.clarity_transform_orientation,
        'WORLD',
        "the tool did not go back to its own coordinate system",
    )


def _object_origin_pixel(object, region, region_3d):
    """Where the manipulator sits in object mode: the object's own origin, projected."""
    from bpy_extras.view3d_utils import location_3d_to_region_2d

    position_2d = location_3d_to_region_2d(region, region_3d, object.matrix_world.translation)
    if position_2d is None:
        raise Exception("the manipulator is off screen")
    return (region.x + int(round(position_2d.x)), region.y + int(round(position_2d.y)))


def _vertex_pixels(object, region, region_3d):
    from bpy_extras.view3d_utils import location_3d_to_region_2d

    result = []
    for vertex in object.data.vertices:
        world = object.matrix_world @ vertex.co
        position_2d = location_3d_to_region_2d(region, region_3d, world)
        if position_2d is None:
            continue
        if not (8 < position_2d.x < region.width - 8 and 8 < position_2d.y < region.height - 8):
            continue
        result.append(
            (vertex.index,
             (region.x + int(round(position_2d.x)), region.y + int(round(position_2d.y))),
             world.copy())
        )
    return result


def pivot_snap_drag_lands_on_the_target():
    """
    A snapped drag puts the pivot on the target itself, and the grab offset does not come along.

    This is the wiring, not the rule. `clarity_pivot_snap_decision_get` is pinned by
    `transform_snap_test.cc`, but the fields it decides from - `has_target`, and the target it takes
    verbatim - are filled in `recalcDataClarityPivot` from `t->tsnap.snap_target` while a real drag
    is running, and nothing drove a real drag at them. The unit tests would keep passing if the drag
    stopped arriving.

    The reference is measured, not assumed: in `fixtures/maya_2025_pivot_gestures.json` the same
    gesture - grabbed deliberately off centre, `V` held, dropped on a vertex - answers `move -rpr`
    onto that vertex, with the pivot 0.0 away from it.

    In object mode, as that capture was: snapping refuses the geometry being transformed, and in edit
    mode with the whole cube selected there is nothing left for the pointer to find - the trace says
    `target=0` for a pointer sitting exactly on a vertex.
    """
    import bpy
    from mathutils import Vector

    e, t, window = ui.test_window()
    trace = _trace_reset()

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

    handle = _object_origin_pixel(object, region, region_3d)
    candidates = _vertex_pixels(object, region, region_3d)
    t.assertTrue(candidates, "no vertex of the cube is on screen to snap to")

    def pixel_distance(entry):
        return ((entry[1][0] - handle[0]) ** 2 + (entry[1][1] - handle[1]) ** 2) ** 0.5

    index, target_pixel, target_world = max(candidates, key=pixel_distance)
    t.assertGreater(pixel_distance((index, target_pixel, target_world)), 40,
                    "the cube is too small on screen for the drag to be unambiguous")

    e.cursor_position_set(*handle, move=True)
    yield
    # `D` toggles Edit Pivot; without it the press below belongs to the object manipulator.
    yield e.d()

    # Over the handle, and only then the press: the manipulator is offered a plain press when one of
    # its handles is highlighted, and the highlight is computed from the move.
    e.cursor_position_set(*handle, move=True)
    yield
    # Off centre on purpose - that offset is what must *not* survive the snap.
    grab = (handle[0] + 6, handle[1] + 6)
    e.cursor_position_set(*grab, move=True)
    yield

    e.v.press()
    yield
    e.leftmouse.press()
    yield
    for step in range(1, 6):
        x = grab[0] + (target_pixel[0] - grab[0]) * step / 5
        y = grab[1] + (target_pixel[1] - grab[1]) * step / 5
        e.cursor_position_set(int(round(x)), int(round(y)), move=True)
        yield
    e.leftmouse.release()
    yield
    e.v.release()
    yield

    updates = _trace_lines("pivot-snap")
    t.assertTrue(_trace_lines("pivot-drag-begin"),
                 "the drag never reached the pivot conversion, see " + trace)
    t.assertTrue(updates, "the drag ran but no snap update was recorded, see " + trace)

    snapped = [line for line in updates if _trace_fields(line)["target"] == "1"]
    t.assertTrue(snapped, "the drag found nothing to snap to, see " + trace)

    last = _trace_fields(snapped[-1])
    t.assertEqual(last["from_target"], "1", "the pivot was placed by the pointer, not by the target")

    result = Vector([float(value) for value in last["result"].split()])
    target = Vector([float(value) for value in last["target_co"].split()])
    pointer = Vector([float(value) for value in last["pointer"].split()])
    t.assertLess((result - target).length, 1.0e-4,
                 "the pivot did not land on the target: {!r} against {!r}".format(result, target))
    t.assertGreater((result - pointer).length, 1.0e-6,
                    "the target and the pointer agree, so this drag proves nothing")


_PROFILE_CACHE = {}


def _profile_value(name):
    """
    One geometry constant of the drawn manipulator, in gizmo units.

    The test aims where the C++ profile says the arrow is drawn instead of repeating its numbers, so
    that changing the size of the manipulator moves the aim with it and never silently turns this
    into a test of empty screen space.
    """
    if not _PROFILE_CACHE:
        import sys
        from pathlib import Path

        root = Path(__file__).resolve().parents[3]
        sys.path.insert(0, str(root / "tests" / "pivot_reference"))
        try:
            from test_clarity_pivot_visual_profile import _profile_float
        finally:
            del sys.path[0]
        source = (
            root / "source/blender/editors/transform/transform_gizmo_clarity_cache.hh"
        ).read_text(encoding="utf-8")
        _PROFILE_CACHE["source"] = source
        _PROFILE_CACHE["read"] = _profile_float
    return _PROFILE_CACHE["read"](_PROFILE_CACHE["source"], name)


def _pivot_direction_screen(object, region, region_3d, direction, origin=None):
    """
    Where one direction out of the pivot runs on screen: the centre, the screen direction, and how
    many pixels one gizmo unit spans along it.

    The manipulator is drawn at a constant pixel size - one gizmo unit is `gizmo_size` pixels in the
    view plane. A world direction is foreshortened by however far it leans out of that plane, which
    is the ratio between its projected length and a view-plane vector's.
    """
    import bpy
    from bpy_extras.view3d_utils import location_3d_to_region_2d
    from mathutils import Vector

    if origin is None:
        origin = object.matrix_world.translation
    axis = direction.normalized()
    in_view_plane = region_3d.view_rotation @ Vector((1.0, 0.0, 0.0))

    here = location_3d_to_region_2d(region, region_3d, origin)
    along = location_3d_to_region_2d(region, region_3d, origin + axis)
    across = location_3d_to_region_2d(region, region_3d, origin + in_view_plane)
    if here is None or along is None or across is None:
        raise Exception("the manipulator is off screen")
    if (across - here).length < 1.0:
        raise Exception("the view has no scale to measure the manipulator against")

    unit = bpy.context.preferences.view.gizmo_size * ((along - here).length / (across - here).length)
    centre = Vector((region.x + here.x, region.y + here.y))
    return centre, (along - here).normalized(), unit


def _pivot_axis_screen(object, region, region_3d, axis_index, origin=None):
    """Where one pivot axis runs on screen. See #_pivot_direction_screen."""
    from mathutils import Vector

    axis = Vector((0.0, 0.0, 0.0))
    axis[axis_index] = 1.0
    return _pivot_direction_screen(object, region, region_3d, axis, origin)


def _pivot_axis_arrow_pixels(object, region, region_3d, axis_index):
    """The stem of one pivot arrow: centre, direction, and the distances it spans, in pixels."""
    centre, direction, unit = _pivot_axis_screen(object, region, region_3d, axis_index)
    return (
        centre,
        direction,
        _profile_value("edit_pivot_axis_start") * unit,
        _profile_value("edit_pivot_axis_end") * unit,
    )


def _pivot_drag_probe(e, point):
    """
    Aim at one point, press, drag, cancel. Yields once per simulated step.

    Returns the `pivot-drag-begin` line this gesture wrote, or None when the press started no pivot
    drag at all - which is the whole measurement: the line exists only for a press that a pivot
    handle answered.

    The cursor is moved twice before the press because a handle is offered a press only once it is
    highlighted, and the highlight is computed from the move that precedes it. The drag is cancelled
    so that the manipulator is still in the same place for the next probe.
    """
    before = len(_trace_lines("pivot-drag-begin"))
    x, y = int(round(point.x)), int(round(point.y))
    e.cursor_position_set(x, y, move=True)
    yield
    e.cursor_position_set(x, y, move=True)
    yield
    e.leftmouse.press()
    yield
    for step in range(1, 4):
        e.cursor_position_set(x + step * 6, y, move=True)
        yield
    yield e.esc()
    e.leftmouse.release()
    yield
    lines = _trace_lines("pivot-drag-begin")
    return lines[-1] if len(lines) > before else None


def pivot_axis_handle_drags_the_pivot_along_one_axis():
    """
    A press on an axis arrow starts a pivot move constrained to that axis, and nothing else.

    Maya's number for the gesture is in `fixtures/maya_2025_pivot_gestures.json`: a press 75 px out
    along X answers `move -r -1.405948 0 0`, one component. The rule on this side is pinned by
    `AConstrainedDragKeepsThePivotOnItsConstraint`. Blender's trackball is hidden in Edit Pivot so
    its selection disc cannot cover the Maya-sized arrow; this test keeps that arrow reachable.

    The drag is cancelled: what is being checked is which transform the press began and under which
    constraint, and letting it finish would only move the pivot.
    """
    import bpy

    e, t, window = ui.test_window()
    trace = _trace_reset()

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

    centre, direction, start, end = _pivot_axis_arrow_pixels(object, region, region_3d, 0)
    t.assertGreater(end - start, 10.0, "the X arrow is too short on screen to aim at")
    grab = centre + direction * ((start + end) * 0.5)
    grab = (int(round(grab.x)), int(round(grab.y)))

    e.cursor_position_set(int(round(centre.x)), int(round(centre.y)), move=True)
    yield
    # Enter Edit Pivot directly from the factory-startup Select state. This intentionally keeps the
    # Metal selection pass cold: the axis must not depend on a transform-tool draw having warmed it.
    # `D` toggles Edit Pivot; without it the press belongs to the object manipulator.
    yield e.d()

    # Over the arrow, and only then the press: a handle is offered a plain press once it is
    # highlighted, and the highlight is computed from the move.
    e.cursor_position_set(*grab, move=True)
    yield
    e.cursor_position_set(*grab, move=True)
    yield
    e.leftmouse.press()
    yield
    for step in range(1, 4):
        e.cursor_position_set(grab[0] + step * 6, grab[1], move=True)
        yield
    yield e.esc()
    e.leftmouse.release()
    yield

    begins = _trace_lines("pivot-drag-begin")
    t.assertTrue(
        begins,
        "the press at {!r}, on the X arrow between {:.0f} and {:.0f} px from the centre {!r}, "
        "started no pivot drag, see {:s}".format(
            grab, start, end, (int(centre.x), int(centre.y)), trace),
    )
    fields = _trace_fields(begins[-1])
    t.assertEqual(fields["mode"], "1",
                  "the arrow started transform mode " + fields["mode"] + ", not a translation")
    constraint = int(fields["con"])
    t.assertTrue(constraint & 1, "the drag the arrow started carries no constraint")
    t.assertTrue(constraint & 2, "the drag is constrained, but not to the pivot's X axis")


def pivot_axis_handles_answer_all_along_the_arrow():
    """
    Every part of an axis arrow answers a press, and answers with its own axis.

    The complaint this pins down is not that the handles never work - it is that hitting them is a
    matter of luck. Picking is decided by the depth buffer among everything Edit Pivot draws: three
    rings cross the three arrows, plane handles sit between them and a centre square sits on top of
    where they all meet, so an arrow can be highlighted at one distance from the centre and lost at
    the next. A single press in the middle of the stem cannot see that; a sweep of the whole arrow
    can, and it reports which distances failed rather than only that something did.

    Each probe presses, drags and cancels, so the manipulator stays where it was and the next probe
    aims at the same geometry. `pivot-drag-begin` carries the transform mode and the constraint the
    pressed handle asked for: mode 1 is a translation, and the constraint bits are X, Y and Z from
    bit 1 up, with bit 0 saying a constraint applies at all.
    """
    import bpy
    from mathutils import Vector

    e, t, window = ui.test_window()
    trace = _trace_reset()

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

    start = _profile_value("edit_pivot_axis_start")
    end = _profile_value("edit_pivot_axis_end")
    # The cone continues 0.25 gizmo units past the stem, and the tip is a handle like the rest of it.
    tip = end + 0.25
    # Along the stem: just inside both ends, the middle, and the two quarters between - the ring
    # band crosses one of them, the plane handles sit beside another, and the centre square is
    # nearest the first. Six pixels off the line is the other half of what the hit cylinder around
    # the stem promises, and the cone is probed down its middle because it narrows to a point.
    # The innermost aim clears the centre square: it is drawn 0.19 units across, so its corners
    # reach further than its edges and the first tenth of the stem is inside them. That square is a
    # handle of its own and is allowed to answer there.
    probes = [
        (start + (end - start) * fraction, offset)
        for fraction in (0.15, 0.3, 0.5, 0.7, 0.95)
        for offset in (0.0, 6.0)
    ]
    probes.append((end + 0.12, 0.0))

    centre, _, _ = _pivot_axis_screen(object, region, region_3d, 0)
    e.cursor_position_set(int(round(centre.x)), int(round(centre.y)), move=True)
    yield
    # `D` toggles Edit Pivot. Without the mode these presses belong to the object manipulator.
    yield e.d()

    misses = []
    for axis_index, axis_name in enumerate("XYZ"):
        for aim, offset in probes:
            centre, direction, unit = _pivot_axis_screen(object, region, region_3d, axis_index)
            across = Vector((-direction.y, direction.x))
            point = centre + direction * (aim * unit) + across * offset
            line = yield from _pivot_drag_probe(e, point)
            where = "{:s} at {:.0f} px out, {:.0f} px across".format(
                axis_name, aim * unit, offset)
            if line is None:
                misses.append(where + ": no drag started")
                continue
            fields = _trace_fields(line)
            constraint = int(fields["con"])
            if fields["mode"] != "1":
                misses.append(where + ": transform mode " + fields["mode"])
            elif not constraint & 1:
                misses.append(where + ": the drag carries no constraint")
            elif not constraint & (1 << (axis_index + 1)):
                misses.append(where + ": constrained to {:d}, not to {:s}".format(
                    constraint, axis_name))

    t.assertFalse(
        misses,
        "{:d} of {:d} aims at an axis arrow did not start that axis, see {:s}:\n  {:s}".format(
            len(misses), 3 * len(probes), trace, "\n  ".join(misses)),
    )

    # And the same gesture past the end of the arrow starts nothing, which is what makes the sweep
    # above a measurement of the arrow rather than of the whole screen.
    centre, direction, unit = _pivot_axis_screen(object, region, region_3d, 0)
    beyond = centre + direction * ((tip + 0.5) * unit)
    line = yield from _pivot_drag_probe(e, beyond)
    t.assertIsNone(
        line,
        "a press {:.0f} px out, past the {:.0f} px tip of the X arrow, still started a pivot "
        "drag".format((tip + 0.5) * unit, tip * unit),
    )


def _ring_facing_view(region_3d, around):
    """How far one point of a ring leans towards the camera, from -1 behind to 1 in front."""
    from mathutils import Vector

    return around.normalized().dot(region_3d.view_rotation @ Vector((0.0, 0.0, 1.0)))


def _ring_screen_points(object, region, region_3d, axis_index, radius):
    """
    The drawn half of one ring as a screen polyline, sampled every ten degrees.

    Maya clips a ring at the plane through the pivot: only the arc facing the camera is drawn, and
    the selection pass is clipped with it, so the half that is not there answers nothing.
    """
    from mathutils import Vector

    points = []
    for step in range(36):
        angle = step * (math.pi / 18.0)
        around = Vector((0.0, 0.0, 0.0))
        around[(axis_index + 1) % 3] = math.cos(angle)
        around[(axis_index + 2) % 3] = math.sin(angle)
        if _ring_facing_view(region_3d, around) < 0.0:
            continue
        centre, direction, unit = _pivot_direction_screen(object, region, region_3d, around)
        points.append(centre + direction * (radius * unit))
    return points


def _ring_probe_direction(object, region, region_3d, axis_index, radius, offsets):
    """
    A direction out of the pivot where one ring is alone on screen, at every offset probed.

    A ring lies in the plane of the other two axes and crosses both of them, and those crossings
    belong to the arrows. Halfway between them it is clear of both - in three dimensions. On screen
    it need not be: a view can lay the diagonal of two axes right along the third, which is the same
    coincidence that lets a plane handle sit on an arrow. So the place is found rather than assumed:
    the ring is walked - the drawn half of it - and the angle whose probes stand furthest from all
    three arrows wins.

    The offsets are part of the search because they move along the radius, and every arrow runs out
    of the same centre: a step towards it is a step towards all three of them. The other two rings
    count as well - three rings around one point cross each other, and a crossing is a place where
    either of them may fairly answer.
    """
    from mathutils import Vector

    others = [_ring_screen_points(object, region, region_3d, other, radius)
              for other in range(3) if other != axis_index]

    def walk(facing_min):
        best = None
        for step in range(72):
            angle = step * (math.pi / 36.0)
            around = Vector((0.0, 0.0, 0.0))
            around[(axis_index + 1) % 3] = math.cos(angle)
            around[(axis_index + 2) % 3] = math.sin(angle)
            if _ring_facing_view(region_3d, around) < facing_min:
                continue
            centre, direction, unit = _pivot_direction_screen(object, region, region_3d, around)
            clearance = None
            for offset in offsets:
                point = centre + direction * (radius * unit + offset)
                near = min(_distance_to_axis(object, region, region_3d, other, point)
                           for other in range(3))
                for ring in others:
                    near = min(near, min((point - other).length for other in ring))
                clearance = near if clearance is None else min(clearance, near)
            if best is None or clearance > best[0]:
                best = (clearance, centre, direction, unit)
        return best

    # Only the half that is drawn, with a margin that keeps the probe off the clip plane itself,
    # where the ring ends. A ring seen face on has no such half - it lies in the view plane, the
    # clip takes nothing away from it, and then the whole of it is fair game.
    best = walk(0.25) or walk(-1.0)
    clearance, centre, direction, unit = best
    return centre, direction, unit, clearance


def _distance_to_axis(object, region, region_3d, axis_index, point):
    """How far a screen point is from the line one arrow runs along."""
    centre, direction, _ = _pivot_axis_screen(object, region, region_3d, axis_index)
    offset = point - centre
    return abs(offset.x * direction.y - offset.y * direction.x)


def pivot_rings_answer_beside_their_line():
    """
    A rotation ring answers the cursor near it, not only on it.

    Maya gives the tolerance to the cursor rather than to the handle: its rings are drawn one pixel
    wide and picked one pixel wide, and what makes them comfortable is the manipulator Pick Range,
    the eight pixels within which the cursor must land before a handle highlights. A ring is the
    handle that shows this most plainly - it is a curve, so the only way to be on it is to be
    exactly on it, and every pixel of slack has to come from somewhere else.

    Six and ten pixels off the line are past the ring's own selection band, so this passes only
    while the cursor carries a range of its own.
    """
    import bpy
    from mathutils import Vector

    e, t, window = ui.test_window()
    trace = _trace_reset()

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

    centre, _, _ = _pivot_axis_screen(object, region, region_3d, 0)
    e.cursor_position_set(int(round(centre.x)), int(round(centre.y)), move=True)
    yield
    # `D` toggles Edit Pivot, which is the layout that draws the rings.
    yield e.d()

    radius = _profile_value("edit_pivot_rotate_scale")
    # Outwards only. Every arrow leaves the same centre, so a step from the ring towards it is a
    # step towards all three of them, and those pixels are the arrows' by the rule that made the
    # axes reachable at all. Outside the ring nothing else is drawn until the plane handles, which
    # is where a ring has to answer for itself. Six pixels is already past its own selection band;
    # ten is past anything the band could explain.
    offsets = (6.0, 10.0)
    misses = []
    for axis_index, axis_name in enumerate("XYZ"):
        centre, direction, unit, clearance = _ring_probe_direction(
            object, region, region_3d, axis_index, radius, offsets)
        # A neighbour reaches about sixteen pixels from itself here - its own selection width, or a
        # few pixels of tapered stem, plus the corner of the cursor's square range - and it is meant
        # to win those. A probe inside that is not a probe of this ring. Three rings and three
        # arrows around one point leave little more than that, which is the measurement this
        # threshold really carries: the manipulator is crowded, and every pixel of clearance it has
        # left is spoken for.
        t.assertGreater(clearance, 17.0,
                        "no place on the {:s} ring stands clear of the other handles in this view, "
                        "the best is {:.0f} px".format(axis_name, clearance))
        for offset in offsets:
            # Off the line along the radius: the ring runs across that direction, so the whole
            # offset is distance from it.
            point = centre + direction * (radius * unit + offset)
            line = yield from _pivot_drag_probe(e, point)
            where = "{:s} ring, {:.0f} px off its line, {:.0f} px clear of every arrow".format(
                axis_name, offset, clearance)
            if line is None:
                misses.append(where + ": no drag started")
                continue
            fields = _trace_fields(line)
            if fields["mode"] != "2":
                misses.append(where + ": transform mode " + fields["mode"] + " constraint " +
                              fields["con"] + ", not a rotation")
            elif not int(fields["con"]) & (1 << (axis_index + 1)):
                misses.append(where + ": rotated around {:s}, not {:s}".format(
                    fields["con"], axis_name))

    t.assertFalse(
        misses,
        "{:d} of {:d} aims beside a ring did not reach it, see {:s}:\n  {:s}".format(
            len(misses), 6, trace, "\n  ".join(misses)),
    )


def _pivot_drag_along_axis(e, object, region, region_3d, axis_index, steps=5):
    """
    Grab an axis arrow and carry it. Yields once per simulated step, and lets go at the end.

    The manipulator is aimed at from where the pivot is now, not from the object's origin: once it
    has been moved the two are no longer the same point, and a second drag aimed at the origin grabs
    nothing at all.
    """
    import bpy
    from mathutils import Vector

    origin = Vector(bpy.context.window_manager.clarity_pivot_position)
    centre, direction, unit = _pivot_axis_screen(object, region, region_3d, axis_index, origin)
    start = _profile_value("edit_pivot_axis_start")
    end = _profile_value("edit_pivot_axis_end")
    grab = centre + direction * ((start + end) * 0.5 * unit)
    x, y = int(round(grab.x)), int(round(grab.y))

    e.cursor_position_set(x, y, move=True)
    yield
    e.cursor_position_set(x, y, move=True)
    yield
    e.leftmouse.press()
    yield
    for step in range(1, steps + 1):
        e.cursor_position_set(int(round(x + direction.x * step * 8)),
                              int(round(y + direction.y * step * 8)), move=True)
        yield
    e.leftmouse.release()
    yield


def pivot_axis_drag_is_undone():
    """
    One Undo puts a dragged pivot back where it was.

    Maya keeps the pivot in the transform node, so moving it is an edit to the scene like any other
    and the undo queue carries it without being asked. Here the pivot of a component lives in the
    window runtime, which no undo step knows about, so the runtime has to hand its own before-and-
    after to the step being pushed. That handoff was wired for the click and for the reset commands
    and never for the drag - the one gesture that could not be performed at all until the handles
    became reachable, which is why nothing noticed.

    The manipulator's own position is what is checked, not the storage behind it: object pivots and
    component pivots are kept in different places, and what the user undoes is the manipulator they
    moved.
    """
    import bpy
    from mathutils import Vector

    e, t, window = ui.test_window()
    _trace_reset()

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

    centre, _, _ = _pivot_axis_screen(object, region, region_3d, 0)
    e.cursor_position_set(int(round(centre.x)), int(round(centre.y)), move=True)
    yield
    # `D` toggles Edit Pivot.
    yield e.d()

    manager = bpy.context.window_manager
    start = Vector(manager.clarity_pivot_position)
    yield from _pivot_drag_along_axis(e, object, region, region_3d, 0)
    once = Vector(manager.clarity_pivot_position)
    yield from _pivot_drag_along_axis(e, object, region, region_3d, 1)
    twice = Vector(manager.clarity_pivot_position)
    t.assertGreater((once - start).length, 0.05, "the first drag did not move the pivot")
    t.assertGreater((twice - once).length, 0.05, "the second drag did not move the pivot")

    # Two moves and one Undo: what comes back is the pivot as the first drag left it. Undoing to
    # where it started would mean the pivot was dropped rather than restored - the same result a
    # pivot that simply recomputes itself from the selection would give, and not undo at all.
    yield e.ctrl.z()
    for _ in range(3):
        yield
    restored = Vector(manager.clarity_pivot_position)
    t.assertLess((restored - once).length, 1.0e-4,
                 "Undo left the pivot at {!r}, not back at {!r} where the first drag left it "
                 "(it started at {!r})".format(tuple(restored), tuple(once), tuple(start)))
    t.assertTrue(manager.clarity_pivot_edit_active, "Undo left Edit Pivot")

    # And Redo carries it forward again: the step holds both sides of the move, so the runtime
    # follows the queue in either direction rather than only being able to go back. `Ctrl Y` is
    # Maya's redo and the only chord that reaches the operator here - the Clarity dispatcher claims
    # `Ctrl Shift Z` for the face-centre toggle before the keymap sees it.
    yield e.ctrl.y()
    for _ in range(3):
        yield
    redone = Vector(manager.clarity_pivot_position)
    t.assertLess((redone - twice).length, 1.0e-4,
                 "Redo left the pivot at {!r}, not forward at {!r}".format(
                     tuple(redone), tuple(twice)))


def pivot_component_drag_is_undone():
    """
    The same Undo for the pivot of a component selection.

    The sibling of `pivot_axis_drag_is_undone`, and the one that can fail on its own: an object's
    pivot is stored on the object, so the memory-file step a transform pushes carries it back
    whether anyone arranged for that or not. A component's pivot is stored in the window runtime,
    which no undo step reaches unless the runtime hands its own before-and-after to the step.
    """
    import bpy
    from mathutils import Vector

    e, t, window = ui.test_window()
    _trace_reset()

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
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_mode(type='EDGE')
        bpy.ops.mesh.select_all(action='SELECT')
    for _ in range(4):
        yield

    centre, _, _ = _pivot_axis_screen(object, region, region_3d, 0)
    e.cursor_position_set(int(round(centre.x)), int(round(centre.y)), move=True)
    yield
    yield e.d()

    manager = bpy.context.window_manager
    start = Vector(manager.clarity_pivot_position)
    yield from _pivot_drag_along_axis(e, object, region, region_3d, 0)
    once = Vector(manager.clarity_pivot_position)
    yield from _pivot_drag_along_axis(e, object, region, region_3d, 1)
    twice = Vector(manager.clarity_pivot_position)
    t.assertGreater((once - start).length, 0.05, "the first drag did not move the component pivot")
    t.assertGreater((twice - once).length, 0.05, "the second drag did not move the component pivot")

    # As in the object case: one Undo has to give back the pivot the first drag authored, not the
    # selection centre it started from. A runtime pivot that is dropped on undo lands on that
    # centre, which is exactly the failure this arrangement is here to tell apart.
    yield e.ctrl.z()
    for _ in range(3):
        yield
    restored = Vector(manager.clarity_pivot_position)
    t.assertLess((restored - once).length, 1.0e-4,
                 "Undo left the component pivot at {!r}, not back at {!r} where the first drag "
                 "left it (it started at {!r})".format(tuple(restored), tuple(once), tuple(start)))
    t.assertTrue(manager.clarity_pivot_edit_active, "Undo left Edit Pivot")

    # And Redo carries it forward again: the step holds both sides of the move, so the runtime
    # follows the queue in either direction rather than only being able to go back. `Ctrl Y` is
    # Maya's redo and the only chord that reaches the operator here - the Clarity dispatcher claims
    # `Ctrl Shift Z` for the face-centre toggle before the keymap sees it.
    yield e.ctrl.y()
    for _ in range(3):
        yield
    redone = Vector(manager.clarity_pivot_position)
    t.assertLess((redone - twice).length, 1.0e-4,
                 "Redo left the pivot at {!r}, not forward at {!r}".format(
                     tuple(redone), tuple(twice)))


def pivot_click_aligns_the_pivot_to_the_clicked_vertex():
    """
    A click on a vertex aims the pivot along that vertex's normal.

    The sibling of `pivot_click_aligns_the_pivot_to_the_clicked_edge`, and it exists because that one
    kept passing while vertices stopped working entirely: a mesh vertex is reported only through
    `SCE_SNAP_TO_EDGE_ENDPOINT`, `SCE_SNAP_TO_POINT` covers loose points, and asking for endpoints
    alongside edges hands a third of every edge to each of its ends. `pivot_snap_target_query` and
    the click now ask in two passes for that reason, and this is what holds the vertex half of it.

    The cube's corner is the case that cannot pass by accident: its vertex normal is the diagonal,
    45 degrees from every face beside it and from every edge meeting it.
    """
    import bpy
    from mathutils import Vector

    e, t, window = ui.test_window()
    trace = _trace_reset()

    bpy.context.preferences.inputs.interaction_preset = 'CLARITY'
    yield

    area, region = _view3d_area_region(window)
    region_3d = area.spaces[0].region_3d
    object = bpy.data.objects["Cube"]
    with bpy.context.temp_override(window=window, area=area, region=region):
        bpy.context.view_layer.objects.active = object
        object.select_set(True)
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_mode(type='VERT')
        bpy.ops.mesh.select_all(action='SELECT')
    yield

    candidates = _vertex_pixels(object, region, region_3d)
    t.assertTrue(candidates, "no vertex of the cube is on screen to click")
    index, pixel, world = candidates[0]

    e.cursor_position_set(*pixel, move=True)
    yield
    # `D` toggles Edit Pivot. Without the mode the click below is an ordinary selection.
    yield e.d()

    e.leftmouse.press()
    yield
    e.leftmouse.release()
    yield

    hits = _trace_lines("pivot-click hit")
    t.assertTrue(hits, "the click never reached TRANSFORM_OT_clarity_pivot_click, see " + trace)
    fields = _trace_fields(hits[-1])

    # `SCE_SNAP_TO_VERTEX`, the composite of `SCE_SNAP_TO_POINT` and `SCE_SNAP_TO_EDGE_ENDPOINT`.
    t.assertTrue(
        int(fields["type"]) & 5,
        "a click on vertex {:d} at {!r} reported snap type {:s}, not a vertex".format(
            index, pixel, fields["type"]),
    )
    t.assertEqual(int(fields["index"]), index, "the click aimed at a different vertex")

    normal = Vector([float(value) for value in fields["normal"].split()])
    expected = world.normalized()
    t.assertGreater(
        normal.dot(expected), 0.99,
        "expected the corner's own normal {!r}, got {!r}".format(
            tuple(round(value, 3) for value in expected),
            tuple(round(value, 3) for value in normal),
        ),
    )


def diag_green_dot():
    """TEMPORARY diagnostic: capture the viewport and the screen positions of every candidate."""
    import bpy
    from bpy_extras.view3d_utils import location_3d_to_region_2d
    from mathutils import Vector

    e, t, window = ui.test_window()
    _trace_reset()

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
    for _ in range(3):
        yield

    manager = bpy.context.window_manager
    centre, direction, unit = _pivot_axis_screen(object, region, region_3d, 0)
    e.cursor_position_set(int(round(centre.x)), int(round(centre.y)), move=True)
    yield
    yield e.d()
    for _ in range(4):
        yield
    # Move the pivot well away from the object so every candidate is distinguishable.
    grab = centre + direction * (0.45 * unit)
    x, y = int(round(grab.x)), int(round(grab.y))
    e.cursor_position_set(x, y, move=True)
    yield
    e.cursor_position_set(x, y, move=True)
    yield
    e.leftmouse.press()
    yield
    for step in range(1, 10):
        e.cursor_position_set(x + step * 12, y - step * 6, move=True)
        yield
    e.leftmouse.release()
    for _ in range(6):
        yield
    # Park the cursor away from everything so no hover marker is drawn.
    e.cursor_position_set(int(round(centre.x)) + 300, int(round(centre.y)) + 200, move=True)
    for _ in range(4):
        yield

    def screen(point):
        position = location_3d_to_region_2d(region, region_3d, Vector(point))
        if position is None:
            return None
        return (round(region.x + position.x, 1), round(region.y + position.y, 1))

    lines = ["region=({:d},{:d},{:d},{:d})".format(region.x, region.y, region.width, region.height)]
    lines.append("pivot {!r}".format(screen(manager.clarity_pivot_position)))
    lines.append("object_origin {!r}".format(screen(object.matrix_world.translation)))
    mesh = object.data
    for index, polygon in enumerate(mesh.polygons):
        lines.append("face_center {:d} {!r}".format(
            index, screen(object.matrix_world @ polygon.center)))
    for index, vertex in enumerate(mesh.vertices):
        lines.append("vertex {:d} {!r}".format(index, screen(object.matrix_world @ vertex.co)))
    with open("S:/Clarity/diag-dot.txt", "w", encoding="utf-8") as file:
        file.write("\n".join(lines))

    with bpy.context.temp_override(window=window, area=area, region=region):
        bpy.ops.screen.screenshot(filepath="S:/Clarity/diag-dot.png")
    yield
