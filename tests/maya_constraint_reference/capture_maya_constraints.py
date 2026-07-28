"""Capture Maya 2025 point-constraint channel behavior as deterministic JSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import maya.standalone

maya.standalone.initialize(name="python")

import maya.cmds as cmds  # noqa: E402


def _json_value(value: Any) -> Any:
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    return value


def _transform(node: str) -> dict[str, Any]:
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
        "offsetParentMatrix": _json_value(
            cmds.getAttr(node + ".offsetParentMatrix")
        ),
        "matrix": _json_value(
            cmds.xform(node, query=True, objectSpace=True, matrix=True)
        ),
        "worldMatrix": _json_value(cmds.getAttr(node + ".worldMatrix[0]")),
        "parentMatrix": _json_value(cmds.getAttr(node + ".parentMatrix[0]")),
    }


def _create_scene() -> tuple[str, str, str]:
    cmds.file(new=True, force=True)
    parent = cmds.createNode("transform", name="constrainedParent")
    constrained = cmds.createNode("transform", name="constrained")
    target_a = cmds.createNode("transform", name="targetA")
    target_b = cmds.createNode("transform", name="targetB")
    cmds.parent(constrained, parent)

    cmds.setAttr(parent + ".translate", 4.0, -2.0, 7.0, type="double3")
    cmds.setAttr(parent + ".rotate", 17.0, -21.0, 8.0, type="double3")
    cmds.setAttr(parent + ".scale", -1.5, 0.75, 2.0, type="double3")

    cmds.setAttr(constrained + ".translate", 1.0, 2.0, 3.0, type="double3")
    cmds.setAttr(constrained + ".rotate", 13.0, -9.0, 22.0, type="double3")
    cmds.setAttr(constrained + ".rotatePivot", 0.5, -0.25, 1.0, type="double3")
    cmds.setAttr(constrained + ".rotateAxis", 5.0, 7.0, -3.0, type="double3")
    cmds.setAttr(
        constrained + ".offsetParentMatrix",
        1.0,
        0.15,
        0.0,
        0.0,
        0.0,
        1.0,
        -0.2,
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

    cmds.setAttr(target_a + ".translate", 9.0, -4.0, 6.0, type="double3")
    cmds.setAttr(target_a + ".rotatePivot", 1.0, 0.5, -0.25, type="double3")
    cmds.setAttr(target_b + ".translate", -3.0, 8.0, 2.0, type="double3")
    cmds.setAttr(target_b + ".rotatePivot", -0.5, 1.25, 0.75, type="double3")
    return constrained, target_a, target_b


def _constraint_state(node: str) -> dict[str, Any]:
    targets = cmds.pointConstraint(node, query=True, targetList=True) or []
    aliases = cmds.pointConstraint(node, query=True, weightAliasList=True) or []
    return {
        "name": node,
        "targets": targets,
        "weightAliases": aliases,
        "weights": [cmds.getAttr(node + "." + alias) for alias in aliases],
        "offset": _json_value(cmds.getAttr(node + ".offset")[0]),
        "constraintTranslate": _json_value(
            cmds.getAttr(node + ".constraintTranslate")[0]
        ),
    }


def _capture(name: str, maintain_offset: bool, skip: tuple[str, ...], weights):
    constrained, target_a, target_b = _create_scene()
    initial = _transform(constrained)
    targets = [target_a] if len(weights) == 1 else [target_a, target_b]
    kwargs = {"maintainOffset": maintain_offset}
    if skip:
        kwargs["skip"] = skip
    constraint = cmds.pointConstraint(*targets, constrained, **kwargs)[0]
    aliases = cmds.pointConstraint(
        constraint, query=True, weightAliasList=True
    )
    for alias, weight in zip(aliases, weights):
        cmds.setAttr(constraint + "." + alias, weight)
    return {
        "name": name,
        "initialAuthoredChannels": initial,
        "evaluated": _transform(constrained),
        "constraint": _constraint_state(constraint),
        "targets": {
            target_a: _transform(target_a),
            target_b: _transform(target_b),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    scenarios = {
        "one_target": _capture("one_target", False, (), (1.0,)),
        "two_targets_equal": _capture(
            "two_targets_equal", False, (), (1.0, 1.0)
        ),
        "two_targets_weighted": _capture(
            "two_targets_weighted", False, (), (0.5, 1.0)
        ),
        "maintain_offset": _capture(
            "maintain_offset", True, (), (1.0,)
        ),
        "skip_y": _capture("skip_y", False, ("y",), (1.0,)),
    }
    result = {
        "schema": 1,
        "mayaVersion": cmds.about(version=True),
        "apiVersion": cmds.about(apiVersion=True),
        "constraintType": "pointConstraint",
        "scenarios": scenarios,
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
        maya.standalone.uninitialize()
