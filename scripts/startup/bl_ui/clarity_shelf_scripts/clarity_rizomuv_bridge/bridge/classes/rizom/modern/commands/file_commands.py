"""Handles file operations in RizomUV."""

import logging
import os
from typing import Optional, cast

from .....file_access import DataDirectory
from .....types import ExportTypes
from ....exceptions.io_exceptions import InvalidFileFormatError
from ..base.rizom_api import RizomApi
from .select_commands import SelectCommands

logger = logging.getLogger(__name__)


class FileCommands:
    def __init__(self, api: RizomApi, select: SelectCommands, data_dir: DataDirectory):
        self.api = api
        self.select = select

        self.files = {
            "OBJ": data_dir.mesh_files.obj,
            "FBX": data_dir.mesh_files.fbx,
            "USD": data_dir.mesh_files.usd,
        }

    def _set_up_axis(self, up_axis: str, forward_axis: str):
        """Set the Rizom up axis based on the user preference."""
        if up_axis == "NEGATIVE_Z" or up_axis == "Z":
            self.api.set({"Path": "Prefs.Viewport.Viewport3D.UpVector", "Value": "z"})
        elif up_axis == "NEGATIVE_Y" or up_axis == "Y":
            self.api.set({"Path": "Prefs.Viewport.Viewport3D.UpVector", "Value": "y"})
        elif up_axis == "NEGATIVE_X" or up_axis == "X":
            self.api.set({"Path": "Prefs.Viewport.Viewport3D.UpVector", "Value": "x"})

    def get_file(self) -> str:
        """Get the path of the currently loaded file.

        Returns:
            The path of the currently loaded file.

        """
        return self.api.get("Prefs.LastLoadedFile")

    def save_file(self):
        """Save the currently loaded file."""
        # Ensure the file suffix isnt set so that import works properly.
        self.api.set({"Path": "Prefs.FileSuffix", "Value": ""})
        self.api.save(self.get_file_type(), self.get_file())

    def get_file_type(self) -> ExportTypes:
        """Get the type of the currently loaded file.

        Returns:
            The type of the currently loaded file.

        """
        loaded_file = self.get_file()
        extension = os.path.splitext(loaded_file)[1][1:][:3].upper()
        if extension not in ("FBX", "OBJ", "USD"):
            raise InvalidFileFormatError(extension)
        return cast(ExportTypes, extension)

    def set_texture_file(self, texture_path: str):
        """Set the texture file in RizomUV.

        Args:
            texture_path: The path to the texture file.

        """
        self.api.set(
            {
                "Path": "Lib.Scene.Textures.List[0].File.Path",
                "Value": texture_path,
                "UndoAble": False,
            }
        )

    def load_file(
        self,
        uvmap: Optional[str],
        file_format: ExportTypes,
        up_axis: str,
        forward_axis: str,
        weld_uvs: bool,
        normals: bool,
    ):
        """Load a file into RizomUV.

        Args:
            uvmap: The name of the UV map to select.
            file_format: The format of the file to load.
            up_axis: The up axis of the file to load.
            forward_axis: The forward axis of the file to load.
            weld_uvs: Whether to weld overlapping UVs.
            normals: Whether to load normals.

        """
        params = {
            "File.Path": str(self.files[file_format]),
            "File.XYZUVW": True,
            "File.UVWProps": True,
            "File.ImportGroups": True,
            "File.Normals": normals,
            "File.AutoWeld": weld_uvs,
            "File.Meta": True,
            "__Focus": True,
        }

        self.api.load(params)
        self._set_up_axis(up_axis, forward_axis)
        logger.info(f"{file_format} file loaded into RizomUV")

        if file_format == "OBJ":
            self.api.set({"Path": "Lib.Scene.Settings.Unit", "Value": "m", "UndoAble": False})
            self.api.uv_set({"Mode": "Rename", "Name": uvmap})

        if uvmap:
            self.select.select_uvmap(uvmap)
            logger.info(f"Active UV map set to {uvmap} in RizomUV")
