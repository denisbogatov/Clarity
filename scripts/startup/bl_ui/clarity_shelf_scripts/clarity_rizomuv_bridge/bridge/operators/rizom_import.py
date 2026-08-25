"""Operator for importing a file from RizomUV and tranferring UV data to objects in Blender."""

import logging
from typing import Callable, cast
from uuid import uuid4

import bpy
from bpy.types import Context, Material, Mesh, Object, Operator, ViewLayer

from ..classes.data.import_models import RizomData
from ..classes.data.import_results import UVTransferResult
from ..classes.exceptions.rizom_exeptions import (
    RizomLegacyConnectionError,
    RizomLinkConnectionError,
    RizomLinkModuleNotFoundError,
    RizomLinkUnsupportedError,
)
from ..classes.rizom.legacy.rizom_legacy import RizomLegacy
from ..classes.rizom.modern.rizom_link import RizomLink
from ..classes.rizom.rizom_base import RizomBase
from ..file_access import get_data_directory
from ..utils import addon_utils, io_utils, object_utils, usd_utils
from ..utils.exceptions_utils import cancel_with_logged_exception
from ..utils.validation_utils import assert_has_equal_polycount

logger = logging.getLogger(__name__)


def _find_view3d_context(context: Context):
    """Find a regular 3D View that can host Blender's import/edit operators."""
    for window in context.window_manager.windows:
        screen = window.screen
        if screen is None:
            continue
        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue
            region = next(
                (candidate for candidate in area.regions if candidate.type == "WINDOW"),
                None,
            )
            if region is not None:
                return window, area, region
    return None


