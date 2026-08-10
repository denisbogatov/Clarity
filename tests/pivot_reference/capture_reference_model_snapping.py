# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Build Maya models and record the result of real snapped manipulator drags.

Unlike ``capture_reference_snapping.py``, which records only the activation state machine, this
capture creates a subject cube plus point, curve and mesh-center targets. Native mouse events drag
the selected model in the viewport, edit its pivot against another model, and Shift-drag snapped
duplicates. Every case records transforms, target geometry, numeric distance to the expected
target, Maya's command echo and before/drag/after screenshots.

The run replaces the current scene. Save work before pressing the window's
``Записать снаппинг на моделях`` button.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Callable

import capture_reference_autopilot as autopilot
import capture_reference_commands as commands
import capture_reference_pivot as reference
import capture_reference_snapping as activation
import debug_reference_pivot as debug
from reference_backend import cmds, mel


def _safe(description: str, function: Callable[[], Any]) -> Any:
    return reference._safe(description, function)


def _vector(value: Any) -> list[float]:
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        return [float(item) for item in value[:3]]
    return [0.0, 0.0, 0.0]


def _distance(a: list[float], b: list[float]) -> float:
    return math.sqrt(sum((a[index] - b[index]) ** 2 for index in range(3)))


def _dot(a: list[float], b: list[float]) -> float:
    return sum(a[index] * b[index] for index in range(3))


def _normalized(value: list[float]) -> list[float]:
    length = math.sqrt(_dot(value, value))
    if length <= 1.0e-12:
        return [0.0, 0.0, -1.0]
    return [item / length for item in value]


def _box_extents(bounds: list[float]) -> list[float]:
    return [
        abs(float(bounds[3]) - float(bounds[0])),
        abs(float(bounds[4]) - float(bounds[1])),
        abs(float(bounds[5]) - float(bounds[2])),
    ]


def _segment_distance(point: list[float], start: list[float], end: list[float]) -> float:
    direction = [end[index] - start[index] for index in range(3)]
    length_squared = sum(value * value for value in direction)
    if length_squared <= 1.0e-12:
        return _distance(point, start)
    factor = sum(
        (point[index] - start[index]) * direction[index] for index in range(3)
    ) / length_squared
    factor = max(0.0, min(1.0, factor))
    closest = [start[index] + direction[index] * factor for index in range(3)]
    return _distance(point, closest)


def _curve_distance(point: list[float], curve: str) -> float:
    shape = (cmds.listRelatives(curve, shapes=True, fullPath=True) or [curve])[0]
    node = cmds.createNode("nearestPointOnCurve", name="snapNearestPointOnCurve")
    try:
        cmds.connectAttr(shape + ".worldSpace[0]", node + ".inputCurve", force=True)
        cmds.setAttr(node + ".inPosition", *point, type="double3")
        closest = _vector(cmds.getAttr(node + ".position")[0])
        return _distance(point, closest)
    finally:
        cmds.delete(node)


def _bounds_contains(point: list[float], bounds: list[float], tolerance: float = 1.0e-4) -> bool:
    return all(
        float(bounds[index]) - tolerance
        <= point[index]
        <= float(bounds[index + 3]) + tolerance
        for index in range(3)
    )


def _translation(node: str) -> list[float]:
    return _vector(cmds.xform(node, query=True, worldSpace=True, translation=True))


def _pivot(node: str) -> list[float]:
    return _vector(cmds.xform(node, query=True, worldSpace=True, rotatePivot=True))


def _vertices(node: str) -> list[list[float]]:
    count = int(cmds.polyEvaluate(node, vertex=True))
    return [
        _vector(
            cmds.xform(
                "{}.vtx[{}]".format(node, index),
                query=True,
                worldSpace=True,
                translation=True,
            )
        )
        for index in range(count)
    ]


def _local_vertices(node: str) -> list[list[float]]:
    count = int(cmds.polyEvaluate(node, vertex=True))
    return [
        _vector(
            cmds.xform(
                "{}.vtx[{}]".format(node, index),
                query=True,
                objectSpace=True,
                translation=True,
            )
        )
        for index in range(count)
    ]


def _shape_uuids(node: str) -> list[str]:
    shapes = cmds.listRelatives(node, shapes=True, fullPath=True) or []
    result: list[str] = []
    for shape in shapes:
        uuids = cmds.ls(shape, uuid=True) or []
        result.extend(str(value) for value in uuids)
    return sorted(result)


def _attribute_vector(node: str, attribute: str) -> list[float]:
    value = _safe(attribute, lambda: cmds.getAttr(node + "." + attribute))
    if isinstance(value, (list, tuple)) and value:
        return _vector(value[0])
    return _vector(value)


def _subject_nodes(scene: dict[str, Any]) -> list[str]:
    """The original and any Shift-drag duplicates, excluding their shape nodes."""
    nodes = cmds.ls(scene["subject"] + "*", type="transform", long=True) or []
    return sorted(str(node) for node in nodes)


def _subject_objects(scene: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "node": node,
            "translationWorld": _translation(node),
            "pivotWorld": _pivot(node),
            "rotate": _attribute_vector(node, "rotate"),
            "scale": _attribute_vector(node, "scale"),
            "vertices": _vertices(node),
            "shapeUuids": _shape_uuids(node),
            "worldBoundingBox": reference._json_value(cmds.exactWorldBoundingBox(node)),
        }
        for node in _subject_nodes(scene)
    ]


def _subject_state(scene: dict[str, Any]) -> dict[str, Any]:
    node = scene["subject"]
    manip_orientation = _safe(
        "manipPivot orientation",
        lambda: cmds.manipPivot(query=True, orientation=True),
    )
    state = {
        "translate": reference._json_value(cmds.getAttr(node + ".translate")[0]),
        "rotate": reference._json_value(cmds.getAttr(node + ".rotate")[0]),
        "scale": reference._json_value(cmds.getAttr(node + ".scale")[0]),
        "translationWorld": _translation(node),
        "pivotWorld": _pivot(node),
        "worldMatrix": reference._json_value(cmds.getAttr(node + ".worldMatrix[0]")),
        "worldBoundingBox": reference._json_value(cmds.exactWorldBoundingBox(node)),
        "firstVertexWorld": _vertices(node)[0],
        "rotatePivot": _attribute_vector(node, "rotatePivot"),
        "scalePivot": _attribute_vector(node, "scalePivot"),
        "rotatePivotTranslate": _attribute_vector(node, "rotatePivotTranslate"),
        "rotateAxis": _attribute_vector(node, "rotateAxis"),
        "manipPivotOrientation": reference._json_value(manip_orientation),
        "parent": reference._json_value(cmds.listRelatives(node, parent=True, fullPath=True) or []),
        "subjectObjects": _subject_objects(scene),
        "selection": reference._json_value(cmds.ls(selection=True, long=True) or []),
        "snap": activation._state(),
    }
    companion = scene.get("companion")
    if companion and cmds.objExists(companion):
        state["companion"] = {
            "translationWorld": _translation(companion),
            "pivotWorld": _pivot(companion),
            "vertices": _vertices(companion),
            "worldBoundingBox": reference._json_value(cmds.exactWorldBoundingBox(companion)),
        }
    return state


def _target_state(scene: dict[str, Any]) -> dict[str, Any]:
    curve_points = [
        _vector(cmds.pointPosition("{}.cv[{}]".format(scene["curve"], index), world=True))
        for index in range(2)
    ]
    panel, _widget = autopilot._viewport_widget()
    camera = cmds.modelPanel(panel, query=True, camera=True)
    if cmds.nodeType(camera) == "camera":
        parents = cmds.listRelatives(camera, parent=True, fullPath=True) or []
        if parents:
            camera = parents[0]
    view_direction = [0.0, 0.0, -1.0]
    matrix = cmds.xform(camera, query=True, worldSpace=True, matrix=True)
    if isinstance(matrix, (list, tuple)) and len(matrix) >= 11:
        view_direction = _normalized(
            [-float(matrix[8]), -float(matrix[9]), -float(matrix[10])]
        )
    return {
        "pointModel": {
            "node": scene["point_target"],
            "center": _translation(scene["point_target"]),
            "vertices": _vertices(scene["point_target"]),
        },
        "centerModel": {
            "node": scene["center_target"],
            "center": _translation(scene["center_target"]),
            "vertices": _vertices(scene["center_target"]),
        },
        "curve": {"node": scene["curve"], "endpoints": curve_points},
        "curvedCurve": {"node": scene["curved_curve"]},
        "closedCurve": {"node": scene["closed_curve"]},
        "pivotTarget": {
            "node": scene["pivot_target"],
            "pivot": _pivot(scene["pivot_target"]),
        },
        "orientationTarget": {
            "node": scene["orientation_target"],
            "rotate": _attribute_vector(scene["orientation_target"], "rotate"),
        },
        "asymmetricTarget": {
            "node": scene["asymmetric_target"],
            "center": _translation(scene["asymmetric_target"]),
            "bounds": reference._json_value(cmds.exactWorldBoundingBox(scene["asymmetric_target"])),
        },
        "ambiguityTargets": [
            {"node": node, "pivot": _pivot(node)} for node in scene["ambiguity_targets"]
        ],
        "grid": {
            "spacing": _safe("grid spacing", lambda: cmds.grid(query=True, spacing=True)),
            "divisions": _safe("grid divisions", lambda: cmds.grid(query=True, divisions=True)),
        },
        "view": {"camera": camera, "direction": view_direction},
    }


