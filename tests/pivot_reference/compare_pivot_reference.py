# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Diff the Clarity pivot capture against the Maya one, step by step.

Plain Python, no Maya and no Blender: both sides have already been recorded.

  python tests/pivot_reference/compare_pivot_reference.py \
      --maya tests/pivot_reference/fixtures/maya_2025_pivot_interaction.json \
      --clarity tests/pivot_reference/fixtures/clarity_pivot_interaction.json

Scenarios and steps are matched by name, which is why both capture scripts use the same ones. Only
the decisions are compared - is a pivot position authored, is a frame authored, which coordinate
system does the active tool resolve to, and did the pivot's world point move - because those are the
rules. Channel values are not: the two transform models reach the same manipulator through different
channels on purpose, and a numeric diff there would report noise as divergence.

Exit code is 1 when anything diverges, so this can guard a change instead of only describing one.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

# `manipMoveContext -mode`, from the Move Tool page, mapped to the vocabulary the fork's marking menu
# uses. Modes with no counterpart here are named so a divergence report can still print them.
MAYA_MODE_NAMES = {
    0: "OBJECT",
    1: "OBJECT",  # Local space: object axes for a node with no parent shear.
    2: "WORLD",
    3: "NORMAL",
    4: "GIMBAL",
    5: "LIVE_OBJECT",
    6: "CUSTOM",
    10: "COMPONENT",
}

# Steps whose whole purpose is to put the pivot somewhere else. Every other step has to leave the
# pivot's world point where it found it - that is the invariant `Freeze Transformations` and
# `Apply object transform` are judged by.
PIVOT_MOVING_STEPS = {"move_pivots", "reset_position", "reset_both", "bake_position", "bake_both"}

# Steps where the authored-frame flag is not comparable, with the reason. Maya's bake is emulated in
# `capture_reference_pivot._bake_orientation_impl` - the wrapper `bakeCustomToolPivot.mel` needs live
# viewport contexts - and that emulation performs the rotation without touching `manipPivot`, so the
# frame it just baked is still reported as authored. This fork clears it, which is what a baked frame
# means: there is nothing custom left to show.
FRAME_FLAG_INCOMPARABLE_STEPS = {"bake_orientation", "bake_position", "bake_both"}

# Steps that transform the object itself, where the geometry moving is the point. Everything else -
# every pivot edit, every bake, every freeze - has to leave a vertex exactly where it found it.
GEOMETRY_MOVING_STEPS = {"rotate_object", "move_object"}

# #ed::clarity::ClarityMoveOrientation, as the RNA enum reports it.
CLARITY_ORIENTATION_NAMES = {
    "OBJECT": "OBJECT",
    "WORLD": "WORLD",
    "COMPONENT": "COMPONENT",
    "GIMBAL": "GIMBAL",
    "CUSTOM": "CUSTOM",
}


def _maya_orientation(capture: dict[str, Any]) -> str | None:
    """Coordinate system the Move context was on, or None when the capture could not read it."""
    entry = capture.get("axisOrientation", {}).get("contextMode", {}).get("move")
    if not isinstance(entry, dict):
        return None
    mode = entry.get("mode")
    if not isinstance(mode, int):
        return None
    return MAYA_MODE_NAMES.get(mode, "MODE_{}".format(mode))


def _clarity_orientation(capture: dict[str, Any]) -> str | None:
    resolved = capture.get("axisOrientation", {}).get("resolved")
    if not isinstance(resolved, str):
        return None
    return CLARITY_ORIENTATION_NAMES.get(resolved, resolved)


def _pivot_flags(capture: dict[str, Any]) -> tuple[bool | None, bool | None]:
    manip = capture.get("state", {}).get("manipPivot", {})
    position = manip.get("positionValid")
    orientation = manip.get("orientationValid")
    return (
        position if isinstance(position, bool) else None,
        orientation if isinstance(orientation, bool) else None,
    )


