"""Capture Maya 2025 custom-pivot behavior as deterministic JSON fixtures.

Run with Maya's Python:

  mayapy capture_reference_pivot.py --output fixtures/maya_2025_pivot_reference.json

The script intentionally records transform channels and manipPivot state after every
operation. It does not reduce the result to matrices, because different Maya channel
states can produce the same matrix and behave differently on the next edit.

The interaction scenarios - the ones that enter custom pivot editing mode or ask a tool
context which axis orientation it is set to - need a running Maya, because a standalone
session has no tool contexts. Under `mayapy` they are recorded as `{"error": ...}` instead
of being silently skipped, and the same file can be run from Maya's Script Editor to fill
them in:

  import sys; sys.path.append(r"<this directory>")
  import capture_reference_pivot as capture
  capture.write(r"<this directory>/fixtures/maya_2025_pivot_interaction.json")
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Callable

from reference_backend import cmds, mel, standalone  # noqa: E402


def _json_value(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    return value


def capture_transform(node: str) -> dict[str, Any]:
    return {
        "translate": _json_value(cmds.getAttr(node + ".translate")[0]),
        "rotate": _json_value(cmds.getAttr(node + ".rotate")[0]),
        "rotateOrder": cmds.getAttr(node + ".rotateOrder"),
        "rotateAxis": _json_value(cmds.getAttr(node + ".rotateAxis")[0]),
        "scale": _json_value(cmds.getAttr(node + ".scale")[0]),
        "shear": _json_value(cmds.getAttr(node + ".shear")[0]),
        "rotatePivot": _json_value(cmds.getAttr(node + ".rotatePivot")[0]),
        "rotatePivotTranslate": _json_value(
            cmds.getAttr(node + ".rotatePivotTranslate")[0]
        ),
        "scalePivot": _json_value(cmds.getAttr(node + ".scalePivot")[0]),
        "scalePivotTranslate": _json_value(
            cmds.getAttr(node + ".scalePivotTranslate")[0]
        ),
        "rotatePivotWorld": _json_value(
            cmds.xform(node, query=True, worldSpace=True, rotatePivot=True)
        ),
        "scalePivotWorld": _json_value(
            cmds.xform(node, query=True, worldSpace=True, scalePivot=True)
        ),
        "offsetParentMatrix": _json_value(
            cmds.getAttr(node + ".offsetParentMatrix")
        ),
        "matrix": _json_value(
            cmds.xform(node, query=True, matrix=True, objectSpace=True)
        ),
        "worldMatrix": _json_value(cmds.getAttr(node + ".worldMatrix[0]")),
        # Where the geometry is, not where the object claims to be. A bake is allowed to move the
        # origin - that is what it does - but not the vertices, and the world matrix alone cannot tell
        # those apart: `preserveGeometryPosition` keeps the shape still by moving it in object space,
        # so the matrix changes while nothing visibly does.
        "worldBoundingBox": _json_value(
            cmds.exactWorldBoundingBox(node, ignoreInvisible=False)
        ),
        "firstVertexWorld": _json_value(
            cmds.xform(node + ".vtx[0]", query=True, worldSpace=True, translation=True)
        ),
        "manipPivot": {
            "valid": cmds.manipPivot(query=True, valid=True),
            "positionValid": cmds.manipPivot(query=True, posValid=True),
            "orientationValid": cmds.manipPivot(query=True, oriValid=True),
            "position": _json_value(cmds.manipPivot(query=True, position=True)),
            "orientation": _json_value(
                cmds.manipPivot(query=True, orientation=True)
            ),
            "pinned": cmds.manipPivot(query=True, pinPivot=True),
            "snapPosition": cmds.manipPivot(query=True, snapPos=True),
            "snapOrientation": cmds.manipPivot(query=True, snapOri=True),
            "resetMode": cmds.manipPivot(query=True, resetMode=True),
            "bakeOrientationAutomatically": cmds.manipPivot(
                query=True, bakeOri=True
            ),
        },
    }


def _create_scene() -> tuple[str, str, str]:
    cmds.file(new=True, force=True)
    cmds.manipPivot(
        reset=True,
        pinPivot=False,
        snapPos=True,
        snapOri=True,
        bakeOri=False,
        resetMode=0,
    )
    # The axis orientation of a tool is session state, not scene state: `file -new` does not touch it,
    # so a scenario that ends in `Custom` hands `Custom` to the next one and every early step reads a
    # value the scenario never set. Put back to World - the Move Tool's own default - so each scenario
    # starts where the one before it did. The tool is activated first because a context that has never
    # been used cannot be edited, and answers a leftover value when queried.
    _safe("setToolTo Move", lambda: cmds.setToolTo("Move"))
    for key in ("move", "rotate", "scale"):
        _safe(
            "reset " + key + " mode",
            lambda key=key: _set_axis_orientation(key, 2 if key == "move" else 0),
        )

    parent = cmds.createNode("transform", name="pivotParent")
    node, _subject_history = cmds.polyCube(
        name="pivotSubject", width=2.0, height=4.0, depth=6.0
    )
    child, _child_shape = cmds.polyCube(
        name="pivotChild", width=0.5, height=0.75, depth=1.0
    )
    cmds.parent(node, parent)
    cmds.parent(child, node)
    shape = cmds.listRelatives(node, shapes=True, fullPath=True)[0]

    cmds.setAttr(parent + ".translate", 7.0, -3.0, 5.0, type="double3")
    cmds.setAttr(parent + ".rotate", 17.0, -31.0, 9.0, type="double3")
    cmds.setAttr(parent + ".scale", -2.0, 0.75, 1.5, type="double3")

    cmds.setAttr(node + ".translate", 1.25, -2.5, 3.75, type="double3")
    cmds.setAttr(node + ".rotate", 20.0, -35.0, 70.0, type="double3")
    cmds.setAttr(node + ".rotateOrder", 4)
    cmds.setAttr(node + ".rotateAxis", 11.0, -7.0, 5.0, type="double3")
    cmds.setAttr(node + ".scale", 2.0, -0.5, 1.25, type="double3")
    cmds.setAttr(node + ".shear", 0.2, -0.3, 0.4, type="double3")
    cmds.setAttr(
        node + ".offsetParentMatrix",
        1.0,
        0.15,
        0.0,
        0.0,
        0.0,
        1.0,
        -0.25,
        0.0,
        0.1,
        0.0,
        1.0,
        0.0,
        2.0,
        -1.0,
        0.5,
        1.0,
        type="matrix",
    )
    cmds.setAttr(child + ".translate", 2.0, 1.0, -0.5, type="double3")
    cmds.select(node, replace=True)
    return node, shape, child


def _capture_sequence(
    name: str,
    action: Callable[[str, str, str], None],
) -> dict[str, Any]:
    node, shape, child = _create_scene()
    captures = [{"action": "initial", "state": capture_transform(node)}]
    action(node, shape, child)
    captures.append({"action": name, "state": capture_transform(node)})
    captures[-1]["childWorldMatrix"] = _json_value(
        cmds.getAttr(child + ".worldMatrix[0]")
    )
    return {"subject": node, "captures": captures}


def _safe(description: str, function: Callable[[], Any]) -> Any:
    """Value of  function, or the error it raised.

    An interaction step that a standalone session cannot perform must not cost the rest of the
    capture: what is missing is then visible in the fixture instead of absent from it.
    """
    try:
        return function()
    except Exception as error:  # noqa: BLE001 - the message is the result here.
        return {"error": "{}: {}".format(description, error)}


_CONTEXT_CANDIDATES = {
    "move": ("Move", "moveSuperContext", "$gMove"),
    "rotate": ("Rotate", "RotateSuperContext", "$gRotate"),
    "scale": ("Scale", "scaleSuperContext", "$gScale"),
}


def _context_names(key: str) -> list[str]:
    """Every name this session might have the tool's context under, most likely first.

    `$gMove` and its neighbours name the context Maya *would* create, and a session that has not
    used the tool yet does not have it: the first capture read `moveSuperContext` and Maya answered
    "Object not found", while `currentCtx()` reported the context as plain `Move`. So the names are
    tried in turn, the current context included, and the one that answers is recorded with the value.
    """
    names: list[str] = []
    for candidate in _CONTEXT_CANDIDATES[key]:
        if candidate.startswith("$"):
            value = _safe(
                "global " + candidate, lambda name=candidate: mel.eval("$tmp = " + name)
            )
            if isinstance(value, str) and value:
                names.append(value)
            continue
        names.append(candidate)
    current = _safe("currentCtx", lambda: cmds.currentCtx())
    if isinstance(current, str) and current and current not in names:
        names.append(current)
    return names


def _tool_contexts() -> dict[str, list[str]]:
    return {key: _context_names(key) for key in _CONTEXT_CANDIDATES}


def _context_mode(key: str, query: Callable[[str], Any]) -> dict[str, Any]:
    """`-mode` of the tool's context: 2 is World, 0 Object, 6 Custom, per the Move Tool page."""
    attempts: dict[str, Any] = {}
    for name in _context_names(key):
        exists = _safe("contextInfo " + name, lambda value=name: cmds.contextInfo(value, exists=True))
        if exists is not True:
            attempts[name] = "does not exist"
            continue
        value = _safe("mode of " + name, lambda used=name: query(used))
        if not isinstance(value, dict):
            return {"context": name, "mode": value, "attempts": attempts}
        attempts[name] = value["error"]
    return {"attempts": attempts}