def _create_scene() -> dict[str, Any]:
    cmds.file(new=True, force=True)
    _safe("reset manipPivot", lambda: cmds.manipPivot(reset=True, pinPivot=False))

    subject, _subject_history = cmds.polyCube(
        name="snapSubject", width=1.5, height=1.5, depth=1.5
    )
    subject_shape = cmds.listRelatives(subject, shapes=True, fullPath=True)[0]
    point_target, _ = cmds.polyCube(
        name="snapPointTarget", width=2.0, height=2.0, depth=2.0
    )
    center_target, _ = cmds.polyCube(
        name="snapCenterTarget", width=2.4, height=2.4, depth=2.4
    )
    curve = cmds.curve(
        name="snapCurveTarget",
        degree=1,
        point=[(-2.0, 0.0, -3.0), (4.0, 0.0, -3.0)],
    )
    curved_curve = cmds.curve(
        name="snapCurvedTarget",
        degree=3,
        point=[(-3.0, 2.5, -3.0), (-1.0, 4.0, -1.5), (2.0, 3.5, -2.0), (4.0, 2.0, -4.0)],
    )
    closed_curve = cmds.circle(
        name="snapClosedCurveTarget", normal=(0.0, 1.0, 0.0), radius=2.0
    )[0]
    cmds.setAttr(closed_curve + ".translate", 0.0, 2.0, -2.0, type="double3")
    pivot_target, _ = cmds.polyCube(
        name="snapPivotTarget", width=1.8, height=1.8, depth=1.8
    )
    orientation_target, _ = cmds.polyCube(
        name="snapOrientationTarget", width=2.0, height=0.5, depth=2.0
    )
    asymmetric_target, _ = cmds.polyCube(
        name="snapAsymmetricTarget", width=2.0, height=2.0, depth=2.0
    )
    surface_target, _ = cmds.polyPlane(
        name="snapLiveSurface", width=4.0, height=4.0, subdivisionsX=1, subdivisionsY=1
    )
    companion, _ = cmds.polyCube(
        name="snapCompanion", width=1.0, height=1.0, depth=1.0
    )
    ambiguity_a = cmds.spaceLocator(name="snapAmbiguousA")[0]
    ambiguity_b = cmds.spaceLocator(name="snapAmbiguousB")[0]
    subject_parent = cmds.group(empty=True, name="snapHierarchyParent")
    cmds.setAttr(subject + ".translate", -4.25, 0.0, 0.0, type="double3")
    cmds.setAttr(point_target + ".translate", 3.0, 0.0, 0.0, type="double3")
    cmds.setAttr(center_target + ".translate", 3.0, 0.0, 3.0, type="double3")
    cmds.setAttr(pivot_target + ".translate", 0.0, 3.0, 2.5, type="double3")
    cmds.setAttr(pivot_target + ".rotatePivot", 0.55, 0.35, -0.25, type="double3")
    cmds.setAttr(pivot_target + ".scalePivot", 0.55, 0.35, -0.25, type="double3")
    _safe(
        "show target pivot",
        lambda: cmds.setAttr(pivot_target + ".displayRotatePivot", True),
    )
    cmds.setAttr(orientation_target + ".translate", 0.0, 3.0, -0.5, type="double3")
    cmds.setAttr(orientation_target + ".rotate", 25.0, 35.0, 10.0, type="double3")
    cmds.setAttr(asymmetric_target + ".translate", -1.5, 1.0, 4.0, type="double3")
    cmds.xform(asymmetric_target + ".vtx[6]", relative=True, objectSpace=True, translation=(2.5, 1.0, -0.5))
    cmds.setAttr(surface_target + ".translate", 0.0, -3.0, 2.0, type="double3")
    cmds.setAttr(companion + ".translate", -4.25, 0.0, 2.5, type="double3")
    cmds.setAttr(ambiguity_a + ".translate", 0.9, 1.7, 1.0, type="double3")
    cmds.setAttr(ambiguity_b + ".translate", 1.1, 1.7, 1.0, type="double3")

    optional_targets = [
        curved_curve,
        closed_curve,
        pivot_target,
        orientation_target,
        asymmetric_target,
        surface_target,
        companion,
        ambiguity_a,
        ambiguity_b,
    ]
    for node in optional_targets:
        cmds.setAttr(node + ".visibility", False)

    scene = {
        "subject": subject,
        "subject_shape": subject_shape,
        "point_target": point_target,
        "center_target": center_target,
        "curve": curve,
        "curved_curve": curved_curve,
        "closed_curve": closed_curve,
        "pivot_target": pivot_target,
        "orientation_target": orientation_target,
        "asymmetric_target": asymmetric_target,
        "surface_target": surface_target,
        "companion": companion,
        "ambiguity_targets": [ambiguity_a, ambiguity_b],
        "subject_parent": subject_parent,
        "optional_targets": optional_targets,
        "initial_translate": [-4.25, 0.0, 0.0],
        "initial_vertices": _local_vertices(subject),
        "initial_grid_spacing": cmds.grid(query=True, spacing=True),
        "initial_grid_divisions": cmds.grid(query=True, divisions=True),
    }
    autopilot._STATE.clear()
    autopilot._STATE.update(
        {"node": subject, "shape": subject_shape, "panel": None, "output": ""}
    )
    autopilot._focus_viewport()
    cmds.select([subject, point_target, center_target, curve], replace=True)
    cmds.viewFit(animate=False, fitFactor=0.78)
    autopilot._settle(0.4)
    cmds.select(subject, replace=True)
    cmds.setToolTo("Move")
    autopilot._settle(0.2)
    return scene


def _reset_subject(scene: dict[str, Any], tool: str = "move") -> None:
    node = scene["subject"]
    _safe("clear live surface", lambda: cmds.makeLive(none=True))
    _safe("object selection mode", lambda: cmds.selectMode(object=True))
    cmds.grid(
        spacing=scene["initial_grid_spacing"],
        divisions=scene["initial_grid_divisions"],
    )
    duplicates = [
        candidate
        for candidate in _subject_nodes(scene)
        if candidate.split("|")[-1] != node
    ]
    if duplicates:
        cmds.delete(duplicates)
    if cmds.listRelatives(node, parent=True):
        cmds.parent(node, world=True)
    parent = scene["subject_parent"]
    cmds.setAttr(parent + ".translate", 0.0, 0.0, 0.0, type="double3")
    cmds.setAttr(parent + ".rotate", 0.0, 0.0, 0.0, type="double3")
    cmds.setAttr(parent + ".scale", 1.0, 1.0, 1.0, type="double3")
    for index, position in enumerate(scene["initial_vertices"]):
        cmds.xform(
            "{}.vtx[{}]".format(node, index),
            objectSpace=True,
            translation=position,
        )
    cmds.setAttr(node + ".translate", *scene["initial_translate"], type="double3")
    cmds.setAttr(node + ".rotate", 0.0, 0.0, 0.0, type="double3")
    cmds.setAttr(node + ".scale", 1.0, 1.0, 1.0, type="double3")
    for attribute in (
        "rotatePivot",
        "scalePivot",
        "rotatePivotTranslate",
        "scalePivotTranslate",
    ):
        cmds.setAttr(node + "." + attribute, 0.0, 0.0, 0.0, type="double3")
    companion = scene["companion"]
    cmds.setAttr(companion + ".translate", -4.25, 0.0, 2.5, type="double3")
    cmds.setAttr(companion + ".rotate", 0.0, 0.0, 0.0, type="double3")
    cmds.setAttr(companion + ".scale", 1.0, 1.0, 1.0, type="double3")
    for optional in scene["optional_targets"]:
        cmds.setAttr(optional + ".visibility", False)
    for base_target in (scene["point_target"], scene["center_target"], scene["curve"]):
        cmds.setAttr(base_target + ".visibility", True)
    panel, _widget = autopilot._viewport_widget()
    camera = cmds.modelPanel(panel, query=True, camera=True)
    if cmds.nodeType(camera) == "camera":
        camera_shape = camera
    else:
        shapes = cmds.listRelatives(camera, shapes=True, type="camera", fullPath=True) or []
        camera_shape = shapes[0] if shapes else None
    if camera_shape:
        cmds.setAttr(camera_shape + ".orthographic", False)
    _safe("reset manipPivot", lambda: cmds.manipPivot(reset=True, pinPivot=False))
    for flag in activation._PERSISTENT_MODES:
        _safe("clear " + flag, lambda flag=flag: cmds.snapMode(**{flag: False}))
    for key in activation._CONTEXT_FLAGS:
        activation._set_context_flag(key, "snap", False)
        activation._set_context_flag(key, "snapRelative", False)
    activation._set_context_flag("move", "mode", 2)
    activation._set_context_flag("move", "snapComponentsRelative", True)
    activation._set_context_flag("move", "snapPivotPos", True)
    activation._set_context_flag("move", "snapPivotOri", False)
    _safe("clear undo", lambda: cmds.flushUndo())
    cmds.select(node, replace=True)
    cmds.setToolTo(activation._TOOL_NAMES[tool])
    autopilot._settle(0.15)
    commands.drain()


def _pixel(world: list[float], description: str) -> tuple[int, int]:
    result = autopilot._world_to_desktop(world)
    if result is None:
        raise RuntimeError(description + " находится вне viewport")
    return result


def _subject_pixel(scene: dict[str, Any]) -> tuple[int, int]:
    return _pixel(_pivot(scene["subject"]), "пивот snapSubject")


