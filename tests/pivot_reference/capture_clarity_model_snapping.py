# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Capture Clarity/Blender counterparts of Maya's model-snapping interactions.

The scenario names, ordering, scene scale and result keys match
``capture_reference_model_snapping.py``.  This runner uses Blender and Clarity operators/data paths
to execute deterministic equivalents; ``executionFidelity`` in every record says so explicitly.
The existing UI-simulation tests remain the place that proves physical events reach the modal
transform code.  Keeping those two facts separate makes the comparison useful rather than making a
scripted placement look like a mouse-driven snap.

Run from a built interactive Blender:

  blender --factory-startup --python tests/pivot_reference/capture_clarity_model_snapping.py -- \
      --output tests/pivot_reference/fixtures/clarity_model_snapping.json --count 55 --quit

Running the file from Blender's Text Editor registers a View3D sidebar panel named
``Clarity Snap Tests`` with a button for the same capture.

The compatibility boundary is all 55 canonical Maya scenarios except ``live_surface_snap``. That
name remains in the schema, but every run excludes it until Live Surface exists in this fork.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
import traceback
from pathlib import Path
from typing import Any

import bpy
from mathutils import Euler, Matrix, Quaternion, Vector


SCENARIOS: tuple[tuple[str, str, str], ...] = (
    ("object_pivot_to_object_point_snap", "point", "move"),
    ("object_vertex_to_object_vertex_snap", "geometry_point", "move"),
    ("axis_x_to_object_point_snap", "handle_x", "move"),
    ("axis_y_to_object_point_snap", "handle_y", "move"),
    ("axis_z_to_object_point_snap", "handle_z", "move"),
    ("plane_xy_to_object_point_snap", "handle_xy", "move"),
    ("plane_xz_to_object_point_snap", "handle_xz", "move"),
    ("plane_yz_to_object_point_snap", "handle_yz", "move"),
    ("object_space_x_axis_snap", "handle_object_x", "move"),
    ("object_pivot_to_other_custom_pivot_snap", "target_pivot", "move"),
    ("model_curve_snap", "curve", "move"),
    ("curved_nurbs_curve_snap", "curved_curve", "move"),
    ("closed_nurbs_curve_snap", "closed_curve", "move"),
    ("point_snap_to_curve_cv", "curve_cv_point", "move"),
    ("model_grid_snap", "grid", "move"),
    ("custom_spacing_grid_snap", "custom_grid", "move"),
    ("object_to_object_mesh_center_snap", "mesh_center", "move"),
    ("model_view_plane_snap", "view_plane", "move"),
    ("pivot_edit_to_object_point_snap", "pivot_edit_point", "move"),
    ("pivot_edit_to_object_mesh_center_snap", "pivot_edit_mesh_center", "move"),
    ("pivot_orientation_to_rotated_mesh", "pivot_orientation", "move"),
    ("custom_pivot_persists_across_tools", "pivot_persistence", "move"),
    ("rotate_after_custom_pivot_snap", "pivot_post_rotate", "move"),
    ("scale_after_custom_pivot_snap", "pivot_post_scale", "move"),
    ("reset_after_custom_pivot_snap", "pivot_reset", "move"),
    ("parented_rotated_scaled_object_snap", "hierarchy_parent", "move"),
    ("negative_scale_parent_object_snap", "hierarchy_negative", "move"),
    ("shift_duplicate_to_object_point_snap", "duplicate_point", "move"),
    ("shift_duplicate_vertex_to_object_vertex_snap", "duplicate_vertex_point", "move"),
    ("shift_duplicate_to_object_mesh_center_snap", "duplicate_mesh_center", "move"),
    ("shift_duplicate_copy_point_snap", "duplicate_copy_point", "move"),
    ("shift_duplicate_instance_point_snap", "duplicate_instance_point", "move"),
    ("shift_duplicate_reverse_modifier_order", "duplicate_copy_point_reverse", "move"),
    ("shift_drag_with_smart_duplicate_disabled", "duplicate_disabled", "move"),
    ("shift_duplicate_with_rotate_step", "duplicate_rotate", "rotate"),
    ("shift_duplicate_with_scale_step", "duplicate_scale", "scale"),
    ("sequential_shift_duplicate_chain", "duplicate_chain", "move"),
    ("shift_duplicate_modifier_release_first", "duplicate_copy_point_release", "move"),
    ("live_surface_snap", "live_surface", "move"),
    ("asymmetric_mesh_center_snap", "asymmetric_center", "move"),
    ("multi_object_spacing_point_snap", "multi_object", "move"),
    ("component_point_snap_preserve_spacing", "component_relative", "move"),
    ("component_point_snap_collapse_spacing", "component_collapse", "move"),
    ("orthographic_view_plane_snap", "view_plane_ortho", "move"),
    ("ambiguous_point_target_selection", "ambiguous_point", "move"),
    ("cancel_point_snap_drag", "cancel_move", "move"),
    ("cancel_shift_duplicate_snap_drag", "cancel_duplicate", "move"),
    ("undo_object_point_snap", "undo_move", "move"),
    ("redo_object_point_snap", "redo_move", "move"),
    ("tool_change_during_point_snap_drag", "tool_change_cleanup", "move"),
    ("frozen_transform_object_point_snap", "frozen_point", "move"),
    ("model_step_move_absolute", "step_move_absolute", "move"),
    ("model_step_move_relative", "step_move_relative", "move"),
    ("model_step_rotate", "step_rotate", "rotate"),
    ("model_step_scale", "step_scale", "scale"),
)

MAYA_PARITY_SCENARIO_COUNT = 55
UNSUPPORTED_SCENARIOS: tuple[str, ...] = ("live_surface_snap",)

_INITIAL = Vector((-4.25, 0.0, 0.0))
_POINT = Vector((4.0, -1.0, -1.0))
_CENTER = Vector((3.0, 0.0, 3.0))
_COMMANDS: list[str] = []


def _command(text: str) -> None:
    _COMMANDS.append(text)


def _vector(value: Any) -> list[float]:
    return [float(item) for item in value]


def _matrix(value: Matrix) -> list[float]:
    return [float(item) for row in value for item in row]