class ImportFromRizom(Operator):
    """Import meshes from RizomUV and transfer UV maps.

    Relies on object names to correctly pair objects for data transfer.

    """

    bl_description = "Import meshes from RizomUV and transfer UV maps"
    bl_idname = "wm.rizom_import"
    bl_label = "Import (RizomUV)"
    bl_options = {"REGISTER"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.prefs = addon_utils.get_prefs()
        self.data_dir = get_data_directory()

    def _connect_to_rizom(self) -> RizomBase:
        if self.prefs.use_livelink:
            logger.info("Connecting to RizomUV using livelink")
            try:
                rizom = RizomLink(self.prefs.rizom_path, self.data_dir, self.prefs.connection_timeout)
                if rizom.connection_manager.connect():
                    return rizom
                raise RizomLinkConnectionError("There is no RizomUVLink instance active.")
            except (RizomLinkUnsupportedError, RizomLinkModuleNotFoundError):
                logger.info("RizomLink module unavailable, falling back to legacy methods")
                self.prefs.use_livelink = False
                return self._connect_to_rizom()
        else:
            logger.info("Connecting to RizomUV using legacy methods")
            legacy = RizomLegacy(self.prefs.rizom_path, self.data_dir, self.prefs.connection_timeout)
            connected = legacy.is_connected()
            if not connected:
                raise RizomLegacyConnectionError()
            return legacy

    def _post_import_actions(self, context: Context, objects: list[Object]):
        """Run any post import actions.

        Args:
            context: The current Blender context.
            objects: The objects to run the actions on.

        """
        if self.prefs.export_format == "USD":
            usd_utils.import_usd_props(objects)

        if self.prefs.mark_seams or self.prefs.mark_sharp:
            object_utils.mark_edges(context, objects, self.prefs.mark_seams, self.prefs.mark_sharp)

    def _handle_obj_import(self, imported_objects: list[Object], incoming_data: RizomData):
        """Handle OBJ import.

        When you import an obj file it will reset the uv map name to UVMap,
        rename it to the UV map name from Rizom so that it will transfer to the correct map.

        Args:
            imported_objects: The imported objects.
            incoming_data: The incoming data from Rizom.

        """
        for obj in imported_objects:
            obj.data.uv_layers[0].name = incoming_data.uv_maps[0]

    def _delete_object_materials(self, objects: list[Object]):
        """Delete materials from objects.

        Args:
            objects: The objects to delete materials from.

        """
        materials: set[Material] = set()
        for obj in objects:
            if hasattr(obj, "material_slots"):
                materials.update(slot.material for slot in obj.material_slots if slot.material)

        if materials:
            for mat in materials:
                try:
                    bpy.data.materials.remove(mat, do_unlink=True)
                except ReferenceError as e:
                    logger.warning(f"Could not remove material: {e}")
                    pass

    def execute(self, context: Context) -> set:
        """Run the import from a regular 3D View, not the Script Tool host."""
        view3d_context = _find_view3d_context(context)
        if view3d_context is None:
            self.report({"ERROR"}, "RizomUV import requires an open 3D View")
            return {"CANCELLED"}

        window, area, region = view3d_context
        with context.temp_override(window=window, area=area, region=region):
            return self._execute_in_view3d(bpy.context)

    def _execute_in_view3d(self, context: Context) -> set:
        """Operator call method."""
        try:
            rizom = self._connect_to_rizom()
        except Exception as e:
            return cancel_with_logged_exception(self, e)

        restore_selection = _save_selection(context)

        try:
            incoming_data = rizom.get_scene_data()
        except Exception as e:
            return cancel_with_logged_exception(self, e)

        restore_visibility = object_utils.unhide_all_objects(context)
        restore_names, name_map, parent_empties = _rename_objects(context, incoming_data)
        _duplicate_bug_workaround(context, list(name_map.values()))

        def cleanup():
            restore_names()

            if self.prefs.reveal_hidden:
                restore_visibility()

            if not self.prefs.replace_objects:
                restore_selection()

        try:
            imported_objects = io_utils.import_file(context, self.prefs.export_format, self.data_dir)
            if incoming_data.file_path.lower().endswith(".obj"):
                self._handle_obj_import(imported_objects, incoming_data)

            if self.prefs.replace_objects:
                scene_objects = list(name_map.values())
                object_utils.delete_objects(scene_objects + parent_empties)
                self._post_import_actions(context, imported_objects)
                self.report({"INFO"}, f"Replaced {len(scene_objects)} objects after importing from RizomUV")
                return {"FINISHED"}

            _update_uvmaps(
                imported_objects, name_map, self.prefs.create_missing_uvmaps, self.prefs.delete_unmatched_uvmaps
            )
            self.report({"INFO"}, f"Successfully updated {len(imported_objects)} objects after importing from RizomUV")

            self._post_import_actions(context, list(name_map.values()))
            self._delete_object_materials(imported_objects)
            object_utils.delete_objects(imported_objects)
            cleanup()

        except Exception as e:
            return cancel_with_logged_exception(self, e, cleanup)

        return {"FINISHED"}


def _duplicate_bug_workaround(context: Context, blender_objects: list[Object]):
    """Workaround for a Blender bug.

    Args:
        context: The current Blender context.
        blender_objects: The objects that need to have UVs transferred to.

    Since Blender 3.6 when transferring UVs to duplicate objects
    that haven't been edited the UVs will not transfer
    to the correct object. Something to do with how Blender
    internally handles duplicated mesh data probably.

    Bug can be reproduced by making a cube and duplicating it multiple
    times, export to Rizom and edit UVs. When you transfer the UVs some of the
    imported UVs will be overlapping.

    """
    if not context.active_object or context.active_object.type != "MESH":
        for obj in context.scene.objects:
            if obj.type == "MESH":
                context.view_layer.objects.active = obj
                break
    if not context.active_object:
        return

    if context.active_object.type != "MESH":
        return

    bpy.ops.object.mode_set(mode="EDIT")
    for obj in blender_objects:
        obj.select_set(True)
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.object.mode_set(mode="OBJECT")


def _update_uvmaps(rizom_objects: list[Object], name_map: dict[str, Object], add_uvmaps: bool, remove_uvmaps: bool):
    """Transfer UV maps from the incoming data to the imported objects.

    Args:
        rizom_objects: The imported objects.
        name_map: A dictionary mapping names from the incoming data to the scene objects.
        add_uvmaps: Whether to create new UV maps on the matched objects if needed.
        remove_uvmaps: Whether to delete UV maps on the matched objects that did not come from Rizom.

    Raises:
        NonMatchingTopologyError: If the topology of a RizomUV object does not match the matching scene object.

    """
    missing_objects: list[str] = []
    missing_uvmaps: dict[Object, list[str]] = {}
    extra_uvmaps: dict[Object, list[str]] = {}

    for object in rizom_objects:
        matched = name_map.get(object.name)
        if not matched:
            missing_objects.append(object.name)
            continue
        assert_has_equal_polycount(object, matched)
        matched_object_data = cast(Mesh, matched.data)
        rizom_object_data = cast(Mesh, object.data)

        for source_uvmap in rizom_object_data.uv_layers:
            if source_uvmap.name not in matched_object_data.uv_layers:
                missing_uvmaps.setdefault(matched, []).append(source_uvmap.name)

                # Either create the missing UV map or skip it.
                if add_uvmaps:
                    matched_object_data.uv_layers.new(name=source_uvmap.name)
                else:
                    continue

            matched_uvmap = matched_object_data.uv_layers[source_uvmap.name]
            matched_uvmap.data.foreach_set("uv", [uv for loop in source_uvmap.data for uv in loop.uv])

        if remove_uvmaps:
            for uvmap in matched_object_data.uv_layers:
                if uvmap.name not in rizom_object_data.uv_layers:
                    extra_uvmaps.setdefault(matched, []).append(uvmap.name)
                    matched_object_data.uv_layers.remove(uvmap)

    return UVTransferResult(missing_objects, missing_uvmaps)


def _save_selection(context: Context):
    """Save the current selection state."""
    selected_objects = context.selected_objects
    active_object = context.active_object

    def restore_selection():
        for obj in selected_objects:
            obj.select_set(True)
        cast(ViewLayer, context.view_layer).objects.active = active_object

    return restore_selection


def _rename_objects(
    context: Context, incoming_data: RizomData
) -> tuple[Callable, dict[str, Object], list[Object]]:
    """Rename objects in the scene to avoid name collisions.

    Also renames parent empties of matched objects to prevent duplicate empties
    when importing files that include hierarchy.

    Args:
        context: The current Blender context.
        incoming_data: The incoming data from the Rizom import.

    Returns:
        A tuple containing a function that can be used to restore the original names, a dictionary mapping the
        original names to the objects, and a list of parent empties that were renamed.

    """
    scene = context.scene
    scene_objects = scene.objects
    object_map: dict[Object, str] = {}
    name_map: dict[str, Object] = {}

    for name in incoming_data.objects:
        if name in scene_objects:
            obj = scene_objects[name]
            if obj:
                object_map[obj] = obj.name
                name_map[name] = obj
                # Avoid name collisions with a uuid string because if there is a collision
                # blender will automatically increment it so we'll be storing the wrong name.
                obj.name = str(uuid4())

    # Rename parent empties to avoid name collisions during import.
    parent_empties: list[Object] = []
    seen_parents: set[Object] = set()
    for obj in name_map.values():
        parent = obj.parent
        if parent and parent.type == "EMPTY" and parent not in seen_parents:
            seen_parents.add(parent)
            object_map[parent] = parent.name
            parent.name = str(uuid4())
            parent_empties.append(parent)

    def restore_names():
        for obj, name in object_map.items():
            obj.name = name

    return restore_names, name_map, parent_empties
