"""Validate a JSON artifact produced by capture_reference_soft_selection.py.

This file deliberately has no Maya or Clarity dependency, so CI and reviewers can validate a
committed reference capture with ordinary Python.
"""

from __future__ import annotations

import argparse
import json
import os
import sys


REQUIRED_RAMPS = {
    "soft",
    "medium",
    "linear",
    "hard",
    "crater",
    "wave",
    "stairs",
    "ring",
    "sine",
    "interpolation_contract",
}
REQUIRED_GEOMETRY_CASES = {
    "disconnected_volume",
    "disconnected_surface",
    "folded_volume",
    "folded_surface",
    "multiple_objects_volume",
    "multiple_objects_global",
    "nonuniform_scale",
    "multiple_sources",
    "component_kinds",
}


def validate(payload):
    errors = []
    if payload.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if not payload.get("maya", {}).get("api_version"):
        errors.append("maya.api_version is missing")
    if payload.get("source", {}).get("weights") != "maya.api.OpenMaya.MGlobal.getRichSelection":
        errors.append("weight oracle is not Maya Rich Selection")
    if payload.get("source", {}).get("colors") != (
            "maya.cmds.softSelect(query=True, softSelectColorCurve=True)"):
        errors.append("color oracle is not Maya softSelectColorCurve")

    factory = payload.get("factory_settings", {})
    if not factory.get("false_color"):
        errors.append("Maya factory false-color feedback is not enabled")
    color_points = payload.get("factory_color_curve", [])
    if len(color_points) < 3:
        errors.append("factory_color_curve must contain at least black, red and yellow stops")
    elif color_points[0].get("weight") != 0.0 or color_points[-1].get("weight") != 1.0:
        errors.append("factory_color_curve weight domain must be [0, 1]")

    ramps = payload.get("ramps", {})
    missing_ramps = sorted(REQUIRED_RAMPS - set(ramps))
    if missing_ramps:
        errors.append("missing ramps: " + ", ".join(missing_ramps))
    for name in REQUIRED_RAMPS - {"interpolation_contract"}:
        samples = ramps.get(name, {}).get("samples", [])
        if len(samples) != 41:
            errors.append("ramp {!r} must contain 41 samples".format(name))
        elif samples[0].get("position") != 0.0 or samples[-1].get("position") != 1.0:
            errors.append("ramp {!r} sample domain must be [0, 1]".format(name))
    interpolation_contract = ramps.get("interpolation_contract", {})
    for name in ("none", "linear", "smooth", "spline", "spline_neighbors"):
        if len(interpolation_contract.get(name, [])) != 41:
            errors.append("interpolation contract {!r} must contain 41 samples".format(name))

    geometry = payload.get("geometry", {})
    missing_cases = sorted(REQUIRED_GEOMETRY_CASES - set(geometry))
    if missing_cases:
        errors.append("missing geometry cases: " + ", ".join(missing_cases))

    checks = payload.get("checks", [])
    if not checks:
        errors.append("checks are missing")
    failed = [check for check in checks if not check.get("passed")]
    if failed:
        errors.append(
            "failed checks: " + ", ".join(check.get("name", "<unnamed>") for check in failed)
        )
    if payload.get("passed") is not True:
        errors.append("top-level passed flag is not true")
    return errors


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", help="Maya reference JSON")
    args = parser.parse_args(argv)
    capture = os.path.abspath(os.path.expanduser(args.capture))
    with open(capture, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    errors = validate(payload)
    if errors:
        for error in errors:
            print("ERROR: " + error)
        return 1
    print("PASS: {} Maya oracle checks in {}".format(len(payload["checks"]), capture))
    return 0


if __name__ == "__main__":
    sys.exit(main())
