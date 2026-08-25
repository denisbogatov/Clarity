"""Utility functions for working with objects in Blender."""

import logging
import re
from dataclasses import dataclass

import bpy
from bpy.types import Context, LayerCollection, Object, SpaceView3D

from ..classes.data.validation_results import ObjectNameValidationResult
from ..classes.exceptions.blender_exceptions import UnexpectedSpaceTypeError

logger = logging.getLogger(__name__)


# TODO: Handle USD cases.
def fix_object_names(object_results: list[ObjectNameValidationResult]):
    """Fix object names from a list of object name validation results.

    Args:
        object_results: The results to fix.
        export_format: The format being exported to.

    """
    for result in object_results:
        pattern = "|".join(re.escape(substring) for substring in result.invalid_name_substrings)
        cleaned_name = re.sub(pattern, "_", result.target_object.name)

        if cleaned_name != result.target_object.name:
            result.target_object.name = cleaned_name


@dataclass(frozen=True)
class _LayerVisibility:
    """Layer collection visibility state."""

    excluded: bool
    hidden: bool


@dataclass(frozen=True)
class _ObjectVisibilityState:
    """Object visibility state."""

    hide_viewport: bool
    hide_view_layer: bool


def unhide_all_objects(context: Context) -> ():
    """Reveal any hidden objects or layers in the Blender scene.

    Args:
        context: The current Blender context.

    Returns:
        A function that can be used to restore the scene visibility.

    Raises:
        UnexpectedSpaceTypeError: If function is called on a non-view3d space.

    """
    space_data = context.space_data
    if not isinstance(space_data, SpaceView3D):
        raise UnexpectedSpaceTypeError(space_data, SpaceView3D)

    local_view = space_data.local_view
    view_layer = context.view_layer
    layer_dictionary: dict[LayerCollection, _LayerVisibility] = {}
    object_dictionary: dict[Object, _ObjectVisibilityState] = {}
    local_objects: list[Object] = []
    local_active: Object | None = None

    if local_view:
        depsgraph = context.evaluated_depsgraph_get()
        local_objects = [obj for obj in bpy.data.objects if obj.evaluated_get(depsgraph).local_view_get(space_data)]
        local_active = view_layer.objects.active

    def restore_visibility():
        """Restore the scene visibility."""
        for layer, state in layer_dictionary.items():
            layer.exclude = state.excluded
            layer.hide_viewport = state.hidden

        for obj, state in object_dictionary.items():
            obj.hide_viewport = state.hide_viewport
            obj.hide_set(state.hide_view_layer)

        if local_objects or local_active:
            bpy.ops.object.select_all(action="DESELECT")
            for obj in local_objects:
                obj.select_set(True)
            if local_active:
                view_layer.objects.active = local_active
            bpy.ops.view3d.localview(frame_selected=False)
            bpy.ops.object.select_all(action="DESELECT")

    return restore_visibility


def delete_objects(objects: list[Object]):
    """Delete objects from the scene.

    Args:
        objects: The objects to delete.

    """
    for obj in objects:
        bpy.data.objects.remove(obj, do_unlink=True)


def mark_edges(context: Context, objects: list[Object], mark_seams: bool, mark_sharp: bool):
    """Mark UV island boundary edges with the sharp/seam properties as defined by the user.

    Args:
        context: The current Blender context.
        objects: The objects to mark.
        mark_seams: Whether to mark edges as seams.
        mark_sharp: Whether to mark edges as sharp.

    """
    if not objects:
        return

    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    context.view_layer.objects.active = objects[0]

    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.select_all(action="SELECT")
    if mark_seams:
        bpy.ops.mesh.mark_seam(clear=True)
    if mark_sharp:
        bpy.ops.mesh.mark_sharp(clear=True)

    bpy.ops.uv.seams_from_islands(mark_seams=mark_seams, mark_sharp=mark_sharp)
    bpy.ops.object.mode_set(mode="OBJECT")


def has_unapplied_scale(objects: list[Object]) -> bool:
    """Check if any objects have a non-identity scale.

    Args:
        objects: The objects to check.

    Returns:
        True if any object has a scale other than (1, 1, 1).

    """
    from mathutils import Vector

    unit_scale = Vector((1.0, 1.0, 1.0))
    return any(Vector(obj.scale) != unit_scale for obj in objects)


def apply_modifiers(objs: list[Object]):
    """Apply modifiers to the given objects.

    Args:
        objs: The objects to apply modifiers to.

    """
    original_active = bpy.context.view_layer.objects.active
    original_selection = list(bpy.context.selected_objects)

    for obj in objs:
        if obj.type != "MESH":
            continue

        if not obj.modifiers:
            continue

        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)

        for modifier in list(obj.modifiers):
            try:
                bpy.ops.object.modifier_apply(modifier=modifier.name)
            except RuntimeError as e:
                logger.error(e)

        obj.select_set(False)

    for obj in original_selection:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = original_active