def _point_target(scene: dict[str, Any]) -> tuple[list[float], tuple[int, int]]:
    start = _subject_pixel(scene)
    candidates = []
    for world in _vertices(scene["point_target"]):
        pixel = autopilot._world_to_desktop(world)
        if pixel is None:
            continue
        distance = (pixel[0] - start[0]) ** 2 + (pixel[1] - start[1]) ** 2
        candidates.append((distance, world, pixel))
    if not candidates:
        raise RuntimeError("у snapPointTarget нет видимой вершины")
    _, world, pixel = max(candidates, key=lambda item: item[0])
    return world, pixel


def _subject_vertex_target(scene: dict[str, Any]) -> tuple[list[float], tuple[int, int]]:
    pivot = _subject_pixel(scene)
    candidates = []
    for world in _vertices(scene["subject"]):
        pixel = autopilot._world_to_desktop(world)
        if pixel is None:
            continue
        distance = (pixel[0] - pivot[0]) ** 2 + (pixel[1] - pivot[1]) ** 2
        candidates.append((distance, world, pixel))
    if not candidates:
        raise RuntimeError("у snapSubject нет видимой вершины")
    _, world, pixel = max(candidates, key=lambda item: item[0])
    return world, pixel


def _world_axis_pixel(scene: dict[str, Any], axis: int) -> tuple[float, float]:
    origin = _pivot(scene["subject"])
    matrix = cmds.xform(scene["subject"], query=True, worldSpace=True, matrix=True)
    direction = _normalized(
        [float(matrix[axis * 4 + index]) for index in range(3)]
        if isinstance(matrix, (list, tuple)) and len(matrix) >= 12
        else [1.0 if index == axis else 0.0 for index in range(3)]
    )
    start = _pixel(origin, "пивот snapSubject")
    end = _pixel(
        [origin[index] + direction[index] for index in range(3)],
        "ось snapSubject",
    )
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.sqrt(dx * dx + dy * dy)
    return (dx / length, dy / length) if length > 1.0 else (1.0, 0.0)


def _handle_drag(scene: dict[str, Any], axes: tuple[int, ...]) -> None:
    pivot = _subject_pixel(scene)
    directions = [_world_axis_pixel(scene, axis) for axis in axes]
    if len(axes) == 1:
        offset = 80.0
        dx, dy = directions[0]
    else:
        offset = 32.0
        dx = sum(direction[0] for direction in directions)
        dy = sum(direction[1] for direction in directions)
        length = math.sqrt(dx * dx + dy * dy)
        if length > 1.0e-6:
            dx, dy = dx / length, dy / length
    start = (pivot[0] + int(dx * offset), pivot[1] + int(dy * offset))
    _world, target = _point_target(scene)
    autopilot.drag(start, target, hold="V")


def _handle_case(
    scene: dict[str, Any],
    axes: tuple[int, ...],
    move_mode: int = 2,
    rotate: tuple[float, float, float] | None = None,
) -> None:
    if rotate is not None:
        cmds.setAttr(scene["subject"] + ".rotate", *rotate, type="double3")
    _set_move_mode(move_mode)
    _handle_drag(scene, axes)


def _set_move_mode(mode: int) -> None:
    activation._set_context_flag("move", "mode", mode)


def _curve_target(scene: dict[str, Any]) -> tuple[list[float], tuple[int, int]]:
    endpoints = _target_state(scene)["curve"]["endpoints"]
    world = [(endpoints[0][index] + endpoints[1][index]) * 0.5 for index in range(3)]
    return world, _pixel(world, "середина snapCurveTarget")


def _drag_to(scene: dict[str, Any], target: tuple[int, int], hold: str | None = None) -> None:
    autopilot.drag(_subject_pixel(scene), target, hold=hold)


def _point_drag(scene: dict[str, Any]) -> None:
    _, target = _point_target(scene)
    _drag_to(scene, target, hold="V")


def _curve_drag(scene: dict[str, Any]) -> None:
    _, target = _curve_target(scene)
    autopilot.drag(_subject_pixel(scene), target, hold="C", button="middle")


def _grid_drag(scene: dict[str, Any]) -> None:
    target_world = [0.0, 0.0, 0.0]
    _drag_to(scene, _pixel(target_world, "точка сетки"), hold="X")


def _mesh_center_drag(scene: dict[str, Any]) -> None:
    cmds.snapMode(meshCenter=True)
    try:
        target = _pixel(_translation(scene["center_target"]), "центр snapCenterTarget")
        _drag_to(scene, target)
    finally:
        cmds.snapMode(meshCenter=False)


def _view_plane_drag(scene: dict[str, Any]) -> None:
    cmds.snapMode(viewPlane=True)
    try:
        target = _pixel([0.0, 0.0, 3.0], "цель во view plane")
        _drag_to(scene, target)
    finally:
        cmds.snapMode(viewPlane=False)


def _pivot_edit_drag(
    scene: dict[str, Any],
    target: tuple[int, int],
    hold: str | None = None,
    mesh_center: bool = False,
) -> None:
    mel.eval("ctxEditMode")
    if mesh_center:
        cmds.snapMode(meshCenter=True)
    try:
        autopilot.drag(_subject_pixel(scene), target, hold=hold)
    finally:
        if mesh_center:
            cmds.snapMode(meshCenter=False)
        mel.eval("ctxEditMode")


def _pivot_edit_point_drag(scene: dict[str, Any]) -> None:
    _, target = _point_target(scene)
    _pivot_edit_drag(scene, target, hold="V")


def _pivot_edit_mesh_center_drag(scene: dict[str, Any]) -> None:
    target = _pixel(_translation(scene["center_target"]), "центр snapCenterTarget")
    _pivot_edit_drag(scene, target, mesh_center=True)


def _place_pivot_on_subject_vertex(scene: dict[str, Any]) -> None:
    _world, target = _subject_vertex_target(scene)
    _pivot_edit_drag(scene, target, hold="V")


def _align_subject_vertex_to_object_point(scene: dict[str, Any]) -> None:
    _place_pivot_on_subject_vertex(scene)
    _world, target = _point_target(scene)
    autopilot.drag(_subject_pixel(scene), target, hold="V")


def _duplicate_point_drag(scene: dict[str, Any]) -> None:
    _, target = _point_target(scene)
    _duplicate_drag(scene, target, hold="SHIFT+V")


def _duplicate_vertex_to_object_point(scene: dict[str, Any]) -> None:
    _place_pivot_on_subject_vertex(scene)
    _world, target = _point_target(scene)
    _duplicate_drag(scene, target, hold="SHIFT+V")


def _duplicate_mesh_center_drag(scene: dict[str, Any]) -> None:
    target = _pixel(_translation(scene["center_target"]), "центр snapCenterTarget")
    _duplicate_drag(scene, target, hold="SHIFT", mesh_center=True)


def _duplicate_drag(
    scene: dict[str, Any],
    target: tuple[int, int],
    hold: str,
    mesh_center: bool = False,
    duplicate_type: int = 1,
) -> None:
    smart_duplicate = _safe(
        "query smart duplicate",
        lambda: cmds.manipOptions(query=True, enableSmartDuplicate=True),
    )
    smart_duplicate_type = _safe(
        "query smart duplicate type",
        lambda: cmds.manipOptions(query=True, smartDuplicateType=True),
    )
    _safe(
        "enable smart duplicate",
        lambda: cmds.manipOptions(
            enableSmartDuplicate=True, smartDuplicateType=duplicate_type
        ),
    )
    if mesh_center:
        cmds.snapMode(meshCenter=True)
    try:
        autopilot.drag(_subject_pixel(scene), target, hold=hold)
    finally:
        if mesh_center:
            cmds.snapMode(meshCenter=False)
        if isinstance(smart_duplicate, bool):
            _safe(
                "restore smart duplicate",
                lambda: cmds.manipOptions(enableSmartDuplicate=smart_duplicate),
            )
        if isinstance(smart_duplicate_type, int):
            _safe(
                "restore smart duplicate type",
                lambda: cmds.manipOptions(smartDuplicateType=smart_duplicate_type),
            )


def _target_pivot_drag(scene: dict[str, Any]) -> None:
    node = scene["pivot_target"]
    cmds.setAttr(node + ".visibility", True)
    target = _pixel(_pivot(node), "custom pivot snapPivotTarget")
    autopilot.drag(_subject_pixel(scene), target, hold="V")


def _pivot_orientation_snap(scene: dict[str, Any]) -> None:
    node = scene["orientation_target"]
    cmds.setAttr(node + ".visibility", True)
    activation._set_context_flag("move", "snapPivotPos", False)
    activation._set_context_flag("move", "snapPivotOri", True)
    mel.eval("ctxEditMode")
    try:
        autopilot.click(_pixel(_translation(node), "face snapOrientationTarget"))
    finally:
        mel.eval("ctxEditMode")
        activation._set_context_flag("move", "snapPivotPos", True)
        activation._set_context_flag("move", "snapPivotOri", False)


def _pivot_then_rotate(scene: dict[str, Any]) -> None:
    _place_pivot_on_subject_vertex(scene)
    cmds.setToolTo("Rotate")
    _step_rotate(scene)


def _pivot_then_scale(scene: dict[str, Any]) -> None:
    _place_pivot_on_subject_vertex(scene)
    cmds.setToolTo("Scale")
    _step_scale(scene)


def _pivot_persist_across_tools(scene: dict[str, Any]) -> None:
    _place_pivot_on_subject_vertex(scene)
    cmds.setToolTo("Rotate")
    autopilot._settle(0.08)
    cmds.setToolTo("Scale")
    autopilot._settle(0.08)
    cmds.setToolTo("Move")


def _pivot_reset_after_snap(scene: dict[str, Any]) -> None:
    _place_pivot_on_subject_vertex(scene)
    mel.eval("manipPivotReset true true")


