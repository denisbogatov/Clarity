# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Compare Maya and Clarity/Blender model-snapping captures by canonical test name.

This is plain Python: both DCC applications have already written their schema-7 JSON files.

  python3 tests/pivot_reference/compare_model_snapping.py \
      --maya tests/pivot_reference/fixtures/maya_2025_pivot_gestures_model_snapping.json \
      --blender tests/pivot_reference/fixtures/clarity_model_snapping.json

The report keeps result parity and input fidelity separate.  A Blender record marked
``operator_equivalent`` can compare scene outcomes, but cannot prove that native mouse/modifier
events took the same route as Maya's ``nativeInput`` capture.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _tests(capture: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        record["name"]: record
        for record in capture.get("tests", [])
        if isinstance(record, dict) and isinstance(record.get("name"), str)
    }


def _passed(record: dict[str, Any]) -> bool:
    return bool(record.get("analysis", {}).get("passed")) and not bool(record.get("error"))


def compare(maya: dict[str, Any], blender: dict[str, Any]) -> dict[str, Any]:
    maya_tests = _tests(maya)
    blender_tests = _tests(blender)
    order = [record["name"] for record in maya.get("tests", []) if record.get("name")]
    order.extend(sorted(set(blender_tests) - set(order)))
    rows: list[dict[str, Any]] = []

    for name in order:
        maya_record = maya_tests.get(name)
        blender_record = blender_tests.get(name)
        if maya_record is None or blender_record is None:
            rows.append(
                {
                    "name": name,
                    "presentInMaya": maya_record is not None,
                    "presentInBlender": blender_record is not None,
                    "comparable": False,
                    "agreement": False,
                }
            )
            continue

        maya_passed = _passed(maya_record)
        blender_passed = _passed(blender_record)
        mode_matches = maya_record.get("mode") == blender_record.get("mode")
        tool_matches = maya_record.get("tool") == blender_record.get("tool")
        fidelity = blender_record.get(
            "executionFidelity", blender.get("executionFidelity", "unknown")
        )
        rows.append(
            {
                "name": name,
                "presentInMaya": True,
                "presentInBlender": True,
                "comparable": mode_matches and tool_matches,
                "mode": maya_record.get("mode"),
                "tool": maya_record.get("tool"),
                "modeMatches": mode_matches,
                "toolMatches": tool_matches,
                "mayaPassed": maya_passed,
                "blenderPassed": blender_passed,
                "agreement": mode_matches and tool_matches and maya_passed == blender_passed,
                "blenderExecutionFidelity": fidelity,
                "nativeInputComparable": fidelity == "native_input",
                "mayaAnalysis": maya_record.get("analysis", {}),
                "blenderAnalysis": blender_record.get("analysis", {}),
            }
        )

    shared = [row for row in rows if row["presentInMaya"] and row["presentInBlender"]]
    divergences = [row["name"] for row in rows if not row["agreement"]]
    fidelity_warnings = [
        row["name"]
        for row in shared
        if not row.get("nativeInputComparable", False)
    ]
    return {
        "schema": 1,
        "mayaSchema": maya.get("schema"),
        "blenderSchema": blender.get("schema"),
        "counts": {
            "maya": len(maya_tests),
            "blender": len(blender_tests),
            "shared": len(shared),
            "agreements": sum(bool(row["agreement"]) for row in shared),
            "divergences": len(divergences),
            "mayaPassed": sum(_passed(record) for record in maya_tests.values()),
            "blenderPassed": sum(_passed(record) for record in blender_tests.values()),
        },
        "allScenarioNamesMatch": set(maya_tests) == set(blender_tests),
        "allResultsAgree": not divergences,
        "nativeInputComparable": not fidelity_warnings,
        "fidelityWarning": (
            None
            if not fidelity_warnings
            else "Blender used operator-equivalent execution; outcome parity is comparable, native input routing is not."
        ),
        "divergences": divergences,
        "rows": rows,
    }


def _text_report(result: dict[str, Any]) -> str:
    counts = result["counts"]
    lines = [
        "Maya <-> Clarity model snapping",
        "Maya: {maya} tests, {mayaPassed} passed".format(**counts),
        "Blender: {blender} tests, {blenderPassed} passed".format(**counts),
        "Shared: {shared}; agreements: {agreements}; divergences: {divergences}".format(
            **counts
        ),
    ]
    if result.get("fidelityWarning"):
        lines.extend(("", "WARNING: " + result["fidelityWarning"]))
    lines.append("")
    for row in result["rows"]:
        if not row["presentInMaya"]:
            lines.append("ONLY BLENDER  " + row["name"])
        elif not row["presentInBlender"]:
            lines.append("ONLY MAYA     " + row["name"])
        else:
            status = "MATCH" if row["agreement"] else "DIFF"
            lines.append(
                "{:<5} Maya={} Blender={}  {}".format(
                    status, row["mayaPassed"], row["blenderPassed"], row["name"]
                )
            )
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--maya", type=Path, required=True)
    parser.add_argument("--blender", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    maya = json.loads(args.maya.read_text(encoding="utf-8"))
    blender = json.loads(args.blender.read_text(encoding="utf-8"))
    result = compare(maya, blender)
    report = _text_report(result)
    print(report, end="")
    if args.output:
        stem = args.output.with_suffix("") if args.output.suffix else args.output
        stem.parent.mkdir(parents=True, exist_ok=True)
        stem.with_suffix(".json").write_text(
            json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        stem.with_suffix(".log").write_text(report, encoding="utf-8")
    return 0 if result["allResultsAgree"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