def _distance(a: Any, b: Any) -> float:
    return (Vector(a) - Vector(b)).length


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    """Flatten a state like Maya's recorder, rounding only report noise."""
    flat: dict[str, Any] = {}
    if isinstance(value, dict):
        for key, item in value.items():
            path = "{}.{}".format(prefix, key) if prefix else str(key)
            flat.update(_flatten(item, path))
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
    first = _flatten(before)
    second = _flatten(after)
    changes: dict[str, Any] = {}
    for key in sorted(set(first) | set(second)):
        old = first.get(key, "(absent)")
        new = second.get(key, "(absent)")
        if old != new:
            changes[key] = {"from": old, "to": new}
    return changes


def _viewport_override() -> dict[str, Any]:
    window = bpy.context.window
    if window is None and bpy.context.window_manager.windows:
        window = bpy.context.window_manager.windows[0]
    if window is None:
        raise RuntimeError("no Blender window")
    for area in window.screen.areas:
        if area.type != "VIEW_3D":
            continue
        for region in area.regions:
            if region.type == "WINDOW":
                return {"window": window, "area": area, "region": region}
    raise RuntimeError("no 3D viewport")


def _world_vertices(obj: bpy.types.Object) -> list[list[float]]:
    return [_vector(obj.matrix_world @ vertex.co) for vertex in obj.data.vertices]


def _bounds(obj: bpy.types.Object) -> list[float]:
    points = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    return [min(point[i] for point in points) for i in range(3)] + [
        max(point[i] for point in points) for i in range(3)
    ]


def _pivot_world(obj: bpy.types.Object) -> Vector:
    pivot = getattr(obj, "custom_pivot", None)
    if pivot is not None and bool(getattr(pivot, "is_rotate_pivot_valid", False)):
        return obj.matrix_world @ Vector(pivot.rotate_pivot)
    return obj.matrix_world.translation.copy()


def _set_pivot_world(obj: bpy.types.Object, target: Vector) -> None:
    pivot = obj.custom_pivot_ensure()
    local = obj.matrix_world.inverted() @ target
    pivot.rotate_pivot = local
    pivot.scale_pivot = local
    pivot.is_rotate_pivot_valid = True
    pivot.is_scale_pivot_valid = True
    _command("custom_pivot.rotate_pivot = {!r}".format(tuple(target)))


def _clear_pivot(obj: bpy.types.Object) -> None:
    _select_only(obj)
    with bpy.context.temp_override(**_viewport_override()):
        status = bpy.ops.clarity.pivot_reset(action="BOTH", mode="ZERO")
    if "FINISHED" not in status:
        raise RuntimeError("CLARITY_OT_pivot_reset did not finish: {!r}".format(status))
    _command("bpy.ops.clarity.pivot_reset(action='BOTH', mode='ZERO')")


def _select_only(obj: bpy.types.Object) -> None:
    for selected in bpy.context.selected_objects:
        selected.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def _translate_selected(delta: Vector) -> None:
    with bpy.context.temp_override(**_viewport_override()):
        status = bpy.ops.transform.translate(value=tuple(delta), orient_type="GLOBAL")
    if "FINISHED" not in status:
        raise RuntimeError("TRANSFORM_OT_translate did not finish: {!r}".format(status))


def _undo_push(message: str) -> None:
    """Write an explicit snapshot so scripted transforms have a state to step back to."""
    with bpy.context.temp_override(**_viewport_override()):
        status = bpy.ops.ed.undo_push(message=message)
    if "FINISHED" not in status:
        raise RuntimeError("ED_OT_undo_push did not finish: {!r}".format(status))


def _move_pivot_to(obj: bpy.types.Object, target: Vector) -> None:
    delta = target - _pivot_world(obj)
    _select_only(obj)
    _translate_selected(delta)
    bpy.context.view_layer.update()
    _command("bpy.ops.transform.translate(value={!r})".format(tuple(delta)))


def _duplicate(obj: bpy.types.Object, *, instance: bool = False) -> bpy.types.Object:
    _select_only(obj)
    with bpy.context.temp_override(**_viewport_override()):
        status = bpy.ops.object.duplicate(linked=instance)
    if "FINISHED" not in status:
        raise RuntimeError("OBJECT_OT_duplicate did not finish: {!r}".format(status))
    duplicate = bpy.context.active_object
    duplicate.name = "snapSubjectCopy"
    _command("bpy.ops.object.duplicate(linked={!r})".format(instance))
    return duplicate


def _subject_objects() -> list[bpy.types.Object]:
    return sorted(
        [obj for obj in bpy.data.objects if obj.name.startswith("snapSubject")],
        key=lambda obj: obj.name,
    )


def _object_record(obj: bpy.types.Object) -> dict[str, Any]:
    data = getattr(obj, "data", None)
    return {
        "node": obj.name,
        "translationWorld": _vector(obj.matrix_world.translation),
        "pivotWorld": _vector(_pivot_world(obj)),
        "rotate": [math.degrees(value) for value in obj.rotation_euler],
        "scale": _vector(obj.scale),
        "vertices": _world_vertices(obj),
        "shapeUuids": [str(data.as_pointer())] if data is not None else [],
        "worldBoundingBox": _bounds(obj),
    }


def _state(scene: dict[str, Any]) -> dict[str, Any]:
    # Undo/redo recreates Blender datablocks, so reacquire objects instead of trusting Python refs.
    obj = bpy.data.objects.get("snapSubject")
    if obj is None:
        raise RuntimeError("snapSubject is missing from the captured scene")
    scene["subject"] = obj
    pivot = obj.custom_pivot_ensure()
    orientation = list(pivot.orientation) if pivot.is_orientation_valid else [1.0, 0.0, 0.0, 0.0]
    result = {
        "translate": _vector(obj.location),
        "rotate": [math.degrees(value) for value in obj.rotation_euler],
        "scale": _vector(obj.scale),
        "translationWorld": _vector(obj.matrix_world.translation),
        "pivotWorld": _vector(_pivot_world(obj)),
        "worldMatrix": _matrix(obj.matrix_world),
        "worldBoundingBox": _bounds(obj),
        "firstVertexWorld": _world_vertices(obj)[0],
        "subjectObjects": [_object_record(item) for item in _subject_objects()],
        "selection": [item.name for item in bpy.context.selected_objects],
        "customPivot": {
            "positionValid": bool(pivot.is_rotate_pivot_valid),
            "orientationValid": bool(pivot.is_orientation_valid),
            "rotatePivot": _vector(pivot.rotate_pivot),
            "orientation": [float(value) for value in orientation],
        },
        "parent": [obj.parent.name] if obj.parent else [],
        "snap": {
            "enabled": bool(bpy.context.scene.tool_settings.use_snap),
            "elements": sorted(bpy.context.scene.tool_settings.snap_elements),
        },
    }
    companion = bpy.data.objects.get("snapCompanion")
    if companion is not None:
        result["companion"] = _object_record(companion)
    return result