def _parented_point_drag(scene: dict[str, Any], negative_scale: bool = False) -> None:
    parent = scene["subject_parent"]
    cmds.setAttr(parent + ".translate", 1.25, -0.75, 0.5, type="double3")
    cmds.setAttr(parent + ".rotate", 20.0, 35.0, -15.0, type="double3")
    scale = (-1.5, 0.8, 1.25) if negative_scale else (1.5, 0.8, 1.25)
    cmds.setAttr(parent + ".scale", *scale, type="double3")
    cmds.parent(scene["subject"], parent)
    cmds.select(scene["subject"], replace=True)
    _set_move_mode(0)
    _world, target = _point_target(scene)
    autopilot.drag(_subject_pixel(scene), target, hold="V")


def _duplicate_typed(scene: dict[str, Any], duplicate_type: int) -> None:
    _world, target = _point_target(scene)
    _duplicate_drag(scene, target, hold="SHIFT+V", duplicate_type=duplicate_type)


def _duplicate_modifier_reverse(scene: dict[str, Any]) -> None:
    _world, target = _point_target(scene)
    _duplicate_drag(scene, target, hold="V+SHIFT", duplicate_type=1)


def _duplicate_disabled(scene: dict[str, Any]) -> None:
    previous = _safe(
        "query smart duplicate",
        lambda: cmds.manipOptions(query=True, enableSmartDuplicate=True),
    )
    cmds.manipOptions(enableSmartDuplicate=False)
    try:
        _world, target = _point_target(scene)
        autopilot.drag(_subject_pixel(scene), target, hold="SHIFT+V")
    finally:
        if isinstance(previous, bool):
            cmds.manipOptions(enableSmartDuplicate=previous)


def _duplicate_rotate(scene: dict[str, Any]) -> None:
    cmds.setToolTo("Rotate")
    activation._set_context_flag("rotate", "snapValue", 15.0)
    activation._set_context_flag("rotate", "snap", True)
    pivot = _subject_pixel(scene)
    try:
        _smart_transform_drag(
            (pivot[0] + 90, pivot[1]),
            (pivot[0] + 64, pivot[1] - 64),
        )
    finally:
        activation._set_context_flag("rotate", "snap", False)


def _duplicate_scale(scene: dict[str, Any]) -> None:
    cmds.setToolTo("Scale")
    activation._set_context_flag("scale", "snapValue", 0.5)
    activation._set_context_flag("scale", "snap", True)
    pivot = _subject_pixel(scene)
    axis = autopilot._axis_pixel_direction()
    try:
        _smart_transform_drag(
            (pivot[0] + int(axis[0] * 80), pivot[1] + int(axis[1] * 80)),
            (pivot[0] + int(axis[0] * 145), pivot[1] + int(axis[1] * 145)),
        )
    finally:
        activation._set_context_flag("scale", "snap", False)


def _smart_transform_drag(start: tuple[int, int], end: tuple[int, int]) -> None:
    previous_enabled = cmds.manipOptions(query=True, enableSmartDuplicate=True)
    previous_type = cmds.manipOptions(query=True, smartDuplicateType=True)
    cmds.manipOptions(enableSmartDuplicate=True, smartDuplicateType=1)
    try:
        autopilot.drag(start, end, hold="SHIFT")
    finally:
        cmds.manipOptions(
            enableSmartDuplicate=previous_enabled,
            smartDuplicateType=previous_type,
        )


def _curved_curve_drag(scene: dict[str, Any]) -> None:
    node = scene["curved_curve"]
    cmds.setAttr(node + ".visibility", True)
    target_world = _vector(cmds.pointOnCurve(node, parameter=0.5, position=True))
    autopilot.drag(
        _subject_pixel(scene),
        _pixel(target_world, "snapCurvedTarget parameter 0.5"),
        hold="C",
        button="middle",
    )


def _closed_curve_drag(scene: dict[str, Any]) -> None:
    node = scene["closed_curve"]
    cmds.setAttr(node + ".visibility", True)
    target_world = _vector(cmds.pointOnCurve(node, parameter=1.25, position=True))
    autopilot.drag(
        _subject_pixel(scene),
        _pixel(target_world, "snapClosedCurveTarget"),
        hold="C",
        button="middle",
    )


def _curve_cv_point_drag(scene: dict[str, Any]) -> None:
    node = scene["curved_curve"]
    cmds.setAttr(node + ".visibility", True)
    target_world = _vector(cmds.pointPosition(node + ".cv[0]", world=True))
    autopilot.drag(_subject_pixel(scene), _pixel(target_world, "curve CV"), hold="V")


def _custom_grid_drag(scene: dict[str, Any]) -> None:
    cmds.grid(spacing=2.5, divisions=5)
    target = [2.5, 0.0, 2.5]
    autopilot.drag(_subject_pixel(scene), _pixel(target, "custom grid point"), hold="X")


def _frozen_transform_point_drag(scene: dict[str, Any]) -> None:
    cmds.makeIdentity(scene["subject"], apply=True, translate=True, rotate=True, scale=True)
    cmds.select(scene["subject"], replace=True)
    _point_drag(scene)


def _live_surface_drag(scene: dict[str, Any]) -> None:
    node = scene["surface_target"]
    cmds.setAttr(node + ".visibility", True)
    cmds.makeLive(node)
    try:
        target = _translation(node)
        autopilot.drag(_subject_pixel(scene), _pixel(target, "snapLiveSurface"))
    finally:
        cmds.makeLive(none=True)


def _asymmetric_center_drag(scene: dict[str, Any]) -> None:
    node = scene["asymmetric_target"]
    cmds.setAttr(node + ".visibility", True)
    cmds.snapMode(meshCenter=True)
    try:
        autopilot.drag(
            _subject_pixel(scene),
            _pixel(_translation(node), "snapAsymmetricTarget"),
        )
    finally:
        cmds.snapMode(meshCenter=False)


def _multi_object_drag(scene: dict[str, Any]) -> None:
    companion = scene["companion"]
    cmds.setAttr(companion + ".visibility", True)
    cmds.select([companion, scene["subject"]], replace=True)
    subject_bounds = cmds.exactWorldBoundingBox(scene["subject"])
    companion_bounds = cmds.exactWorldBoundingBox(companion)
    start_world = [
        (
            min(subject_bounds[index], companion_bounds[index])
            + max(subject_bounds[index + 3], companion_bounds[index + 3])
        )
        * 0.5
        for index in range(3)
    ]
    _world, target = _point_target(scene)
    autopilot.drag(_pixel(start_world, "multi-selection pivot"), target, hold="V")


def _component_snap(scene: dict[str, Any], relative: bool) -> None:
    node = scene["subject"]
    cmds.select([node + ".vtx[0]", node + ".vtx[1]"], replace=True)
    cmds.selectMode(component=True)
    cmds.setToolTo("Move")
    activation._set_context_flag("move", "snapComponentsRelative", relative)
    points = _vertices(node)[:2]
    start_world = [(points[0][index] + points[1][index]) * 0.5 for index in range(3)]
    _world, target = _point_target(scene)
    autopilot.drag(_pixel(start_world, "component selection pivot"), target, hold="V")


def _orthographic_view_plane_drag(scene: dict[str, Any]) -> None:
    panel, _widget = autopilot._viewport_widget()
    camera = cmds.modelPanel(panel, query=True, camera=True)
    if cmds.nodeType(camera) != "camera":
        shapes = cmds.listRelatives(camera, shapes=True, type="camera", fullPath=True) or []
        camera = shapes[0]
    cmds.setAttr(camera + ".orthographic", True)
    cmds.viewFit(animate=False, fitFactor=0.78)
    autopilot._settle(0.15)
    _view_plane_drag(scene)


def _ambiguous_point_drag(scene: dict[str, Any]) -> None:
    for node in scene["ambiguity_targets"]:
        cmds.setAttr(node + ".visibility", True)
    targets = [_pivot(node) for node in scene["ambiguity_targets"]]
    midpoint = [(targets[0][index] + targets[1][index]) * 0.5 for index in range(3)]
    autopilot.drag(_subject_pixel(scene), _pixel(midpoint, "ambiguous point midpoint"), hold="V")


def _cancel_move(scene: dict[str, Any]) -> None:
    _world, target = _point_target(scene)
    autopilot.drag_cancel(_subject_pixel(scene), target, hold="V")


def _cancel_duplicate(scene: dict[str, Any]) -> None:
    previous = cmds.manipOptions(query=True, enableSmartDuplicate=True)
    cmds.manipOptions(enableSmartDuplicate=True)
    try:
        _world, target = _point_target(scene)
        autopilot.drag_cancel(_subject_pixel(scene), target, hold="SHIFT+V")
    finally:
        cmds.manipOptions(enableSmartDuplicate=previous)


def _move_then_undo(scene: dict[str, Any]) -> None:
    _point_drag(scene)
    cmds.undo()


def _move_then_undo_redo(scene: dict[str, Any]) -> None:
    _point_drag(scene)
    cmds.undo()
    cmds.redo()


def _duplicate_chain(scene: dict[str, Any]) -> None:
    _duplicate_typed(scene, 1)
    selected = cmds.ls(selection=True, type="transform", long=True) or []
    if not selected:
        raise RuntimeError("первая Shift-копия не стала активной")
    previous_enabled = cmds.manipOptions(query=True, enableSmartDuplicate=True)
    previous_type = cmds.manipOptions(query=True, smartDuplicateType=True)
    cmds.manipOptions(enableSmartDuplicate=True, smartDuplicateType=1)
    try:
        autopilot.drag(
            _pixel(_pivot(selected[0]), "pivot первой Shift-копии"),
            _pixel([0.0, 0.0, 0.0], "grid origin"),
            hold="SHIFT+X",
        )
    finally:
        cmds.manipOptions(
            enableSmartDuplicate=previous_enabled,
            smartDuplicateType=previous_type,
        )


