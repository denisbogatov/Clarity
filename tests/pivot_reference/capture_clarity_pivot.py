# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Record this fork's Edit Pivot behavior in the schema the Maya capture uses.

Run it against a built Blender, from the repository root. A window is required, not `--background`:
the pivot operators poll for a 3D viewport, and a background session has no screen to hold one.

  blender --factory-startup --python tests/pivot_reference/capture_clarity_pivot.py -- \
      --output tests/pivot_reference/fixtures/clarity_pivot_interaction.json --quit

`compare_pivot_reference.py` then diffs the result against
`fixtures/maya_2025_pivot_interaction.json` step by step. The shared schema is the point: the diff is
the answer, and neither side has to be re-derived by hand.

The steps mirror `capture_reference_pivot.py`, and one of them cannot be mirrored: the Clarity tool is
switched by a physical key, so a script cannot make Move the active tool. It does not matter for what
is compared here - a tool without a coordinate system of its own resolves against Move's slot - and
the click that authors a frame in the viewport has its own test, `test_clarity_pivot`, which drives
real events. Everything else is an operator or a property, and a step that still fails is recorded as
`{"error": ...}` rather than skipped, exactly as the Maya side records what a standalone session
cannot perform.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Callable

import bpy
from mathutils import Euler, Vector


def _safe(description: str, function: Callable[[], Any]) -> Any:
    try:
        return function()
    except Exception as error:  # noqa: BLE001 - the message is the result here.
        return {"error": "{}: {}".format(description, error)}


def _vector(value: Any) -> list[float]:
    return [float(item) for item in value]


def _matrix(value: Any) -> list[float]:
    return [float(item) for row in value for item in row]


def _viewport_override() -> dict[str, Any]:
    """Context the pivot operators poll for: a 3D viewport and its window region."""
    window = bpy.context.window_manager.windows[0]
    for area in window.screen.areas:
        if area.type != "VIEW_3D":
            continue
        for region in area.regions:
            if region.type == "WINDOW":
                return {"window": window, "area": area, "region": region}
    raise RuntimeError("no 3D viewport in this session")


def _world_bounding_box(object: Any) -> list[float] | None:
    """`[min_x, min_y, min_z, max_x, max_y, max_z]`, the shape of Maya's `exactWorldBoundingBox`."""
    corners = [object.matrix_world @ Vector(corner) for corner in object.bound_box]
    if not corners:
        return None
    return [min(corner[axis] for corner in corners) for axis in range(3)] + [
        max(corner[axis] for corner in corners) for axis in range(3)
    ]


def _first_vertex_world(object: Any) -> list[float] | None:
    mesh = getattr(object, "data", None)
    vertices = getattr(mesh, "vertices", None)
    if not vertices:
        return None
    return _vector(object.matrix_world @ vertices[0].co)


