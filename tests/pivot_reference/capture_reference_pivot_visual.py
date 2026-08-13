# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Measure Maya's transform/pivot manipulator as pixels, settings, colors and screen geometry.

Run this from a live Maya session; the one-click entry point is the
``Записать внешний вид пивота`` button in :mod:`capture_reference_window`::

  import capture_reference_pivot_visual as visual
  visual.run(r"S:\\Clarity\\blender\\tests\\pivot_reference\\fixtures\\maya_2025_pivot_visual")

Every state is captured three times without moving the camera or manipulator: over flat black,
50% gray and white viewports. Maya's framebuffer supplies the manipulator's native alpha directly.
The three backgrounds record its actual compositing behavior and provide a fallback solve

``composite = alpha * foreground + (1 - alpha) * background``

when framebuffer alpha is unavailable. The resulting transparent PNG keeps the dark capture's
display RGB and the measured framebuffer opacity of arrows, planar handles, rings and anti-aliased
edges. JSON beside it records the camera matrices, pivot pixel, viewport/DPI data, Maya palettes,
manipulator preferences, tool contexts and numeric pixel metrics.

The capture uses a temporary empty transform and camera in the current scene.  It restores the
selection, tool, panel, cursor, colors, manipulator size and custom-pivot state in ``finally`` and
does not replace or save the scene.
"""

from __future__ import annotations

import datetime
import importlib
import json
import math
import os
import platform
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Sequence

import capture_reference_pivot as reference
import pivot_visual_schema as schema
from reference_backend import cmds, mel


_DEFAULT_OUTPUT = Path(__file__).parent / "fixtures" / "maya_2025_pivot_visual"
_CROP_RADIUS_LOGICAL_PIXELS = 260
_SETTLE_SECONDS = 0.08

_TOOLS = {
    "move": ("Move", cmds.manipMoveContext, 2),
    "rotate": ("Rotate", cmds.manipRotateContext, 0),
    "scale": ("Scale", cmds.manipScaleContext, 0),
}

_MANIP_OPTION_FLAGS = (
    "enableSmartDuplicate",
    "enableSmartExtrude",
    "handleSize",
    "hideManipOnCtrl",
    "hideManipOnShift",
    "hideManipOnShiftCtrl",
    "linePick",
    "lineSize",
    "middleMouseRepositioning",
    "pivotRotateHandleOffset",
    "planeHandleOffset",
    "pointSize",
    "preselectHighlight",
    "refreshMode",
    "rememberActiveHandle",
    "rememberActiveHandleAfterToolSwitch",
    "scale",
    "showExtrudeSliders",
    "showPivotRotateHandle",
    "showPlaneHandles",
    "smartDuplicateType",
)

_CONTEXT_FLAGS = {
    "move": (
        "activeHandle",
        "currentActiveHandle",
        "editPivotMode",
        "editPivotPosition",
        "lastMode",
        "manipVisible",
        "mode",
        "orientAxes",
        "pinPivot",
        "pivotOriHandle",
        "position",
        "snap",
        "snapComponentsRelative",
        "snapLiveFaceCenter",
        "snapLivePoint",
        "snapPivotOri",
        "snapPivotPos",
        "snapRelative",
        "snapValue",
        "translate",
        "tweakMode",
    ),
    "rotate": (
        "activeHandle",
        "centerTrackball",
        "currentActiveHandle",
        "editPivotMode",
        "editPivotPosition",
        "lastMode",
        "manipVisible",
        "mode",
        "orientAxes",
        "pinPivot",
        "pivotOriHandle",
        "position",
        "rotate",
        "snap",
        "snapPivotOri",
        "snapPivotPos",
        "snapRelative",
        "snapValue",
        "tweakMode",
        "useCenterPivot",
        "useManipPivot",
        "useObjectPivot",
    ),
    "scale": (
        "activeHandle",
        "currentActiveHandle",
        "editPivotMode",
        "editPivotPosition",
        "lastMode",
        "manipVisible",
        "mode",
        "orientAxes",
        "pinPivot",
        "pivotOriHandle",
        "position",
        "preventNegativeScale",
        "scale",
        "snap",
        "snapPivotOri",
        "snapPivotPos",
        "snapRelative",
        "snapValue",
        "tweakMode",
        "useManipPivot",
        "useObjectPivot",
    ),
}


def refresh_modules() -> None:
    """Re-read pure helpers in Maya sessions that stay open while this file changes."""
    importlib.reload(schema)


def _safe(description: str, function: Callable[[], Any]) -> Any:
    return reference._safe(description, function)


def _json_value(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    return value


def _qt():
    try:
        from PySide6 import QtCore, QtGui, QtWidgets  # type: ignore
        from shiboken6 import wrapInstance  # type: ignore
    except ImportError:
        from PySide2 import QtCore, QtGui, QtWidgets  # type: ignore
        from shiboken2 import wrapInstance  # type: ignore
    return QtCore, QtGui, QtWidgets, wrapInstance


def _settle(seconds: float = _SETTLE_SECONDS) -> None:
    _, _, QtWidgets, _ = _qt()
    application = QtWidgets.QApplication.instance()
    cmds.refresh(force=True)
    deadline = time.time() + seconds
    while time.time() < deadline:
        if application is not None:
            application.processEvents()
        time.sleep(0.004)
    cmds.refresh(force=True)
    if application is not None:
        application.processEvents()
        time.sleep(0.008)
        application.processEvents()


def _viewport_widget():
    """Return the largest visible model panel and its Qt widget."""
    import maya.OpenMayaUI as omui  # noqa: N813

    _, _, QtWidgets, wrap_instance = _qt()
    visible = [
        panel
        for panel in (cmds.getPanel(visiblePanels=True) or [])
        if cmds.getPanel(typeOf=panel) == "modelPanel"
    ]
    candidates = visible or (cmds.getPanel(type="modelPanel") or [])
    best = None
    for panel in candidates:
        pointer = omui.MQtUtil.findControl(panel)
        if pointer is None:
            continue
        widget = wrap_instance(int(pointer), QtWidgets.QWidget)
        area = widget.width() * widget.height()
        if not widget.isVisible():
            area //= 100
        if best is None or area > best[0]:
            best = area, panel, widget
    if best is None:
        raise RuntimeError("нет видимой 3D-панели, внешний вид пивота негде снять")
    return best[1], best[2]


def _view(panel: str):
    import maya.OpenMayaUI as omui  # noqa: N813

    view = omui.M3dView()
    try:
        omui.M3dView.getM3dViewFromModelPanel(panel, view)
        return view
    except Exception:
        return omui.M3dView.active3dView()


def _matrix_values(matrix: Any) -> list[float]:
    values = []
    for row in range(4):
        for column in range(4):
            try:
                values.append(float(matrix(row, column)))
            except TypeError:
                values.append(float(matrix[row][column]))
    return values


def _pivot_logical_pixel(panel: str, widget: Any) -> tuple[int, int, tuple[int, int]]:
    import maya.OpenMaya as om  # noqa: N813

    view = _view(panel)
    x_util = om.MScriptUtil()
    x_util.createFromInt(0)
    x_pointer = x_util.asShortPtr()
    y_util = om.MScriptUtil()
    y_util.createFromInt(0)
    y_pointer = y_util.asShortPtr()
    visible = view.worldToView(om.MPoint(0.0, 0.0, 0.0), x_pointer, y_pointer)
    x = int(om.MScriptUtil.getShort(x_pointer))
    y = int(om.MScriptUtil.getShort(y_pointer))
    view_width = int(view.portWidth())
    view_height = int(view.portHeight())
    if visible is False or not (0 <= x < view_width and 0 <= y < view_height):
        raise RuntimeError("пивот в начале координат не попал в выбранную 3D-панель")
    return x, view_height - y, (view_width, view_height)


def _grab_widget(widget: Any):
    _, _, QtWidgets, _ = _qt()
    application = QtWidgets.QApplication.instance()
    if application is None:
        raise RuntimeError("у Maya нет QApplication для захвата viewport")
    # `widget.window().windowHandle()` can hand PySide a transient QWindow that Maya deletes during
    # workspace-layout updates. Resolve the screen from the viewport's global center instead; the
    # QApplication owns that QScreen for the lifetime of the process.
    center = widget.mapToGlobal(widget.rect().center())
    screen = application.screenAt(center) or application.primaryScreen()
    if screen is None:
        raise RuntimeError("у окна Maya нет экрана для захвата viewport")
    origin = widget.mapToGlobal(widget.rect().topLeft())
    pixmap = screen.grabWindow(0, origin.x(), origin.y(), widget.width(), widget.height())
    if pixmap is None or pixmap.isNull():
        raise RuntimeError("операционная система не отдала пиксели viewport")
    return pixmap.toImage(), screen, origin, "qScreenGrabWindow"


def _grab_view_buffer(panel: str, widget: Any):
    """Read Maya's own color buffer, avoiding desktop capture and Screen Recording permission."""
    import maya.OpenMaya as om  # noqa: N813

    _, QtGui, QtWidgets, _ = _qt()
    application = QtWidgets.QApplication.instance()
    if application is None:
        raise RuntimeError("у Maya нет QApplication для чтения framebuffer")
    center = widget.mapToGlobal(widget.rect().center())
    screen = application.screenAt(center) or application.primaryScreen()
    if screen is None:
        raise RuntimeError("у Maya нет QScreen для метаданных framebuffer")

    view = _view(panel)
    view.refresh(False, True)
    maya_image = om.MImage()
    view.readColorBuffer(maya_image, True)
    maya_image.verticalFlip()
    descriptor, temporary_name = tempfile.mkstemp(prefix="clarity_maya_view_", suffix=".png")
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        maya_image.writeToFile(str(temporary), "png")
        image = QtGui.QImage(str(temporary))
        if image.isNull():
            raise RuntimeError("M3dView readColorBuffer вернул пустое изображение")
        image = image.copy()
    finally:
        try:
            temporary.unlink()
        except OSError:
            pass
    origin = widget.mapToGlobal(widget.rect().topLeft())
    return image, screen, origin, "m3dViewReadColorBuffer"