def _duplicate_modifier_release_first(scene: dict[str, Any]) -> None:
    _world, target = _point_target(scene)
    previous_enabled = cmds.manipOptions(query=True, enableSmartDuplicate=True)
    previous_type = cmds.manipOptions(query=True, smartDuplicateType=True)
    cmds.manipOptions(enableSmartDuplicate=True, smartDuplicateType=1)
    try:
        autopilot.drag(
            _subject_pixel(scene),
            target,
            hold="SHIFT+V",
            release_hold_before_mouse=True,
        )
    finally:
        cmds.manipOptions(
            enableSmartDuplicate=previous_enabled,
            smartDuplicateType=previous_type,
        )


def _tool_change_during_snap(scene: dict[str, Any]) -> None:
    _world, target = _point_target(scene)
    autopilot.drag_tool_change(_subject_pixel(scene), target, "Rotate", hold="V")


def _step_move(scene: dict[str, Any], relative: bool) -> None:
    activation._set_context_flag("move", "snapValue", 1.0)
    activation._set_context_flag("move", "snapRelative", relative)
    activation._set_context_flag("move", "snap", True)
    try:
        pivot = _subject_pixel(scene)
        axis = autopilot._axis_pixel_direction()
        start = (pivot[0] + int(axis[0] * 80), pivot[1] + int(axis[1] * 80))
        end = (pivot[0] + int(axis[0] * 145), pivot[1] + int(axis[1] * 145))
        autopilot.drag(start, end)
    finally:
        activation._set_context_flag("move", "snap", False)
        activation._set_context_flag("move", "snapRelative", False)


def _step_rotate(scene: dict[str, Any]) -> None:
    activation._set_context_flag("rotate", "snapValue", 15.0)
    activation._set_context_flag("rotate", "snapRelative", False)
    activation._set_context_flag("rotate", "snap", True)
    try:
        pivot = _subject_pixel(scene)
        autopilot.drag((pivot[0] + 90, pivot[1]), (pivot[0] + 64, pivot[1] - 64))
    finally:
        activation._set_context_flag("rotate", "snap", False)


def _step_scale(scene: dict[str, Any]) -> None:
    activation._set_context_flag("scale", "snapValue", 0.5)
    activation._set_context_flag("scale", "snapRelative", False)
    activation._set_context_flag("scale", "snap", True)
    try:
        pivot = _subject_pixel(scene)
        axis = autopilot._axis_pixel_direction()
        start = (pivot[0] + int(axis[0] * 80), pivot[1] + int(axis[1] * 80))
        end = (pivot[0] + int(axis[0] * 145), pivot[1] + int(axis[1] * 145))
        autopilot.drag(start, end)
    finally:
        activation._set_context_flag("scale", "snap", False)