def capture_transform(object_name: str) -> dict[str, Any]:
    """Channels and pivot state, under the Maya capture's key names where they mean the same thing.

    Both stores are recorded, because which one carries the pivot is part of what the comparison has
    to see: `clarityTransform` is this fork's DAG channel block, `customPivot` the shim.
    """
    object = bpy.data.objects[object_name]
    pivot = object.custom_pivot
    clarity = object.clarity_transform
    rotate_pivot_world = None
    if pivot is not None and pivot.is_rotate_pivot_valid:
        rotate_pivot_world = _vector(object.matrix_world @ Vector(pivot.rotate_pivot))
    return {
        "translate": _vector(object.location),
        "rotate": [math.degrees(angle) for angle in object.rotation_euler],
        "scale": _vector(object.scale),
        "matrix": _matrix(object.matrix_local),
        "worldMatrix": _matrix(object.matrix_world),
        # The same pair of probes the Maya capture takes, and for the same reason: a bake moves the
        # origin on purpose and must not move the geometry, and the world matrix cannot tell those two
        # apart on its own.
        "worldBoundingBox": _world_bounding_box(object),
        "firstVertexWorld": _first_vertex_world(object),
        "rotatePivotWorld": rotate_pivot_world,
        "clarityTransform": None
        if clarity is None
        else {
            "translation": _vector(clarity.translation),
            "rotation": [math.degrees(angle) for angle in clarity.rotation],
            "rotateAxis": [math.degrees(angle) for angle in clarity.rotate_axis],
            "scale": _vector(clarity.scale),
            "shear": _vector(clarity.shear),
            "rotatePivot": _vector(clarity.rotate_pivot),
            "rotatePivotTranslate": _vector(clarity.rotate_pivot_translate),
            "scalePivot": _vector(clarity.scale_pivot),
            "scalePivotTranslate": _vector(clarity.scale_pivot_translate),
        },
        "customPivot": None
        if pivot is None
        else {
            "rotatePivot": _vector(pivot.rotate_pivot),
            "scalePivot": _vector(pivot.scale_pivot),
            "orientation": _vector(pivot.orientation),
        },
        "manipPivot": {
            # The three questions `manipPivot -q` answers, so the rows line up with Maya's.
            "positionValid": False
            if pivot is None
            else bool(pivot.is_rotate_pivot_valid or pivot.is_scale_pivot_valid),
            "orientationValid": False if pivot is None else bool(pivot.is_orientation_valid),
            "valid": False
            if pivot is None
            else bool(
                pivot.is_rotate_pivot_valid
                or pivot.is_scale_pivot_valid
                or pivot.is_orientation_valid
            ),
        },
    }


def capture_axis_orientation() -> dict[str, Any]:
    """What the active tool resolves to, and the slot value underneath it.

    `clarity_transform_orientation` is the resolved answer, `CUSTOM` included - the state Maya reads
    as `manipMoveContext -mode 6`. The slots are what `Custom` sits on top of and never overwrites.
    """
    window_manager = bpy.context.window_manager
    slots = bpy.context.scene.transform_orientation_slots
    return {
        "resolved": _safe(
            "clarity_transform_orientation",
            lambda: window_manager.clarity_transform_orientation,
        ),
        "activeTool": _safe("clarity_tool", lambda: window_manager.clarity_tool),
        "slots": {
            name: {"type": slots[index].type, "use": bool(slots[index].use)}
            for index, name in enumerate(("default", "move", "rotate", "scale"))
        },
        "editPivot": _safe(
            "pivot edit target",
            lambda: bool(bpy.context.window_manager.clarity_pivot_edit_active)
            if hasattr(bpy.context.window_manager, "clarity_pivot_edit_active")
            else None,
        ),
        "selection": [object.name for object in bpy.context.selected_objects],
    }


def _create_scene() -> str:
    """The Maya fixture's scene, with the same hard cases.

    A parent with non-uniform negative scale, a rotated and non-uniformly scaled subject, and a
    child, so a pivot rule that only holds for an axis-aligned object at the origin cannot pass here
    either.
    """
    # Emptied rather than reloaded: `read_factory_settings` replaces the whole file, and with it the
    # window and screen this capture is running inside, which leaves the context without so much as an
    # active object.
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()
    for object in list(bpy.data.objects):
        bpy.data.objects.remove(object)
    slots = bpy.context.scene.transform_orientation_slots
    for index in range(4):
        slots[index].type = "GLOBAL"
        if index > 0:
            slots[index].use = False
    # Clears `Custom` for the tool as well, so one scenario cannot start where the last one ended.
    bpy.ops.clarity.transform_orientation_set(tool="MOVE", orientation="WORLD")

    bpy.ops.mesh.primitive_cube_add(size=2.0)
    subject = bpy.context.active_object
    subject.name = "pivotSubject"

    bpy.ops.object.empty_add()
    parent = bpy.context.active_object
    parent.name = "pivotParent"
    parent.location = (7.0, -3.0, 5.0)
    parent.rotation_euler = Euler([math.radians(angle) for angle in (17.0, -31.0, 9.0)], "XYZ")
    parent.scale = (-2.0, 0.75, 1.5)

    bpy.ops.mesh.primitive_cube_add(size=0.5)
    child = bpy.context.active_object
    child.name = "pivotChild"

    subject.parent = parent
    child.parent = subject
    subject.location = (1.25, -2.5, 3.75)
    subject.rotation_euler = Euler([math.radians(angle) for angle in (20.0, -35.0, 70.0)], "XYZ")
    subject.scale = (2.0, -0.5, 1.25)
    child.location = (2.0, 1.0, -0.5)

    bpy.context.window_manager.clarity_interaction_enabled = True
    bpy.ops.object.select_all(action="DESELECT")
    subject.select_set(True)
    bpy.context.view_layer.objects.active = subject
    bpy.context.view_layer.update()
    return subject.name