def capture_axis_orientation() -> dict[str, Any]:
    """Which coordinate system each transform tool is set to.

    Two readings of the same state, because they are the two the documentation names:
    `manipPivot -moveToolOri/-rotateToolOri/-scaleToolOri`, and the `-mode` of each tool context,
    whose enumeration the Move Tool page spells out (2 is World, 0 Object, 6 Custom).
    """
    return {
        "manipPivot": {
            "moveToolOri": _safe(
                "moveToolOri", lambda: cmds.manipPivot(query=True, moveToolOri=True)
            ),
            "rotateToolOri": _safe(
                "rotateToolOri", lambda: cmds.manipPivot(query=True, rotateToolOri=True)
            ),
            "scaleToolOri": _safe(
                "scaleToolOri", lambda: cmds.manipPivot(query=True, scaleToolOri=True)
            ),
        },
        "contextMode": {
            "move": _context_mode(
                "move", lambda name: cmds.manipMoveContext(name, query=True, mode=True)
            ),
            "rotate": _context_mode(
                "rotate", lambda name: cmds.manipRotateContext(name, query=True, mode=True)
            ),
            "scale": _context_mode(
                "scale", lambda name: cmds.manipScaleContext(name, query=True, mode=True)
            ),
        },
        "contextNames": _tool_contexts(),
        "currentContext": _safe("currentCtx", lambda: cmds.currentCtx()),
        "selection": _safe("selection", lambda: cmds.ls(selection=True) or []),
    }