def _analysis(
    mode: str,
    scene: dict[str, Any],
    before: dict[str, Any],
    after: dict[str, Any],
) -> dict[str, Any]:
    pivot = after["pivotWorld"]
    moved = _distance(before["pivotWorld"], pivot)
    result: dict[str, Any] = {"pivotMoved": moved, "passed": False}
    targets = _target_state(scene)
    if mode.startswith("handle_"):
        suffix = mode.removeprefix("handle_")
        axes = tuple("xyz".index(axis) for axis in suffix if axis in "xyz")
        delta = [pivot[index] - before["pivotWorld"][index] for index in range(3)]
        if suffix == "object_x":
            matrix = before["worldMatrix"]
            direction = _normalized([float(matrix[index]) for index in range(3)])
            along = _dot(delta, direction)
            perpendicular = _distance(delta, [along * value for value in direction])
            result.update(
                {
                    "localAxisDirection": direction,
                    "distanceAlongAxis": along,
                    "perpendicularDistance": perpendicular,
                    "passed": abs(along) > 1.0e-4 and perpendicular <= 1.0e-3,
                }
            )
            return result
        active_residual = min(
            math.sqrt(sum((pivot[index] - point[index]) ** 2 for index in axes))
            for point in targets["pointModel"]["vertices"]
        )
        inactive = [index for index in range(3) if index not in axes]
        inactive_residual = max(
            (abs(delta[index]) for index in inactive), default=0.0
        )
        result.update(
            {
                "activeAxes": ["XYZ"[index] for index in axes],
                "activeTargetResidual": active_residual,
                "inactiveAxisResidual": inactive_residual,
                "passed": moved > 1.0e-4
                and active_residual <= 1.0e-4
                and inactive_residual <= 1.0e-4,
            }
        )
        return result
    if mode == "target_pivot":
        distance = _distance(pivot, targets["pivotTarget"]["pivot"])
        result.update({"distanceToTargetPivot": distance, "passed": distance <= 1.0e-4})
        return result
    if mode == "pivot_orientation":
        before_orientation = _vector(before["manipPivotOrientation"])
        after_orientation = _vector(after["manipPivotOrientation"])
        manip_delta = _distance(before_orientation, after_orientation)
        axis_delta = _distance(before["rotateAxis"], after["rotateAxis"])
        bounds_delta = max(
            abs(float(after["worldBoundingBox"][index]) - float(before["worldBoundingBox"][index]))
            for index in range(6)
        )
        result.update(
            {
                "manipOrientationDelta": manip_delta,
                "rotateAxisDelta": axis_delta,
                "geometryBoundsDelta": bounds_delta,
                "passed": max(manip_delta, axis_delta) > 1.0e-4 and bounds_delta <= 1.0e-4,
            }
        )
        return result
    if mode.startswith("pivot_post_"):
        vertex_at_pivot = min(_distance(pivot, point) for point in _vertices(scene["subject"]))
        if mode.endswith("rotate"):
            values = [float(value) for value in after["rotate"]]
            residual = max(abs(value / 15.0 - round(value / 15.0)) for value in values)
            changed = any(abs(value) > 1.0e-4 for value in values)
        else:
            before_extents = _box_extents(before["worldBoundingBox"])
            after_extents = _box_extents(after["worldBoundingBox"])
            ratios = [after_extents[i] / before_extents[i] for i in range(3)]
            changed_ratios = [value for value in ratios if abs(value - 1.0) > 1.0e-4]
            residual = max(
                (abs(value / 0.5 - round(value / 0.5)) for value in changed_ratios),
                default=1.0,
            )
            changed = bool(changed_ratios)
            result["geometryScaleRatios"] = ratios
        result.update(
            {
                "vertexDistanceToCustomPivot": vertex_at_pivot,
                "stepResidual": residual,
                "passed": changed and residual <= 1.0e-4 and vertex_at_pivot <= 1.0e-4,
            }
        )
        return result
    if mode == "pivot_persistence":
        vertex_distance = min(_distance(pivot, point) for point in _vertices(scene["subject"]))
        result.update(
            {
                "vertexDistanceToPivot": vertex_distance,
                "objectTranslationDelta": _distance(before["translationWorld"], after["translationWorld"]),
                "passed": vertex_distance <= 1.0e-4
                and _distance(before["translationWorld"], after["translationWorld"]) <= 1.0e-4,
            }
        )
        return result
    if mode == "pivot_reset":
        distance = _distance(pivot, after["translationWorld"])
        bounds_delta = max(
            abs(float(after["worldBoundingBox"][index]) - float(before["worldBoundingBox"][index]))
            for index in range(6)
        )
        result.update(
            {"distanceToObjectOrigin": distance, "geometryBoundsDelta": bounds_delta,
             "passed": distance <= 1.0e-4 and bounds_delta <= 1.0e-4}
        )
        return result
    if mode.startswith("hierarchy_"):
        distance = min(
            _distance(pivot, point) for point in targets["pointModel"]["vertices"]
        )
        result.update(
            {
                "parentAfter": after["parent"],
                "distanceToNearestPoint": distance,
                "passed": bool(after["parent"]) and distance <= 1.0e-4,
            }
        )
        return result
    if mode in {"curved_curve", "closed_curve"}:
        curve = scene["curved_curve"] if mode == "curved_curve" else scene["closed_curve"]
        distance = _curve_distance(pivot, curve)
        result.update({"distanceToNurbsCurve": distance, "passed": distance <= 1.0e-4})
        return result
    if mode == "curve_cv_point":
        target = _vector(cmds.pointPosition(scene["curved_curve"] + ".cv[0]", world=True))
        distance = _distance(pivot, target)
        result.update({"distanceToCurveCV": distance, "passed": distance <= 1.0e-4})
        return result
    if mode == "live_surface":
        surface_y = _translation(scene["surface_target"])[1]
        bounds = cmds.exactWorldBoundingBox(scene["surface_target"])
        result.update(
            {
                "distanceToSurfacePlane": abs(pivot[1] - surface_y),
                "insideSurfaceBounds": _bounds_contains(pivot, list(bounds), tolerance=0.05),
                "passed": abs(pivot[1] - surface_y) <= 1.0e-4
                and _bounds_contains(pivot, list(bounds), tolerance=0.05),
            }
        )
        return result
    if mode == "asymmetric_center":
        bounds = list(targets["asymmetricTarget"]["bounds"])
        inside = _bounds_contains(pivot, bounds)
        result.update(
            {
                "insideAsymmetricMeshBounds": inside,
                "distanceToTransformCenter": _distance(
                    pivot, targets["asymmetricTarget"]["center"]
                ),
                "passed": moved > 1.0e-4 and inside,
            }
        )
        return result
    if mode == "multi_object":
        before_offset = [
            before["companion"]["translationWorld"][index] - before["translationWorld"][index]
            for index in range(3)
        ]
        after_offset = [
            after["companion"]["translationWorld"][index] - after["translationWorld"][index]
            for index in range(3)
        ]
        spacing_delta = _distance(before_offset, after_offset)
        moved_companion = _distance(
            before["companion"]["translationWorld"], after["companion"]["translationWorld"]
        )
        bounds = [after["worldBoundingBox"], after["companion"]["worldBoundingBox"]]
        selection_center = [
            (
                min(float(item[index]) for item in bounds)
                + max(float(item[index + 3]) for item in bounds)
            )
            * 0.5
            for index in range(3)
        ]
        target_residual = min(
            _distance(selection_center, point) for point in targets["pointModel"]["vertices"]
        )
        result.update(
            {
                "relativeSpacingDelta": spacing_delta,
                "companionMoved": moved_companion,
                "selectionCenterDistanceToTarget": target_residual,
                "passed": moved > 1.0e-4
                and moved_companion > 1.0e-4
                and spacing_delta <= 1.0e-4
                and target_residual <= 1.0e-4,
            }
        )
        return result
    if mode.startswith("component_"):
        before_points = before["subjectObjects"][0]["vertices"][:2]
        after_points = after["subjectObjects"][0]["vertices"][:2]
        spacing_before = _distance(before_points[0], before_points[1])
        spacing_after = _distance(after_points[0], after_points[1])
        target_distance = max(
            min(_distance(point, target) for target in targets["pointModel"]["vertices"])
            for point in after_points
        )
        relative = mode.endswith("relative")
        passed = (
            abs(spacing_after - spacing_before) <= 1.0e-4
            if relative
            else spacing_after <= 1.0e-4 and target_distance <= 1.0e-4
        )
        result.update(
            {
                "spacingBefore": spacing_before,
                "spacingAfter": spacing_after,
                "maxDistanceToTargetPoint": target_distance,
                "passed": passed,
            }
        )
        return result
    if mode == "ambiguous_point":
        distances = [
            _distance(pivot, entry["pivot"]) for entry in targets["ambiguityTargets"]
        ]
        chosen = distances.index(min(distances))
        result.update(
            {"candidateDistances": distances, "chosenCandidate": chosen,
             "passed": min(distances) <= 1.0e-4}
        )
        return result
    if mode in {"cancel_move", "cancel_duplicate", "undo_move"}:
        bounds_delta = max(
            abs(float(after["worldBoundingBox"][index]) - float(before["worldBoundingBox"][index]))
            for index in range(6)
        )
        count_unchanged = len(after["subjectObjects"]) == len(before["subjectObjects"])
        snap_modes = after.get("snap", {}).get("snapMode", {})
        active_snap_modes = [
            key
            for key in activation._PERSISTENT_MODES
            if snap_modes.get(key) is True
        ]
        result.update(
            {
                "objectCountUnchanged": count_unchanged,
                "geometryBoundsDelta": bounds_delta,
                "activeSnapModesAfter": active_snap_modes,
                "passed": moved <= 1.0e-4
                and bounds_delta <= 1.0e-4
                and count_unchanged
                and not active_snap_modes,
            }
        )
        return result
    if mode == "redo_move":
        distance = min(_distance(pivot, point) for point in targets["pointModel"]["vertices"])
        result.update({"distanceAfterRedo": distance, "passed": distance <= 1.0e-4})
        return result
    if mode == "tool_change_cleanup":
        snap_modes = after.get("snap", {}).get("snapMode", {})
        active = [key for key in activation._PERSISTENT_MODES if snap_modes.get(key) is True]
        current_tool = _safe("current context", lambda: cmds.currentCtx())
        result.update(
            {
                "activeSnapModesAfter": active,
                "currentContextAfter": current_tool,
                "passed": not active and "Rotate" in str(current_tool),
            }
        )
        return result
    if mode in {"point", "frozen_point"}:
        distances = [_distance(pivot, point) for point in targets["pointModel"]["vertices"]]
        result.update(
            {"distanceToNearestPoint": min(distances), "passed": min(distances) <= 1.0e-4}
        )
    elif mode == "geometry_point":
        geometry_distance = min(
            _distance(subject_point, target_point)
            for subject_point in _vertices(scene["subject"])
            for target_point in targets["pointModel"]["vertices"]
        )
        pivot_distance = min(
            _distance(pivot, target_point)
            for target_point in targets["pointModel"]["vertices"]
        )
        result.update(
            {
                "geometryPointDistance": geometry_distance,
                "pivotDistanceToTargetPoint": pivot_distance,
                "passed": moved > 1.0e-4
                and geometry_distance <= 1.0e-4
                and pivot_distance <= 1.0e-4,
            }
        )
    elif mode == "curve":
        endpoints = targets["curve"]["endpoints"]
        distance = _segment_distance(pivot, endpoints[0], endpoints[1])
        result.update({"distanceToCurve": distance, "passed": distance <= 1.0e-4})
    elif mode in {"grid", "custom_grid"}:
        spacing = targets["grid"]["spacing"]
        spacing = float(spacing) if isinstance(spacing, (int, float)) and spacing else 1.0
        nearest = [round(pivot[0] / spacing) * spacing, 0.0, round(pivot[2] / spacing) * spacing]
        distance = _distance(pivot, nearest)
        result.update(
            {"nearestGridPoint": nearest, "distanceToGrid": distance, "passed": distance <= 1.0e-4}
        )
    elif mode == "mesh_center":
        distance = _distance(pivot, targets["centerModel"]["center"])
        result.update({"distanceToMeshCenter": distance, "passed": distance <= 1.0e-4})
    elif mode in {"view_plane", "view_plane_ortho"}:
        delta = [pivot[index] - before["pivotWorld"][index] for index in range(3)]
        depth_delta = _dot(delta, targets["view"]["direction"])
        result.update(
            {
                "cameraDirection": targets["view"]["direction"],
                "depthDelta": depth_delta,
                "passed": moved > 1.0e-4 and abs(depth_delta) <= 1.0e-3,
            }
        )
    elif mode.startswith("pivot_edit"):
        if mode.endswith("point"):
            distances = [_distance(pivot, point) for point in targets["pointModel"]["vertices"]]
            target_distance = min(distances)
            target_name = "distanceToNearestPoint"
        else:
            target_distance = _distance(pivot, targets["centerModel"]["center"])
            target_name = "distanceToMeshCenter"
        translation_delta = _distance(before["translationWorld"], after["translationWorld"])
        bounds_delta = max(
            abs(float(after["worldBoundingBox"][index]) - float(before["worldBoundingBox"][index]))
            for index in range(6)
        )
        result.update(
            {
                target_name: target_distance,
                "objectTranslationDelta": translation_delta,
                "geometryBoundsDelta": bounds_delta,
                "passed": target_distance <= 1.0e-4
                and translation_delta <= 1.0e-4
                and bounds_delta <= 1.0e-4,
            }
        )
    elif mode == "duplicate_chain":
        before_nodes = {item["node"] for item in before["subjectObjects"]}
        new_objects = [
            item for item in after["subjectObjects"] if item["node"] not in before_nodes
        ]
        selected = set(after["selection"])
        result.update(
            {
                "objectCountAfter": len(after["subjectObjects"]),
                "newObjects": [item["node"] for item in new_objects],
                "selectedAfter": sorted(selected),
                "passed": len(after["subjectObjects"]) == 3
                and len(new_objects) == 2
                and any(item["node"] in selected for item in new_objects),
            }
        )
    elif mode == "duplicate_disabled":
        distance = min(_distance(pivot, point) for point in targets["pointModel"]["vertices"])
        result.update(
            {
                "objectCountAfter": len(after["subjectObjects"]),
                "distanceToTarget": distance,
                "passed": len(after["subjectObjects"]) == 1 and distance <= 1.0e-4,
            }
        )
    elif mode in {"duplicate_rotate", "duplicate_scale"}:
        before_nodes = {item["node"] for item in before["subjectObjects"]}
        new_objects = [
            item for item in after["subjectObjects"] if item["node"] not in before_nodes
        ]
        changed = False
        residual = 1.0
        if len(new_objects) == 1 and mode == "duplicate_rotate":
            values = new_objects[0]["rotate"]
            changed = any(abs(value) > 1.0e-4 for value in values)
            residual = max(abs(value / 15.0 - round(value / 15.0)) for value in values)
        elif len(new_objects) == 1:
            values = new_objects[0]["scale"]
            changed = any(abs(value - 1.0) > 1.0e-4 for value in values)
            residual = max(abs(value / 0.5 - round(value / 0.5)) for value in values)
        result.update(
            {
                "newObjects": [item["node"] for item in new_objects],
                "stepResidual": residual,
                "passed": len(new_objects) == 1 and changed and residual <= 1.0e-4,
            }
        )
    elif mode.startswith("duplicate"):
        before_nodes = {item["node"] for item in before["subjectObjects"]}
        after_objects = after["subjectObjects"]
        new_objects = [item for item in after_objects if item["node"] not in before_nodes]
        originals = [
            item
            for item in after_objects
            if item["node"].split("|")[-1] == scene["subject"]
        ]
        before_originals = [
            item
            for item in before["subjectObjects"]
            if item["node"].split("|")[-1] == scene["subject"]
        ]
        original_translation_delta: float | None = (
            _distance(originals[0]["translationWorld"], scene["initial_translate"])
            if originals
            else None
        )
        original_bounds_delta: float | None = None
        if originals and before_originals:
            original_bounds_delta = max(
                abs(
                    float(originals[0]["worldBoundingBox"][index])
                    - float(before_originals[0]["worldBoundingBox"][index])
                )
                for index in range(6)
            )
        copy_distance: float | None = None
        copy_geometry_distance: float | None = None
        if len(new_objects) == 1:
            copy_pivot = new_objects[0]["pivotWorld"]
            if "point" in mode:
                copy_distance = min(
                    _distance(copy_pivot, point)
                    for point in targets["pointModel"]["vertices"]
                )
                copy_geometry_distance = min(
                    _distance(copy_point, target_point)
                    for copy_point in new_objects[0]["vertices"]
                    for target_point in targets["pointModel"]["vertices"]
                )
            else:
                copy_distance = _distance(copy_pivot, targets["centerModel"]["center"])
        geometry_required = "vertex" in mode
        shape_relation_ok = True
        shared_shapes: list[str] = []
        if len(new_objects) == 1 and originals:
            shared_shapes = sorted(
                set(new_objects[0]["shapeUuids"]) & set(originals[0]["shapeUuids"])
            )
            if "copy" in mode:
                shape_relation_ok = not shared_shapes
            elif "instance" in mode:
                shape_relation_ok = bool(shared_shapes)
        result.update(
            {
                "objectCountBefore": len(before["subjectObjects"]),
                "objectCountAfter": len(after_objects),
                "newObjects": [item["node"] for item in new_objects],
                "originalTranslationDelta": original_translation_delta,
                "originalBoundsDelta": original_bounds_delta,
                "copyDistanceToTarget": copy_distance,
                "copyGeometryPointDistance": copy_geometry_distance,
                "sharedShapeUuids": shared_shapes,
                "selectedAfter": after["selection"],
                "passed": len(before["subjectObjects"]) == 1
                and len(after_objects) == 2
                and len(new_objects) == 1
                and original_translation_delta is not None
                and original_translation_delta <= 1.0e-4
                and original_bounds_delta is not None
                and original_bounds_delta <= 1.0e-4
                and copy_distance is not None
                and copy_distance <= 1.0e-4
                and shape_relation_ok
                and (
                    not geometry_required
                    or (
                        copy_geometry_distance is not None
                        and copy_geometry_distance <= 1.0e-4
                    )
                ),
            }
        )
    elif mode.startswith("step_move"):
        values = after["translate"]
        base_x = scene["initial_translate"][0] if mode.endswith("relative") else 0.0
        stepped_x = float(values[0]) - base_x
        residual = abs(stepped_x - round(stepped_x))
        orthogonal = max(
            abs(float(values[index]) - scene["initial_translate"][index])
            for index in (1, 2)
        )
        result.update(
            {
                "axis": "X",
                "stepSize": 1.0,
                "stepResidual": residual,
                "orthogonalResidual": orthogonal,
                "passed": moved > 1.0e-4
                and residual <= 1.0e-4
                and orthogonal <= 1.0e-4,
            }
        )
    elif mode == "step_rotate":
        angles = [float(value) for value in after["rotate"]]
        residual = max(abs(value / 15.0 - round(value / 15.0)) for value in angles)
        result.update(
            {
                "stepDegrees": 15.0,
                "stepResidual": residual,
                "passed": any(abs(value) > 1.0e-4 for value in angles) and residual <= 1.0e-4,
            }
        )
    elif mode == "step_scale":
        before_extents = _box_extents(before["worldBoundingBox"])
        after_extents = _box_extents(after["worldBoundingBox"])
        ratios = [
            after_extents[index] / before_extents[index]
            if before_extents[index] > 1.0e-12
            else 1.0
            for index in range(3)
        ]
        changed = [index for index, value in enumerate(ratios) if abs(value - 1.0) > 1.0e-4]
        residual = max(
            (abs(ratios[index] / 0.5 - round(ratios[index] / 0.5)) for index in changed),
            default=0.0,
        )
        result.update(
            {
                "stepSize": 0.5,
                "boundingBoxBefore": before_extents,
                "boundingBoxAfter": after_extents,
                "geometryScaleRatios": ratios,
                "changedAxes": ["XYZ"[index] for index in changed],
                "stepResidual": residual,
                "transformScale": after["scale"],
                "passed": bool(changed) and residual <= 1.0e-4,
            }
        )
    return result