def _redraw() -> None:
    """Force one real draw of the viewport.

    A scripted session never redraws on its own, and two things the capture is about only happen on a
    draw: the manipulator refresh, which is where the rule that a frame dies with its selection is
    reconciled, and the region's view data, which the snap query behind a pivot click reads. Without
    this the capture measured a session no user ever sees.
    """
    with bpy.context.temp_override(**_viewport_override()):
        bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=1)


def _capture_steps(steps: list[tuple[str, Callable[[str], None]]]) -> dict[str, Any]:
    subject = _create_scene()
    _redraw()
    captures = [
        {
            "action": "initial",
            "state": capture_transform(subject),
            "axisOrientation": capture_axis_orientation(),
        }
    ]
    for name, action in steps:
        error = _safe(name, lambda action=action: action(subject))
        _redraw()
        capture = {
            "action": name,
            "state": capture_transform(subject),
            "axisOrientation": capture_axis_orientation(),
        }
        if isinstance(error, dict) and "error" in error:
            capture["error"] = error["error"]
        captures.append(capture)
    return {"subject": subject, "captures": captures}


# ---------------------------------------------------------------------------------------------
# Steps, one per Maya step of the same name so the comparison can line them up by name alone.
# ---------------------------------------------------------------------------------------------


def _pick_orientation(orientation: str) -> Callable[[str], None]:
    def action(_subject: str) -> None:
        with bpy.context.temp_override(**_viewport_override()):
            bpy.ops.clarity.transform_orientation_set(tool="MOVE", orientation=orientation)

    return action


def _toggle_pivot_edit(_subject: str) -> None:
    with bpy.context.temp_override(**_viewport_override()):
        bpy.ops.clarity.pivot_edit_toggle()


def _aim_orientation(subject: str) -> None:
    """A frame on the pivot, written the way Maya's `manipPivot -ori` writes one.

    Storage only. It deliberately does not go through the click, so what this step proves is that the
    frame is *stored* and survives the steps after it. Selecting `Custom` for the tool is the click's
    job, and #_aim_orientation_click is the step that exercises it.
    """
    pivot = bpy.data.objects[subject].custom_pivot_ensure()
    quaternion = Euler([math.radians(angle) for angle in (23.0, -41.0, 12.0)], "XYZ").to_quaternion()
    pivot.orientation = (quaternion.w, quaternion.x, quaternion.y, quaternion.z)
    pivot.is_orientation_valid = True