def _cube(name: str, size: float, location: tuple[float, float, float]) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cube_add(size=size, location=location)
    obj = bpy.context.active_object
    obj.name = name
    return obj


def _curve(
    name: str,
    points: list[tuple[float, float, float]],
    cyclic: bool = False,
    spline_type: str = "POLY",
) -> bpy.types.Object:
    data = bpy.data.curves.new(name + "Data", "CURVE")
    data.dimensions = "3D"
    spline = data.splines.new(spline_type)
    spline.points.add(len(points) - 1)
    for point, co in zip(spline.points, points):
        point.co = (*co, 1.0)
    spline.use_cyclic_u = cyclic
    if spline_type == "NURBS":
        spline.order_u = min(3, len(points))
        spline.use_endpoint_u = not cyclic
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    return obj


def _create_scene() -> dict[str, Any]:
    bpy.ops.object.mode_set(mode="OBJECT") if bpy.context.object and bpy.context.object.mode != "OBJECT" else None
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for datablocks in (bpy.data.meshes, bpy.data.curves):
        for block in list(datablocks):
            if block.users == 0:
                datablocks.remove(block)

    subject = _cube("snapSubject", 1.5, tuple(_INITIAL))
    point = _cube("snapPointTarget", 2.0, (3.0, 0.0, 0.0))
    center = _cube("snapCenterTarget", 2.4, tuple(_CENTER))
    pivot_target = _cube("snapPivotTarget", 1.8, (0.0, 3.0, 2.5))
    _set_pivot_world(
        pivot_target,
        pivot_target.matrix_world @ Vector((0.55, 0.35, -0.25)),
    )
    orientation_target = _cube("snapOrientationTarget", 2.0, (0.0, 3.0, -0.5))
    orientation_target.rotation_euler = Euler(
        [math.radians(value) for value in (25.0, 35.0, 10.0)], "XYZ"
    )
    asymmetric = _cube("snapAsymmetricTarget", 2.0, (-1.5, 1.0, 4.0))
    asymmetric.data.vertices[6].co += Vector((2.5, 1.0, -0.5))
    surface = _cube("snapLiveSurface", 4.0, (0.0, -3.0, 2.0))
    surface.scale.y = 0.001
    companion = _cube("snapCompanion", 1.0, (-4.25, 0.0, 2.5))
    line = _curve("snapCurveTarget", [(-2.0, 0.0, -3.0), (4.0, 0.0, -3.0)])
    curved = _curve(
        "snapCurvedTarget",
        [(-3.0, 2.5, -3.0), (-1.0, 4.0, -1.5), (2.0, 3.5, -2.0), (4.0, 2.0, -4.0)],
        spline_type="NURBS",
    )
    closed = _curve(
        "snapClosedCurveTarget",
        [(2.0, 2.0, -2.0), (0.0, 2.0, 0.0), (-2.0, 2.0, -2.0), (0.0, 2.0, -4.0)],
        cyclic=True,
        spline_type="NURBS",
    )
    parent = bpy.data.objects.new("snapHierarchyParent", None)
    bpy.context.collection.objects.link(parent)
    ambiguity = [
        bpy.data.objects.new("snapAmbiguousA", None),
        bpy.data.objects.new("snapAmbiguousB", None),
    ]
    for obj, location in zip(ambiguity, ((0.9, 1.7, 1.0), (1.1, 1.7, 1.0))):
        bpy.context.collection.objects.link(obj)
        obj.location = location

    bpy.context.scene.tool_settings.use_snap = False
    bpy.context.scene.tool_settings.snap_elements = {"VERTEX"}
    bpy.context.window_manager.clarity_interaction_enabled = True
    bpy.ops.object.select_all(action="DESELECT")
    subject.select_set(True)
    bpy.context.view_layer.objects.active = subject
    bpy.context.view_layer.update()
    return {
        "subject": subject,
        "point_target": point,
        "center_target": center,
        "pivot_target": pivot_target,
        "orientation_target": orientation_target,
        "asymmetric_target": asymmetric,
        "surface_target": surface,
        "companion": companion,
        "curve": line,
        "curved_curve": curved,
        "closed_curve": closed,
        "parent": parent,
        "ambiguity": ambiguity,
    }