def _pivot_world(capture: dict[str, Any]) -> list[float] | None:
    value = capture.get("state", {}).get("rotatePivotWorld")
    if isinstance(value, list) and len(value) == 3:
        return [float(item) for item in value]
    return None


def _geometry_probe(capture: dict[str, Any]) -> list[float] | None:
    """Where the geometry is, from whichever probe the capture carries.

    A bake moves the object origin on purpose; it must not move a vertex. The world matrix cannot tell
    those apart, which is why both captures record a world bounding box and one world-space vertex.
    """
    state = capture.get("state", {})
    # The vertex first, and the bounding box only for something that has no vertices. A bounding box is
    # cached per object and recomputed lazily: right after a bake transforms the mesh in place, a
    # scripted session reads the old object-space box against the new matrix and reports a move that did
    # not happen. A vertex is read from the mesh the bake just wrote.
    for key in ("firstVertexWorld", "worldBoundingBox"):
        value = state.get(key)
        if isinstance(value, list) and value and all(
            isinstance(item, (int, float)) for item in value
        ):
            return [float(item) for item in value]
    return None


def _steps(scenario: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Captures by step name. A repeated name keeps the last, which is what a re-run of a step means."""
    return {capture["action"]: capture for capture in scenario.get("captures", [])}


def compare(maya: dict[str, Any], clarity: dict[str, Any]) -> list[str]:
    """Human-readable divergences, empty when the two agree on every shared step."""
    divergences: list[str] = []
    maya_scenarios = maya.get("interactionScenarios", {})
    clarity_scenarios = clarity.get("interactionScenarios", {})

    shared = [name for name in maya_scenarios if name in clarity_scenarios]
    for name in sorted(set(maya_scenarios) - set(clarity_scenarios)):
        divergences.append("scenario {}: only in the Maya capture".format(name))
    for name in sorted(set(clarity_scenarios) - set(maya_scenarios)):
        divergences.append("scenario {}: only in the Clarity capture".format(name))

    for name in shared:
        maya_steps = _steps(maya_scenarios[name])
        clarity_steps = _steps(clarity_scenarios[name])
        for step in maya_steps:
            if step not in clarity_steps:
                continue
            maya_capture = maya_steps[step]
            clarity_capture = clarity_steps[step]

            maya_position, maya_orientation_valid = _pivot_flags(maya_capture)
            clarity_position, clarity_orientation_valid = _pivot_flags(clarity_capture)
            if (
                step not in FRAME_FLAG_INCOMPARABLE_STEPS
                and maya_orientation_valid is not None
                and clarity_orientation_valid is not None
                and maya_orientation_valid != clarity_orientation_valid
            ):
                divergences.append(
                    "{}/{}: authored frame maya={} clarity={}".format(
                        name, step, maya_orientation_valid, clarity_orientation_valid
                    )
                )
            # The position validity is deliberately not compared. `manipPivot -q -posValid` answers for
            # Maya's component pivot, which is tool state, while an object's pivot position lives in its
            # channels and never shows up there - `xform -pivots` leaves `posValid` false. The fork has
            # one store for both, so the flags describe different things and only the world point below
            # transfers between the two.
            _ = (maya_position, clarity_position)

            maya_mode = _maya_orientation(maya_capture)
            clarity_mode = _clarity_orientation(clarity_capture)
            # `initial` is skipped for this one question: Maya's tool contexts do not exist until the
            # tool is first activated, and until then their `-mode` answers a value left over from
            # whatever asked last - `fixtures/maya_2025_pivot_debug.log` catches it reporting 3 and 6
            # for contexts that had never been used. Every step after the first is real.
            if step == "initial" or name == "axis_orientation_defaults":
                # `axis_orientation_defaults` measures Maya's own pre-activation reading, which the
                # fork has no counterpart for: it has no notion of a coordinate system that does not
                # exist yet. The scenario is still captured on both sides for its pivot flags.
                maya_mode = None
            if maya_mode is not None and clarity_mode is not None and maya_mode != clarity_mode:
                divergences.append(
                    "{}/{}: coordinate system maya={} clarity={}".format(
                        name, step, maya_mode, clarity_mode
                    )
                )

        # No step in any scenario is allowed to move the geometry. Checked per side, because the two
        # scenes are not the same scene - only the invariant transfers, and a bake that moves a vertex
        # is a bug in whichever side moved it.
        for side, steps in (("maya", maya_steps), ("clarity", clarity_steps)):
            probes = [
                (step, _geometry_probe(capture))
                for step, capture in steps.items()
                if _geometry_probe(capture) is not None
            ]
            for (first_step, first), (next_step, following) in zip(probes, probes[1:]):
                if next_step in GEOMETRY_MOVING_STEPS or len(first) != len(following):
                    continue
                if any(abs(a - b) > 1.0e-3 for a, b in zip(first, following)):
                    divergences.append(
                        "{}/{}: {} moved the geometry between {} and {}".format(
                            name, next_step, side, first_step, next_step
                        )
                    )

        # The pivot's world point has to survive every step that is not about moving it, and that is
        # checked within each capture rather than across the two: the scenes are not identical, so only
        # the invariant transfers, not the coordinates.
        for side, steps in (("maya", maya_steps), ("clarity", clarity_steps)):
            points = [
                (step, _pivot_world(capture))
                for step, capture in steps.items()
                if _pivot_world(capture) is not None
            ]
            for (first_step, first), (next_step, following) in zip(points, points[1:]):
                if next_step in PIVOT_MOVING_STEPS:
                    continue
                if any(abs(a - b) > 1.0e-3 for a, b in zip(first, following)):
                    divergences.append(
                        "{}/{}: {} pivot world point moved {} -> {} between {} and {}".format(
                            name,
                            next_step,
                            side,
                            [round(value, 3) for value in first],
                            [round(value, 3) for value in following],
                            first_step,
                            next_step,
                        )
                    )
    return divergences


def summary(maya: dict[str, Any], clarity: dict[str, Any]) -> list[str]:
    """Both sides of every shared step, so an unexpected agreement is as visible as a divergence."""
    lines: list[str] = []
    maya_scenarios = maya.get("interactionScenarios", {})
    clarity_scenarios = clarity.get("interactionScenarios", {})
    for name in maya_scenarios:
        if name not in clarity_scenarios:
            continue
        lines.append("=== {}".format(name))
        maya_steps = _steps(maya_scenarios[name])
        clarity_steps = _steps(clarity_scenarios[name])
        for step, maya_capture in maya_steps.items():
            clarity_capture = clarity_steps.get(step)
            if clarity_capture is None:
                lines.append("  {:<22} clarity: (no such step)".format(step))
                continue
            maya_position, maya_frame = _pivot_flags(maya_capture)
            clarity_position, clarity_frame = _pivot_flags(clarity_capture)
            lines.append(
                "  {:<22} frame {}/{}  position {}/{}  system {}/{}".format(
                    step,
                    maya_frame,
                    clarity_frame,
                    maya_position,
                    clarity_position,
                    _maya_orientation(maya_capture),
                    _clarity_orientation(clarity_capture),
                )
            )
    return lines


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--maya", type=Path, required=True)
    parser.add_argument("--clarity", type=Path, required=True)
    parser.add_argument(
        "--quiet", action="store_true", help="Report divergences only, without the full table"
    )
    args = parser.parse_args()

    maya = json.loads(args.maya.read_text(encoding="utf-8"))
    clarity = json.loads(args.clarity.read_text(encoding="utf-8"))

    if not args.quiet:
        print("\n".join(summary(maya, clarity)))
        print()

    divergences = compare(maya, clarity)
    if not divergences:
        print("no divergence on any shared step")
        return 0
    print("divergences ({}):".format(len(divergences)))
    for line in divergences:
        print(" ", line)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
