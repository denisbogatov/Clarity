"""Wrapper class for the RizomUVLink API, includes some extended functionality."""

import logging
import platform
from typing import Literal

from ....file_access import DataDirectory
from ....utils.rizom_utils import validate_and_transform_rizom_path
from ...data.import_models import RizomData
from ...exceptions.rizom_exeptions import RizomLinkUnsupportedError
from ..rizom_base import RizomBase
from .base.rizom_api import RizomApi
from .base.rizom_connection_manager import RizomConnectionManager
from .base.rizom_module_loader import RizomModuleLoader
from .commands.file_commands import FileCommands
from .commands.object_commands import ObjectCommands
from .commands.select_commands import SelectCommands
from .commands.uvmap_commands import UvmapCommands

logger = logging.getLogger(__name__)


def _texel_density(tex_den: float, unit: Literal["km", "m", "dm", "cm", "mm", "in", "ft", "yd", "mi"]) -> float:
    """Convert texel density value to different units of measurement.

    Args:
       tex_den: The texel density value to convert.
       unit: The unit to convert to.

    Returns:
       float: The converted texel density value.

    """
    unit_dict = {
        "km": tex_den,
        "m": tex_den,
        "dm": tex_den * 10,
        "cm": tex_den * 100,
        "mm": tex_den * 1000,
        "in": tex_den * 39.370079,
        "ft": tex_den * 3.28084,
        "yd": tex_den * 1.093613,
        "mi": tex_den * 0.000621371,
    }

    return unit_dict[unit]


class RizomLink(RizomBase):
    """Class for managing the RizomUVLink process."""

    def __init__(self, rizom_path: str, data_dir: DataDirectory, connection_timeout: int):
        """Initialize the RizomLink class.

        Args:
            rizom_path: The path to the RizomUV executable.
            data_dir: The data directory.
            connection_timeout: The duration Blender will wait for the RizomUVLink connection before timing out.

        Raises:
            RizomLinkUnsupportedError: If the platform is not supported.
            InvalidRizomPathError: If the rizom installation path is invalid.

        """
        if platform.system() != "Windows":
            raise RizomLinkUnsupportedError("RizomUV's LiveLink module currently only supports Windows")

        self._rizom_path = validate_and_transform_rizom_path(rizom_path)
        self._data_dir = data_dir

        self._module_manager = RizomModuleLoader(rizom_path)
        self.connection_manager = RizomConnectionManager(
            self._module_manager, self._data_dir, self._rizom_path, connection_timeout
        )

        self.api = RizomApi(self.connection_manager)
        self.select = SelectCommands(self.api)
        self.uvmaps = UvmapCommands(self.select, self.api)
        self.files = FileCommands(self.api, self.select, self._data_dir)
        self.objects = ObjectCommands(self.api, self.files)

    def get_scene_data(self) -> RizomData:
        """Get the data from the current RizomUV session.

        Returns:
            A dataclass containing the object names and UV map names from the current RizomUV session.

        """
        self.save_file()
        return RizomData(self.objects.get_object_names(), self.uvmaps.get_uvmap_names(), self.files.get_file())

    def save_file(self):
        """Save the currently loaded file in RizomUV."""
        self.files.save_file()

    def quit(self):
        """Close the RizomUV instance."""
        self.api.quit()
