"""Application-level Custom Pivot persistence, copy, and undo regression test."""

import os

import bpy


def assert_matrix_near(actual, expected, tolerance=1.0e-6):
    for row in range(4):
        for column in range(4):
            assert abs(actual[row][column] - expected[row][column]) <= tolerance


bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_cube_add()
subject = bpy.context.object
subject.name = "CustomPivotLifecycleSubject"
subject.location = (1.25, -2.5, 3.75)
subject.rotation_euler = (0.2, -0.4, 0.7)
subject.scale = (2.0, -0.5, 1.25)
assert subject.transform_model == 'BLENDER'
assert subject.custom_pivot is None

pivot = subject.custom_pivot_ensure()
assert not pivot.is_rotate_pivot_valid
assert not pivot.is_scale_pivot_valid
pivot.rotate_pivot = (0.5, -1.0, 2.0)
# Writing one pivot must not activate the other one.
assert pivot.is_rotate_pivot_valid
assert not pivot.is_scale_pivot_valid
pivot.scale_pivot = (-0.75, 1.5, 0.25)
assert pivot.is_rotate_pivot_valid
assert pivot.is_scale_pivot_valid
pivot.orientation = (0.9238795325, 0.0, 0.3826834324, 0.0)

child = bpy.data.objects.new("CustomPivotLifecycleChild", None)
bpy.context.collection.objects.link(child)
child.parent = subject
child.location = (2.0, 1.0, -0.5)

bpy.context.view_layer.update()
world_before = subject.matrix_world.copy()
child_world_before = child.matrix_world.copy()
transform_before = {
    "location": tuple(subject.location),
    "rotation_euler": tuple(subject.rotation_euler),
    "scale": tuple(subject.scale),
}
pivot_before = {
    "rotate_pivot": tuple(pivot.rotate_pivot),
    "scale_pivot": tuple(pivot.scale_pivot),
    "orientation": tuple(pivot.orientation),
}

subject.select_set(True)
bpy.context.view_layer.objects.active = subject
bpy.ops.object.duplicate(linked=True)
duplicate = bpy.context.object
assert duplicate.transform_model == 'BLENDER'
assert duplicate.custom_pivot is not None
assert tuple(duplicate.custom_pivot.rotate_pivot) == pivot_before["rotate_pivot"]
assert tuple(duplicate.custom_pivot.scale_pivot) == pivot_before["scale_pivot"]
assert duplicate.data is subject.data
bpy.data.objects.remove(duplicate, do_unlink=True)

bpy.context.view_layer.objects.active = subject
subject.select_set(True)
# Two pushes, not one: in background mode the memfile undo stack is empty until something
# initializes it, so the first push only becomes the initial state and leaves nothing to step back
# to. The same note is in `bl_global_undo.py`, which is where this pattern comes from.
bpy.ops.ed.undo_push(message="Custom pivot lifecycle initial state")
bpy.ops.ed.undo_push(message="Custom pivot lifecycle before delete")
bpy.ops.object.delete()
bpy.ops.ed.undo()
subject = bpy.data.objects["CustomPivotLifecycleSubject"]
child = bpy.data.objects["CustomPivotLifecycleChild"]
bpy.context.view_layer.update()
assert_matrix_near(subject.matrix_world, world_before)
assert_matrix_near(child.matrix_world, child_world_before)

path = os.path.join(bpy.app.tempdir, "custom_pivot_lifecycle.blend")
bpy.ops.wm.save_as_mainfile(filepath=path, check_existing=False)
bpy.ops.wm.open_mainfile(filepath=path)
subject = bpy.data.objects["CustomPivotLifecycleSubject"]
child = bpy.data.objects["CustomPivotLifecycleChild"]
bpy.context.view_layer.update()

assert subject.transform_model == 'BLENDER'
for name, expected in transform_before.items():
    assert tuple(getattr(subject, name)) == expected
assert subject.custom_pivot is not None
for name, expected in pivot_before.items():
    assert tuple(getattr(subject.custom_pivot, name)) == expected
assert subject.custom_pivot.is_rotate_pivot_valid
assert subject.custom_pivot.is_scale_pivot_valid
assert subject.custom_pivot.is_orientation_valid
assert_matrix_near(subject.matrix_world, world_before)
assert_matrix_near(child.matrix_world, child_world_before)

if os.path.exists(path):
    os.remove(path)