def _cropped_viewport(panel: str, widget: Any) -> tuple[Any, dict[str, Any]]:
    try:
        image, screen, origin, capture_method = _grab_view_buffer(panel, widget)
    except Exception as buffer_error:
        image, screen, origin, capture_method = _grab_widget(widget)
        capture_method += " (M3dView failed: {})".format(buffer_error)
    logical_x, logical_y, view_size = _pivot_logical_pixel(panel, widget)
    scale_x = image.width() / float(max(1, view_size[0]))
    scale_y = image.height() / float(max(1, view_size[1]))
    pivot_x = int(round(logical_x * scale_x))
    pivot_y = int(round(logical_y * scale_y))
    radius_x = int(round(_CROP_RADIUS_LOGICAL_PIXELS * scale_x))
    radius_y = int(round(_CROP_RADIUS_LOGICAL_PIXELS * scale_y))
    left = pivot_x - radius_x
    top = pivot_y - radius_y
    right = pivot_x + radius_x
    bottom = pivot_y + radius_y
    if left < 0 or top < 0 or right > image.width() or bottom > image.height():
        raise RuntimeError(
            "viewport слишком мал для эталонного crop {} px вокруг пивота".format(
                _CROP_RADIUS_LOGICAL_PIXELS
            )
        )
    cropped = image.copy(left, top, right - left, bottom - top)
    return cropped, {
        "viewportLogicalSize": [widget.width(), widget.height()],
        "viewportRenderSize": list(view_size),
        "viewportImageSize": [image.width(), image.height()],
        "viewportDesktopOrigin": [int(origin.x()), int(origin.y())],
        "cropInViewportImage": [left, top, right - left, bottom - top],
        "cropSize": [cropped.width(), cropped.height()],
        "pivotInCrop": [pivot_x - left, pivot_y - top],
        "logicalToImageScale": [scale_x, scale_y],
        "widgetDevicePixelRatio": float(widget.devicePixelRatioF()),
        "screenDevicePixelRatio": float(screen.devicePixelRatio()),
        "screenName": screen.name(),
        "screenDepth": int(screen.depth()),
        "captureMethod": capture_method,
    }


def _image_rgba_bytes(image: Any) -> tuple[Any, bytes]:
    _, QtGui, _, _ = _qt()
    converted = image.convertToFormat(QtGui.QImage.Format_RGBA8888)
    size = converted.bytesPerLine() * converted.height()
    pointer = converted.constBits()
    try:
        pointer.setsize(size)
    except AttributeError:
        pass
    return converted, bytes(pointer[:size])