def _aim_orientation_click(_subject: str) -> None:
    """The real gesture: the pivot click operator, on whatever is under the middle of the viewport.

    This is the path that authors the frame *and* selects `Custom` for the tool. It is kept here but not
    used by the scenarios below: a scripted session draws nothing, and the snap query behind the click
    answered `type=0` - nothing under the pointer - even with the view framed on the selection, so the
    step recorded a reset instead of a frame. The gesture belongs where real events are available:
    `tests/python/ui_simulate/test_clarity_pivot.py`, which is also where the rule that authoring
    selects `Custom` should be asserted, against `wm.clarity_transform_orientation`.
    """
    from bpy_extras.view3d_utils import location_3d_to_region_2d

    override = _viewport_override()
    region = override["region"]
    region_data = override["area"].spaces.active.region_3d
    with bpy.context.temp_override(**override):
        bpy.ops.view3d.view_selected()
    _redraw()
    target = bpy.data.objects[_subject].matrix_world.translation
    position = location_3d_to_region_2d(region, region_data, target)
    if position is None:
        raise RuntimeError("the subject does not project into the region")
    with bpy.context.temp_override(**override):
        bpy.ops.transform.clarity_pivot_click(
            mouse=(int(position.x), int(position.y)), shift=False, ctrl=True
        )


def _move_pivots(subject: str) -> None:
    """The pivot moved to a world point, the way `xform -pivots -preserve` does in the Maya capture."""
    object = bpy.data.objects[subject]
    pivot = object.custom_pivot_ensure()
    local = object.matrix_world.inverted() @ Vector((9.25, -4.5, 6.75))
    pivot.rotate_pivot = local
    pivot.scale_pivot = local
    pivot.is_rotate_pivot_valid = True
    pivot.is_scale_pivot_valid = True


def _rotate_object(subject: str) -> None:
    bpy.data.objects[subject].rotation_euler = Euler(
        [math.radians(angle) for angle in (40.0, 15.0, -25.0)], "XYZ"
    )
    bpy.context.view_layer.update()


def _apply_transform(subject: str) -> None:
    object = bpy.data.objects[subject]
    bpy.ops.object.select_all(action="DESELECT")
    object.select_set(True)
    bpy.context.view_layer.objects.active = object
    with bpy.context.temp_override(**_viewport_override()):
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)


def _clear_selection(_subject: str) -> None:
    bpy.ops.object.select_all(action="DESELECT")


def _select_subject(subject: str) -> None:
    object = bpy.data.objects[subject]
    object.select_set(True)
    bpy.context.view_layer.objects.active = object


def _reset_orientation(_subject: str) -> None:
    with bpy.context.temp_override(**_viewport_override()):
        bpy.ops.clarity.pivot_reset(action="ORIENTATION")


def _bake_orientation(_subject: str) -> None:
    """Bake Pivot / Orientation: the authored frame becomes the object's own basis.

    The step the Maya debug log made suspicious - there the world matrix moved under
    `preserveGeometryPosition`. Ours compensates the geometry by `inverse(world_after) * world_before`
    and restores the children, so the probes are what says whether that holds on a mirrored object.
    """
    with bpy.context.temp_override(**_viewport_override()):
        bpy.ops.clarity.pivot_bake(mode="ORIENTATION")


def _bake_position(_subject: str) -> None:
    with bpy.context.temp_override(**_viewport_override()):
        bpy.ops.clarity.pivot_bake(mode="POSITION")