def _pivot_edit_mode_toggle() -> Any:
    """The command `D` is bound to: it enters custom pivot editing mode and leaves it again."""
    return _safe("ctxEditMode", lambda: mel.eval("ctxEditMode"))


def _capture_steps(
    steps: list[tuple[str, Callable[[str, str, str], None]]],
) -> dict[str, Any]:
    """One scene, a capture after every step.

    The channel scenarios below answer "what did this operation leave behind"; these answer "and
    what did the step after it do to that", which is the question every Edit Pivot rule is about.
    """
    node, shape, child = _create_scene()
    captures = [
        {
            "action": "initial",
            "state": capture_transform(node),
            "axisOrientation": capture_axis_orientation(),
        }
    ]
    for name, action in steps:
        _safe(name, lambda action=action: action(node, shape, child))
        captures.append(
            {
                "action": name,
                "state": capture_transform(node),
                "axisOrientation": capture_axis_orientation(),
            }
        )
    return {"subject": node, "captures": captures}


def _set_custom_pivot(node: str, _shape: str, _child: str) -> None:
    cmds.manipPivot(
        position=(9.25, -4.5, 6.75),
        orientation=(math.radians(23.0), math.radians(-41.0), math.radians(12.0)),
    )


def _move_object_pivots(node: str, _shape: str, _child: str) -> None:
    cmds.xform(node, worldSpace=True, pivots=(9.25, -4.5, 6.75), preserve=True)


