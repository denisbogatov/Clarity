"""Operator for exporting mesh items to RizomUV."""

import logging
from typing import Optional, cast

from bpy.types import Context, Event, Mesh, Object, Operator

from ..classes.exceptions.rizom_exeptions import RizomLinkModuleNotFoundError, RizomLinkUnsupportedError
from ..classes.exceptions.validation_exceptions import (
    InvalidObjectNamesError,
    InvalidUVSetNamesError,
    InvalidUVSetsError,
)
from ..classes.rizom.legacy.rizom_legacy import RizomLegacy
from ..classes.rizom.modern.rizom_link import RizomLink
from ..file_access import get_data_directory
from ..utils import (
    addon_utils,
    io_utils,
    mesh_utils,
    object_utils,
    selection_utils,
    usd_utils,
    uv_utils,
    validation_utils,
)
from ..utils.exceptions_utils import cancel_with_logged_exception
from ..utils.hooks.usd_hook import UsdHookRizom

logger = logging.getLogger(__name__)


class ExportToRizom(Operator):
    """Export selected mesh items and open the resulting file in RizomUV.

    If a live connection is open to RizomUV the mesh will be loaded, otherwise it will
    first open RizomUV then load the mesh.

    """

    bl_description = "Export selected objects to a file and load in RizomUV"
    bl_idname = "wm.rizom_export"
    bl_label = "Export (RizomUV)"
    bl_options = {"REGISTER"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.prefs = addon_utils.get_prefs()
        self.uvmap_prop = addon_utils.get_uvmaps_prop()
        self.data_dir = get_data_directory()

    @classmethod
    def poll(cls, context: Context) -> bool:
        """Check if there is an active object and that it is a mesh or empty.

        Returns:
            True if there is an active object and that it is a mesh or empty.

        """
        return context.active_object is not None and context.active_object.type in {"MESH", "EMPTY"}

    def _validate(
        self, active_object: Object, target_objects: list[Object], all_objects: list[Object] | None = None
    ) -> bool:
        """Validate objects targeted for export, avoiding exporting invalid state to RizomUV.

        Args:
            active_object: The active mesh object.
            target_objects: The mesh objects targeted for export.
            all_objects: All objects being exported (meshes + empties) for name validation.

        Returns:
            True if validation was successful.

        """
        try:
            validation_utils.assert_valid_for_export(
                active_object, target_objects, self.prefs.export_format, all_objects
            )
        except InvalidUVSetNamesError as e:
            self.report({"ERROR"}, "The active object has invalid UV map names (see console for details)")
            validation_utils.log_invalid_uvmap_names(e.invalid_uvmaps)
            return False
        except InvalidUVSetsError as e:
            self.report({"ERROR"}, "Selected objects do not all have the same UV map names (see console for details)")
            validation_utils.log_non_matching_uvmaps(e.results)
            return False
        except InvalidObjectNamesError as e:
            validation_utils.log_invalid_object_names(e.results)
            if self.prefs.fix_object_names:
                object_utils.fix_object_names(e.results)
                logger.info("Object names were automatically fixed.")
                return True
            self.report({"ERROR"}, "Some objects do not have valid names (see console for details)")
            return False

        return True

    def _run_pre_export_actions(self, context: Context, target_objects: list[Object]):
        """Run all pre-export mesh edit actions.

        Args:
            context: The current blender context.
            active_object: The active object.
            target_objects: The objects targeted for export.

        """
        if self.prefs.export_action == "USE_SEAMS":
            for obj in target_objects:
                uv_utils.unwrap_uvs(context, self.uvmap_prop.uv_map, obj, self.prefs.target_all_uvmaps)

        if self.prefs.triangulate:
            mesh_utils.triangulate(context, target_objects)

        if self.prefs.apply_modifiers:
            object_utils.apply_modifiers(target_objects)

    def _export(self, context: Context, objects: list[Object]):
        """Export the selected objects to RizomUV.

        Have to override the context because for some reason the selected objects flag on the FBX
        exporter does not reliably work, thanks Blender!.

        Args:
            context: The current blender context.
            objects: The objects to export.

        """
        ctx_override = cast(Context, context.copy())
        ctx_override["selected_objects"] = objects

        with context.temp_override(**ctx_override):  # type: ignore
            match self.prefs.export_format:
                case "OBJ":
                    io_utils.export_obj(
                        str(self.data_dir.mesh_files.obj),
                        self.prefs.forward_axis,
                        self.prefs.up_axis,
                    )
                case "FBX":
                    io_utils.export_fbx(
                        str(self.data_dir.mesh_files.fbx),
                        self.prefs.forward_axis,
                        self.prefs.up_axis,
                    )
                case "USD":
                    usd_utils.export_usd_props(objects)
                    with UsdHookRizom.enabled():
                        io_utils.export_usd(
                            str(self.data_dir.mesh_files.usd),
                            self.prefs.forward_axis,
                            self.prefs.up_axis,
                        )

    def _send_to_rizom(self, uvmaps: list[str]):
        """Send the file to RizomUV.

        Will attempt to use the livelink module if it is enabled, otherwise defaults
        to the legacy module. Livelink should be used whenever possible.

        Args:
            uvmaps: The names of the uvmaps being sent to RizomUV,
                    used to for QoL purposes, ensuring the correct UV map is selected.

        """
        if self.prefs.use_livelink:
            try:
                link = RizomLink(self.prefs.rizom_path, self.data_dir, self.prefs.connection_timeout)
                link.connection_manager.connect_or_start()
                active_uvmap = self.uvmap_prop.uv_map
                link.files.load_file(
                    active_uvmap,
                    self.prefs.export_format,
                    self.prefs.up_axis,
                    self.prefs.forward_axis,
                    self.prefs.weld_uvs,
                    self.prefs.normals,
                )

                if self.prefs.rizom_texture and self.prefs.export_texture:
                    link.api.load_user_texture(
                        self.prefs.rizom_texture,
                        self.prefs.background_texture,
                        self.prefs.uv_texture,
                        self.prefs.mesh_texture,
                    )

                self._run_post_export_action(uvmaps, link)
            except (RizomLinkUnsupportedError, RizomLinkModuleNotFoundError) as e:
                self.prefs.use_livelink = False
                logger.info("Your RizomUV version does not support RizomUVLink, livelink is disabled")
                logger.error(e)
                self._send_to_rizom(uvmaps)
        else:
            legacy = RizomLegacy(self.prefs.rizom_path, self.data_dir, self.prefs.connection_timeout)
            legacy.connect_or_start()
            legacy.load_file(uvmaps[0], self.prefs.export_format)

    def _run_post_export_action(self, uvmaps: list[str], rizom_link: Optional[RizomLink]):
        """Run the selected export action (if any).

        Args:
            uvmaps: The names of the uvmaps to run the action on.
            rizom_link: The RizomLink instance, if not using the livelink it is None.

        """
        match self.prefs.export_action:
            case "RESET_UVS":
                rizom_link.uvmaps.reset_uvmaps(uvmaps)
                return

    def execute(self, context: Context) -> set:
        """Operator call method."""
        if not self.prefs.rizom_path:
            self.report({"ERROR"}, "Rizom path not set in the addon preferences")
            return {"CANCELLED"}

        selection_utils.deselect_non_exportable_objects(context)
        active_object = cast(Object, context.active_object)  # Operator poll ensures this is not None
        target_objects = selection_utils.get_objects_for_export(active_object, self.prefs.exclude_clones)
        target_empties = selection_utils.get_selected_empties()

        if not target_objects:
            self.report({"ERROR"}, "No mesh objects selected for export")
            return {"CANCELLED"}

        active_mesh = active_object if active_object.type == "MESH" else target_objects[0]

        if not self._validate(active_mesh, target_objects, target_objects + target_empties):
            return {"CANCELLED"}

        self._run_pre_export_actions(context, target_objects)

        try:
            self._export(context, target_objects + target_empties)
            self._send_to_rizom(cast(Mesh, active_mesh.data).uv_layers.keys())
        except Exception as e:
            return cancel_with_logged_exception(self, e)

        self.report({"INFO"}, f"Exported {len(target_objects)} objects to RizomUV")

        return {"FINISHED"}

    def invoke(self, context: Context, event: Event):
        """Run before execution of the operator.

        Used to enable a confirmation dialog before execution.

        """
        selection_utils.deselect_non_exportable_objects(context)
        active_object = cast(Object, context.active_object)
        target_objects = selection_utils.get_objects_for_export(active_object, self.prefs.exclude_clones)

        if not target_objects:
            self.report({"ERROR"}, "No mesh objects selected for export")
            return {"CANCELLED"}

        if object_utils.has_unapplied_scale(target_objects):
            return context.window_manager.invoke_confirm(
                self,
                event,
                title="Unapplied Scale Detected",
                message="Some objects have unapplied scale, this may cause issues in RizomUV. Continue?",
            )

        if self.prefs.confirm_export:
            return context.window_manager.invoke_confirm(
                self,
                event,
                title="Confirm Export",
                message=f"This will overwrite the existing RizomUV {self.prefs.export_format} file",
            )

        return self.execute(context)
