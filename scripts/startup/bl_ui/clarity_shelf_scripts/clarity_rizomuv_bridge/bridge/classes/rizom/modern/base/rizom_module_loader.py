"""Handles loading and importing the RizomUVLink module."""

import importlib
import logging
import sys
from pathlib import Path
from types import ModuleType

from ....exceptions.rizom_exeptions import RizomLinkModuleNotFoundError

logger = logging.getLogger(__name__)


class RizomModuleLoader:
    """Handles loading and importing the RizomUVLink module."""

    def __init__(self, rizom_path: str):
        """Initialize the RizomModuleLoader.

        Args:
            rizom_path: The path to the RizomUV installation.

        Raises:
            RizomLinkModuleNotFoundError: If the RizomUVLink module could not be found.

        """
        self.rizom_path = rizom_path
        self.module_path: Path | None = None
        self.module = self._find_and_import_module()

    def _find_and_import_module(self):
        """Attempt to import from installation, then bundled version.

        Raises:
            RizomLinkModuleNotFoundError: If the RizomUVLink module could not be found.

        """
        # Try installed version first
        installed_path = Path(self.rizom_path).parent / "RizomUVLink"
        logger.info(f"Attempting to load RizomUVLink from installed path: {installed_path}")
        module = self._attempt_import(installed_path)
        if module:
            logger.info("Loaded RizomUVLink from installed path.")
            return module

        # Fall back to bundled version
        bundled_path = Path(__file__).parents[4] / "lib" / "RizomUVLink"
        module = self._attempt_import(bundled_path)
        if module:
            logger.info("Loaded RizomUVLink from bundled path.")
            return module

        raise RizomLinkModuleNotFoundError()

    def _attempt_import(self, path: Path) -> None | ModuleType:
        """Try to import module from given path.

        Args:
            path: The path to import from.

        Returns:
            The imported module or None if the import failed.

        """
        if not (path.exists() and path.is_dir()):
            return None

        str_path = str(path)
        sys.path.append(str_path)
        try:
            module = importlib.import_module("RizomUVLink")
            self.module_path = path
            return module
        except Exception:
            logger.error(f"Failed to import RizomUVLink from {path}", exc_info=True)
            if str_path in sys.path:
                sys.path.remove(str_path)
            return None