def _set_independent_flags(node: str, _shape: str, _child: str) -> None:
    cmds.manipPivot(position=(9.25, -4.5, 6.75), pinPivot=True)
    cmds.manipPivot(snapPos=False, snapOri=True, bakeOri=True, resetMode=1)


def _reset_position(mode: int) -> Callable[[str, str, str], None]:
    def action(node: str, _shape: str, _child: str) -> None:
        cmds.xform(node, worldSpace=True, pivots=(9.25, -4.5, 6.75))
        cmds.manipPivot(position=(9.25, -4.5, 6.75), resetMode=mode)
        mel.eval("manipPivotReset true false")

    return action


def _reset_orientation(node: str, _shape: str, _child: str) -> None:
    cmds.manipPivot(
        orientation=(
            math.radians(23.0),
            math.radians(-41.0),
            math.radians(12.0),
        )
    )
    mel.eval("manipPivotReset false true")


def _reset_both(node: str, _shape: str, _child: str) -> None:
    cmds.xform(node, worldSpace=True, pivots=(9.25, -4.5, 6.75))
    cmds.manipPivot(
        position=(9.25, -4.5, 6.75),
        orientation=(math.radians(23.0), math.radians(-41.0), math.radians(12.0)),
        resetMode=0,
    )
    mel.eval("manipPivotReset true true")


def _bake_position(node: str, _shape: str, _child: str) -> None:
    cmds.xform(node, worldSpace=True, pivots=(9.25, -4.5, 6.75))
    _bake_position_impl(node)


def _bake_position_impl(node: str) -> None:
    # Exact command sequence from Maya 2025's bakeCustomToolPivot.mel. Calling the
    # wrapper itself requires initialized viewport tool contexts, which mayapy does
    # not create in standalone mode.
    old_pivot = cmds.xform(
        node, query=True, parentSpace=True, scalePivot=True
    )
    cmds.xform(node, zeroTransformPivots=True)
    new_translation = cmds.getAttr(node + ".translate")[0]
    delta = tuple(old_pivot[axis] - new_translation[axis] for axis in range(3))
    cmds.move(
        *delta,
        node,
        relative=True,
        localSpace=True,
        preserveChildPosition=True,
        preserveGeometryPosition=True,
    )


def _bake_orientation_impl(node: str) -> None:
    # Exact transform command used by bakeCustomToolPivot.mel after reading the
    # active tool's custom orientation.
    cmds.rotate(
        23.0,
        -41.0,
        12.0,
        node,
        absolute=True,
        preserveChildPosition=True,
        preserveGeometryPosition=True,
        worldSpace=True,
        forceOrderXYZ=True,
    )


def _bake_orientation(node: str, _shape: str, _child: str) -> None:
    _bake_orientation_impl(node)


def _bake_both(node: str, _shape: str, _child: str) -> None:
    cmds.xform(node, worldSpace=True, pivots=(9.25, -4.5, 6.75))
    _bake_orientation_impl(node)
    _bake_position_impl(node)


def _component_selection(node: str, shape: str, _child: str) -> None:
    cmds.select(shape + ".vtx[0:2]", replace=True)
    cmds.setToolTo("Move")


