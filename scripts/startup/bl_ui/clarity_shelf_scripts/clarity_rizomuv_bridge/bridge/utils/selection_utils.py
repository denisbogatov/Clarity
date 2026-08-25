"""Utility functions for working with Blender selections."""

import bpy
from bpy.types import Context, Object


def deselect_non_exportable_objects(context: Context):
    """Deselect all objects that are not exportable (not mesh or empty).

    Args:
        context: The current blender context.

    """
    for obj in bpy.context.selected_objects:
        if obj.type not in {"MESH", "EMPTY"}:
            obj.select_set(False)


def get_selected_meshes() -> list[Object]:
    """Get a list of selected mesh objects.

    Wrapper around bpy.context.selected_objects that handles edge cases.

    Different from bpy.context.selected_objects:
    - Avoids possible bug with selected objects being empty
    - Considers active objects to be selected
    - Filters to only mesh objects

    Returns:
        List[Object]: Selected mesh objects in the scene.

    Raises:
        RuntimeError: If no active scene is found.

    """
    act_obj = bpy.context.active_object
    scene = bpy.context.scene
    if not scene:
        raise RuntimeError(f"No scene found when accessing bpy.context.scene, [{bpy.context.scene}].")

    # context.scene instead of context.selected_objects
    # context weirdness with operators can lead to selected_objects being empty
    sel_objs = [obj for obj in scene.objects if obj.type == "MESH" and obj.select_get()]

    # Covers an edge case where it is possible to have an active object not selected
    if not sel_objs and act_obj is not None and act_obj.type == "MESH":
        act_obj.select_set(True)
        sel_objs = [act_obj]

    return sel_objs


def split_objects_by_shared_data(objects: list[Object]) -> tuple[list[Object], set[Object]]:
    """Separate object instances from selection.

    Args:
        context (Context): The current Blender context.
        objects (list[Object]): The objects to check for instanced objects and separate.

    Returns:
        tuple[list[Object], set[Object]]: The unique objects and instanced objects.

    """
    data_blocks = set()
    unique_objects = []
    instanced_objects = set()

    for obj in objects:
        if obj.data not in data_blocks:
            data_blocks.add(obj.data)
            unique_objects.append(obj)
        else:
            instanced_objects.add(obj)

    return unique_objects, instanced_objects


def get_selected_empties() -> list[Object]:
    """Get a list of selected empty objects.

    Returns:
        list[Object]: Selected empty objects in the scene.

    Raises:
        RuntimeError: If no active scene is found.

    """
    scene = bpy.context.scene
    if not scene:
        raise RuntimeError(f"No scene found when accessing bpy.context.scene, [{bpy.context.scene}].")

    return [obj for obj in scene.objects if obj.type == "EMPTY" and obj.select_get()]


def get_objects_for_export(act_obj: Object, exclude_clones: bool) -> list[Object]:
    """Get the selection of objects for export to RizomUV.

    If the addon preference exclude_clones is set to True, then don't select multiple objects
    which share the same data block.

    Args:
        act_obj (Object): The active object.
        exclude_clones (bool): Whether to exclude clones from the export.

    Returns:
        list[Object]: The objects to export.

    """
    selected_objects = get_selected_meshes()
    if exclude_clones:
        unique, cloned = split_objects_by_shared_data(selected_objects)
        if act_obj in cloned:
            # If the active object is a clone, swap positions with matching data in the unique list.
            for i, obj in enumerate(unique):
                if obj.data == act_obj.data:
                    cloned.remove(act_obj)
                    cloned.add(unique[i])
                    unique[i] = act_obj
                    break
        return unique
    return selected_objects
