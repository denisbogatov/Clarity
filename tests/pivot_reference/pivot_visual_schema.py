# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Pure-Python contract and pixel math for the Maya manipulator visual reference.

The Maya runner lives in :mod:`capture_reference_pivot_visual`.  Keeping the contract and the
compositing equation in this module lets ordinary CPython test the important part without importing
Maya or Qt.
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence


SCHEMA_VERSION = 2
VIEWS = ("perspective", "front", "right", "top")


def case_specs() -> list[dict[str, Any]]:
    """Every visual state the capture must record, in deterministic order."""
    cases: list[dict[str, Any]] = []

    for tool in ("move", "rotate", "scale"):
        for view in VIEWS:
            cases.append(
                {
                    "name": "{}_{}_default".format(tool, view),
                    "tool": tool,
                    "view": view,
                    "handle": None,
                    "manipScale": 1.0,
                }
            )

    handles = {
        "move": ((0, "x"), (1, "y"), (2, "z"), (3, "center"),
                 (4, "xy"), (5, "yz"), (6, "xz")),
        "rotate": ((0, "x"), (1, "y"), (2, "z"), (3, "view"), (4, "arcball")),
        "scale": ((0, "x"), (1, "y"), (2, "z"), (3, "center")),
    }
    for tool, values in handles.items():
        for value, label in values:
            cases.append(
                {
                    "name": "{}_perspective_handle_{}".format(tool, label),
                    "tool": tool,
                    "view": "perspective",
                    "handle": value,
                    "handleName": label,
                    "manipScale": 1.0,
                }
            )

    for tool in ("move", "rotate", "scale"):
        for factor, label in ((0.75, "075"), (1.5, "150")):
            cases.append(
                {
                    "name": "{}_perspective_size_{}".format(tool, label),
                    "tool": tool,
                    "view": "perspective",
                    "handle": None,
                    "manipScale": factor,
                }
            )

    for tool, channel in (("move", "translateX"), ("rotate", "rotateY"),
                          ("scale", "scaleZ")):
        cases.append(
            {
                "name": "{}_perspective_locked_{}".format(tool, channel),
                "tool": tool,
                "view": "perspective",
                "handle": None,
                "manipScale": 1.0,
                "lockedChannel": channel,
            }
        )

    for view in VIEWS:
        cases.append(
            {
                "name": "edit_pivot_{}_default".format(view),
                "tool": "move",
                "view": view,
                "handle": None,
                "manipScale": 1.0,
                "editPivot": True,
                "pinned": False,
            }
        )
    cases.append(
        {
            "name": "edit_pivot_perspective_pinned",
            "tool": "move",
            "view": "perspective",
            "handle": None,
            "manipScale": 1.0,
            "editPivot": True,
            "pinned": True,
        }
    )

    # A custom authored frame is visible after edit mode closes and is the state Clarity ultimately
    # has to reproduce, not only the temporary D-key editor.
    for tool in ("move", "rotate", "scale"):
        cases.append(
            {
                "name": "{}_perspective_custom_pinned".format(tool),
                "tool": tool,
                "view": "perspective",
                "handle": None,
                "manipScale": 1.0,
                "customPivot": True,
                "pinned": True,
            }
        )
    return cases


def required_case_names() -> set[str]:
    return {case["name"] for case in case_specs()}


def _median(values: Iterable[float]) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[middle])
    return (float(ordered[middle - 1]) + float(ordered[middle])) * 0.5


def _decode_channel(value: int | float, transfer: str) -> float:
    encoded = max(0.0, min(1.0, float(value) / 255.0))
    if transfer == "display":
        return encoded
    if transfer != "srgb":
        raise ValueError("unknown compositing transfer {!r}".format(transfer))
    if encoded <= 0.04045:
        return encoded / 12.92
    return ((encoded + 0.055) / 1.055) ** 2.4


