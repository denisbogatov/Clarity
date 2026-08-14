"""One-click Maya oracle for Clarity Soft Selection.

Run this module from Maya's Script Editor, call :func:`show`, and press the single validation
button. The harness never imports Clarity code: curve values come from Maya's ramp control and
component weights come from ``MGlobal.getRichSelection()``.

The current Maya scene is saved to a temporary copy and restored, including unsaved edits and its
original file name. The original file on disk is never overwritten.
"""

from __future__ import annotations

import datetime
import json
import math
import os
import tempfile
import traceback

import maya.api.OpenMaya as om
import maya.cmds as cmds


WINDOW_NAME = "claritySoftSelectionReferenceWindow"
OUTPUT_FIELD = "claritySoftSelectionReferenceOutput"
SCHEMA_VERSION = 1
DEFAULT_OUTPUT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "fixtures",
    "maya_soft_selection_reference.json",
)

PRESETS = {
    # Exact Maya 2025 presets from scripts/others/softSelectProperties.mel.
    "soft": "1,0,2,0,1,2",
    "medium": "1,0.5,2,0,1,2,1,0,2",
    "linear": "0,1,0,1,0,1,0,1,1",
    "hard": "1,0,0,0,1,2",
    "crater": "0,0,2,1,0.8,2,0,1,2",
    "wave": "1,0,2,0,0.16,2,0.75,0.32,2,0,0.48,2,0.25,0.64,2,0,0.8,2,0,1,2",
    "stairs": "1,0,1,0.75,0.25,1,0.5,0.5,1,0.75,0.25,1,0.25,0.75,1,1,0.249,1,0.749,0.499,1,0.499,0.749,1",
    "ring": "0,0.25,2,1,0.5,2,0,0.75,2",
    "sine": "1,0,2,0,0.16,2,1,0.32,2,0,0.48,2,1,0.64,2,0,0.8,2,0,1,2",
}

SAMPLES = [index / 40.0 for index in range(41)]
COMPONENT_NAMES = {
    om.MFn.kMeshVertComponent: "vertex",
    om.MFn.kMeshEdgeComponent: "edge",
    om.MFn.kMeshPolygonComponent: "face",
}


class CheckLog:
    def __init__(self):
        self.entries = []

    def true(self, name, condition, details=""):
        self.entries.append(
            {
                "name": name,
                "passed": bool(condition),
                "details": str(details) if details else "",
            }
        )

    def close(self, name, actual, expected, tolerance=1.0e-6):
        passed = math.isclose(float(actual), float(expected), abs_tol=tolerance)
        self.true(name, passed, "expected={!r}, actual={!r}".format(expected, actual))

    @property
    def passed(self):
        return all(entry["passed"] for entry in self.entries)


def _parse_curve(encoded):
    values = [float(value) for value in encoded.split(",")]
    if not values or len(values) % 3:
        raise ValueError("invalid Maya ramp string: {!r}".format(encoded))
    return [
        {
            "value": values[index],
            "position": values[index + 1],
            "interpolation": int(values[index + 2]),
        }
        for index in range(0, len(values), 3)
    ]


def _canonical_curve(encoded):
    return sorted(
        (
            round(point["position"], 8),
            round(point["value"], 8),
            point["interpolation"],
        )
        for point in _parse_curve(encoded)
    )


def _parse_color_curve(encoded):
    values = [float(value) for value in encoded.split(",")]
    if not values or len(values) % 5:
        raise ValueError("invalid Maya color ramp string: {!r}".format(encoded))
    return [
        {
            "color": values[index:index + 3],
            "weight": values[index + 3],
            "interpolation": int(values[index + 4]),
        }
        for index in range(0, len(values), 5)
    ]


def _soft_select_snapshot():
    query_flags = {
        "enabled": "softSelectEnabled",
        "falloff": "softSelectFalloff",
        "distance": "softSelectDistance",
        "curve": "softSelectCurve",
        "false_color": "enableFalseColor",
        "color_curve": "softSelectColorCurve",
    }
    result = {}
    for name, flag in query_flags.items():
        try:
            result[name] = cmds.softSelect(query=True, **{flag: True})
        except (RuntimeError, TypeError) as exception:
            # Some flags were added after older supported Maya releases. Keeping the error in the
            # fixture makes version drift visible without aborting the geometric oracle.
            result[name] = {"unsupported": str(exception)}
    return result


