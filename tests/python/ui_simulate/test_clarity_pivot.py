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

Requires ``BLENDER_CLARITY_SNAP_TRACE_FILE``: the click operator reports what it hit and what it
applied there, and that trace is what the assertions read.

    blender --enable-event-simulate --factory-startup \\
        --python tests/python/ui_simulate/run_blender_setup.py -- \\
        --tests test_clarity_pivot.pivot_click_aligns_the_pivot_to_the_clicked_edge
"""

import os

import modules.ui_test_utils as ui


def _trace_path():
    path = os.environ.get("BLENDER_CLARITY_SNAP_TRACE_FILE")
    if not path:
        raise Exception("BLENDER_CLARITY_SNAP_TRACE_FILE must be set for this test")
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
