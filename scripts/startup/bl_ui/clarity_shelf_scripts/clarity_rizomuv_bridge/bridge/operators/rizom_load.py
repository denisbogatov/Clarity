"""Operator for loading an existing file into RizomUV."""

import logging

from bpy.types import Context, Operator

from ..classes.exceptions.rizom_exeptions import RizomLinkUnsupportedError
from ..classes.rizom.modern.rizom_link import RizomLink
from ..file_access import get_data_directory
from ..utils import (
    addon_utils,
)
from ..utils.exceptions_utils import cancel_with_logged_exception

logger = logging.getLogger(__name__)


class LoadInRizom(Operator):
    """Load an existing file into RizomUV with no export.

    If a live connection is open to RizomUV the mesh will be loaded, otherwise it will
    first open RizomUV then load the mesh.

    """

    bl_description = "Load the selected file format into RizomUV, no meshes will be exported"
    bl_idname = "wm.rizom_load"
    bl_label = "Load (RizomUV)"
    bl_options = {"REGISTER"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.prefs = addon_utils.get_prefs()
        self.data_dir = get_data_directory()

    def _load_in_rizom(self):
        """Send the file to RizomUV."""
        if self.prefs.use_livelink:
            try:
                link = RizomLink(self.prefs.rizom_path, self.data_dir, self.prefs.connection_timeout)
                link.connection_manager.connect_or_start()
                link.files.load_file(
                    None,
                    self.prefs.export_format,
                    self.prefs.up_axis,
                    self.prefs.forward_axis,
                    self.prefs.weld_uvs,
                    self.prefs.normals,
                )

                if self.prefs.export_texture and self.prefs.rizom_texture:
                    link.api.load_user_texture(
                        self.prefs.rizom_texture,
                        self.prefs.background_texture,
                        self.prefs.uv_texture,
                        self.prefs.mesh_texture,
                    )

            except RizomLinkUnsupportedError:
                self.prefs.use_livelink = False
                logger.info("Your RizomUV version does not support RizomUVLink, livelink is disabled")
                self._load_in_rizom()
        else:
            raise NotImplementedError("TODO")

    def execute(self, context: Context) -> set:
        """Operator call method."""
        if not self.prefs.rizom_path:
            self.report({"ERROR"}, "Rizom path not set in the addon preferences")
            return {"CANCELLED"}

        try:
            self._load_in_rizom()
        except Exception as e:
            return cancel_with_logged_exception(self, e)

        self.report({"INFO"}, f"Loading {self.prefs.export_format} file into RizomUV")

        return {"FINISHED"}