def _restore_soft_select(snapshot):
    edit_flags = {
        "enabled": "softSelectEnabled",
        "falloff": "softSelectFalloff",
        "distance": "softSelectDistance",
        "curve": "softSelectCurve",
        "false_color": "enableFalseColor",
        "color_curve": "softSelectColorCurve",
    }
    for name, flag in edit_flags.items():
        value = snapshot.get(name)
        if isinstance(value, dict) and "unsupported" in value:
            continue
        try:
            cmds.softSelect(edit=True, **{flag: value})
        except (RuntimeError, TypeError):
            pass


class _SceneRoundTrip:
    """Restore the user's in-memory scene without writing over its real path."""

    def __enter__(self):
        self.original_name = cmds.file(query=True, sceneName=True)
        self.original_modified = bool(cmds.file(query=True, modified=True))
        descriptor, self.temporary_path = tempfile.mkstemp(
            prefix="clarity_soft_selection_scene_", suffix=".mb"
        )
        os.close(descriptor)
        os.remove(self.temporary_path)

        try:
            cmds.file(rename=self.temporary_path)
            cmds.file(save=True, type="mayaBinary", force=True)
        except Exception:
            cmds.file(rename=self.original_name or "untitled")
            try:
                os.remove(self.temporary_path)
            except OSError:
                pass
            raise
        return self

    def __exit__(self, exc_type, exc_value, exc_traceback):
        try:
            cmds.file(self.temporary_path, open=True, force=True)
            cmds.file(rename=self.original_name or "untitled")
            cmds.file(modified=self.original_modified)
        finally:
            try:
                os.remove(self.temporary_path)
            except OSError:
                pass
        return False


def _new_scene():
    cmds.file(new=True, force=True)


def _create_mesh(name, vertices, faces):
    transform = cmds.createNode("transform", name=name)
    selection = om.MSelectionList()
    selection.add(transform)
    parent = selection.getDagPath(0).node()

    counts = [len(face) for face in faces]
    connections = [vertex for face in faces for vertex in face]
    mesh_object = om.MFnMesh().create(vertices, counts, connections, parent=parent)
    shape = om.MFnDagNode(mesh_object).fullPathName()
    cmds.rename(shape, name + "Shape")
    return cmds.ls(transform, long=True)[0]


def _set_soft_selection(mode, radius, curve=PRESETS["soft"]):
    cmds.softSelect(
        edit=True,
        softSelectEnabled=True,
        softSelectFalloff=mode,
        softSelectDistance=radius,
        softSelectCurve=curve,
    )


def _capture_rich_selection(objects):
    rich_selection = om.MGlobal.getRichSelection()
    selection = rich_selection.getSelection()
    raw_components = []

    for selection_index in range(selection.length()):
        try:
            dag_path, component = selection.getComponent(selection_index)
        except RuntimeError:
            continue
        if component.isNull():
            continue

        component_type = component.apiType()
        component_name = COMPONENT_NAMES.get(component_type)
        if component_name is None:
            component_name = str(component.apiTypeStr)
        try:
            component_fn = om.MFnSingleIndexedComponent(component)
        except RuntimeError:
            continue

        elements = component_fn.getElements()
        weighted_elements = []
        for local_index, element in enumerate(elements):
            weight = component_fn.weight(local_index)
            weighted_elements.append(
                {
                    "index": int(element),
                    "influence": float(weight.influence),
                    "seam": float(weight.seam),
                }
            )
        raw_components.append(
            {
                "dag_path": dag_path.fullPathName(),
                "component": component_name,
                "elements": weighted_elements,
            }
        )

    vertex_weights = {}
    for transform in objects:
        long_transform = cmds.ls(transform, long=True)[0]
        shapes = cmds.listRelatives(long_transform, shapes=True, fullPath=True, type="mesh") or []
        vertex_count = int(cmds.polyEvaluate(long_transform, vertex=True))
        weights = [0.0] * vertex_count
        for component in raw_components:
            if component["component"] != "vertex" or component["dag_path"] not in shapes:
                continue
            for element in component["elements"]:
                weights[element["index"]] = element["influence"]
        vertex_weights[long_transform] = weights

    return {
        "raw_components": raw_components,
        "vertex_weights": vertex_weights,
    }