def _encode_channel(value: float, transfer: str) -> int:
    linear = max(0.0, min(1.0, value))
    if transfer == "display":
        encoded = linear
    elif transfer == "srgb":
        if linear <= 0.0031308:
            encoded = 12.92 * linear
        else:
            encoded = 1.055 * (linear ** (1.0 / 2.4)) - 0.055
    else:
        raise ValueError("unknown compositing transfer {!r}".format(transfer))
    return int(round(max(0.0, min(1.0, encoded)) * 255.0))


def solve_composite_pixel(
    dark: Sequence[int],
    light: Sequence[int],
    dark_background: Sequence[int] = (0, 0, 0),
    light_background: Sequence[int] = (255, 255, 255),
    alpha_cutoff: float = 1.0 / 255.0,
    transfer: str = "display",
) -> tuple[int, int, int, int]:
    """Recover display-referred straight RGBA from the same pixel on two flat backgrounds.

    For each channel ``C = alpha * foreground + (1-alpha) * background``.  Subtracting the
    light-background capture from the dark one removes the foreground, so alpha can be measured
    instead of guessed from Maya preferences.  The median of the usable RGB channel estimates makes
    the solve tolerant of byte rounding.
    """
    transmission = []
    for channel in range(3):
        dark_bg = _decode_channel(dark_background[channel], transfer)
        light_bg = _decode_channel(light_background[channel], transfer)
        span = light_bg - dark_bg
        if abs(span) >= 8.0 / 255.0:
            transmission.append(
                (
                    _decode_channel(light[channel], transfer)
                    - _decode_channel(dark[channel], transfer)
                )
                / span
            )
    alpha = max(0.0, min(1.0, 1.0 - _median(transmission)))
    if alpha <= alpha_cutoff:
        return 0, 0, 0, 0

    foreground = []
    one_minus_alpha = 1.0 - alpha
    for channel in range(3):
        dark_value = _decode_channel(dark[channel], transfer)
        light_value = _decode_channel(light[channel], transfer)
        dark_bg = _decode_channel(dark_background[channel], transfer)
        light_bg = _decode_channel(light_background[channel], transfer)
        estimates = (
            (dark_value - one_minus_alpha * dark_bg) / alpha,
            (light_value - one_minus_alpha * light_bg) / alpha,
        )
        # One byte is not a constant-sized interval after sRGB decoding. Weight each endpoint by
        # the inverse decoded quantization interval; this keeps a nearly black ring color from being
        # pulled toward the much coarser subtraction at the white endpoint.
        uncertainties = (
            abs(
                _decode_channel(float(dark[channel]) + 0.5, transfer)
                - _decode_channel(float(dark[channel]) - 0.5, transfer)
            ),
            abs(
                _decode_channel(float(light[channel]) + 0.5, transfer)
                - _decode_channel(float(light[channel]) - 0.5, transfer)
            ),
        )
        weights = [1.0 / max(uncertainty, 1.0e-9) ** 2 for uncertainty in uncertainties]
        weighted = sum(value * weight for value, weight in zip(estimates, weights)) / sum(weights)
        foreground.append(_encode_channel(weighted, transfer))
    return foreground[0], foreground[1], foreground[2], int(round(alpha * 255.0))


def composite_pixel(
    foreground_rgba: Sequence[int],
    background: Sequence[int],
    transfer: str = "display",
) -> tuple[int, int, int]:
    """Composite a solved pixel for the gray-background residual test."""
    alpha = max(0.0, min(1.0, float(foreground_rgba[3]) / 255.0))
    result = []
    for channel in range(3):
        foreground = _decode_channel(foreground_rgba[channel], transfer)
        backdrop = _decode_channel(background[channel], transfer)
        result.append(_encode_channel(alpha * foreground + (1.0 - alpha) * backdrop, transfer))
    return result[0], result[1], result[2]


