"""Functions for finding/managing the users RizomUV application."""

import logging
import os
import platform
from pathlib import Path

from ..classes.exceptions.rizom_exeptions import RizomNotFoundError

logger = logging.getLogger(__name__)


def check_for_livelink(rizom_path: str) -> bool:
    """Check if the user is using a version of RizomUV with the livelink module.

    Args:
        rizom_path: The path to the RizomUV executable.

    Returns:
        True if the RizomUVLink module is present.

    """
    module = Path(rizom_path).parent / "RizomUVLink"
    return module.exists() and module.is_dir()


def validate_and_transform_rizom_path(rizom_path: str) -> str:
    """Validate the rizom path and transform it if necessary.

    Handles adjusting the path for MacOS, this is necessary because
    the Blender file browser does not allow users to browse inside the app
    bundle.

    Args:
        rizom_path: The path to the RizomUV executable.

    Returns:
        The validated and transformed path.

    Raises:
        RizomNotFoundError: If the path to the RizomUV executable is invalid.

    """
    if platform.system() == "Windows":
        if not rizom_path.endswith(".exe"):
            raise RizomNotFoundError(rizom_path)
        return rizom_path
    if platform.system() == "Darwin" and rizom_path.endswith(".app"):
        filename = os.path.basename(rizom_path)
        basename, _ = os.path.splitext(filename)
        final_path = os.path.join(rizom_path, "Contents", "MacOS", basename)
        logger.info(f"MacOS detected, adjusting path from {rizom_path} to {final_path}")
        return final_path

    return rizom_path


def get_latest_rizomuv_path_windows() -> str | None:
    """Attempt to locate the latest version of RizomUV installed on the system.

    Returns:
       The path to the RizomUV installation directory or None if it could not be found.

    """
    import winreg

    for major in range(9, 1, -1):
        for minor in range(10, -1, -1):
            if major == 2 and minor < 2:
                continue
            rizom_reg_path = f"SOFTWARE\\Rizom Lab\\RizomUV VS RS 202{major}.{minor}"
            try:
                key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, rizom_reg_path)
                exe_path = winreg.QueryValue(key, "rizomuv.exe")
                return os.path.dirname(exe_path)
            except FileNotFoundError:
                pass
    return None


def get_rizom_path() -> str:
    """Attempt to locate the latest version of RizomUV installed on the system.

    Will attempt to locate the RizomUV executable on Windows systems, macOS search currently
    not supported. Will verify that the path leads to a rizomuv.exe file.

    Returns:
        The path to the RizomUV executable or an empty string if it could not be found.

    """
    if platform.system() == "Windows":
        path = get_latest_rizomuv_path_windows()
        if not path:
            return ""

        rizom_exe = os.path.join(path, "rizomuv.exe")
        if os.path.isfile(rizom_exe):
            return rizom_exe

    return ""
