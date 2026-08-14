# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Integration contract for Clarity's Maya-style symmetric modeling mode."""

import math
import unittest

import bmesh
import bpy


def _clear_scene():
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)


def _mesh_object(name, vertices, edges=()):
    mesh = bpy.data.meshes.new(name + "Mesh")
    mesh.from_pydata(vertices, edges, ())
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _enter_vertex_edit(obj, selected):
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.context.tool_settings.mesh_select_mode = (True, False, False)
    bpy.ops.object.mode_set(mode='EDIT')
    edit_mesh = bmesh.from_edit_mesh(obj.data)
    edit_mesh.verts.ensure_lookup_table()
    for vertex in edit_mesh.verts:
        vertex.select_set(vertex.index in selected)
    edit_mesh.select_flush_mode()
    bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)


def _translate(value):
    result = bpy.ops.transform.translate(value=value, orient_type='GLOBAL')
    if 'FINISHED' not in result:
        raise AssertionError("symmetry transform did not finish: {!r}".format(result))
    bpy.ops.object.mode_set(mode='OBJECT')


class ClaritySymmetryTest(unittest.TestCase):
    def setUp(self):
        _clear_scene()
        window_manager = bpy.context.window_manager
        window_manager.clarity_interaction_enabled = True
        window_manager.clarity_symmetry_mode = 'OFF'
        window_manager.clarity_symmetry_axis = 'X'
        window_manager.clarity_symmetry_tolerance = 0.001
        window_manager.clarity_symmetry_preserve_seam = True
        window_manager.clarity_symmetry_seam_tolerance = 0.001
        window_manager.clarity_symmetry_allow_partial = True

    def tearDown(self):
        _clear_scene()

    def assertVectorAlmostEqual(self, actual, expected, places=6):
        self.assertEqual(len(actual), len(expected))
        for actual_value, expected_value in zip(actual, expected):
            self.assertAlmostEqual(actual_value, expected_value, places=places)

    def test_object_x_reflects_an_unselected_partner(self):
        obj = _mesh_object("ObjectSpace", [(1.0, 0.0, 0.0), (-1.0, 0.0, 0.0)])
        _enter_vertex_edit(obj, {0})
        bpy.context.window_manager.clarity_symmetry_mode = 'OBJECT'
        _translate((0.0, 1.0, 0.0))
        self.assertVectorAlmostEqual(obj.data.vertices[0].co, (1.0, 1.0, 0.0))
        self.assertVectorAlmostEqual(obj.data.vertices[1].co, (-1.0, 1.0, 0.0))

    def test_world_x_uses_the_world_plane_for_a_rotated_object(self):
        obj = _mesh_object("WorldSpace", [(0.0, -1.0, 0.0), (0.0, 1.0, 0.0)])
        obj.rotation_euler.z = math.radians(90.0)
        bpy.context.view_layer.update()
        _enter_vertex_edit(obj, {0})
        bpy.context.window_manager.clarity_symmetry_mode = 'WORLD'
        _translate((0.0, 1.0, 0.0))
        world = [obj.matrix_world @ vertex.co for vertex in obj.data.vertices]
        world.sort(key=lambda coordinate: coordinate.x)
        self.assertVectorAlmostEqual(world[0], (-1.0, 1.0, 0.0))
        self.assertVectorAlmostEqual(world[1], (1.0, 1.0, 0.0))

    def test_tolerance_accepts_a_slightly_asymmetric_pair(self):
        obj = _mesh_object("Tolerance", [(1.0, 0.0, 0.0), (-1.0005, 0.0, 0.0)])
        _enter_vertex_edit(obj, {0})
        window_manager = bpy.context.window_manager
        window_manager.clarity_symmetry_mode = 'OBJECT'
        window_manager.clarity_symmetry_tolerance = 0.001
        _translate((0.0, 1.0, 0.0))
        self.assertVectorAlmostEqual(obj.data.vertices[1].co, (-1.0, 1.0, 0.0))

    def test_topology_pairs_asymmetric_path_ends(self):
        obj = _mesh_object(
            "Topology",
            [(2.0, 0.0, 0.0), (0.0, 0.0, 0.0), (-1.0, 0.0, 0.0)],
            [(0, 1), (1, 2)],
        )
        _enter_vertex_edit(obj, {0})
        bpy.context.window_manager.clarity_symmetry_mode = 'TOPOLOGY'
        _translate((0.0, 1.0, 0.0))
        self.assertVectorAlmostEqual(obj.data.vertices[0].co, (2.0, 1.0, 0.0))
        self.assertVectorAlmostEqual(obj.data.vertices[2].co, (-2.0, 1.0, 0.0))

    def test_preserve_seam_blocks_only_the_reflection_axis(self):
        obj = _mesh_object("Seam", [(0.0, 0.0, 0.0)])
        _enter_vertex_edit(obj, {0})
        window_manager = bpy.context.window_manager
        window_manager.clarity_symmetry_mode = 'OBJECT'
        window_manager.clarity_symmetry_preserve_seam = True
        _translate((1.0, 2.0, 0.0))
        self.assertVectorAlmostEqual(obj.data.vertices[0].co, (0.0, 2.0, 0.0))

        _enter_vertex_edit(obj, {0})
        window_manager.clarity_symmetry_preserve_seam = False
        _translate((1.0, 0.0, 0.0))
        self.assertVectorAlmostEqual(obj.data.vertices[0].co, (1.0, 2.0, 0.0))


if __name__ == "__main__":
    unittest.main(argv=[__file__])