def transfer_residuals(
    dark: Sequence[int],
    middle: Sequence[int],
    light: Sequence[int],
    dark_background: Sequence[int] = (0, 0, 0),
    middle_background: Sequence[int] = (128, 128, 128),
    light_background: Sequence[int] = (255, 255, 255),
) -> dict[str, int]:
    """Compare display-byte and sRGB source-over models for the same measured pixel."""
    result = {}
    for transfer in ("display", "srgb"):
        solved = solve_composite_pixel(
            dark,
            light,
            dark_background,
            light_background,
            transfer=transfer,
        )
        predicted = composite_pixel(solved, middle_background, transfer=transfer)
        result[transfer] = sum(
            abs(predicted[channel] - int(middle[channel])) for channel in range(3)
        )
    return result


def native_framebuffer_rgba(pixel: Sequence[int]) -> tuple[int, int, int, int]:
    """Keep Maya's straight framebuffer color and measured alpha, clearing transparent RGB."""
    if len(pixel) < 4:
        raise ValueError("native framebuffer pixel must contain RGBA")
    alpha = max(0, min(255, int(pixel[3])))
    if alpha == 0:
        return 0, 0, 0, 0
    return tuple(max(0, min(255, int(pixel[index]))) for index in range(3)) + (alpha,)


def classify_color(rgb: Sequence[int]) -> str:
    """Coarse semantic hue used only for metrics; the reconstructed PNG remains authoritative."""
    red, green, blue = (float(rgb[index]) for index in range(3))
    maximum = max(red, green, blue)
    minimum = min(red, green, blue)
    if maximum < 45.0 or maximum - minimum < 25.0:
        return "neutral"
    if red > 1.18 * green and red > 1.18 * blue:
        return "xRed"
    if green > 1.12 * red and green > 1.12 * blue:
        return "yGreen"
    if blue > 1.12 * red and blue > 1.12 * green:
        return "zBlue"
    if red > 0.72 * maximum and green > 0.72 * maximum and blue < 0.62 * maximum:
        return "selectedYellow"
    if green > 0.72 * maximum and blue > 0.72 * maximum and red < 0.62 * maximum:
        return "cyan"
    if red > 0.72 * maximum and blue > 0.72 * maximum and green < 0.62 * maximum:
        return "magenta"
    return "other"


def validate_fixture(data: Any) -> list[str]:
    """Return human-readable schema errors; an empty list means the fixture is usable."""
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["fixture root must be an object"]
    if data.get("schemaVersion") != SCHEMA_VERSION:
        errors.append("schemaVersion must be {}".format(SCHEMA_VERSION))
    if not isinstance(data.get("environment"), dict):
        errors.append("environment must be an object")
    captures = data.get("captures")
    if not isinstance(captures, list):
        return errors + ["captures must be an array"]

    names = [capture.get("name") for capture in captures if isinstance(capture, dict)]
    if len(names) != len(set(names)):
        errors.append("capture names must be unique")
    missing = sorted(required_case_names() - set(names))
    if missing:
        errors.append("missing cases: " + ", ".join(missing))

    for index, capture in enumerate(captures):
        if not isinstance(capture, dict):
            errors.append("capture {} must be an object".format(index))
            continue
        name = capture.get("name", "#{}".format(index))
        if capture.get("error"):
            errors.append("{} failed: {}".format(name, capture["error"]))
            continue
        artifacts = capture.get("artifacts")
        if not isinstance(artifacts, dict):
            errors.append("{} has no artifacts".format(name))
        else:
            for key in ("dark", "middle", "light", "rgba"):
                if not artifacts.get(key):
                    errors.append("{} has no {} artifact".format(name, key))
        metrics = capture.get("pixelMetrics")
        if not isinstance(metrics, dict):
            errors.append("{} has no pixelMetrics".format(name))
        elif int(metrics.get("visiblePixels", 0)) <= 0:
            errors.append("{} has no visible manipulator pixels".format(name))
        elif metrics.get("alphaSource") not in {"nativeFramebuffer", "threeBackgroundSolve"}:
            errors.append("{} has no alpha source".format(name))
        elif metrics.get("compositingTransferTest", {}).get("selected") not in {"display", "srgb"}:
            errors.append("{} has no validated compositing transfer".format(name))
    return errors