def _select_and_capture(objects, components):
    cmds.select(clear=True)
    cmds.select(components, replace=True)
    cmds.refresh(force=True)
    return _capture_rich_selection(objects)


def _weights(capture, transform):
    long_transform = cmds.ls(transform, long=True)[0]
    return capture["vertex_weights"][long_transform]


def _capture_ramps(checks):
    window = cmds.window()
    try:
        cmds.columnLayout()
        control = cmds.gradientControlNoAttr()
        result = {}
        for preset_name, encoded in PRESETS.items():
            cmds.gradientControlNoAttr(control, edit=True, asString=encoded)
            returned = cmds.gradientControlNoAttr(control, query=True, asString=True)
            values = [
                float(cmds.gradientControlNoAttr(control, query=True, valueAtPoint=sample))
                for sample in SAMPLES
            ]
            result[preset_name] = {
                "source": encoded,
                "canonical": returned,
                "points": _parse_curve(returned),
                "samples": [
                    {"position": position, "value": value}
                    for position, value in zip(SAMPLES, values)
                ],
            }
            checks.true(
                "ramp.{}.round_trip".format(preset_name),
                _canonical_curve(returned) == _canonical_curve(encoded),
                returned,
            )

        soft_samples = result["soft"]["samples"]
        checks.close("ramp.soft.at_0", soft_samples[0]["value"], 1.0)
        checks.close("ramp.soft.at_05", soft_samples[20]["value"], 0.5)
        checks.close("ramp.soft.at_1", soft_samples[40]["value"], 0.0)
        checks.true(
            "ramp.soft.monotonic",
            all(
                left["value"] >= right["value"]
                for left, right in zip(soft_samples, soft_samples[1:])
            ),
        )
        checks.true(
            "ramp.soft.symmetric",
            all(
                math.isclose(
                    soft_samples[index]["value"] + soft_samples[40 - index]["value"],
                    1.0,
                    abs_tol=1.0e-6,
                )
                for index in range(41)
            ),
        )

        interpolation_curves = {
            "none": "1,0,0,0,1,0",
            "linear": "1,0,1,0,1,1",
            "smooth": "1,0,2,0,1,2",
            "spline": "1,0,3,0,1,3",
            # Asymmetric spacing/values distinguish neighbor-aware spline math from smoothstep and
            # uniform Catmull-Rom approximations.
            "spline_neighbors": "1,0,3,0.2,0.25,3,0.9,0.7,3,0,1,3",
        }
        result["interpolation_contract"] = {}
        for name, encoded in interpolation_curves.items():
            cmds.gradientControlNoAttr(control, edit=True, asString=encoded)
            result["interpolation_contract"][name] = [
                float(cmds.gradientControlNoAttr(control, query=True, valueAtPoint=sample))
                for sample in SAMPLES
            ]
        checks.close(
            "ramp.none.outgoing_segment",
            result["interpolation_contract"]["none"][20],
            1.0,
        )
        checks.close(
            "ramp.linear.outgoing_segment",
            result["interpolation_contract"]["linear"][10],
            0.75,
        )
        return result
    finally:
        cmds.deleteUI(window, window=True)


def _capture_disconnected_shells(mode):
    _new_scene()
    obj = _create_mesh(
        "DisconnectedShells",
        [
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (1.0, 1.0, 0.0),
            (0.0, 1.0, 0.0),
            (0.25, 0.25, 0.2),
            (1.25, 0.25, 0.2),
            (1.25, 1.25, 0.2),
            (0.25, 1.25, 0.2),
        ],
        [(0, 1, 2, 3), (4, 5, 6, 7)],
    )
    _set_soft_selection(mode, 2.0)
    return obj, _select_and_capture([obj], [obj + ".vtx[0]"])


