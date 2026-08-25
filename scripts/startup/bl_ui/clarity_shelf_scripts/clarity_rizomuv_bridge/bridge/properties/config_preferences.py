"""Preferences for handling addon configuration."""

import logging
import platform

from bpy.props import BoolProperty, IntProperty, StringProperty

from ..utils import rizom_utils
from ..utils.update_callbacks import logging_toggle

logger = logging.getLogger(__name__)


class ConfigPreferences:
    """Preferences for handling addon configuration."""

    rizom_path: StringProperty(
        name="Rizom Exe",
        subtype="FILE_PATH",
        description="Path to the RizomUV program executable",
        default=rizom_utils.get_rizom_path(),
    )

    use_livelink: BoolProperty(
        name="Use LiveLink Module",
        description="Use the RizomUVLink module for connecting with RizomUV. (Windows only / Rizom 2023+)",
        default=True if platform.system() == "Windows" else False,
    )

    enable_logging: BoolProperty(
        name="Enable Logging",
        default=True,
        update=lambda self, _: logging_toggle(self.enable_logging, logger),  # type: ignore
        description="Log addon debug information to the console",
    )

    connection_timeout: IntProperty(
        name="Import Timeout",
        default=10,
        min=10,
        subtype="TIME_ABSOLUTE",
        description=(
            "How long Blender will wait for RizomUV to respond "
            "before cancelling the operation.\n"
            "Blender will be unresponsive during this time but higher values may be required for large files"
        ),
    )
