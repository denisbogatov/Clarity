"""Capture Maya 2025 custom-pivot behavior as deterministic JSON fixtures.

Run with Maya's Python:

  mayapy capture_reference_pivot.py --output fixtures/maya_2025_pivot_reference.json

The script intentionally records transform channels and manipPivot state after every
operation. It does not reduce the result to matrices, because different Maya channel
states can produce the same matrix and behave differently on the next edit.
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

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
    result = {
        "schema": 1,
        "mayaVersion": cmds.about(version=True),
        "apiVersion": cmds.about(apiVersion=True),
        "units": {"linear": "centimeter", "angularChannels": "degree"},
        "scenarios": {
            name: _capture_sequence(name, action)
            for name, action in scenarios.items()
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
        standalone.uninitialize()