def _tool_switch(node: str, _shape: str, _child: str) -> None:
    cmds.manipPivot(
        position=(9.25, -4.5, 6.75),
        orientation=(math.radians(23.0), math.radians(-41.0), math.radians(12.0)),
        pinPivot=True,
    )
    cmds.setToolTo("Move")
    cmds.setToolTo("Rotate")
    cmds.setToolTo("Scale")


def _object_switch(node: str, _shape: str, child: str) -> None:
    cmds.manipPivot(
        position=(9.25, -4.5, 6.75),
        orientation=(math.radians(23.0), math.radians(-41.0), math.radians(12.0)),
        pinPivot=True,
    )
    cmds.select(child, replace=True)
    cmds.select(node, replace=True)


# -----------------------------------------------------------------------------------------------
# Interaction scenarios: what pivot editing does to the tool's coordinate system, and what a
# selection change does to the frame. These are the rules the fork's manipulator argues about, and
# they need a running Maya - a standalone session has no tool contexts to answer for.
# -----------------------------------------------------------------------------------------------


def _use_move_tool(_node: str, _shape: str, _child: str) -> None:
    cmds.setToolTo("Move")


_CONTEXT_SETTERS = {
    "move": lambda name, mode: cmds.manipMoveContext(name, edit=True, mode=mode),
    "rotate": lambda name, mode: cmds.manipRotateContext(name, edit=True, mode=mode),
    "scale": lambda name, mode: cmds.manipScaleContext(name, edit=True, mode=mode),
}


def _set_axis_orientation(key: str, mode: int) -> None:
    """`-mode` on whichever name this session has the tool's context under."""
    for name in _context_names(key):
        if cmds.contextInfo(name, exists=True):
            _CONTEXT_SETTERS[key](name, mode)
            return
    raise RuntimeError("no {} context to set mode {} on".format(key, mode))


def _set_move_axis_orientation(mode: int) -> None:
    _set_axis_orientation("move", mode)


def _pick_world_axis_orientation(_node: str, _shape: str, _child: str) -> None:
    """World, the Move Tool's documented default, picked explicitly so the step after is readable."""
    _set_move_axis_orientation(2)


def _pick_object_axis_orientation(_node: str, _shape: str, _child: str) -> None:
    _set_move_axis_orientation(0)


def _enter_pivot_edit_mode(_node: str, _shape: str, _child: str) -> None:
    _pivot_edit_mode_toggle()


def _leave_pivot_edit_mode(_node: str, _shape: str, _child: str) -> None:
    _pivot_edit_mode_toggle()


def _aim_pivot_orientation(_node: str, _shape: str, _child: str) -> None:
    """What a click on a component leaves behind: an orientation on the manip pivot."""
    cmds.manipPivot(
        orientation=(math.radians(23.0), math.radians(-41.0), math.radians(12.0))
    )


def _select_faces(*indices: int) -> Callable[[str, str, str], None]:
    def action(_node: str, shape: str, _child: str) -> None:
        cmds.select([shape + ".f[{}]".format(index) for index in indices], replace=True)

    return action


def _clear_selection(_node: str, _shape: str, _child: str) -> None:
    cmds.select(clear=True)


def _rotate_object(_node: str, _shape: str, _child: str) -> None:
    cmds.setAttr(_node + ".rotate", 40.0, 15.0, -25.0, type="double3")


def _freeze_transformations(node: str, _shape: str, _child: str) -> None:
    """Modify > Freeze Transformations, the operation `Apply object transform` is compared with."""
    cmds.makeIdentity(node, apply=True, translate=True, rotate=True, scale=True, normal=0)


def _reset_orientation_command(_node: str, _shape: str, _child: str) -> None:
    """`manipPivotReset false true`, the orientation-only reset the Tool Settings button runs."""
    mel.eval("manipPivotReset false true")