def _capture_folded_strip(mode):
    _new_scene()
    centerline = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.1, 1.0)]
    vertices = []
    for x, y in centerline:
        vertices.extend([(x, y, 0.0), (x, y, 0.1)])
    obj = _create_mesh("FoldedStrip", vertices, [(0, 2, 3, 1), (2, 4, 5, 3), (4, 6, 7, 5)])
    _set_soft_selection(mode, 1.5)
    return obj, _select_and_capture([obj], [obj + ".vtx[0]"])


def _capture_multiple_objects(mode):
    _new_scene()
    subject = _create_mesh(
        "Subject",
        [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 0.2, 0.0), (0.0, 0.2, 0.0)],
        [(0, 1, 2, 3)],
    )
    neighbor = _create_mesh(
        "Neighbor",
        [(0.5, 0.0, 0.0), (1.5, 0.0, 0.0), (1.5, 0.2, 0.0), (0.5, 0.2, 0.0)],
        [(0, 1, 2, 3)],
    )
    _set_soft_selection(mode, 2.0)
    return (subject, neighbor), _select_and_capture(
        [subject, neighbor], [subject + ".vtx[0]"]
    )


def _capture_nonuniform_scale():
    _new_scene()
    obj = _create_mesh(
        "Scaled",
        [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0),
         (0.0, 0.1, 0.0), (1.0, 0.1, 0.0), (2.0, 0.1, 0.0)],
        [(0, 1, 4, 3), (1, 2, 5, 4)],
    )
    cmds.setAttr(obj + ".scaleX", 2.0)
    _set_soft_selection(0, 3.0)
    return obj, _select_and_capture([obj], [obj + ".vtx[0]"])


def _capture_multiple_sources():
    _new_scene()
    vertices = [(float(x), 0.0, 0.0) for x in range(5)]
    vertices.extend((float(x), 0.1, 0.0) for x in range(5))
    obj = _create_mesh(
        "MultipleSources",
        vertices,
        [(x, x + 1, x + 6, x + 5) for x in range(4)],
    )
    _set_soft_selection(0, 1.5)
    return obj, _select_and_capture([obj], [obj + ".vtx[0]", obj + ".vtx[4]"])


def _capture_component_kinds():
    result = {}
    for component_name, component in (
        ("vertex", ".vtx[0]"),
        ("edge", ".e[0]"),
        ("face", ".f[0]"),
    ):
        _new_scene()
        obj = _create_mesh(
            "ComponentKinds",
            [
                (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0),
                (0.0, 1.0, 0.0), (1.0, 1.0, 0.0), (2.0, 1.0, 0.0),
            ],
            [(0, 1, 4, 3), (1, 2, 5, 4)],
        )
        _set_soft_selection(0, 2.0)
        result[component_name] = _select_and_capture([obj], [obj + component])
    return result