SCENARIOS: dict[str, list[tuple[str, Callable[[str], None]]]] = {
    "axis_orientation_defaults": [
        ("select_object", _select_subject),
    ],
    "pivot_edit_selects_custom": [
        ("pick_world", _pick_orientation("WORLD")),
        ("enter_pivot_edit", _toggle_pivot_edit),
        ("aim_orientation", _aim_orientation_click),
        ("leave_pivot_edit", _toggle_pivot_edit),
        ("pick_object", _pick_orientation("OBJECT")),
    ],
    # The same sequence with the frame written straight to the property, so a failed click cannot hide
    # what the steps after it do to a frame that is definitely there.
    "pivot_frame_survives_mode_exit": [
        ("pick_world", _pick_orientation("WORLD")),
        ("enter_pivot_edit", _toggle_pivot_edit),
        ("aim_orientation", _aim_orientation),
        ("leave_pivot_edit", _toggle_pivot_edit),
        ("pick_object", _pick_orientation("OBJECT")),
    ],
    "pivot_frame_after_object_rotation": [
        ("enter_pivot_edit", _toggle_pivot_edit),
        ("aim_orientation", _aim_orientation_click),
        ("leave_pivot_edit", _toggle_pivot_edit),
        ("rotate_object", _rotate_object),
    ],
    "freeze_transformations": [
        ("move_pivots", _move_pivots),
        ("enter_pivot_edit", _toggle_pivot_edit),
        ("aim_orientation", _aim_orientation_click),
        ("leave_pivot_edit", _toggle_pivot_edit),
        ("freeze", _apply_transform),
    ],
    # Through the click, because the rule is keyed on the object the frame was authored *on*: a frame
    # written straight to the property has no author, and the rule deliberately leaves those alone -
    # that is what keeps a frame loaded from a file from being wiped by the first selection change.
    #
    # This scenario records the rule but cannot confirm it. Dropping the frame runs from the event
    # dispatcher and from the manipulator refresh, and an empty selection has neither in a scripted
    # session: no events arrive, and with nothing selected there is no manipulator to refresh. The
    # confirmation belongs to `tests/python/ui_simulate/test_clarity_pivot.py`, which has real events.
    "selection_drops_frame": [
        # The mode has to be on for the click: the operator asks for a pivot target first and cancels
        # without one, which is why this scenario opens the mode and closes it again.
        ("enter_pivot_edit", _toggle_pivot_edit),
        ("aim_orientation", _aim_orientation_click),
        ("leave_pivot_edit", _toggle_pivot_edit),
        ("clear_selection", _clear_selection),
        ("select_again", _select_subject),
    ],
    "bake_keeps_the_geometry": [
        ("move_pivots", _move_pivots),
        ("enter_pivot_edit", _toggle_pivot_edit),
        ("aim_orientation", _aim_orientation_click),
        ("leave_pivot_edit", _toggle_pivot_edit),
        ("bake_orientation", _bake_orientation),
        ("bake_position", _bake_position),
    ],
    "reset_orientation_drops_frame": [
        ("enter_pivot_edit", _toggle_pivot_edit),
        ("aim_orientation", _aim_orientation_click),
        ("leave_pivot_edit", _toggle_pivot_edit),
        ("reset_orientation", _reset_orientation),
    ],
}


def write(output: Path | str) -> None:
    result = {
        "schema": 1,
        "blenderVersion": bpy.app.version_string,
        "buildHash": bpy.app.build_hash.decode()
        if isinstance(bpy.app.build_hash, bytes)
        else str(bpy.app.build_hash),
        "units": {"linear": "meter", "angularChannels": "degree"},
        "interactionScenarios": {
            name: _capture_steps(steps) for name, steps in SCENARIOS.items()
        },
    }
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print("wrote", output)


def _run(output: Path, quit_when_done: bool) -> None:
    """Capture once, and leave a log next to the fixture whatever happens.

    A `--python` script runs while Blender is still starting, and anything it prints can be lost with
    the console it printed to. The log is written from here, so a failed run says why in a file the
    caller already knows the path of.
    """
    log = output.with_suffix(".log")
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        # A timer callback has no screen context of its own - not even `active_object` - so the whole
        # capture runs inside the viewport it needs anyway.
        with bpy.context.temp_override(**_viewport_override()):
            write(output)
        log.write_text("ok", encoding="utf-8")
    except Exception:  # noqa: BLE001 - the traceback is the report.
        import traceback

        log.write_text(traceback.format_exc(), encoding="utf-8")
    if quit_when_done:
        bpy.ops.wm.quit_blender()


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--quit", action="store_true", help="Close Blender when the capture is done")
    args = parser.parse_args(argv)

    # Through a timer, not straight away: the operators poll for a viewport, and at import time the
    # window this session will use is not finished yet.
    def deferred() -> None:
        _run(args.output, args.quit)
        return None

    bpy.app.timers.register(deferred, first_interval=0.5)


if __name__ == "__main__":
    main(sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else [])
