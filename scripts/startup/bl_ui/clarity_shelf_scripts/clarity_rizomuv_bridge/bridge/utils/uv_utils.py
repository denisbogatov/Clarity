"""Utility functions for working with UV maps in Blender."""

from typing import cast

import bpy
from bpy.types import Context, Mesh, Object

from ..classes.exceptions.blender_exceptions import UnexpectedObjectTypeError


def unwrap_uvs(context: Context, uvmap_name: str, object: Object, all_uvmaps: bool):
    """Unwrap UVs on the given mesh objects using the built in blender unwrap operator.

    Args:
        context: The current blender context.
        uvmap_name: The name of the uvmap to unwrap.
        object: The object to unwrap UVs.
        all_uvmaps: Whether to unwrap all UV maps on the object or just the given map

    """

    def unwrap():
        bpy.ops.uv.select_all(action="SELECT")
        bpy.ops.uv.weld()
        bpy.ops.uv.unwrap(margin=0.01)
        bpy.ops.uv.select_all(action="DESELECT")

    context.view_layer.objects.active = object
    data = cast(Mesh, object.data)
    active_map = data.uv_layers[uvmap_name]
    data.uv_layers.active = active_map

    bpy.ops.object.mode_set(mode="EDIT")
    unwrap()

    if all_uvmaps:
        for uvmap in data.uv_layers:
            if uvmap.name != uvmap_name:
                data.uv_layers.active = uvmap
                unwrap()

    data.uv_layers.active = active_map
    bpy.ops.object.mode_set(mode="OBJECT")


def pop_uvmaps(object: Object, count: int):
    """Pop the given number of UV maps from the object.

    Args:
        object: The object to pop UV maps from.
        count: The number of UV maps to pop.

    Raises:
        UnexpectedObjectTypeError: If the object is not a mesh.

    """
    if object.type != "MESH":
        raise UnexpectedObjectTypeError(object, Mesh)

    data = cast(Mesh, object.data)
    for _ in range(count):
        if len(data.uv_layers) > 0:
            data.uv_layers.remove(data.uv_layers[-1])


def add_uvmaps(object: Object, count: int):
    """Add the given number of UV maps to the object.

    Args:
        object: The object to add UV maps to.
        count: The number of UV maps to add.

    Raises:
        UnexpectedObjectTypeError: If the object is not a mesh.

    """
    if object.type != "MESH":
        raise UnexpectedObjectTypeError(object, Mesh)

    data = cast(Mesh, object.data)
    for _ in range(count):
        data.uv_layers.new()
