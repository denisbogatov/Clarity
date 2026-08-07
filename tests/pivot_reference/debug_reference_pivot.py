# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Verbose Maya trace of Edit Pivot: one snapshot per micro-step, plus what each step changed.

`capture_reference_pivot.py` records the rules the fork is compared against; this one is for reading.
It walks a long sequence in small steps, snapshots everything after each, and writes the *difference*
from the previous step next to it, so the answer to "what did this action actually touch" is in the
file rather than in a diff done by hand across 200 KB of JSON.

Run it from Maya's Script Editor - the tool contexts and `ctxEditMode` need a running session:

  import sys; sys.path.append(r"S:\\Clarity\\blender\\tests\\pivot_reference")
  import debug_reference_pivot as debug
  debug.run(r"S:\\Clarity\\blender\\tests\\pivot_reference\\fixtures\\maya_2025_pivot_debug")

It writes `<path>.json` (everything) and `<path>.log` (readable, diffs only). Under `mayapy` it still
runs, and every step that needs a context is recorded as an error instead of being skipped - the same
honesty rule the other captures follow.

The scene is the fixture's: a parent with non-uniform negative scale, a rotated and sheared subject
and a child, because a pivot rule that only holds for an axis-aligned object at the origin is not a
rule.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import capture_reference_pivot as reference
from reference_backend import cmds, mel


def _safe(description: str, function: Callable[[], Any]) -> Any:
    return reference._safe(description, function)


def _tool_state() -> dict[str, Any]:
    """Everything about the manipulator that a command can answer, for all three tools at once."""
    modes = {
        "move": reference._context_mode(
            "move", lambda name: cmds.manipMoveContext(name, query=True, mode=True)
        ),
        "rotate": reference._context_mode(
            "rotate", lambda name: cmds.manipRotateContext(name, query=True, mode=True)
        ),
        "scale": reference._context_mode(
            "scale", lambda name: cmds.manipScaleContext(name, query=True, mode=True)
        ),
    }
    pivot_flags = {
        name: _safe(name, lambda flag=name: cmds.manipPivot(query=True, **{flag: True}))
        for name in (
            "valid",
            "posValid",
            "oriValid",
            "position",
            "orientation",
            "pinPivot",
            "snapPos",
            "snapOri",
            "resetMode",
            "bakeOri",
            "moveToolOri",
            "rotateToolOri",
            "scaleToolOri",
        )
    }
    return {
        "contextMode": modes,
        "manipPivot": pivot_flags,
        "currentContext": _safe("currentCtx", lambda: cmds.currentCtx()),
        "selectMode": {
            "object": _safe("selectMode object", lambda: cmds.selectMode(query=True, object=True)),
            "component": _safe(
                "selectMode component", lambda: cmds.selectMode(query=True, component=True)
            ),
        },
        "selectType": {
            name: _safe(
                "selectType " + name,
                lambda flag=name: cmds.selectType(query=True, **{flag: True}),
            )
            for name in ("vertex", "edge", "facet")
        },
        "selection": _safe("selection", lambda: cmds.ls(selection=True) or []),
    }


def _snapshot(node: str) -> dict[str, Any]:
    return {"transform": reference.capture_transform(node), "tool": _tool_state()}


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    """A snapshot as `path -> value` pairs, so two of them can be compared key by key."""
    flat: dict[str, Any] = {}
    if isinstance(value, dict):
        for key, item in value.items():
            flat.update(_flatten(item, "{}.{}".format(prefix, key) if prefix else str(key)))
    elif isinstance(value, list):
        if value and all(isinstance(item, (int, float)) for item in value):
            flat[prefix] = [round(float(item), 5) for item in value]
        else:
            for index, item in enumerate(value):
                flat.update(_flatten(item, "{}[{}]".format(prefix, index)))
    elif isinstance(value, float):
        flat[prefix] = round(value, 5)
    else:
        flat[prefix] = value
    return flat