def _background_sample(data: bytes, image: Any) -> list[int]:
    values = [[], [], []]
    width = image.width()
    height = image.height()
    row_bytes = image.bytesPerLine()
    for corner_x in (0, max(0, width - 8)):
        for corner_y in (0, max(0, height - 8)):
            for y in range(corner_y, min(height, corner_y + 8)):
                for x in range(corner_x, min(width, corner_x + 8)):
                    offset = y * row_bytes + x * 4
                    for channel in range(3):
                        values[channel].append(data[offset + channel])
    return [int(round(_percentile(channel, 0.5))) for channel in values]


def _percentile(values: Sequence[int | float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    position = max(0.0, min(1.0, fraction)) * (len(ordered) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _new_color_stat() -> dict[str, Any]:
    return {
        "pixels": 0,
        "rgbSum": [0, 0, 0],
        "alpha": [],
        "bounds": [10**9, 10**9, -10**9, -10**9],
        "radii": [],
        "radialAlpha": {},
    }


def _finish_color_stat(stat: dict[str, Any], pivot: Sequence[int]) -> dict[str, Any]:
    pixels = stat["pixels"]
    if not pixels:
        return {
            "pixels": 0,
            "meanRGB": [0, 0, 0],
            "alpha": {"p10": 0.0, "p50": 0.0, "p90": 0.0, "max": 0.0},
            "boundsFromPivot": None,
            "radiusPixels": {"p10": 0.0, "p50": 0.0, "p90": 0.0, "max": 0.0},
        }
    alpha = stat["alpha"]
    radii = stat["radii"]
    bounds = stat["bounds"]
    return {
        "pixels": pixels,
        "meanRGB": [int(round(total / float(pixels))) for total in stat["rgbSum"]],
        "alpha": {
            "p10": round(_percentile(alpha, 0.1) / 255.0, 4),
            "p50": round(_percentile(alpha, 0.5) / 255.0, 4),
            "p90": round(_percentile(alpha, 0.9) / 255.0, 4),
            "max": round(max(alpha) / 255.0, 4),
        },
        "boundsFromPivot": [
            bounds[0] - pivot[0],
            bounds[1] - pivot[1],
            bounds[2] - pivot[0],
            bounds[3] - pivot[1],
        ],
        "radiusPixels": {
            "p10": round(_percentile(radii, 0.1), 2),
            "p50": round(_percentile(radii, 0.5), 2),
            "p90": round(_percentile(radii, 0.9), 2),
            "max": round(max(radii), 2),
        },
        # Rotation circles form narrow peaks in this profile; arrow shafts and heads occupy a wider
        # range. Keeping alpha coupled to radius makes their opacity directly readable from JSON.
        "radialAlphaProfile": [
            {
                "radiusPixels": radius,
                "pixels": len(values),
                "alphaP50": round(_percentile(values, 0.5) / 255.0, 4),
                "alphaP90": round(_percentile(values, 0.9) / 255.0, 4),
            }
            for radius, values in sorted(stat["radialAlpha"].items())
        ],
    }


def _choose_compositing_transfer(dark: Any, middle: Any, light: Any) -> dict[str, Any]:
    """Use the gray capture to decide whether Maya blended in display or sRGB-linear space."""
    images_and_bytes = [_image_rgba_bytes(image) for image in (dark, middle, light)]
    images = [entry[0] for entry in images_and_bytes]
    buffers = [entry[1] for entry in images_and_bytes]
    dimensions = {(image.width(), image.height()) for image in images}
    if len(dimensions) != 1:
        raise RuntimeError("dark/mid/light viewport captures have different dimensions")
    backgrounds = [_background_sample(data, image) for image, data in images_and_bytes]
    scores = {"display": [0.0, 0], "srgb": [0.0, 0]}
    width, height = images[0].width(), images[0].height()
    strides = [image.bytesPerLine() for image in images]
    for y in range(0, height, 2):
        for x in range(0, width, 2):
            offsets = [y * stride + x * 4 for stride in strides]
            pixels = [
                buffers[index][offsets[index]:offsets[index] + 3]
                for index in range(3)
            ]
            solved = {
                transfer: schema.solve_composite_pixel(
                    pixels[0],
                    pixels[2],
                    backgrounds[0],
                    backgrounds[2],
                    transfer=transfer,
                )
                for transfer in scores
            }
            # Both models must be scored on the same pixels. Their decoded alpha estimates differ,
            # so independently filtering each model would make the residuals incomparable.
            if not any(16 <= value[3] <= 239 for value in solved.values()):
                continue
            residuals = schema.transfer_residuals(
                pixels[0], pixels[1], pixels[2], backgrounds[0], backgrounds[1], backgrounds[2]
            )
            for transfer, residual in residuals.items():
                scores[transfer][0] += residual
                scores[transfer][1] += 1
    mean = {
        transfer: (total / count if count else None)
        for transfer, (total, count) in scores.items()
    }
    usable = {transfer: value for transfer, value in mean.items() if value is not None}
    selected = min(usable, key=usable.get) if usable else "display"
    return {
        "selected": selected,
        "meanAbsoluteRgbByteResidual": mean,
        "testedPixels": {transfer: values[1] for transfer, values in scores.items()},
        "backgroundSamples": {
            "dark": backgrounds[0], "middle": backgrounds[1], "light": backgrounds[2]
        },
    }


def _native_framebuffer_alpha(images_and_bytes: Sequence[tuple[Any, bytes]]) -> dict[str, Any]:
    """Prove that the framebuffer supplied one stable, nontrivial alpha map for all backgrounds."""
    images = [entry[0] for entry in images_and_bytes]
    buffers = [entry[1] for entry in images_and_bytes]
    if len({(image.width(), image.height()) for image in images}) != 1:
        return {"usable": False, "reason": "capture dimensions differ"}
    width, height = images[0].width(), images[0].height()
    strides = [image.bytesPerLine() for image in images]
    nonzero = 0
    transparent = 0
    different = 0
    values = set()
    for y in range(height):
        for x in range(width):
            alpha = [buffers[index][y * strides[index] + x * 4 + 3] for index in range(3)]
            values.add(alpha[0])
            nonzero += alpha[0] > 0
            transparent += alpha[0] == 0
            different += not (alpha[0] == alpha[1] == alpha[2])
    usable = nonzero > 0 and transparent > 0 and different == 0 and max(values, default=0) > 0
    return {
        "usable": usable,
        "mapsIdentical": different == 0,
        "differentPixels": different,
        "nonzeroPixels": nonzero,
        "transparentPixels": transparent,
        "distinctAlphaValues": len(values),
        "minimum": min(values, default=0),
        "maximum": max(values, default=0),
        "reason": None if usable else "alpha is absent, opaque, or changes with the background",
    }


def _reconstruct_rgba(dark: Any, middle: Any, light: Any,
                      pivot: Sequence[int]) -> tuple[Any, dict[str, Any]]:
    """Solve the background captures and return a straight-alpha QImage plus numeric metrics."""
    _, QtGui, _, _ = _qt()
    images_and_bytes = [_image_rgba_bytes(image) for image in (dark, middle, light)]
    native_alpha = _native_framebuffer_alpha(images_and_bytes)
    transfer_test = _choose_compositing_transfer(dark, middle, light)
    transfer = transfer_test["selected"]
    dark_image, dark_bytes = images_and_bytes[0]
    light_image, light_bytes = images_and_bytes[2]
    if (dark_image.width(), dark_image.height()) != (light_image.width(), light_image.height()):
        raise RuntimeError("dark/light viewport captures have different dimensions")

    dark_background = _background_sample(dark_bytes, dark_image)
    light_background = _background_sample(light_bytes, light_image)
    width, height = dark_image.width(), dark_image.height()
    row_bytes = width * 4
    output = bytearray(row_bytes * height)
    all_alpha: list[int] = []
    color_stats: dict[str, dict[str, Any]] = {}
    quantized: dict[tuple[int, int, int], int] = {}
    bounds = [10**9, 10**9, -10**9, -10**9]
    bands = {"edgeOrVeryFaint": 0, "translucent": 0, "mostlyOpaque": 0, "opaque": 0}

    dark_stride = dark_image.bytesPerLine()
    light_stride = light_image.bytesPerLine()
    for y in range(height):
        for x in range(width):
            dark_offset = y * dark_stride + x * 4
            light_offset = y * light_stride + x * 4
            dark_rgb = dark_bytes[dark_offset:dark_offset + 3]
            light_rgb = light_bytes[light_offset:light_offset + 3]
            if native_alpha["usable"]:
                red, green, blue, alpha = schema.native_framebuffer_rgba(
                    dark_bytes[dark_offset:dark_offset + 4]
                )
            else:
                red, green, blue, alpha = schema.solve_composite_pixel(
                    dark_rgb,
                    light_rgb,
                    dark_background,
                    light_background,
                    transfer=transfer,
                )
            output_offset = y * row_bytes + x * 4
            output[output_offset:output_offset + 4] = bytes((red, green, blue, alpha))
            if alpha <= 0:
                continue

            all_alpha.append(alpha)
            bounds[0] = min(bounds[0], x)
            bounds[1] = min(bounds[1], y)
            bounds[2] = max(bounds[2], x)
            bounds[3] = max(bounds[3], y)
            if alpha < 32:
                bands["edgeOrVeryFaint"] += 1
            elif alpha < 192:
                bands["translucent"] += 1
            elif alpha < 250:
                bands["mostlyOpaque"] += 1
            else:
                bands["opaque"] += 1

            color_class = schema.classify_color((red, green, blue))
            stat = color_stats.setdefault(color_class, _new_color_stat())
            stat["pixels"] += 1
            for channel, value in enumerate((red, green, blue)):
                stat["rgbSum"][channel] += value
            stat["alpha"].append(alpha)
            stat["bounds"][0] = min(stat["bounds"][0], x)
            stat["bounds"][1] = min(stat["bounds"][1], y)
            stat["bounds"][2] = max(stat["bounds"][2], x)
            stat["bounds"][3] = max(stat["bounds"][3], y)
            radius = math.hypot(x - pivot[0], y - pivot[1])
            stat["radii"].append(radius)
            radial_bin = int(round(radius / 2.0) * 2)
            stat["radialAlpha"].setdefault(radial_bin, []).append(alpha)

            if alpha >= 64:
                key = tuple(int(round(value / 8.0) * 8) for value in (red, green, blue))
                key = tuple(min(255, value) for value in key)
                quantized[key] = quantized.get(key, 0) + 1

    result = QtGui.QImage(
        bytes(output), width, height, row_bytes, QtGui.QImage.Format_RGBA8888
    ).copy()
    visible = len(all_alpha)
    metrics = {
        "alphaSource": "nativeFramebuffer" if native_alpha["usable"] else "threeBackgroundSolve",
        "nativeFramebufferAlphaTest": native_alpha,
        "backgroundSamples": transfer_test["backgroundSamples"],
        "compositingTransferTest": transfer_test,
        "visiblePixels": visible,
        "coverageByAlphaBand": bands,
        "alpha": {
            "p10": round(_percentile(all_alpha, 0.1) / 255.0, 4),
            "p50": round(_percentile(all_alpha, 0.5) / 255.0, 4),
            "p90": round(_percentile(all_alpha, 0.9) / 255.0, 4),
            "max": round((max(all_alpha) if all_alpha else 0) / 255.0, 4),
        },
        "boundsFromPivot": None if not visible else [
            bounds[0] - pivot[0],
            bounds[1] - pivot[1],
            bounds[2] - pivot[0],
            bounds[3] - pivot[1],
        ],
        "colorClasses": {
            name: _finish_color_stat(stat, pivot)
            for name, stat in sorted(color_stats.items())
        },
        "dominantDisplayColors": [
            {"rgb": list(color), "pixels": count}
            for color, count in sorted(
                quantized.items(), key=lambda item: (-item[1], item[0])
            )[:16]
        ],
    }
    return result, metrics


def _query_rgb(name: str) -> Any:
    value = _safe(name + " RGBA", lambda: cmds.displayRGBColor(name, query=True, alpha=True))
    if isinstance(value, dict):
        value = _safe(name + " RGB", lambda: cmds.displayRGBColor(name, query=True))
    return _json_value(value)


def _set_background(rgb: Sequence[float]) -> None:
    for name in ("background", "backgroundTop", "backgroundBottom"):
        cmds.displayRGBColor(name, float(rgb[0]), float(rgb[1]), float(rgb[2]))
    _settle()


def _capture_flat_background(panel: str, widget: Any, rgb: Sequence[float],
                             label: str) -> tuple[Any, dict[str, Any]]:
    """Set, flush and verify one flat background before trusting its viewport image."""
    _set_background(rgb)
    # A priming read plus another event-loop turn makes the following read the requested frame,
    # rather than the preceding one. This also protects the QScreen fallback from compositor lag.
    _cropped_viewport(panel, widget)
    _settle(0.05)
    image, screen = _cropped_viewport(panel, widget)
    converted, data = _image_rgba_bytes(image)
    sample = _background_sample(data, converted)
    if label == "dark":
        valid = max(sample) <= 30
    elif label == "light":
        valid = min(sample) >= 225
    else:
        valid = all(64 <= value <= 192 for value in sample)
    if not valid:
        raise RuntimeError(
            "фон {} снялся как RGB {}, framebuffer устарел; для QScreen fallback также проверьте, "
            "что viewport не перекрыт и Maya разрешена запись экрана".format(label, sample)
        )
    return image, screen


def _query_manip_options() -> dict[str, Any]:
    result = {}
    for flag in _MANIP_OPTION_FLAGS:
        result[flag] = _json_value(
            _safe("manipOptions " + flag, lambda flag=flag: cmds.manipOptions(query=True, **{flag: True}))
        )
    return result


def _context_name(tool: str) -> str:
    for name in reference._context_names(tool):
        if _safe("contextInfo " + name, lambda name=name: cmds.contextInfo(name, exists=True)) is True:
            return name
    raise RuntimeError("Maya did not create the {} manipulator context".format(tool))


def _query_context(tool: str) -> dict[str, Any]:
    _tool_name, command, _mode = _TOOLS[tool]
    try:
        context = _context_name(tool)
    except RuntimeError as error:
        # A fresh Maya session may not instantiate a tool context until that tool is activated. The
        # individual case activates it before capture; environment metadata should still be written.
        return {"error": str(error)}
    values: dict[str, Any] = {"name": context}
    for flag in _CONTEXT_FLAGS[tool]:
        values[flag] = _json_value(
            _safe(
                "{} {}".format(tool, flag),
                lambda flag=flag: command(context, query=True, **{flag: True}),
            )
        )
    return values


def _query_pivot() -> dict[str, Any]:
    return {
        "valid": _safe("pivot valid", lambda: cmds.manipPivot(query=True, valid=True)),
        "positionValid": _safe("pivot posValid", lambda: cmds.manipPivot(query=True, posValid=True)),
        "orientationValid": _safe("pivot oriValid", lambda: cmds.manipPivot(query=True, oriValid=True)),
        "position": _json_value(_safe("pivot position", lambda: cmds.manipPivot(query=True, position=True))),
        "orientation": _json_value(
            _safe("pivot orientation", lambda: cmds.manipPivot(query=True, orientation=True))
        ),
        "pinned": _safe("pivot pinned", lambda: cmds.manipPivot(query=True, pinPivot=True)),
        "snapPosition": _safe("pivot snapPos", lambda: cmds.manipPivot(query=True, snapPos=True)),
        "snapOrientation": _safe("pivot snapOri", lambda: cmds.manipPivot(query=True, snapOri=True)),
        "resetMode": _safe("pivot resetMode", lambda: cmds.manipPivot(query=True, resetMode=True)),
        "bakeOrientationAutomatically": _safe(
            "pivot bakeOri", lambda: cmds.manipPivot(query=True, bakeOri=True)
        ),
    }


def _palette() -> dict[str, Any]:
    indexed = []
    for index in range(32):
        value = _safe("colorIndex {}".format(index), lambda index=index: cmds.colorIndex(index, query=True))
        indexed.append({"index": index, "rgb": _json_value(value)})
    rgb_names = (
        "background",
        "backgroundTop",
        "backgroundBottom",
        "active",
        "lead",
        "hilite",
        "selection",
        "activeComponent",
        "activeAffected",
        "object",
        "template",
    )
    return {
        "colorIndex": indexed,
        "namedRGB": {name: _query_rgb(name) for name in rgb_names},
        # `-list` is intentionally kept as raw evidence too. Some Maya builds print the list instead
        # of returning it; that difference is useful and the measured pixels do not depend on it.
        "displayRGBColorListReturn": _json_value(
            _safe("displayRGBColor list", lambda: cmds.displayRGBColor(list=True))
        ),
        "displayColorListReturn": _json_value(
            _safe("displayColor list", lambda: cmds.displayColor(list=True))
        ),
    }


def _color_management() -> dict[str, Any]:
    flags = (
        "cmEnabled",
        "configFileEnabled",
        "configFilePath",
        "displayName",
        "viewName",
        "outputTransformName",
        "renderingSpaceName",
    )
    return {
        flag: _json_value(
            _safe(
                "colorManagementPrefs " + flag,
                lambda flag=flag: cmds.colorManagementPrefs(query=True, **{flag: True}),
            )
        )
        for flag in flags
    }


def _panel_state(panel: str) -> dict[str, Any]:
    flags = (
        "grid",
        "headsUpDisplay",
        "manipulators",
        "selectionHiliting",
        "displayAppearance",
        "displayLights",
        "rendererName",
        "wireframeOnShaded",
    )
    result = {
        flag: _json_value(
            _safe(
                "modelEditor " + flag,
                lambda flag=flag: cmds.modelEditor(panel, query=True, **{flag: True}),
            )
        )
        for flag in flags
    }
    result["isolateSelect"] = _json_value(
        _safe("isolateSelect state", lambda: cmds.isolateSelect(panel, query=True, state=True))
    )
    return result


def _set_panel_for_capture(panel: str) -> None:
    for flag, value in (
        ("grid", False),
        ("headsUpDisplay", False),
        ("selectionHiliting", False),
        ("manipulators", True),
    ):
        _safe(
            "set modelEditor " + flag,
            lambda flag=flag, value=value: cmds.modelEditor(panel, edit=True, **{flag: value}),
        )


def _restore_panel(panel: str, state: dict[str, Any]) -> None:
    for flag in ("grid", "headsUpDisplay", "selectionHiliting", "manipulators"):
        value = state.get(flag)
        if isinstance(value, (bool, int)):
            _safe(
                "restore modelEditor " + flag,
                lambda flag=flag, value=value: cmds.modelEditor(panel, edit=True, **{flag: value}),
            )


def _isolate_for_capture(panel: str, subject: str) -> dict[str, Any]:
    """Show only the empty subject without changing the scene's objects or display flags."""
    was_enabled = _safe(
        "isolateSelect state", lambda: cmds.isolateSelect(panel, query=True, state=True)
    ) is True
    set_name = None
    members: list[str] = []
    if was_enabled:
        queried = _safe(
            "isolateSelect set", lambda: cmds.isolateSelect(panel, query=True, viewObjects=True)
        )
        if isinstance(queried, str) and queried:
            set_name = queried
            values = _safe("isolateSelect members", lambda: cmds.sets(set_name, query=True) or [])
            members = list(values) if isinstance(values, list) else []
            cmds.sets(clear=set_name)
            cmds.sets(subject, add=set_name)
            return {"enabled": True, "set": set_name, "members": members}

    cmds.isolateSelect(panel, state=True)
    cmds.select(subject, replace=True)
    cmds.isolateSelect(panel, addSelected=True)
    set_name = _safe(
        "capture isolateSelect set", lambda: cmds.isolateSelect(panel, query=True, viewObjects=True)
    )
    return {"enabled": False, "set": set_name if isinstance(set_name, str) else None, "members": []}


def _restore_isolate(panel: str, state: dict[str, Any]) -> None:
    if state.get("enabled"):
        set_name = state.get("set")
        if isinstance(set_name, str) and cmds.objExists(set_name):
            cmds.sets(clear=set_name)
            members = [member for member in state.get("members", []) if cmds.objExists(member)]
            if members:
                cmds.sets(members, add=set_name)
        return
    _safe("disable capture isolateSelect", lambda: cmds.isolateSelect(panel, state=False))


def _environment(panel: str, widget: Any) -> dict[str, Any]:
    QtCore, _, _, _ = _qt()
    return {
        "mayaVersion": _safe("Maya version", lambda: cmds.about(version=True)),
        "mayaApiVersion": _safe("Maya API version", lambda: cmds.about(apiVersion=True)),
        "mayaOperatingSystem": _safe("Maya OS", lambda: cmds.about(operatingSystem=True)),
        "mayaQtVersion": _safe("Maya Qt version", lambda: cmds.about(qtVersion=True)),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "qtRuntimeVersion": QtCore.qVersion(),
        "linearUnit": _safe("linear unit", lambda: cmds.currentUnit(query=True, linear=True)),
        "angleUnit": _safe("angle unit", lambda: cmds.currentUnit(query=True, angle=True)),
        "timeUnit": _safe("time unit", lambda: cmds.currentUnit(query=True, time=True)),
        "panel": panel,
        "panelState": _panel_state(panel),
        "viewportLogicalSize": [widget.width(), widget.height()],
        "widgetDevicePixelRatio": float(widget.devicePixelRatioF()),
        "colorManagement": _color_management(),
        "manipOptions": _query_manip_options(),
        "contexts": {tool: _query_context(tool) for tool in _TOOLS},
        "pivot": _query_pivot(),
        "palette": _palette(),
    }


def _configure_camera(camera: str, shape: str, view_name: str) -> None:
    if view_name == "perspective":
        cmds.setAttr(shape + ".orthographic", False)
        cmds.setAttr(shape + ".focalLength", 50.0)
        cmds.viewPlace(camera, eye=(8.0, 6.0, 10.0), lookAt=(0.0, 0.0, 0.0), animate=False)
    else:
        transforms = {
            "front": ((0.0, 0.0, 10.0), (0.0, 0.0, 0.0)),
            "right": ((10.0, 0.0, 0.0), (0.0, 90.0, 0.0)),
            "top": ((0.0, 10.0, 0.0), (-90.0, 0.0, 0.0)),
        }
        translation, rotation = transforms[view_name]
        cmds.setAttr(shape + ".orthographic", True)
        cmds.setAttr(shape + ".orthographicWidth", 8.0)
        cmds.setAttr(camera + ".translate", *translation, type="double3")
        cmds.setAttr(camera + ".rotate", *rotation, type="double3")


def _camera_state(panel: str, camera: str, shape: str) -> dict[str, Any]:
    import maya.OpenMaya as om  # noqa: N813

    view = _view(panel)
    model_view = om.MMatrix()
    projection = om.MMatrix()
    # This capture uses Maya API 1.0 for compatibility with the existing worldToView code. Its
    # matrix accessors fill an output MMatrix instead of returning one (API 2.0 does the latter).
    view.modelViewMatrix(model_view)
    view.projectionMatrix(projection)
    return {
        "camera": camera,
        "worldMatrix": _json_value(cmds.getAttr(camera + ".worldMatrix[0]")),
        "orthographic": bool(cmds.getAttr(shape + ".orthographic")),
        "orthographicWidth": float(cmds.getAttr(shape + ".orthographicWidth")),
        "focalLength": float(cmds.getAttr(shape + ".focalLength")),
        "nearClipPlane": float(cmds.getAttr(shape + ".nearClipPlane")),
        "farClipPlane": float(cmds.getAttr(shape + ".farClipPlane")),
        "modelViewMatrix": _matrix_values(model_view),
        "projectionMatrix": _matrix_values(projection),
    }


def _edit_pivot_active() -> bool:
    for tool in _TOOLS:
        value = _safe(
            tool + " edit pivot mode",
            lambda tool=tool: _TOOLS[tool][1](
                _context_name(tool), query=True, editPivotMode=True
            ),
        )
        if value is True:
            return True
    return False


def _leave_edit_pivot() -> None:
    if _edit_pivot_active():
        _safe("leave edit pivot", lambda: mel.eval("ctxEditMode"))
        _settle(0.03)


def _reset_subject_state(subject: str) -> None:
    _leave_edit_pivot()
    for channel in ("translateX", "translateY", "translateZ", "rotateX", "rotateY", "rotateZ",
                    "scaleX", "scaleY", "scaleZ"):
        _safe(
            "unlock " + channel,
            lambda channel=channel: cmds.setAttr(subject + "." + channel, lock=False),
        )
    _safe("reset custom pivot", lambda: cmds.manipPivot(reset=True, pinPivot=False))
    cmds.select(subject, replace=True)


def _apply_case(case: dict[str, Any], subject: str, camera: str, shape: str,
                initial_scale: float) -> dict[str, Any]:
    _reset_subject_state(subject)
    factor = float(case.get("manipScale", 1.0))
    cmds.manipOptions(scale=initial_scale * factor)
    _configure_camera(camera, shape, case["view"])

    tool = case["tool"]
    tool_name, context_command, mode = _TOOLS[tool]
    cmds.setToolTo(tool_name)
    context = _context_name(tool)
    _safe(
        "set {} context mode".format(tool),
        lambda: context_command(context, edit=True, mode=mode),
    )

    if case.get("customPivot"):
        cmds.manipPivot(
            position=(0.0, 0.0, 0.0),
            orientation=(math.radians(23.0), math.radians(-41.0), math.radians(12.0)),
            pinPivot=bool(case.get("pinned")),
        )
    if case.get("editPivot"):
        mel.eval("ctxEditMode")
        cmds.manipPivot(pinPivot=bool(case.get("pinned")))
    elif case.get("pinned") and not case.get("customPivot"):
        cmds.manipPivot(pinPivot=True)

    handle = case.get("handle")
    requested_handle = int(handle) if handle is not None else 3
    # Always set a deterministic baseline: Maya remembers the last active handle per tool across
    # tool switches, so leaving an idle/size case untouched would make it inherit an earlier case.
    # `currentActiveHandle`, unlike the default `activeHandle`, addresses the displayed manipulator.
    _safe(
        "set {} current handle {}".format(tool, requested_handle),
        lambda: context_command(
            context, edit=True, currentActiveHandle=requested_handle
        ),
    )
    locked = case.get("lockedChannel")
    if locked:
        cmds.setAttr(subject + "." + locked, lock=True)

    _settle()
    return {
        "requested": dict(case),
        "actualContext": _query_context(tool),
        "pivot": _query_pivot(),
    }


def _artifact_paths(output: Path, case_name: str) -> dict[str, Path]:
    stem = "{}_{}".format(output.name, case_name)
    return {
        "dark": output.parent / (stem + "_dark.png"),
        "middle": output.parent / (stem + "_middle.png"),
        "light": output.parent / (stem + "_light.png"),
        "rgba": output.parent / (stem + "_rgba.png"),
    }


def _capture_case(output: Path, case: dict[str, Any], panel: str, widget: Any,
                  subject: str, camera: str, camera_shape: str,
                  initial_scale: float) -> dict[str, Any]:
    record: dict[str, Any] = {"name": case["name"]}
    paths = _artifact_paths(output, case["name"])
    try:
        record["state"] = _apply_case(case, subject, camera, camera_shape, initial_scale)
        record["camera"] = _camera_state(panel, camera, camera_shape)

        dark, screen = _capture_flat_background(
            panel, widget, (0.0, 0.0, 0.0), "dark"
        )
        if not dark.save(str(paths["dark"]), "PNG"):
            raise RuntimeError("не удалось записать {}".format(paths["dark"]))

        middle, middle_screen = _capture_flat_background(
            panel, widget, (0.5, 0.5, 0.5), "middle"
        )
        if screen["cropSize"] != middle_screen["cropSize"]:
            raise RuntimeError("dark/middle crop changed size")
        if not middle.save(str(paths["middle"]), "PNG"):
            raise RuntimeError("не удалось записать {}".format(paths["middle"]))

        light, light_screen = _capture_flat_background(
            panel, widget, (1.0, 1.0, 1.0), "light"
        )
        if screen["cropSize"] != light_screen["cropSize"]:
            raise RuntimeError("dark/light crop changed size")
        if not light.save(str(paths["light"]), "PNG"):
            raise RuntimeError("не удалось записать {}".format(paths["light"]))

        rgba, metrics = _reconstruct_rgba(dark, middle, light, screen["pivotInCrop"])
        if not rgba.save(str(paths["rgba"]), "PNG"):
            raise RuntimeError("не удалось записать {}".format(paths["rgba"]))
        record["screen"] = screen
        record["pixelMetrics"] = metrics
        record["artifacts"] = {name: path.name for name, path in paths.items()}
        warnings = []
        if metrics["visiblePixels"] < 50:
            warnings.append("манипулятор почти или полностью отсутствует в crop")
        highlighted_axis = {
            "x": "xRed", "y": "yGreen", "z": "zBlue"
        }.get(case.get("handleName"))
        for axis in ("xRed", "yGreen", "zBlue"):
            if axis == highlighted_axis:
                continue
            if metrics["colorClasses"].get(axis, {}).get("pixels", 0) == 0:
                warnings.append("не найден цветовой класс {}".format(axis))
        if warnings:
            record["warnings"] = warnings
    except Exception as error:  # A failed view must not cost all the other reference views.
        record["error"] = "{}: {}".format(type(error).__name__, error)
    return record


def _restore_pivot(state: dict[str, Any]) -> None:
    _safe("restore pivot reset", lambda: cmds.manipPivot(reset=True))
    kwargs: dict[str, Any] = {}
    if state.get("positionValid") and isinstance(state.get("position"), list):
        kwargs["position"] = state["position"]
    if state.get("orientationValid") and isinstance(state.get("orientation"), list):
        kwargs["orientation"] = state["orientation"]
    for source, target, expected in (
        ("pinned", "pinPivot", (bool,)),
        ("snapPosition", "snapPos", (bool,)),
        ("snapOrientation", "snapOri", (bool,)),
        ("resetMode", "resetMode", (int,)),
        ("bakeOrientationAutomatically", "bakeOri", (bool,)),
    ):
        value = state.get(source)
        if isinstance(value, expected):
            kwargs[target] = value
    if kwargs:
        _safe("restore custom pivot", lambda: cmds.manipPivot(**kwargs))


def _restore_contexts(states: dict[str, Any]) -> None:
    for tool, state in states.items():
        if not isinstance(state, dict):
            continue
        _tool_name, command, _default = _TOOLS[tool]
        context = state.get("name")
        if not isinstance(context, str):
            continue
        for flag in ("mode", "activeHandle", "currentActiveHandle"):
            value = state.get(flag)
            if isinstance(value, int):
                _safe(
                    "restore {} {}".format(tool, flag),
                    lambda flag=flag, value=value: command(
                        context, edit=True, **{flag: value}
                    ),
                )


def _write(output: Path, result: dict[str, Any]) -> dict[str, Any]:
    output.parent.mkdir(parents=True, exist_ok=True)
    json_path = output.with_suffix(".json")
    log_path = output.with_suffix(".log")
    json_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    lines = [
        "Maya {} pivot visual reference".format(result["environment"].get("mayaVersion", "?")),
        "schema {} | {} captures | {} failed".format(
            result["schemaVersion"], len(result["captures"]), len(result.get("failed", []))
        ),
        "RGBA prefers Maya's native framebuffer alpha.",
        "Three backgrounds validate blending and provide the fallback solve when needed.",
        "",
    ]
    for capture in result["captures"]:
        if capture.get("error"):
            lines.append("FAIL {} | {}".format(capture["name"], capture["error"]))
            continue
        metrics = capture["pixelMetrics"]
        colors = metrics.get("colorClasses", {})
        transfer = metrics.get("compositingTransferTest", {}).get("selected", "?")
        lines.append(
            "PASS {} | pixels={} alpha(p10/p50/p90/max)={}/{}/{}/{} "
            "x/y/z={}/{}/{} alphaSource={} transfer={} bounds={}".format(
                capture["name"],
                metrics["visiblePixels"],
                metrics["alpha"]["p10"],
                metrics["alpha"]["p50"],
                metrics["alpha"]["p90"],
                metrics["alpha"]["max"],
                colors.get("xRed", {}).get("pixels", 0),
                colors.get("yGreen", {}).get("pixels", 0),
                colors.get("zBlue", {}).get("pixels", 0),
                metrics.get("alphaSource", "?"),
                transfer,
                metrics.get("boundsFromPivot"),
            )
        )
        for warning in capture.get("warnings", []):
            lines.append("  WARN " + warning)
    if result.get("restoreErrors"):
        lines.append("")
        lines.append("RESTORE WARNINGS")
        lines.extend("  " + value for value in result["restoreErrors"])
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "json": str(json_path),
        "log": str(log_path),
        "captures": len(result["captures"]),
        "failed": list(result.get("failed", [])),
    }


def run(output: str | Path = _DEFAULT_OUTPUT,
        case_names: Sequence[str] | None = None) -> dict[str, Any]:
    """Capture every case and return the paths/counts shown by the Maya window."""
    refresh_modules()
    output = Path(output)
    if output.suffix.lower() in {".json", ".log", ".png"}:
        output = output.with_suffix("")
    output.parent.mkdir(parents=True, exist_ok=True)

    panel, widget = _viewport_widget()
    environment = _environment(panel, widget)
    old_selection = cmds.ls(selection=True, long=True) or []
    old_tool = _safe("current tool", lambda: cmds.currentCtx())
    old_camera = _safe("panel camera", lambda: cmds.modelPanel(panel, query=True, camera=True))
    old_panel = _panel_state(panel)
    old_background = {name: _query_rgb(name) for name in (
        "background", "backgroundTop", "backgroundBottom"
    )}
    old_pivot = _query_pivot()
    old_contexts = {tool: _query_context(tool) for tool in _TOOLS}
    initial_scale_value = environment["manipOptions"].get("scale")
    initial_scale = float(initial_scale_value) if isinstance(initial_scale_value, (int, float)) else 1.0
    QtCore, QtGui, _, _ = _qt()
    old_cursor = QtGui.QCursor.pos()

    result: dict[str, Any] = {
        "schemaVersion": schema.SCHEMA_VERSION,
        "capturedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "method": {
            "name": "native framebuffer RGBA with three-background validation and fallback",
            "equation": "composite = alpha * foreground + (1 - alpha) * background",
            "alphaPriority": ["nativeFramebuffer", "threeBackgroundSolve"],
            "backgrounds": {
                "dark": [0.0, 0.0, 0.0],
                "middle": [0.5, 0.5, 0.5],
                "light": [1.0, 1.0, 1.0],
            },
            "colorSpace": "display-referred viewport framebuffer bytes",
            "cropRadiusLogicalPixels": _CROP_RADIUS_LOGICAL_PIXELS,
        },
        "environment": environment,
        "captures": [],
    }
    cases = schema.case_specs()
    if case_names is not None:
        requested = set(case_names)
        unknown = sorted(requested - {case["name"] for case in cases})
        if unknown:
            raise ValueError("unknown pivot visual cases: " + ", ".join(unknown))
        cases = [case for case in cases if case["name"] in requested]
        result["requestedCases"] = list(case_names)
    subject = None
    camera = None
    isolate_state = None
    restore_errors = []
    try:
        subject = cmds.createNode("transform", name="__clarityPivotVisualSubject#")
        camera, camera_shape = cmds.camera(name="__clarityPivotVisualCamera#")
        cmds.modelPanel(panel, edit=True, camera=camera)
        _set_panel_for_capture(panel)
        cmds.select(subject, replace=True)
        isolate_state = _isolate_for_capture(panel, subject)
        # Keep the cursor away from every handle so the default cases are genuinely idle. Handle
        # cases use the context's explicit currentActiveHandle and do not rely on desktop position.
        corner = widget.mapToGlobal(QtCore.QPoint(4, 4))
        QtGui.QCursor.setPos(corner)
        _settle()

        for case in cases:
            print("pivot visual: {}".format(case["name"]))
            record = _capture_case(
                output, case, panel, widget, subject, camera, camera_shape, initial_scale
            )
            result["captures"].append(record)
    finally:
        try:
            _leave_edit_pivot()
        except Exception as error:
            restore_errors.append("edit pivot: {}".format(error))
        for name, value in old_background.items():
            try:
                if isinstance(value, list) and len(value) >= 3:
                    cmds.displayRGBColor(name, *value[:4])
            except Exception as error:
                restore_errors.append("{} color: {}".format(name, error))
        try:
            cmds.manipOptions(scale=initial_scale)
        except Exception as error:
            restore_errors.append("manip scale: {}".format(error))
        try:
            if isinstance(old_camera, str) and old_camera:
                cmds.modelPanel(panel, edit=True, camera=old_camera)
        except Exception as error:
            restore_errors.append("panel camera: {}".format(error))
        try:
            if isolate_state is not None:
                _restore_isolate(panel, isolate_state)
        except Exception as error:
            restore_errors.append("isolate select: {}".format(error))
        _restore_panel(panel, old_panel)
        try:
            deletable = [node for node in (subject, camera) if node and cmds.objExists(node)]
            if deletable:
                cmds.delete(deletable)
        except Exception as error:
            restore_errors.append("temporary nodes: {}".format(error))
        try:
            if old_selection:
                existing = [node for node in old_selection if cmds.objExists(node)]
                cmds.select(existing, replace=True) if existing else cmds.select(clear=True)
            else:
                cmds.select(clear=True)
        except Exception as error:
            restore_errors.append("selection: {}".format(error))
        _restore_contexts(old_contexts)
        try:
            if isinstance(old_tool, str) and old_tool:
                cmds.setToolTo(old_tool)
        except Exception as error:
            restore_errors.append("tool: {}".format(error))
        _restore_pivot(old_pivot)
        try:
            QtGui.QCursor.setPos(old_cursor)
        except Exception as error:
            restore_errors.append("cursor: {}".format(error))
        _settle(0.03)

    result["failed"] = [
        capture["name"] for capture in result["captures"] if capture.get("error")
    ]
    if restore_errors:
        result["restoreErrors"] = restore_errors
    return _write(output, result)


if __name__ == "__main__":
    run()
