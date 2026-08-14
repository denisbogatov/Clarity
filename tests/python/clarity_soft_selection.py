# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Integration contract for Maya-compatible Soft Selection.

The native ``editor_transform`` suite owns exact ramp math. These tests exercise the complete
operator path: edit-mesh conversion, world/surface distance selection, radius persistence and
multi-object scope. A unit Z translation makes every resulting vertex Z coordinate equal to its
soft-selection weight, which keeps the oracle direct and independent of viewport drawing.
"""

import json
import math
import os
import unittest

import bmesh
import bpy
from bl_ui.space_view3d import (
    VIEW3D_OT_soft_selection_hotkey,
    _draw_soft_selection_header_button,
    _soft_selection_curve_evaluate,
)


MAYA_PRESETS = {
    'SOFT': "1,0,2,0,1,2",
    'MEDIUM': "1,0.5,2,0,1,2,1,0,2",
    'LINEAR': "0,1,0,1,0,1,0,1,1",
    'HARD': "1,0,0,0,1,2",
    'CRATER': "0,0,2,1,0.8,2,0,1,2",
    'WAVE': "1,0,2,0,0.16,2,0.75,0.32,2,0,0.48,2,0.25,0.64,2,0,0.8,2,0,1,2",
    'STAIRS': "1,0,1,0.75,0.25,1,0.5,0.5,1,0.75,0.25,1,0.25,0.75,1,1,0.249,1,0.749,0.499,1,0.499,0.749,1",
    'RING': "0,0.25,2,1,0.5,2,0,0.75,2",
    'SINE': "1,0,2,0,0.16,2,1,0.32,2,0,0.48,2,1,0.64,2,0,0.8,2,0,1,2",
}


def _decode_maya_curve(encoded):
    values = [float(value) for value in encoded.split(',')]
    return [
        (values[index], values[index + 1], int(values[index + 2]))
        for index in range(0, len(values), 3)
    ]


def _clear_scene():
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)


def _mesh_object(name, vertices, edges=(), faces=()):
    mesh = bpy.data.meshes.new(name + "Mesh")
    mesh.from_pydata(vertices, edges, faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _enter_edit(objects, active, selected_vertices):
    bpy.ops.object.select_all(action='DESELECT')
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = active
    bpy.context.tool_settings.mesh_select_mode = (True, False, False)
    bpy.ops.object.mode_set(mode='EDIT')

    # Newly created meshes enter Edit Mode with all components selected on some builds. Edit the
    # live BMesh rather than the object-mode Mesh flags so the transform converter sees the exact
    # selection immediately and consistently in multi-object Edit Mode.
    for obj in objects:
        selected = selected_vertices.get(obj.name, set())
        edit_mesh = bmesh.from_edit_mesh(obj.data)
        edit_mesh.verts.ensure_lookup_table()
        edit_mesh.verts.index_update()
        for face in edit_mesh.faces:
            face.select_set(False)
        for edge in edit_mesh.edges:
            edge.select_set(False)
        for vertex in edit_mesh.verts:
            vertex.select_set(False)
        for index in selected:
            edit_mesh.verts[index].select_set(True)
        edit_mesh.select_flush_mode()
        bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
        actual = {vertex.index for vertex in edit_mesh.verts if vertex.select}
        if actual != selected:
            raise AssertionError(
                "failed to establish edit selection for {}: expected {}, got {}".format(
                    obj.name, sorted(selected), sorted(actual)
                )
            )


def _translate_with_soft_selection(mode, radius=2.0):
    settings = bpy.context.scene.tool_settings
    settings.soft_selection.falloff_mode = mode
    settings.soft_selection.radius = radius
    settings.use_proportional_edit = True
    result = bpy.ops.transform.translate(
        value=(0.0, 0.0, 1.0),
        orient_type='GLOBAL',
        use_proportional_edit=True,
    )
    if 'FINISHED' not in result:
        raise AssertionError("soft-selection transform did not finish: {!r}".format(result))
    bpy.ops.object.mode_set(mode='OBJECT')


def _z_values(obj):
    return [vertex.co.z for vertex in obj.data.vertices]


def _maya_oracle(test_case):
    fixture = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "soft_selection_reference",
        "fixtures",
        "maya_soft_selection_reference.json",
    )
    if not os.path.exists(fixture):
        test_case.skipTest("run the one-click Maya reference harness to create the oracle fixture")
    with open(fixture, "r", encoding="utf-8") as handle:
        oracle = json.load(handle)
    test_case.assertTrue(oracle["passed"], "the committed Maya oracle contains failed checks")
    return oracle


def _captured_weights(capture, object_name):
    for path, weights in capture["vertex_weights"].items():
        if path.rsplit('|', 1)[-1] == object_name:
            return weights
    raise AssertionError("Maya capture has no vertex weights for {!r}".format(object_name))


def _z_deltas(obj, initial_vertices):
    return [
        vertex.co.z - initial[2]
        for vertex, initial in zip(obj.data.vertices, initial_vertices)
    ]


class SoftSelectionTest(unittest.TestCase):
    def setUp(self):
        _clear_scene()
        bpy.ops.view3d.soft_selection_reset()

    def tearDown(self):
        _clear_scene()

    def assertFloatSequence(self, actual, expected, tolerance=1e-5):
        self.assertEqual(len(actual), len(expected))
        for index, (actual_value, expected_value) in enumerate(zip(actual, expected)):
            self.assertTrue(
                math.isclose(actual_value, expected_value, abs_tol=tolerance),
                "index {}: expected {}, got {}".format(index, expected_value, actual_value),
            )

    def test_factory_settings_are_maya_2025_defaults(self):
        tool_settings = bpy.context.scene.tool_settings
        settings = tool_settings.soft_selection
        self.assertFalse(tool_settings.use_proportional_edit)
        self.assertEqual(settings.falloff_mode, 'VOLUME')
        self.assertEqual(settings.radius, 5.0)
        self.assertEqual(len(settings.curve_points), 2)
        self.assertFloatSequence(
            [
                settings.curve_points[0].value,
                settings.curve_points[0].position,
                settings.curve_points[1].value,
                settings.curve_points[1].position,
            ],
            [1.0, 0.0, 0.0, 1.0],
        )
        self.assertEqual(settings.curve_points[0].interpolation, 'SMOOTH')
        self.assertEqual(settings.curve_points[1].interpolation, 'SMOOTH')
        self.assertTrue(settings.use_falloff_color)
        self.assertEqual(settings.falloff_color.interpolation, 'LINEAR')
        self.assertEqual(len(settings.falloff_color.elements), 3)
        self.assertFloatSequence(
            [element.position for element in settings.falloff_color.elements],
            [0.0, 0.5, 1.0],
        )
        self.assertFloatSequence(
            [channel for element in settings.falloff_color.elements for channel in element.color],
            [
                0.0, 0.0, 0.0, 1.0,
                1.0, 0.0, 0.0, 1.0,
                1.0, 1.0, 0.0, 1.0,
            ],
        )
        self.assertEqual(
            settings.falloff_color.path_from_id(),
            "tool_settings.soft_selection.falloff_color",
        )
        self.assertEqual(
            settings.falloff_color.elements[1].path_from_id(),
            "tool_settings.soft_selection.falloff_color.elements[1]",
        )

    def test_b_radius_math_matches_maya_relative_and_absolute_contract(self):
        radius_from_drag = VIEW3D_OT_soft_selection_hotkey._radius_from_drag
        self.assertAlmostEqual(radius_from_drag(5.0, 30.0, 10.0, False), 8.0)
        self.assertAlmostEqual(radius_from_drag(5.0, -30.0, 10.0, False), 2.0)
        self.assertAlmostEqual(radius_from_drag(999.0, 30.0, 10.0, True), 3.0)
        self.assertAlmostEqual(radius_from_drag(999.0, -30.0, 10.0, True), 3.0)
        self.assertAlmostEqual(
            radius_from_drag(1.0, -1000.0, 10.0, False),
            VIEW3D_OT_soft_selection_hotkey._MIN_RADIUS,
        )
        self.assertAlmostEqual(
            radius_from_drag(1.0, 1000000.0, 1.0, False),
            VIEW3D_OT_soft_selection_hotkey._MAX_RADIUS,
        )

    def test_viewport_false_color_is_evaluated_from_final_selection_weight(self):
        settings = bpy.context.scene.tool_settings.soft_selection
        ramp = settings.falloff_color

        self.assertFloatSequence(
            [
                _soft_selection_curve_evaluate(settings, distance)
                for distance in (0.0, 0.25, 0.5, 0.75, 1.0)
            ],
            (1.0, 0.84375, 0.5, 0.15625, 0.0),
        )

        # Autodesk's enableFalseColor/softSelectColorCurve contract uses the final rich-selection
        # weight as input: black at 0, red at 0.5 and yellow at 1 by default.
        self.assertFloatSequence(ramp.evaluate(0.0), (0.0, 0.0, 0.0, 1.0))
        self.assertFloatSequence(ramp.evaluate(0.25), (0.5, 0.0, 0.0, 1.0))
        self.assertFloatSequence(ramp.evaluate(0.5), (1.0, 0.0, 0.0, 1.0))
        self.assertFloatSequence(ramp.evaluate(0.75), (1.0, 0.5, 0.0, 1.0))
        self.assertFloatSequence(ramp.evaluate(1.0), (1.0, 1.0, 0.0, 1.0))

        # Viewport Color is feedback only. It must never alter transformation weights.
        settings.use_falloff_color = False
        obj = _mesh_object("FalseColorOff", [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)])
        _enter_edit([obj], obj, {obj.name: {0}})
        _translate_with_soft_selection('VOLUME', radius=2.0)
        self.assertFloatSequence(_z_values(obj), (1.0, 0.5))

    def test_factory_false_color_matches_captured_maya_curve(self):
        oracle = _maya_oracle(self)
        expected = oracle["factory_color_curve"]
        actual = sorted(
            bpy.context.scene.tool_settings.soft_selection.falloff_color.elements,
            key=lambda element: element.position,
        )
        self.assertEqual(len(actual), len(expected))
        self.assertFloatSequence(
            [element.position for element in actual],
            [point["weight"] for point in expected],
        )
        self.assertFloatSequence(
            [channel for element in actual for channel in element.color[:3]],
            [channel for point in expected for channel in point["color"]],
        )

    def test_soft_select_toggle_is_one_maya_state_across_object_and_edit_modes(self):
        tool_settings = bpy.context.scene.tool_settings
        self.assertFalse(tool_settings.use_proportional_edit)
        self.assertFalse(tool_settings.use_proportional_edit_objects)
        self.assertIn('FINISHED', bpy.ops.view3d.soft_selection_toggle())
        self.assertTrue(tool_settings.use_proportional_edit)
        self.assertTrue(tool_settings.use_proportional_edit_objects)
        self.assertIn('FINISHED', bpy.ops.view3d.soft_selection_toggle())
        self.assertFalse(tool_settings.use_proportional_edit)
        self.assertFalse(tool_settings.use_proportional_edit_objects)

    def test_header_uses_one_compound_toggle_and_settings_control(self):
        class Layout:
            def __init__(self):
                self.operator_calls = []
                self.popover_calls = []

            def operator(self, operator, **keywords):
                self.operator_calls.append((operator, keywords))

            def popover(self, **keywords):
                self.popover_calls.append(keywords)

        class Context:
            mode = 'EDIT_MESH'

        tool_settings = bpy.context.scene.tool_settings
        tool_settings.use_proportional_edit = True
        tool_settings.soft_selection.falloff_mode = 'SURFACE'
        layout = Layout()

        _draw_soft_selection_header_button(
            layout, Context(), tool_settings, "use_proportional_edit")

        self.assertEqual(len(layout.operator_calls), 1)
        operator, keywords = layout.operator_calls[0]
        self.assertEqual(operator, "view3d.soft_selection_toggle")
        self.assertEqual(keywords["icon"], 'PROP_CON')
        self.assertTrue(keywords["depress"])
        self.assertEqual(len(layout.popover_calls), 1)
        self.assertEqual(layout.popover_calls[0]["panel"], "VIEW3D_PT_soft_selection")
        self.assertNotIn("icon", layout.popover_calls[0])

        tool_settings.use_proportional_edit = False
        layout = Layout()
        _draw_soft_selection_header_button(
            layout, Context(), tool_settings, "use_proportional_edit")
        self.assertEqual(len(layout.operator_calls), 1)
        _, keywords = layout.operator_calls[0]
        self.assertEqual(keywords["icon"], 'PROP_OFF')
        self.assertFalse(keywords["depress"])
        self.assertEqual(len(layout.popover_calls), 1)

    def test_all_factory_curve_presets_round_trip_without_loss(self):
        interpolation_names = ('NONE', 'LINEAR', 'SMOOTH', 'SPLINE')
        settings = bpy.context.scene.tool_settings.soft_selection
        for preset, encoded in MAYA_PRESETS.items():
            with self.subTest(preset=preset):
                result = bpy.ops.view3d.soft_selection_curve_preset(preset=preset)
                self.assertIn('FINISHED', result)
                expected = _decode_maya_curve(encoded)
                self.assertEqual(len(settings.curve_points), len(expected))
                for actual, (value, position, interpolation) in zip(
                        settings.curve_points, expected):
                    self.assertAlmostEqual(actual.value, value, places=6)
                    self.assertAlmostEqual(actual.position, position, places=6)
                    self.assertEqual(actual.interpolation, interpolation_names[interpolation])

    def test_curves_match_captured_maya_ramp_oracle(self):
        oracle = _maya_oracle(self)

        radius = 10.0
        for preset in MAYA_PRESETS:
            with self.subTest(preset=preset):
                samples = oracle["ramps"][preset.lower()]["samples"]
                self.assertEqual(len(samples), 41)
                obj = _mesh_object(
                    "Oracle" + preset.title(),
                    [(sample["position"] * radius, 0.0, 0.0) for sample in samples],
                    [],
                )
                bpy.ops.view3d.soft_selection_curve_preset(preset=preset)
                self.assertFloatSequence(
                    [
                        _soft_selection_curve_evaluate(
                            bpy.context.scene.tool_settings.soft_selection,
                            sample["position"],
                        )
                        for sample in samples
                    ],
                    [sample["value"] for sample in samples],
                    tolerance=3e-5,
                )
                _enter_edit([obj], obj, {obj.name: {0}})
                _translate_with_soft_selection('VOLUME', radius=radius)

                # The explicitly selected component always has a hard weight of 1.0 in Maya and
                # Clarity, even for presets such as Crater whose mathematical ramp starts at 0.
                expected = [1.0] + [sample["value"] for sample in samples[1:]]
                self.assertFloatSequence(_z_values(obj), expected, tolerance=3e-5)
            _clear_scene()

        interpolation_curves = {
            'none': "1,0,0,0,1,0",
            'linear': "1,0,1,0,1,1",
            'smooth': "1,0,2,0,1,2",
            'spline': "1,0,3,0,1,3",
            'spline_neighbors': "1,0,3,0.2,0.25,3,0.9,0.7,3,0,1,3",
        }
        settings = bpy.context.scene.tool_settings.soft_selection
        for name, encoded in interpolation_curves.items():
            with self.subTest(interpolation=name):
                samples = oracle["ramps"]["interpolation_contract"][name]
                points = _decode_maya_curve(encoded)
                settings.curve_point_count = len(points)
                for point, (value, position, interpolation) in zip(
                        settings.curve_points, points):
                    point.value = value
                    point.position = position
                    point.interpolation = ('NONE', 'LINEAR', 'SMOOTH', 'SPLINE')[interpolation]
                obj = _mesh_object(
                    "Oracle" + name.title(),
                    [(index * radius / 40.0, 0.0, 0.0) for index in range(41)],
                    [],
                )
                _enter_edit([obj], obj, {obj.name: {0}})
                _translate_with_soft_selection('VOLUME', radius=radius)
                self.assertFloatSequence(
                    _z_values(obj), [1.0] + samples[1:], tolerance=3e-5
                )
            _clear_scene()

    def test_geometry_matches_captured_maya_rich_selection_oracle(self):
        geometry = _maya_oracle(self)["geometry"]

        disconnected_vertices = [
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (1.0, 1.0, 0.0),
            (0.0, 1.0, 0.0),
            (0.25, 0.25, 0.2),
            (1.25, 0.25, 0.2),
            (1.25, 1.25, 0.2),
            (0.25, 1.25, 0.2),
        ]
        disconnected_faces = [(0, 1, 2, 3), (4, 5, 6, 7)]
        for mode, case_name in (
                ('VOLUME', "disconnected_volume"),
                ('SURFACE', "disconnected_surface")):
            with self.subTest(case=case_name):
                obj = _mesh_object(
                    "DisconnectedShells",
                    disconnected_vertices,
                    faces=disconnected_faces,
                )
                _enter_edit([obj], obj, {obj.name: {0}})
                _translate_with_soft_selection(mode, radius=2.0)
                self.assertFloatSequence(
                    _z_deltas(obj, disconnected_vertices),
                    _captured_weights(geometry[case_name], "DisconnectedShells"),
                    tolerance=3e-4,
                )
            _clear_scene()

        centerline = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.1, 1.0)]
        folded_vertices = []
        for x, y in centerline:
            folded_vertices.extend([(x, y, 0.0), (x, y, 0.1)])
        folded_faces = [(0, 2, 3, 1), (2, 4, 5, 3), (4, 6, 7, 5)]
        for mode, case_name in (
                ('VOLUME', "folded_volume"),
                ('SURFACE', "folded_surface")):
            with self.subTest(case=case_name):
                obj = _mesh_object("FoldedStrip", folded_vertices, faces=folded_faces)
                _enter_edit([obj], obj, {obj.name: {0}})
                _translate_with_soft_selection(mode, radius=1.5)
                self.assertFloatSequence(
                    _z_deltas(obj, folded_vertices),
                    _captured_weights(geometry[case_name], "FoldedStrip"),
                    tolerance=3e-4,
                )
            _clear_scene()

        sources_vertices = [(float(x), 0.0, 0.0) for x in range(5)]
        sources_vertices.extend((float(x), 0.1, 0.0) for x in range(5))
        sources_faces = [(x, x + 1, x + 6, x + 5) for x in range(4)]
        obj = _mesh_object("MultipleSources", sources_vertices, faces=sources_faces)
        _enter_edit([obj], obj, {obj.name: {0, 4}})
        _translate_with_soft_selection('VOLUME', radius=1.5)
        self.assertFloatSequence(
            _z_deltas(obj, sources_vertices),
            _captured_weights(geometry["multiple_sources"], "MultipleSources"),
            tolerance=3e-4,
        )
        _clear_scene()

        scaled_vertices = [
            (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0),
            (0.0, 0.1, 0.0), (1.0, 0.1, 0.0), (2.0, 0.1, 0.0),
        ]
        scaled_faces = [(0, 1, 4, 3), (1, 2, 5, 4)]
        obj = _mesh_object("Scaled", scaled_vertices, faces=scaled_faces)
        obj.scale.x = 2.0
        _enter_edit([obj], obj, {obj.name: {0}})
        _translate_with_soft_selection('VOLUME', radius=3.0)
        self.assertFloatSequence(
            _z_deltas(obj, scaled_vertices),
            _captured_weights(geometry["nonuniform_scale"], "Scaled"),
            tolerance=3e-4,
        )
        _clear_scene()

        subject_vertices = [
            (0.0, 0.0, 0.0), (1.0, 0.0, 0.0),
            (1.0, 0.2, 0.0), (0.0, 0.2, 0.0),
        ]
        neighbor_vertices = [
            (0.5, 0.0, 0.0), (1.5, 0.0, 0.0),
            (1.5, 0.2, 0.0), (0.5, 0.2, 0.0),
        ]
        for mode, case_name in (
                ('VOLUME', "multiple_objects_volume"),
                ('GLOBAL', "multiple_objects_global")):
            with self.subTest(case=case_name):
                subject = _mesh_object("Subject", subject_vertices, faces=[(0, 1, 2, 3)])
                neighbor = _mesh_object("Neighbor", neighbor_vertices, faces=[(0, 1, 2, 3)])
                _enter_edit(
                    [subject, neighbor], subject, {subject.name: {0}, neighbor.name: set()}
                )
                _translate_with_soft_selection(mode, radius=2.0)
                self.assertFloatSequence(
                    _z_deltas(subject, subject_vertices),
                    _captured_weights(geometry[case_name], "Subject"),
                    tolerance=3e-4,
                )
                self.assertFloatSequence(
                    _z_deltas(neighbor, neighbor_vertices),
                    _captured_weights(geometry[case_name], "Neighbor"),
                    tolerance=3e-4,
                )
            _clear_scene()

    def test_volume_crosses_disconnected_shells_but_surface_does_not(self):
        vertices = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.5, 0.25, 0.0), (1.5, 0.25, 0.0)]
        edges = [(0, 1), (2, 3)]

        volume = _mesh_object("Volume", vertices, edges)
        _enter_edit([volume], volume, {volume.name: {0}})
        _translate_with_soft_selection('VOLUME')
        # Maya factory smooth interpolation: 1 - smoothstep(normalized distance).
        self.assertFloatSequence(_z_values(volume), [1.0, 0.5, 0.8092982, 0.1447743])

        _clear_scene()
        surface = _mesh_object("Surface", vertices, edges)
        _enter_edit([surface], surface, {surface.name: {0}})
        _translate_with_soft_selection('SURFACE')
        self.assertFloatSequence(_z_values(surface), [1.0, 0.5, 0.0, 0.0])

    def test_surface_uses_path_length_instead_of_chord_distance(self):
        obj = _mesh_object(
            "FoldedPath",
            [(0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 2.0, 0.0), (0.1, 0.0, 0.0)],
            [(0, 1), (1, 2), (2, 3)],
        )
        _enter_edit([obj], obj, {obj.name: {0}})
        _translate_with_soft_selection('SURFACE', radius=3.0)
        values = _z_values(obj)
        self.assertAlmostEqual(values[0], 1.0, places=6)
        self.assertGreater(values[1], 0.0)
        self.assertGreater(values[2], 0.0)
        self.assertAlmostEqual(values[3], 0.0, places=6)

    def test_multiple_selected_components_use_the_nearest_source(self):
        obj = _mesh_object(
            "MultipleSources",
            [(float(x), 0.0, 0.0) for x in range(5)],
            [(x, x + 1) for x in range(4)],
        )
        _enter_edit([obj], obj, {obj.name: {0, 4}})
        _translate_with_soft_selection('VOLUME', radius=1.5)
        self.assertFloatSequence(_z_values(obj), [1.0, 0.2592593, 0.0, 0.2592593, 1.0])

    def test_global_is_the_only_mode_reaching_an_unselected_edit_object(self):
        subject = _mesh_object("Subject", [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)], [(0, 1)])
        neighbor = _mesh_object("Neighbor", [(0.5, 0.0, 0.0), (1.5, 0.0, 0.0)], [(0, 1)])
        _enter_edit([subject, neighbor], subject, {subject.name: {0}, neighbor.name: set()})
        _translate_with_soft_selection('VOLUME')
        self.assertFloatSequence(_z_values(neighbor), [0.0, 0.0])

        _clear_scene()
        subject = _mesh_object("Subject", [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)], [(0, 1)])
        neighbor = _mesh_object("Neighbor", [(0.5, 0.0, 0.0), (1.5, 0.0, 0.0)], [(0, 1)])
        _enter_edit([subject, neighbor], subject, {subject.name: {0}, neighbor.name: set()})
        _translate_with_soft_selection('GLOBAL')
        self.assertFloatSequence(_z_values(neighbor), [0.84375, 0.15625])

    def test_custom_none_and_linear_segments_drive_transform_weights(self):
        obj = _mesh_object(
            "Curve",
            [(0.0, 0.0, 0.0), (0.5, 0.0, 0.0), (1.0, 0.0, 0.0)],
            [(0, 1), (1, 2)],
        )
        settings = bpy.context.scene.tool_settings.soft_selection
        settings.curve_point_count = 2
        settings.curve_points[0].position = 0.0
        settings.curve_points[0].value = 1.0
        settings.curve_points[0].interpolation = 'NONE'
        settings.curve_points[1].position = 1.0
        settings.curve_points[1].value = 0.0
        settings.curve_points[1].interpolation = 'LINEAR'
        _enter_edit([obj], obj, {obj.name: {0}})
        _translate_with_soft_selection('VOLUME', radius=1.0)
        self.assertFloatSequence(_z_values(obj), [1.0, 1.0, 0.0])

    def test_object_mode_uses_maya_curve_and_its_own_radius(self):
        selected = _mesh_object("Selected", [(0.0, 0.0, 0.0)], [])
        neighbor = _mesh_object("Neighbor", [(0.0, 0.0, 0.0)], [])
        selected.location.x = 0.0
        neighbor.location.x = 1.0
        bpy.ops.object.select_all(action='DESELECT')
        selected.select_set(True)
        bpy.context.view_layer.objects.active = selected

        tool_settings = bpy.context.scene.tool_settings
        tool_settings.use_proportional_edit_objects = True
        tool_settings.soft_selection.radius = 2.0
        tool_settings.proportional_distance = 0.25
        result = bpy.ops.transform.translate(
            value=(0.0, 0.0, 1.0),
            orient_type='GLOBAL',
            use_proportional_edit=True,
        )
        self.assertIn('FINISHED', result)
        self.assertAlmostEqual(selected.location.z, 1.0, places=6)
        self.assertAlmostEqual(neighbor.location.z, 0.5, places=6)
        self.assertAlmostEqual(tool_settings.soft_selection.radius, 2.0, places=6)


if __name__ == "__main__":
    # Blender's own command-line options remain in sys.argv for scripts started with --python.
    # Passing a clean argv prevents unittest from interpreting --background, --factory-startup,
    # and the other Blender launcher flags as test-runner options.
    unittest.main(argv=[__file__])