def _capture_geometry_contract(checks):
    cases = {}

    volume_obj, cases["disconnected_volume"] = _capture_disconnected_shells(0)
    volume_weights = _weights(cases["disconnected_volume"], volume_obj)
    surface_obj, cases["disconnected_surface"] = _capture_disconnected_shells(1)
    surface_weights = _weights(cases["disconnected_surface"], surface_obj)
    checks.true("distance.volume.crosses_shell", volume_weights[4] > 0.0, volume_weights)
    checks.close("distance.surface.stops_at_shell", surface_weights[4], 0.0)

    volume_obj, cases["folded_volume"] = _capture_folded_strip(0)
    volume_weights = _weights(cases["folded_volume"], volume_obj)
    surface_obj, cases["folded_surface"] = _capture_folded_strip(1)
    surface_weights = _weights(cases["folded_surface"], surface_obj)
    checks.true("distance.volume.uses_chord", volume_weights[6] > 0.0, volume_weights)
    checks.close("distance.surface.uses_path", surface_weights[6], 0.0)

    objects, cases["multiple_objects_volume"] = _capture_multiple_objects(0)
    neighbor_weights = _weights(cases["multiple_objects_volume"], objects[1])
    checks.true(
        "scope.volume.excludes_other_object",
        all(weight == 0.0 for weight in neighbor_weights),
        neighbor_weights,
    )
    objects, cases["multiple_objects_global"] = _capture_multiple_objects(2)
    neighbor_weights = _weights(cases["multiple_objects_global"], objects[1])
    checks.true(
        "scope.global.includes_other_object",
        any(weight > 0.0 for weight in neighbor_weights),
        neighbor_weights,
    )

    scaled_obj, cases["nonuniform_scale"] = _capture_nonuniform_scale()
    scaled_weights = _weights(cases["nonuniform_scale"], scaled_obj)
    checks.true("distance.scale.uses_world_units", 0.0 < scaled_weights[1] < 1.0, scaled_weights)
    checks.close("distance.scale.radius_cutoff", scaled_weights[2], 0.0)

    sources_obj, cases["multiple_sources"] = _capture_multiple_sources()
    source_weights = _weights(cases["multiple_sources"], sources_obj)
    checks.close("sources.left_right_symmetry", source_weights[1], source_weights[3])
    checks.close("sources.first_selected", source_weights[0], 1.0)
    checks.close("sources.last_selected", source_weights[4], 1.0)

    cases["component_kinds"] = _capture_component_kinds()
    for component_name, capture in cases["component_kinds"].items():
        checks.true(
            "components.{}.rich_selection_exists".format(component_name),
            bool(capture["raw_components"]),
        )
    return cases


def _write_json(path, payload):
    path = os.path.abspath(os.path.expanduser(path))
    directory = os.path.dirname(path)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    temporary_path = path + ".tmp"
    with open(temporary_path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(temporary_path, path)
    return path


def run_all(output_path=DEFAULT_OUTPUT):
    """Run the independent Maya oracle and return the complete JSON-compatible payload."""

    checks = CheckLog()
    soft_select_before = _soft_select_snapshot()
    payload = {
        "schema_version": SCHEMA_VERSION,
        "captured_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "maya": {
            "version": cmds.about(version=True),
            "api_version": int(cmds.about(apiVersion=True)),
            "operating_system": cmds.about(operatingSystem=True),
        },
        "source": {
            "weights": "maya.api.OpenMaya.MGlobal.getRichSelection",
            "ramps": "maya.cmds.gradientControlNoAttr(valueAtPoint)",
            "colors": "maya.cmds.softSelect(query=True, softSelectColorCurve=True)",
        },
    }

    try:
        with _SceneRoundTrip():
            try:
                cmds.softSelect(softSelectReset=True)
                payload["factory_settings"] = _soft_select_snapshot()
                factory = payload["factory_settings"]
                checks.true("factory.disabled", not factory["enabled"], factory["enabled"])
                checks.true("factory.volume", factory["falloff"] == 0, factory["falloff"])
                checks.close("factory.radius", factory["distance"], 5.0)
                checks.true(
                    "factory.curve",
                    _canonical_curve(factory["curve"]) == _canonical_curve(PRESETS["soft"]),
                    factory["curve"],
                )
                checks.true(
                    "factory.false_color_enabled",
                    bool(factory["false_color"]),
                    factory["false_color"],
                )
                color_points = sorted(
                    _parse_color_curve(factory["color_curve"]),
                    key=lambda point: point["weight"],
                )
                payload["factory_color_curve"] = color_points
                checks.true(
                    "factory.color_curve.domain",
                    color_points[0]["weight"] == 0.0 and color_points[-1]["weight"] == 1.0,
                    color_points,
                )
                checks.true(
                    "factory.color_curve.black_to_red_to_yellow",
                    all(channel <= 1.0e-6 for channel in color_points[0]["color"]) and
                    any(
                        point["color"][0] > 0.9 and
                        point["color"][1] < 0.1 and
                        point["color"][2] < 0.1
                        for point in color_points[1:-1]
                    ) and
                    color_points[-1]["color"][0] > 0.9 and
                    color_points[-1]["color"][1] > 0.9 and
                    color_points[-1]["color"][2] < 0.1,
                    color_points,
                )
                payload["ramps"] = _capture_ramps(checks)
                payload["geometry"] = _capture_geometry_contract(checks)
            except Exception as exception:  # Keep a useful artifact if one Maya scenario fails.
                checks.true("harness.completed", False, repr(exception))
                payload["exception"] = traceback.format_exc()
    finally:
        # Scene loading should not normally change global soft-selection preferences, but restore
        # after the round-trip as well so a version-specific callback cannot leak test state.
        _restore_soft_select(soft_select_before)

    payload["checks"] = checks.entries
    payload["passed"] = checks.passed
    payload["output_path"] = os.path.abspath(os.path.expanduser(output_path))
    _write_json(payload["output_path"], payload)
    return payload