def write(output: Path | str) -> None:
    """Record every scenario into  output. The entry point a running Maya calls."""
    main(["--output", str(output)])


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    scenarios = {
        "custom_position_orientation": _set_custom_pivot,
        "object_pivot_move": _move_object_pivots,
        "independent_flags": _set_independent_flags,
        "reset_position_center": _reset_position(0),
        "reset_position_zero": _reset_position(1),
        "reset_orientation": _reset_orientation,
        "reset_both": _reset_both,
        "bake_position": _bake_position,
        "bake_orientation": _bake_orientation,
        "bake_both": _bake_both,
        "component_selection": _component_selection,
        "tool_switch": _tool_switch,
        "object_switch_pinned": _object_switch,
    }
    # Ordered, because each step is only readable against the one before it.
    interaction_scenarios = {
        "axis_orientation_defaults": [
            ("select_object", lambda node, shape, child: cmds.select(node, replace=True)),
            ("use_move_tool", _use_move_tool),
        ],
        "pivot_edit_selects_custom": [
            ("use_move_tool", _use_move_tool),
            ("pick_world", _pick_world_axis_orientation),
            ("enter_pivot_edit", _enter_pivot_edit_mode),
            ("aim_orientation", _aim_pivot_orientation),
            ("leave_pivot_edit", _leave_pivot_edit_mode),
            ("pick_object", _pick_object_axis_orientation),
        ],
        "pivot_edit_component_frame": [
            ("use_move_tool", _use_move_tool),
            ("pick_world", _pick_world_axis_orientation),
            ("select_face", _select_faces(0)),
            ("enter_pivot_edit", _enter_pivot_edit_mode),
            ("aim_orientation", _aim_pivot_orientation),
            ("leave_pivot_edit", _leave_pivot_edit_mode),
            ("select_other_face", _select_faces(3)),
            ("clear_selection", _clear_selection),
        ],
        "pivot_frame_after_object_rotation": [
            ("use_move_tool", _use_move_tool),
            ("aim_orientation", _aim_pivot_orientation),
            ("rotate_object", _rotate_object),
        ],
        "freeze_transformations": [
            ("move_pivots", _move_object_pivots),
            ("aim_orientation", _aim_pivot_orientation),
            ("freeze", _freeze_transformations),
        ],
        # The two the fork records as well, so the scenario sets line up and the comparison has no
        # one-sided rows left to report.
        "selection_drops_frame": [
            ("use_move_tool", _use_move_tool),
            ("aim_orientation", _aim_pivot_orientation),
            ("clear_selection", _clear_selection),
            ("select_again", lambda node, _shape, _child: cmds.select(node, replace=True)),
        ],
        # The counterpart of the fork's `bake_keeps_the_geometry`: a bake is allowed to move the origin
        # and not a vertex, and the probes in `capture_transform` are what tells those apart.
        "bake_keeps_the_geometry": [
            ("move_pivots", _move_object_pivots),
            ("enter_pivot_edit", _enter_pivot_edit_mode),
            ("aim_orientation", _aim_pivot_orientation),
            ("leave_pivot_edit", _leave_pivot_edit_mode),
            ("bake_orientation", _bake_orientation),
            ("bake_position", _bake_position),
        ],
        "reset_orientation_drops_frame": [
            ("use_move_tool", _use_move_tool),
            ("aim_orientation", _aim_pivot_orientation),
            ("reset_orientation", _reset_orientation_command),
        ],
    }
    result = {
        "schema": 1,
        "mayaVersion": cmds.about(version=True),
        "apiVersion": cmds.about(apiVersion=True),
        "units": {"linear": "centimeter", "angularChannels": "degree"},
        "scenarios": {
            name: _capture_sequence(name, action)
            for name, action in scenarios.items()
        },
        "interactionScenarios": {
            name: _capture_steps(steps) for name, steps in interaction_scenarios.items()
        },
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    try:
        main()
    finally:
        # None inside a running Maya: that session is not ours to end.
        if standalone is not None:
            standalone.uninitialize()
