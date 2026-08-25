"""Functions for working with blender object hierarchies."""

import bpy
from bpy.types import Context, Object


def flatten_object_hierarchy(context: Context, objects: list[Object]):
    """Flatten the given objects into a single object hierarchy so no parent/child relationships exist.

    Args:
        context: The current blender context.
        objects: The objects to flatten.

    Returns:
        A function that can be used to restore the original hierarchy.

    """
    active_object = context.active_object

    relationships = {}
    for obj in objects:
        relationships[obj] = obj.parent

    for obj in objects:
        if obj.parent is not None:
            context.view_layer.objects.active = obj.parent
            bpy.ops.object.parent_clear(type="CLEAR_KEEP_TRANSFORM")

    context.view_layer.objects.active = active_object

    def restore_hierarchy():
        for obj in objects:
            obj.parent = relationships[obj]
            if obj.parent:
                obj.matrix_parent_inverse = obj.parent.matrix_world.inverted()

    return restore_hierarchy