def _steps(scene: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "name": "object_pivot_to_object_point_snap",
            "mode": "point",
            "tool": "move",
            "perform": lambda: _point_drag(scene),
        },
        {
            "name": "object_vertex_to_object_vertex_snap",
            "mode": "geometry_point",
            "tool": "move",
            "perform": lambda: _align_subject_vertex_to_object_point(scene),
        },
        {
            "name": "axis_x_to_object_point_snap",
            "mode": "handle_x",
            "tool": "move",
            "perform": lambda: _handle_case(scene, (0,)),
        },
        {
            "name": "axis_y_to_object_point_snap",
            "mode": "handle_y",
            "tool": "move",
            "perform": lambda: _handle_case(scene, (1,)),
        },
        {
            "name": "axis_z_to_object_point_snap",
            "mode": "handle_z",
            "tool": "move",
            "perform": lambda: _handle_case(scene, (2,)),
        },
        {
            "name": "plane_xy_to_object_point_snap",
            "mode": "handle_xy",
            "tool": "move",
            "perform": lambda: _handle_case(scene, (0, 1)),
        },
        {
            "name": "plane_xz_to_object_point_snap",
            "mode": "handle_xz",
            "tool": "move",
            "perform": lambda: _handle_case(scene, (0, 2)),
        },
        {
            "name": "plane_yz_to_object_point_snap",
            "mode": "handle_yz",
            "tool": "move",
            "perform": lambda: _handle_case(scene, (1, 2)),
        },
        {
            "name": "object_space_x_axis_snap",
            "mode": "handle_object_x",
            "tool": "move",
            "perform": lambda: _handle_case(scene, (0,), move_mode=0, rotate=(20.0, 35.0, 10.0)),
        },
        {
            "name": "object_pivot_to_other_custom_pivot_snap",
            "mode": "target_pivot",
            "tool": "move",
            "perform": lambda: _target_pivot_drag(scene),
        },
        {"name": "model_curve_snap", "mode": "curve", "tool": "move", "perform": lambda: _curve_drag(scene)},
        {
            "name": "curved_nurbs_curve_snap",
            "mode": "curved_curve",
            "tool": "move",
            "perform": lambda: _curved_curve_drag(scene),
        },
        {
            "name": "closed_nurbs_curve_snap",
            "mode": "closed_curve",
            "tool": "move",
            "perform": lambda: _closed_curve_drag(scene),
        },
        {
            "name": "point_snap_to_curve_cv",
            "mode": "curve_cv_point",
            "tool": "move",
            "perform": lambda: _curve_cv_point_drag(scene),
        },
        {"name": "model_grid_snap", "mode": "grid", "tool": "move", "perform": lambda: _grid_drag(scene)},
        {
            "name": "custom_spacing_grid_snap",
            "mode": "custom_grid",
            "tool": "move",
            "perform": lambda: _custom_grid_drag(scene),
        },
        {
            "name": "object_to_object_mesh_center_snap",
            "mode": "mesh_center",
            "tool": "move",
            "perform": lambda: _mesh_center_drag(scene),
        },
        {
            "name": "model_view_plane_snap",
            "mode": "view_plane",
            "tool": "move",
            "perform": lambda: _view_plane_drag(scene),
        },
        {
            "name": "pivot_edit_to_object_point_snap",
            "mode": "pivot_edit_point",
            "tool": "move",
            "perform": lambda: _pivot_edit_point_drag(scene),
        },
        {
            "name": "pivot_edit_to_object_mesh_center_snap",
            "mode": "pivot_edit_mesh_center",
            "tool": "move",
            "perform": lambda: _pivot_edit_mesh_center_drag(scene),
        },
        {
            "name": "pivot_orientation_to_rotated_mesh",
            "mode": "pivot_orientation",
            "tool": "move",
            "perform": lambda: _pivot_orientation_snap(scene),
        },
        {
            "name": "custom_pivot_persists_across_tools",
            "mode": "pivot_persistence",
            "tool": "move",
            "perform": lambda: _pivot_persist_across_tools(scene),
        },
        {
            "name": "rotate_after_custom_pivot_snap",
            "mode": "pivot_post_rotate",
            "tool": "move",
            "perform": lambda: _pivot_then_rotate(scene),
        },
        {
            "name": "scale_after_custom_pivot_snap",
            "mode": "pivot_post_scale",
            "tool": "move",
            "perform": lambda: _pivot_then_scale(scene),
        },
        {
            "name": "reset_after_custom_pivot_snap",
            "mode": "pivot_reset",
            "tool": "move",
            "perform": lambda: _pivot_reset_after_snap(scene),
        },
        {
            "name": "parented_rotated_scaled_object_snap",
            "mode": "hierarchy_parent",
            "tool": "move",
            "perform": lambda: _parented_point_drag(scene),
        },
        {
            "name": "negative_scale_parent_object_snap",
            "mode": "hierarchy_negative",
            "tool": "move",
            "perform": lambda: _parented_point_drag(scene, negative_scale=True),
        },
        {
            "name": "shift_duplicate_to_object_point_snap",
            "mode": "duplicate_point",
            "tool": "move",
            "perform": lambda: _duplicate_point_drag(scene),
        },
        {
            "name": "shift_duplicate_vertex_to_object_vertex_snap",
            "mode": "duplicate_vertex_point",
            "tool": "move",
            "perform": lambda: _duplicate_vertex_to_object_point(scene),
        },
        {
            "name": "shift_duplicate_to_object_mesh_center_snap",
            "mode": "duplicate_mesh_center",
            "tool": "move",
            "perform": lambda: _duplicate_mesh_center_drag(scene),
        },
        {
            "name": "shift_duplicate_copy_point_snap",
            "mode": "duplicate_copy_point",
            "tool": "move",
            "perform": lambda: _duplicate_typed(scene, 1),
        },
        {
            "name": "shift_duplicate_instance_point_snap",
            "mode": "duplicate_instance_point",
            "tool": "move",
            "perform": lambda: _duplicate_typed(scene, 2),
        },
        {
            "name": "shift_duplicate_reverse_modifier_order",
            "mode": "duplicate_copy_point_reverse",
            "tool": "move",
            "perform": lambda: _duplicate_modifier_reverse(scene),
        },
        {
            "name": "shift_drag_with_smart_duplicate_disabled",
            "mode": "duplicate_disabled",
            "tool": "move",
            "perform": lambda: _duplicate_disabled(scene),
        },
        {
            "name": "shift_duplicate_with_rotate_step",
            "mode": "duplicate_rotate",
            "tool": "rotate",
            "perform": lambda: _duplicate_rotate(scene),
        },
        {
            "name": "shift_duplicate_with_scale_step",
            "mode": "duplicate_scale",
            "tool": "scale",
            "perform": lambda: _duplicate_scale(scene),
        },
        {
            "name": "sequential_shift_duplicate_chain",
            "mode": "duplicate_chain",
            "tool": "move",
            "perform": lambda: _duplicate_chain(scene),
        },
        {
            "name": "shift_duplicate_modifier_release_first",
            "mode": "duplicate_copy_point_release",
            "tool": "move",
            "perform": lambda: _duplicate_modifier_release_first(scene),
        },
        {
            "name": "live_surface_snap",
            "mode": "live_surface",
            "tool": "move",
            "perform": lambda: _live_surface_drag(scene),
        },
        {
            "name": "asymmetric_mesh_center_snap",
            "mode": "asymmetric_center",
            "tool": "move",
            "perform": lambda: _asymmetric_center_drag(scene),
        },
        {
            "name": "multi_object_spacing_point_snap",
            "mode": "multi_object",
            "tool": "move",
            "perform": lambda: _multi_object_drag(scene),
        },
        {
            "name": "component_point_snap_preserve_spacing",
            "mode": "component_relative",
            "tool": "move",
            "perform": lambda: _component_snap(scene, True),
        },
        {
            "name": "component_point_snap_collapse_spacing",
            "mode": "component_collapse",
            "tool": "move",
            "perform": lambda: _component_snap(scene, False),
        },
        {
            "name": "orthographic_view_plane_snap",
            "mode": "view_plane_ortho",
            "tool": "move",
            "perform": lambda: _orthographic_view_plane_drag(scene),
        },
        {
            "name": "ambiguous_point_target_selection",
            "mode": "ambiguous_point",
            "tool": "move",
            "perform": lambda: _ambiguous_point_drag(scene),
        },
        {
            "name": "cancel_point_snap_drag",
            "mode": "cancel_move",
            "tool": "move",
            "perform": lambda: _cancel_move(scene),
        },
        {
            "name": "cancel_shift_duplicate_snap_drag",
            "mode": "cancel_duplicate",
            "tool": "move",
            "perform": lambda: _cancel_duplicate(scene),
        },
        {
            "name": "undo_object_point_snap",
            "mode": "undo_move",
            "tool": "move",
            "perform": lambda: _move_then_undo(scene),
        },
        {
            "name": "redo_object_point_snap",
            "mode": "redo_move",
            "tool": "move",
            "perform": lambda: _move_then_undo_redo(scene),
        },
        {
            "name": "tool_change_during_point_snap_drag",
            "mode": "tool_change_cleanup",
            "tool": "move",
            "perform": lambda: _tool_change_during_snap(scene),
        },
        {
            "name": "frozen_transform_object_point_snap",
            "mode": "frozen_point",
            "tool": "move",
            "perform": lambda: _frozen_transform_point_drag(scene),
        },
        {
            "name": "model_step_move_absolute",
            "mode": "step_move_absolute",
            "tool": "move",
            "perform": lambda: _step_move(scene, False),
        },
        {
            "name": "model_step_move_relative",
            "mode": "step_move_relative",
            "tool": "move",
            "perform": lambda: _step_move(scene, True),
        },
        {"name": "model_step_rotate", "mode": "step_rotate", "tool": "rotate", "perform": lambda: _step_rotate(scene)},
        {"name": "model_step_scale", "mode": "step_scale", "tool": "scale", "perform": lambda: _step_scale(scene)},
    ]