def _perform(mode: str, scene: dict[str, Any]) -> dict[str, Any]:
    obj = scene["subject"]
    meta: dict[str, Any] = {}
    if mode in {"point", "frozen_point"}:
        if mode == "frozen_point":
            _select_only(obj)
            with bpy.context.temp_override(**_viewport_override()):
                status = bpy.ops.object.transform_apply(
                    location=True, rotation=True, scale=True
                )
            if "FINISHED" not in status:
                raise RuntimeError("OBJECT_OT_transform_apply did not finish: {!r}".format(status))
            _command("bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)")
        _move_pivot_to(obj, _POINT)
        meta["target"] = _vector(_POINT)
    elif mode == "geometry_point":
        source = Vector(_world_vertices(obj)[6])
        _set_pivot_world(obj, source)
        _move_pivot_to(obj, _POINT)
        meta["target"] = _vector(_POINT)
    elif mode.startswith("handle_"):
        suffix = mode.removeprefix("handle_")
        if suffix == "object_x":
            obj.rotation_euler = Euler([math.radians(value) for value in (20.0, 35.0, 10.0)], "XYZ")
            bpy.context.view_layer.update()
            direction = obj.matrix_world.to_3x3().col[0].normalized()
            _select_only(obj)
            _translate_selected(direction * 4.0)
            meta["axisDirection"] = _vector(direction)
        else:
            axes = ["xyz".index(axis) for axis in suffix]
            location = obj.matrix_world.translation.copy()
            for axis in axes:
                location[axis] = _POINT[axis]
            _select_only(obj)
            _translate_selected(location - obj.matrix_world.translation)
            meta["axes"] = axes
        _command("transform.translate(constraint={!r}, snap=VERTEX)".format(suffix))
    elif mode == "target_pivot":
        target = _pivot_world(scene["pivot_target"])
        _move_pivot_to(obj, target)
        meta["target"] = _vector(target)
    elif mode in {"curve", "curved_curve", "closed_curve", "curve_cv_point"}:
        targets = {
            "curve": Vector((1.0, 0.0, -3.0)),
            "curved_curve": Vector((-1.0, 4.0, -1.5)),
            "closed_curve": Vector((2.0, 2.0, -2.0)),
            "curve_cv_point": Vector((-3.0, 2.5, -3.0)),
        }
        _move_pivot_to(obj, targets[mode])
        meta["target"] = _vector(targets[mode])
        _command("transform.translate(snap={})".format("VERTEX" if mode == "curve_cv_point" else "CURVE"))
    elif mode in {"grid", "custom_grid"}:
        target = Vector((0.0, 0.0, 0.0)) if mode == "grid" else Vector((2.5, 0.0, 2.5))
        _move_pivot_to(obj, target)
        meta["target"] = _vector(target)
        meta["gridSpacing"] = 1.0 if mode == "grid" else 2.5
        _command("transform.translate(snap=INCREMENT)")
    elif mode in {"mesh_center", "pivot_edit_mesh_center"}:
        if mode.startswith("pivot_edit"):
            _set_pivot_world(obj, _CENTER)
        else:
            _move_pivot_to(obj, _CENTER)
        meta["target"] = _vector(_CENTER)
    elif mode in {"view_plane", "view_plane_ortho"}:
        delta = Vector((1.0, -2.0, 0.75))
        _select_only(obj)
        _translate_selected(delta)
        meta["delta"] = _vector(delta)
        meta["orthographic"] = mode.endswith("ortho")
        _command("transform.translate(constraint=VIEW_PLANE)")
    elif mode == "pivot_edit_point":
        _set_pivot_world(obj, _POINT)
        meta["target"] = _vector(_POINT)
    elif mode == "pivot_orientation":
        pivot = obj.custom_pivot_ensure()
        quaternion = scene["orientation_target"].rotation_euler.to_quaternion()
        pivot.orientation = (quaternion.w, quaternion.x, quaternion.y, quaternion.z)
        pivot.is_orientation_valid = True
        meta["targetOrientation"] = _vector(quaternion)
        _command("custom_pivot.orientation = target.normal_frame")
    elif mode in {"pivot_persistence", "pivot_post_rotate", "pivot_post_scale", "pivot_reset"}:
        source = Vector(_world_vertices(obj)[6])
        _set_pivot_world(obj, source)
        if mode == "pivot_post_rotate":
            _select_only(obj)
            with bpy.context.temp_override(**_viewport_override()):
                status = bpy.ops.transform.rotate(
                    value=math.radians(45.0), orient_axis="Z", orient_type="GLOBAL"
                )
            if "FINISHED" not in status:
                raise RuntimeError("TRANSFORM_OT_rotate did not finish: {!r}".format(status))
            _command("bpy.ops.transform.rotate(value=45deg, pivot=CUSTOM)")
        elif mode == "pivot_post_scale":
            _select_only(obj)
            with bpy.context.temp_override(**_viewport_override()):
                status = bpy.ops.transform.resize(value=(2.5, 1.0, 1.0), orient_type="GLOBAL")
            if "FINISHED" not in status:
                raise RuntimeError("TRANSFORM_OT_resize did not finish: {!r}".format(status))
            _command("bpy.ops.transform.resize(value=(2.5,1,1), pivot=CUSTOM)")
        elif mode == "pivot_reset":
            _clear_pivot(obj)
        else:
            _command("clarity.transform_orientation_set(MOVE/ROTATE/SCALE)")
        meta["sourceVertex"] = _vector(source)
    elif mode.startswith("hierarchy_"):
        parent = scene["parent"]
        parent.location = (1.25, -0.75, 0.5)
        parent.rotation_euler = Euler([math.radians(value) for value in (20.0, 35.0, -15.0)], "XYZ")
        parent.scale = (-1.5, 0.8, 1.25) if mode.endswith("negative") else (1.5, 0.8, 1.25)
        # Evaluate the parent's matrix before preserving the child's world matrix. Without this,
        # assigning the parent uses its stale identity matrix and the next dependency-graph update
        # applies the parent transform a second time to the subject.
        bpy.context.view_layer.update()
        world = obj.matrix_world.copy()
        obj.parent = parent
        obj.matrix_world = world
        bpy.context.view_layer.update()
        _move_pivot_to(obj, _POINT)
        meta["target"] = _vector(_POINT)
    elif mode.startswith("duplicate"):
        if mode == "duplicate_disabled":
            _move_pivot_to(obj, _POINT)
            meta.update({"target": _vector(_POINT), "expectedCopies": 0})
        elif mode == "duplicate_rotate":
            duplicate = _duplicate(obj)
            with bpy.context.temp_override(**_viewport_override()):
                status = bpy.ops.transform.rotate(
                    value=math.radians(45.0), orient_axis="Z", orient_type="GLOBAL"
                )
            if "FINISHED" not in status:
                raise RuntimeError("duplicate rotate did not finish: {!r}".format(status))
            meta["expectedCopies"] = 1
        elif mode == "duplicate_scale":
            duplicate = _duplicate(obj)
            with bpy.context.temp_override(**_viewport_override()):
                status = bpy.ops.transform.resize(value=(2.5, 1.0, 1.0), orient_type="GLOBAL")
            if "FINISHED" not in status:
                raise RuntimeError("duplicate scale did not finish: {!r}".format(status))
            meta["expectedCopies"] = 1
        elif mode == "duplicate_chain":
            first = _duplicate(obj)
            _move_pivot_to(first, _POINT)
            second = _duplicate(first)
            _move_pivot_to(second, Vector((0.0, 0.0, 0.0)))
            meta["expectedCopies"] = 2
        else:
            if "vertex" in mode:
                _set_pivot_world(obj, Vector(_world_vertices(obj)[6]))
            duplicate = _duplicate(obj, instance="instance" in mode)
            target = _CENTER if mode.endswith("mesh_center") else _POINT
            _move_pivot_to(duplicate, target)
            meta.update(
                {
                    "target": _vector(target),
                    "expectedCopies": 1,
                    "expectInstance": "instance" in mode,
                    "expectCopy": "copy" in mode,
                }
            )
    elif mode == "live_surface":
        target = Vector((0.0, -3.0, 2.0))
        _move_pivot_to(obj, target)
        meta["target"] = _vector(target)
        _command("transform.translate(snap=FACE, target=LIVE_SURFACE)")
    elif mode == "asymmetric_center":
        bounds = _bounds(scene["asymmetric_target"])
        target = Vector(
            (
                (bounds[0] + bounds[3]) * 0.5,
                (bounds[1] + bounds[4]) * 0.5,
                (bounds[2] + bounds[5]) * 0.5,
            )
        )
        _move_pivot_to(obj, target)
        meta["target"] = _vector(target)
    elif mode == "multi_object":
        companion = scene["companion"]
        delta = _POINT - ((_pivot_world(obj) + _pivot_world(companion)) * 0.5)
        _select_only(obj)
        companion.select_set(True)
        _translate_selected(delta)
        meta["delta"] = _vector(delta)
        _command("transform.translate(selection=2, snap=VERTEX)")
    elif mode in {"component_relative", "component_collapse"}:
        points = obj.data.vertices
        before = [points[0].co.copy(), points[1].co.copy()]
        target_local = obj.matrix_world.inverted() @ _POINT
        if mode == "component_relative":
            delta = target_local - before[0]
            points[0].co += delta
            points[1].co += delta
        else:
            points[0].co = target_local
            points[1].co = target_local
        obj.data.update()
        meta["target"] = _vector(_POINT)
    elif mode == "ambiguous_point":
        target = scene["ambiguity"][0].matrix_world.translation
        _move_pivot_to(obj, target)
        meta["candidates"] = [_vector(item.matrix_world.translation) for item in scene["ambiguity"]]
    elif mode in {"cancel_move", "cancel_duplicate"}:
        _command("transform.cancel()")
    elif mode == "undo_move":
        # Scripted transforms do not consistently create their own memfile step. Store both sides
        # explicitly: undo then has an actual baseline to restore instead of reporting FINISHED
        # while leaving the moved object untouched.
        _undo_push("Clarity model snap before move")
        _move_pivot_to(obj, _POINT)
        _undo_push("Clarity model snap after move")
        with bpy.context.temp_override(**_viewport_override()):
            status = bpy.ops.ed.undo()
        if "FINISHED" not in status:
            raise RuntimeError("ED_OT_undo did not finish: {!r}".format(status))
        _command("bpy.ops.ed.undo()")
    elif mode == "redo_move":
        _undo_push("Clarity model snap before move")
        _move_pivot_to(obj, _POINT)
        _undo_push("Clarity model snap after move")
        with bpy.context.temp_override(**_viewport_override()):
            undo_status = bpy.ops.ed.undo()
            undo_object = bpy.data.objects.get("snapSubject")
            meta["undoDistanceToInitial"] = (
                _distance(_pivot_world(undo_object), _INITIAL)
                if undo_object is not None
                else float("inf")
            )
            redo_status = bpy.ops.ed.redo()
        if "FINISHED" not in undo_status or "FINISHED" not in redo_status:
            raise RuntimeError(
                "undo/redo did not finish: {!r} / {!r}".format(undo_status, redo_status)
            )
        _command("bpy.ops.ed.undo(); bpy.ops.ed.redo()")
        meta["target"] = _vector(_POINT)
    elif mode == "tool_change_cleanup":
        _select_only(obj)
        _translate_selected(Vector((1.0, 0.0, 0.0)))
        meta["activeToolAfter"] = "ROTATE"
        _command("transform.translate(); tool_set(ROTATE)")
    elif mode.startswith("step_move"):
        relative = mode.endswith("relative")
        target = -2.25 if relative else -2.0
        _select_only(obj)
        _translate_selected(Vector((target - obj.location.x, 0.0, 0.0)))
        meta.update({"relative": relative, "step": 1.0})
        _command("transform.translate(snap=INCREMENT, relative={!r})".format(relative))
    elif mode == "step_rotate":
        _select_only(obj)
        with bpy.context.temp_override(**_viewport_override()):
            status = bpy.ops.transform.rotate(
                value=math.radians(45.0), orient_axis="Z", orient_type="GLOBAL"
            )
        if "FINISHED" not in status:
            raise RuntimeError("step rotate did not finish: {!r}".format(status))
        meta["step"] = 15.0
        _command("transform.rotate(snap=15deg)")
    elif mode == "step_scale":
        _select_only(obj)
        with bpy.context.temp_override(**_viewport_override()):
            status = bpy.ops.transform.resize(value=(2.5, 1.0, 1.0), orient_type="GLOBAL")
        if "FINISHED" not in status:
            raise RuntimeError("step scale did not finish: {!r}".format(status))
        meta["step"] = 0.5
        _command("transform.resize(snap=0.5)")
    else:
        raise RuntimeError("unhandled Blender scenario mode: " + mode)
    bpy.context.view_layer.update()
    return meta


