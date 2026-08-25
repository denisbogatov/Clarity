"""Custom addon preferences."""

import logging

from bpy.types import PropertyGroup

from .. import addon_constants
from .autoseams_preferences import AutoseamsPreferences
from .config_preferences import ConfigPreferences
from .export_preferences import ExportPreferences
from .gui_preferences import GuiPreferences
from .import_preferences import ImportPreferences
from .rizom_preferences import RizomPreferences

logger = logging.getLogger(__name__)


class ClarityRizomBridgePreferences(
    PropertyGroup,
    ConfigPreferences,
    GuiPreferences,
    ExportPreferences,
    ImportPreferences,
    RizomPreferences,
    AutoseamsPreferences,
):
    """Runtime settings owned by the Clarity Script Tool integration."""