def _log_text(result: dict[str, Any]) -> str:
    lines = [
        "Maya {} model snapping".format(result["mayaVersion"]),
        "native input: " + result["nativeInput"],
        "tests: {}".format(len(result["tests"])),
        "",
    ]
    for record in result["tests"]:
        lines.append(
            "{}: {}".format(
                record["name"], "PASS" if record["analysis"].get("passed") else "FAIL"
            )
        )
        if record.get("error"):
            lines.append("  ERROR: " + record["error"])
        for key, value in record["analysis"].items():
            lines.append("  {}: {}".format(key, value))
        lines.append("  before pivot: {}".format(record["before"]["pivotWorld"]))
        lines.append("  after pivot:  {}".format(record["after"]["pivotWorld"]))
        for command in record.get("commands") or []:
            lines.append("  cmd: " + command)
        lines.append("")
    return "\n".join(lines)


def run(output: Path | str, filter_noise: bool = True) -> dict[str, Any]:
    """Replace the scene, run fifty-five real model interactions, and write all artifacts."""
    native_input = autopilot.input_ready()
    original_snap_state = activation._state()
    original_grid = {
        "spacing": cmds.grid(query=True, spacing=True),
        "divisions": cmds.grid(query=True, divisions=True),
    }
    output = Path(output)
    if output.suffix:
        output = output.with_suffix("")
    output.parent.mkdir(parents=True, exist_ok=True)
    history = output.with_name(output.name + "_history").with_suffix(".mel")
    if commands.running():
        raise RuntimeError(
            "уже идёт другая запись команд Maya; сначала завершите её"
        )

    scene = _create_scene()
    autopilot._STATE["output"] = str(output)
    targets = _target_state(scene)
    commands.start(history, filter_noise=filter_noise)
    commands.drain()
    records: list[dict[str, Any]] = []
    try:
        for index, step in enumerate(_steps(scene), 1):
            _reset_subject(scene, step["tool"])
            autopilot._INPUT[:] = []
            autopilot._STATE.pop("last_drag", None)
            before = _subject_state(scene)
            before_shot = autopilot._screenshot(index, step["name"], "before")
            commands.drain()
            drag_shots: list[str] = []

            def capture_drag(tag: str, index: int = index, step: dict[str, Any] = step) -> None:
                suffix = tag if not drag_shots else "{}_{}".format(tag, len(drag_shots) + 1)
                shot = autopilot._screenshot(index, step["name"], suffix)
                if shot:
                    drag_shots.append(shot)

            autopilot._SHOT = capture_drag
            error = _safe(step["name"], step["perform"])
            autopilot._SHOT = None
            echoed = commands.read()
            filtered = commands.dropped()
            after = _subject_state(scene)
            after_shot = autopilot._screenshot(index, step["name"], "after")
            commands.drain()
            screenshots = {"before": before_shot, "after": after_shot}
            if drag_shots:
                screenshots["drag"] = drag_shots[0]
                screenshots["drags"] = drag_shots
            analysis = _safe(
                "analysis " + step["name"],
                lambda step=step, before=before, after=after: _analysis(
                    step["mode"], scene, before, after
                ),
            )
            if not isinstance(analysis, dict):
                analysis = {"error": "analysis returned {!r}".format(analysis)}
            if "error" in analysis:
                analysis["passed"] = False
            record: dict[str, Any] = {
                "name": step["name"],
                "mode": step["mode"],
                "tool": step["tool"],
                "before": before,
                "after": after,
                "changes": debug._difference(before, after),
                "analysis": analysis,
                "commands": echoed.splitlines() if echoed else [],
                "filteredCommandCount": filtered,
                "input": list(autopilot._INPUT),
                "screenshots": screenshots,
            }
            if isinstance(error, dict) and "error" in error:
                record["error"] = error["error"]
                record["analysis"]["passed"] = False
            records.append(record)
    finally:
        autopilot._SHOT = None
        commands.stop()
        activation._restore(original_snap_state)
        cmds.grid(
            spacing=original_grid["spacing"],
            divisions=original_grid["divisions"],
        )

    result = {
        "schema": 7,
        "mayaVersion": cmds.about(version=True),
        "apiVersion": cmds.about(apiVersion=True),
        "nativeInput": native_input,
        "scene": {key: value for key, value in scene.items() if key != "initial_translate"},
        "targets": targets,
        "tests": records,
    }
    json_path = output.with_suffix(".json")
    log_path = output.with_suffix(".log")
    json_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    log_path.write_text(_log_text(result), encoding="utf-8")
    passed = sum(bool(record["analysis"].get("passed")) for record in records)
    failed = [record["name"] for record in records if not record["analysis"].get("passed")]
    print("model snapping: {}/{} passed; wrote".format(passed, len(records)), json_path, log_path)
    return {
        "json": str(json_path),
        "log": str(log_path),
        "history": str(history),
        "tests": len(records),
        "passed": passed,
        "failed": failed,
    }