def _difference(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """What the step changed: only the keys whose value is not the same afterwards."""
    first = _flatten(before)
    second = _flatten(after)
    changes: dict[str, Any] = {}
    for key in sorted(set(first) | set(second)):
        old = first.get(key, "(absent)")
        new = second.get(key, "(absent)")
        if old != new:
            changes[key] = {"from": old, "to": new}
    return changes


# ---------------------------------------------------------------------------------------------
# The sequence. Small steps on purpose: every line is one thing whose effect is worth seeing.
# ---------------------------------------------------------------------------------------------


def _component_select(kind: str, *indices: int) -> Callable[[str, str, str], None]:
    def action(_node: str, shape: str, _child: str) -> None:
        cmds.select(["{}.{}[{}]".format(shape, kind, index) for index in indices], replace=True)

    return action


def _steps() -> list[tuple[str, Callable[[str, str, str], None]]]:
    aim = reference._aim_pivot_orientation
    return [
        ("select_object", lambda node, _shape, _child: cmds.select(node, replace=True)),
        ("tool_move", lambda *_: cmds.setToolTo("Move")),
        ("tool_rotate", lambda *_: cmds.setToolTo("Rotate")),
        ("tool_scale", lambda *_: cmds.setToolTo("Scale")),
        ("tool_move_again", lambda *_: cmds.setToolTo("Move")),
        ("pick_world", reference._pick_world_axis_orientation),
        ("pick_object", reference._pick_object_axis_orientation),
        ("pick_world_again", reference._pick_world_axis_orientation),
        ("enter_pivot_edit", reference._enter_pivot_edit_mode),
        ("aim_orientation", aim),
        ("move_pivots", reference._move_object_pivots),
        ("pin_on", lambda *_: cmds.manipPivot(pinPivot=True)),
        ("select_vertices", _component_select("vtx", 0, 1)),
        ("select_edge", _component_select("e", 3)),
        ("select_face", _component_select("f", 2)),
        ("pin_off", lambda *_: cmds.manipPivot(pinPivot=False)),
        ("select_other_face", _component_select("f", 4)),
        ("back_to_object", lambda node, _shape, _child: cmds.select(node, replace=True)),
        ("aim_orientation_again", aim),
        ("leave_pivot_edit", reference._leave_pivot_edit_mode),
        ("reset_orientation", reference._reset_orientation_command),
        ("aim_orientation_third", aim),
        ("reset_mode_zero", lambda *_: cmds.manipPivot(resetMode=1)),
        ("reset_position", lambda *_: mel.eval("manipPivotReset true false")),
        ("move_pivots_again", reference._move_object_pivots),
        ("bake_orientation", reference._bake_orientation),
        ("bake_position", reference._bake_position),
        ("rotate_object", reference._rotate_object),
        ("freeze", reference._freeze_transformations),
        ("clear_selection", reference._clear_selection),
        ("select_again", lambda node, _shape, _child: cmds.select(node, replace=True)),
        ("undo", lambda *_: _safe("undo", lambda: cmds.undo())),
        ("redo", lambda *_: _safe("redo", lambda: cmds.redo())),
    ]


def run(output: Path | str) -> None:
    """Walk the sequence once, writing `<output>.json` and `<output>.log`."""
    output = Path(output)
    node, shape, child = reference._create_scene()

    previous = _snapshot(node)
    records = [{"action": "initial", "state": previous, "changes": {}}]
    lines = ["initial"]
    for name, action in _steps():
        error = _safe(name, lambda action=action: action(node, shape, child))
        current = _snapshot(node)
        changes = _difference(previous, current)
        record: dict[str, Any] = {"action": name, "state": current, "changes": changes}
        if isinstance(error, dict) and "error" in error:
            record["error"] = error["error"]
            lines.append("{}: FAILED {}".format(name, error["error"]))
        lines.append(name)
        for key, change in changes.items():
            lines.append("  {} : {} -> {}".format(key, change["from"], change["to"]))
        if not changes:
            lines.append("  (nothing changed)")
        records.append(record)
        previous = current

    result = {
        "schema": 1,
        "mayaVersion": cmds.about(version=True),
        "apiVersion": cmds.about(apiVersion=True),
        "subject": node,
        "steps": records,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.with_suffix(".json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    output.with_suffix(".log").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("wrote", output.with_suffix(".json"), "and", output.with_suffix(".log"))