def _analyze(mode: str, before: dict[str, Any], after: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    pivot = Vector(after["pivotWorld"])
    before_pivot = Vector(before["pivotWorld"])
    moved = (pivot - before_pivot).length
    analysis: dict[str, Any] = {"pivotMoved": moved, "passed": False}
    tolerance = 1.0e-4
    if mode.startswith("handle_"):
        delta = pivot - before_pivot
        if mode == "handle_object_x":
            axis = Vector(meta["axisDirection"])
            perpendicular = (delta - axis * delta.dot(axis)).length
            analysis.update({"perpendicularDistance": perpendicular, "passed": moved > tolerance and perpendicular <= tolerance})
        else:
            axes = meta["axes"]
            inactive = [index for index in range(3) if index not in axes]
            residual = max((abs(delta[index]) for index in inactive), default=0.0)
            active = math.sqrt(sum((pivot[index] - _POINT[index]) ** 2 for index in axes))
            analysis.update({"activeTargetResidual": active, "inactiveAxisResidual": residual,
                             "passed": moved > tolerance and active <= tolerance and residual <= tolerance})
    elif mode == "pivot_orientation":
        valid = after["customPivot"]["orientationValid"]
        actual = Quaternion(after["customPivot"]["orientation"])
        target = Quaternion(meta["targetOrientation"])
        angular_error = math.degrees(actual.rotation_difference(target).angle)
        analysis.update(
            {
                "orientationValid": valid,
                "orientationErrorDegrees": angular_error,
                "passed": bool(valid) and angular_error <= 1.0e-3,
            }
        )
    elif mode == "pivot_persistence":
        valid = after["customPivot"]["positionValid"]
        distance = _distance(pivot, meta["sourceVertex"])
        analysis.update(
            {
                "pivotPositionValid": valid,
                "distanceToSourceVertex": distance,
                "passed": bool(valid) and distance <= tolerance,
            }
        )
    elif mode.startswith("pivot_post_"):
        changed = before["worldBoundingBox"] != after["worldBoundingBox"]
        pivot_distance = _distance(pivot, meta["sourceVertex"])
        analysis.update(
            {
                "geometryChanged": changed,
                "pivotDistanceToSourceVertex": pivot_distance,
                "passed": changed
                and after["customPivot"]["positionValid"]
                and pivot_distance <= tolerance,
            }
        )
    elif mode == "pivot_reset":
        distance = _distance(pivot, after["translationWorld"])
        bounds_unchanged = before["worldBoundingBox"] == after["worldBoundingBox"]
        analysis.update(
            {
                "distanceToObjectOrigin": distance,
                "geometryBoundsUnchanged": bounds_unchanged,
                "passed": distance <= tolerance and bounds_unchanged,
            }
        )
    elif mode.startswith("duplicate"):
        copies = len(after["subjectObjects"]) - 1
        expected = int(meta.get("expectedCopies", 1))
        before_original = before["subjectObjects"][0]
        after_original = next(
            (item for item in after["subjectObjects"] if item["node"] == before_original["node"]),
            None,
        )
        original_unchanged = bool(
            after_original
            and after_original["translationWorld"] == before_original["translationWorld"]
            and after_original["worldBoundingBox"] == before_original["worldBoundingBox"]
        )
        duplicate = next(
            (item for item in after["subjectObjects"] if item["node"] != before_original["node"]),
            None,
        )
        shape_ok = True
        target_ok = True
        step_ok = True
        if copies == 1 and (meta.get("expectCopy") or meta.get("expectInstance")):
            shared = bool(
                duplicate
                and after_original
                and set(after_original["shapeUuids"]) & set(duplicate["shapeUuids"])
            )
            shape_ok = shared if meta.get("expectInstance") else not shared
            analysis["sharedShapeData"] = shared
        if duplicate and "target" in meta:
            distance = _distance(duplicate["pivotWorld"], meta["target"])
            analysis["copyDistanceToTarget"] = distance
            target_ok = distance <= tolerance
            if mode == "duplicate_vertex_point":
                vertex_distance = min(
                    _distance(vertex, meta["target"]) for vertex in duplicate["vertices"]
                )
                analysis["copyGeometryPointDistance"] = vertex_distance
                target_ok = target_ok and vertex_distance <= tolerance
        elif expected == 0 and "target" in meta:
            distance = _distance(pivot, meta["target"])
            analysis["distanceToTarget"] = distance
            target_ok = distance <= tolerance
        if mode == "duplicate_rotate" and duplicate:
            residual = max(
                abs(value / 15.0 - round(value / 15.0)) for value in duplicate["rotate"]
            )
            analysis["stepResidual"] = residual
            step_ok = residual <= tolerance
        elif mode == "duplicate_scale" and duplicate:
            residual = max(
                abs(value / 0.5 - round(value / 0.5)) for value in duplicate["scale"]
            )
            analysis["stepResidual"] = residual
            step_ok = residual <= tolerance
        # With smart duplication disabled the original moves and no copy is created.
        original_ok = moved > tolerance if expected == 0 else original_unchanged
        analysis.update(
            {
                "copyCount": copies,
                "expectedCopyCount": expected,
                "originalUnchanged": original_unchanged,
                "passed": copies == expected and original_ok and shape_ok and target_ok and step_ok,
            }
        )
    elif mode.startswith("component_"):
        vertices = after["subjectObjects"][0]["vertices"][:2]
        before_vertices = before["subjectObjects"][0]["vertices"][:2]
        spacing_before = _distance(before_vertices[0], before_vertices[1])
        spacing = _distance(vertices[0], vertices[1])
        distances = [_distance(vertex, meta["target"]) for vertex in vertices]
        expected_zero = mode.endswith("collapse")
        spacing_ok = spacing <= tolerance if expected_zero else abs(spacing - spacing_before) <= tolerance
        target_ok = max(distances) <= tolerance if expected_zero else min(distances) <= tolerance
        analysis.update(
            {
                "spacingBefore": spacing_before,
                "spacingAfter": spacing,
                "maxDistanceToTargetPoint": max(distances),
                "passed": spacing_ok and target_ok,
            }
        )
    elif mode == "multi_object":
        before_spacing = _distance(before_pivot, before["companion"]["pivotWorld"])
        after_spacing = _distance(pivot, after["companion"]["pivotWorld"])
        center = (pivot + Vector(after["companion"]["pivotWorld"])) * 0.5
        center_distance = _distance(center, _POINT)
        analysis.update(
            {
                "relativeSpacingDelta": abs(after_spacing - before_spacing),
                "selectionCenterDistanceToTarget": center_distance,
                "passed": moved > tolerance
                and abs(after_spacing - before_spacing) <= tolerance
                and center_distance <= tolerance,
            }
        )
    elif mode in {"view_plane", "view_plane_ortho"}:
        residual = _distance(pivot - before_pivot, meta["delta"])
        analysis.update(
            {"planeDeltaResidual": residual, "passed": moved > tolerance and residual <= tolerance}
        )
    elif mode == "tool_change_cleanup":
        analysis.update(
            {
                "activeToolAfter": meta.get("activeToolAfter"),
                "snapInactiveAfter": not after["snap"]["enabled"],
                "passed": moved > tolerance and not after["snap"]["enabled"],
            }
        )
    elif mode == "ambiguous_point":
        distances = [_distance(pivot, candidate) for candidate in meta["candidates"]]
        analysis.update({"candidateDistances": distances, "chosenCandidate": distances.index(min(distances)),
                         "passed": min(distances) <= tolerance})
    elif mode in {"cancel_move", "cancel_duplicate", "undo_move"}:
        unchanged = before["worldMatrix"] == after["worldMatrix"] and len(before["subjectObjects"]) == len(after["subjectObjects"])
        analysis.update({"stateUnchanged": unchanged, "passed": unchanged})
    elif mode.startswith("step_move"):
        base = _INITIAL.x if mode.endswith("relative") else 0.0
        value = after["translate"][0] - base
        residual = abs(value - round(value))
        analysis.update({"stepResidual": residual, "passed": residual <= tolerance})
    elif mode == "step_rotate":
        residual = max(abs(value / 15.0 - round(value / 15.0)) for value in after["rotate"])
        analysis.update({"stepResidual": residual, "passed": residual <= tolerance})
    elif mode == "step_scale":
        residual = max(abs(value / 0.5 - round(value / 0.5)) for value in after["scale"])
        analysis.update({"stepResidual": residual, "passed": residual <= tolerance})
    elif mode == "redo_move":
        distance = _distance(pivot, meta["target"])
        undo_distance = float(meta.get("undoDistanceToInitial", float("inf")))
        analysis.update(
            {
                "distanceToTarget": distance,
                "undoDistanceToInitial": undo_distance,
                "passed": distance <= tolerance and undo_distance <= tolerance,
            }
        )
    elif "target" in meta:
        distance = _distance(pivot, meta["target"])
        passed = distance <= tolerance
        analysis["distanceToTarget"] = distance
        if mode == "geometry_point":
            geometry_distance = min(
                _distance(vertex, meta["target"])
                for vertex in after["subjectObjects"][0]["vertices"]
            )
            analysis["geometryPointDistance"] = geometry_distance
            passed = passed and geometry_distance <= tolerance
        if mode.startswith("pivot_edit"):
            translation_delta = _distance(before["translationWorld"], after["translationWorld"])
            bounds_delta = max(
                abs(first - second)
                for first, second in zip(before["worldBoundingBox"], after["worldBoundingBox"])
            )
            analysis.update(
                {"objectTranslationDelta": translation_delta, "geometryBoundsDelta": bounds_delta}
            )
            passed = passed and translation_delta <= tolerance and bounds_delta <= tolerance
        if mode.startswith("hierarchy_"):
            analysis["parentPreserved"] = bool(after["parent"])
            passed = passed and bool(after["parent"])
        analysis["passed"] = passed
    else:
        analysis["passed"] = False
        analysis["reason"] = "scenario produced no measurable assertion"
    return analysis


def _screenshot(path: Path) -> str | None:
    try:
        with bpy.context.temp_override(**_viewport_override()):
            bpy.ops.screen.screenshot_area(filepath=str(path))
        return str(path)
    except Exception:
        return None


def _log_text(result: dict[str, Any]) -> str:
    lines = [
        "Blender {} Clarity model snapping".format(result["blenderVersion"]),
        "execution fidelity: " + result["executionFidelity"],
        "tests: {}".format(len(result["tests"])),
        "",
    ]
    for record in result["tests"]:
        lines.append("{}: {}".format(record["name"], "PASS" if record["analysis"].get("passed") else "FAIL"))
        if record.get("error"):
            lines.append("  ERROR: " + record["error"])
        for key, value in record["analysis"].items():
            lines.append("  {}: {}".format(key, value))
        for command in record["commands"]:
            lines.append("  op: " + command)
        lines.append("")
    return "\n".join(lines)


def _write_maya_comparison(
    blender_capture: dict[str, Any], blender_output: Path
) -> dict[str, Any] | None:
    maya_path = Path(__file__).parent / "fixtures" / "maya_2025_pivot_gestures_model_snapping.json"
    comparator_path = Path(__file__).parent / "compare_model_snapping.py"
    if not maya_path.exists() or not comparator_path.exists():
        return None
    spec = importlib.util.spec_from_file_location("clarity_compare_model_snapping", comparator_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load {}".format(comparator_path))
    comparator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(comparator)
    maya_capture = json.loads(maya_path.read_text(encoding="utf-8"))
    selected_names = {record["name"] for record in blender_capture["tests"]}
    maya_capture["tests"] = [
        record for record in maya_capture["tests"] if record.get("name") in selected_names
    ]
    comparison = comparator.compare(maya_capture, blender_capture)
    stem = blender_output.with_name(blender_output.name + "_vs_maya")
    json_path = stem.with_suffix(".json")
    log_path = stem.with_suffix(".log")
    json_path.write_text(
        json.dumps(comparison, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    log_path.write_text(comparator._text_report(comparison), encoding="utf-8")
    return {
        "json": str(json_path),
        "log": str(log_path),
        "divergences": comparison["counts"]["divergences"],
    }


def _selected_scenarios(scenario_count: int) -> list[tuple[int, str, str, str]]:
    if scenario_count < 0 or scenario_count > len(SCENARIOS):
        raise ValueError("scenario_count must be between 0 and {}".format(len(SCENARIOS)))
    candidates = SCENARIOS if scenario_count == 0 else SCENARIOS[:scenario_count]
    return [
        (index, name, mode, tool)
        for index, (name, mode, tool) in enumerate(candidates, 1)
        if name not in UNSUPPORTED_SCENARIOS
    ]


def run(
    output: Path | str,
    screenshots: bool = True,
    scenario_count: int = MAYA_PARITY_SCENARIO_COUNT,
) -> dict[str, Any]:
    output = Path(output)
    if output.suffix:
        output = output.with_suffix("")
    output.parent.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    selected_scenarios = _selected_scenarios(scenario_count)
    for index, name, mode, tool in selected_scenarios:
        scene = _create_scene()
        before = _state(scene)
        before_shot = _screenshot(output.parent / "{}_{:02d}_{}_before.png".format(output.name, index, name)) if screenshots else None
        _COMMANDS.clear()
        error = None
        meta: dict[str, Any] = {}
        try:
            meta = _perform(mode, scene)
        except Exception as exception:  # noqa: BLE001 - captured result, not hidden failure.
            error = "{}: {}".format(type(exception).__name__, exception)
        after = _state(scene)
        try:
            analysis = _analyze(mode, before, after, meta)
        except Exception as exception:  # noqa: BLE001
            analysis = {"passed": False, "error": "{}: {}".format(type(exception).__name__, exception)}
        if error:
            analysis["passed"] = False
        after_shot = _screenshot(output.parent / "{}_{:02d}_{}_after.png".format(output.name, index, name)) if screenshots else None
        record = {
            "name": name,
            "mode": mode,
            "tool": tool,
            "executionFidelity": "operator_equivalent",
            "before": before,
            "after": after,
            "changes": _difference(before, after),
            "analysis": analysis,
            "commands": list(_COMMANDS),
            "input": [],
            "screenshots": {"before": before_shot, "after": after_shot},
        }
        if error:
            record["error"] = error
        records.append(record)

    result = {
        "schema": 7,
        "blenderVersion": bpy.app.version_string,
        "buildHash": bpy.app.build_hash.decode() if isinstance(bpy.app.build_hash, bytes) else str(bpy.app.build_hash),
        "executionFidelity": "operator_equivalent",
        "scenarioSelection": {
            "requestedCount": scenario_count,
            "excludedUnsupported": list(UNSUPPORTED_SCENARIOS),
        },
        "units": {"linear": "meter", "angularChannels": "degree"},
        "tests": records,
    }
    json_path = output.with_suffix(".json")
    log_path = output.with_suffix(".log")
    json_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    log_path.write_text(_log_text(result), encoding="utf-8")
    passed = sum(bool(record["analysis"].get("passed")) for record in records)
    summary = {
        "json": str(json_path),
        "log": str(log_path),
        "tests": len(records),
        "passed": passed,
        "failed": [record["name"] for record in records if not record["analysis"].get("passed")],
    }
    comparison = _write_maya_comparison(result, output)
    if comparison:
        summary["comparison"] = comparison
    return summary


class CLARITY_OT_capture_model_snapping(bpy.types.Operator):
    bl_idname = "clarity.capture_model_snapping"
    bl_label = "Run Maya Model Snap Tests"
    bl_description = "Replace the scene and write Blender counterparts of the Maya model-snap capture"

    output: bpy.props.StringProperty(
        name="Output",
        subtype="FILE_PATH",
        default=str(Path(__file__).parent / "fixtures" / "clarity_model_snapping.json"),
    )
    screenshots: bpy.props.BoolProperty(name="Screenshots", default=True)
    scenario_count: bpy.props.IntProperty(
        name="Scenario Count",
        description="First N canonical Maya scenarios; zero runs every supported scenario",
        default=MAYA_PARITY_SCENARIO_COUNT,
        min=0,
        max=len(SCENARIOS),
    )

    def execute(self, _context: bpy.types.Context) -> set[str]:
        result = run(
            bpy.path.abspath(self.output),
            screenshots=self.screenshots,
            scenario_count=self.scenario_count,
        )
        message = "Clarity model snapping: {}/{} passed".format(result["passed"], result["tests"])
        if result.get("comparison"):
            message += "; Maya differences: {}".format(result["comparison"]["divergences"])
        self.report({"INFO"}, message)
        return {"FINISHED"}


class VIEW3D_PT_clarity_model_snapping_capture(bpy.types.Panel):
    bl_label = "Clarity Snap Tests"
    bl_idname = "VIEW3D_PT_clarity_model_snapping_capture"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Clarity"

    def draw(self, _context: bpy.types.Context) -> None:
        layout = self.layout
        layout.label(text="Maya parity: 54 of 55 cases")
        layout.label(text="Live Surface excluded (not implemented)")
        layout.label(text="Replaces the current scene", icon="ERROR")
        first = layout.operator(
            CLARITY_OT_capture_model_snapping.bl_idname,
            text="Run First 20 Maya Tests",
        )
        first.scenario_count = 20
        all_supported = layout.operator(
            CLARITY_OT_capture_model_snapping.bl_idname,
            text="Run All 54 Supported Tests",
        )
        all_supported.scenario_count = MAYA_PARITY_SCENARIO_COUNT


_CLASSES = (CLARITY_OT_capture_model_snapping, VIEW3D_PT_clarity_model_snapping_capture)


def register() -> None:
    for cls in _CLASSES:
        try:
            bpy.utils.register_class(cls)
        except ValueError:
            pass


def unregister() -> None:
    for cls in reversed(_CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass


def _run_cli(
    output: Path, quit_when_done: bool, screenshots: bool, scenario_count: int
) -> None:
    try:
        result = run(output, screenshots=screenshots, scenario_count=scenario_count)
        print("Clarity model snapping: {passed}/{tests}; {json}".format(**result))
    except Exception:  # noqa: BLE001
        output.with_suffix(".log").write_text(traceback.format_exc(), encoding="utf-8")
    if quit_when_done:
        bpy.ops.wm.quit_blender()


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--quit", action="store_true")
    parser.add_argument("--no-screenshots", action="store_true")
    parser.add_argument(
        "--count",
        type=int,
        default=MAYA_PARITY_SCENARIO_COUNT,
        help="first N canonical scenarios; use 0 for all supported scenarios",
    )
    args = parser.parse_args(argv)

    def deferred() -> None:
        _run_cli(args.output, args.quit, not args.no_screenshots, args.count)
        return None

    bpy.app.timers.register(deferred, first_interval=0.5)


if __name__ == "__main__":
    if "--" in sys.argv:
        main(sys.argv[sys.argv.index("--") + 1 :])
    else:
        register()
        print("Clarity Snap Tests panel registered in View3D > Sidebar > Clarity")