def _run_from_ui(*_unused):
    output_path = cmds.textFieldButtonGrp(OUTPUT_FIELD, query=True, text=True)
    answer = cmds.confirmDialog(
        title="Clarity Soft Selection",
        message=(
            "Maya временно переключится на контрольные сцены.\n"
            "Текущая сцена и несохранённые изменения "
            "будут восстановлены "
            "из временной копии.\n"
            "История Undo будет очищена открытием временной сцены."
        ),
        button=["Запустить", "Отмена"],
        defaultButton="Запустить",
        cancelButton="Отмена",
        dismissString="Отмена",
    )
    if answer != "Запустить":
        return

    try:
        payload = run_all(output_path)
        failed = [entry for entry in payload["checks"] if not entry["passed"]]
        if payload["passed"]:
            message = "PASS: {} проверок\n\n{}".format(
                len(payload["checks"]), payload["output_path"]
            )
            icon = "information"
        else:
            message = "FAIL: {} из {} проверок\n\n{}\n\n{}".format(
                len(failed),
                len(payload["checks"]),
                failed[0]["name"] if failed else "unknown failure",
                payload["output_path"],
            )
            icon = "critical"
        cmds.confirmDialog(title="Clarity Soft Selection", message=message, button=["OK"], icon=icon)
    except Exception:
        cmds.confirmDialog(
            title="Clarity Soft Selection",
            message="Harness error:\n\n" + traceback.format_exc(),
            button=["OK"],
            icon="critical",
        )
        raise


def _choose_output(*_unused):
    current = cmds.textFieldButtonGrp(OUTPUT_FIELD, query=True, text=True)
    result = cmds.fileDialog2(
        caption="Save Maya Soft Selection Reference",
        fileMode=0,
        fileFilter="JSON (*.json)",
        startingDirectory=os.path.dirname(current),
    )
    if result:
        cmds.textFieldButtonGrp(OUTPUT_FIELD, edit=True, text=result[0])


def show():
    """Show the Maya validation window."""

    if cmds.window(WINDOW_NAME, exists=True):
        cmds.deleteUI(WINDOW_NAME, window=True)
    window = cmds.window(WINDOW_NAME, title="Clarity — Maya Soft Selection Oracle", sizeable=False)
    cmds.columnLayout(adjustableColumn=True, rowSpacing=8, columnAttach=("both", 10))
    cmds.text(
        label=(
            "Независимая проверка Maya Soft Selection\n"
            "Rich Selection API + настоящий Maya ramp evaluator"
        ),
        align="left",
    )
    cmds.textFieldButtonGrp(
        OUTPUT_FIELD,
        label="JSON",
        text=DEFAULT_OUTPUT,
        buttonLabel="Выбрать…",
        buttonCommand=_choose_output,
        adjustableColumn=2,
        columnWidth3=(45, 520, 80),
    )
    cmds.button(
        label="ПРОВЕРИТЬ ВСЁ И СОХРАНИТЬ ЭТАЛОН",
        height=44,
        command=_run_from_ui,
        backgroundColor=(0.22, 0.48, 0.26),
    )
    cmds.text(
        label=(
            "Исходный файл не перезаписывается; после теста "
            "сцена восстанавливается. Undo очищается."
        ),
        align="left",
    )
    cmds.showWindow(window)
    cmds.window(window, edit=True, widthHeight=(680, 178))
    return window


if __name__ == "__main__":
    show()
