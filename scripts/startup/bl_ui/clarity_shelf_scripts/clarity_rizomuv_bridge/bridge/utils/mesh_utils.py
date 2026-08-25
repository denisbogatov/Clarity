"""Functions for editing blender object data and properties."""

from typing import cast

import bmesh
import bpy
from bpy.types import Context, Mesh, Object


def triangulate(context: Context, target_objects: list[Object]):
    """Triangulate the given mesh objects.

    Args:
        context: The current blender context.
        target_objects: The objects to triangulate.

    """
    mode = context.mode
    if mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")

    for obj in target_objects:
        mesh_data = cast(Mesh, obj.data)
        bm = bmesh.new()
        bm.from_mesh(mesh_data)
        bmesh.ops.triangulate(bm, faces=list(bm.faces))
        bm.select_flush(True)
        bm.to_mesh(mesh_data)
