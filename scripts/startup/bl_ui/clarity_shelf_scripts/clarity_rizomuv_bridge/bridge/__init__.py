"""Clarity shelf integration for RizomUV Bridge Ultimate."""

import logging

import bpy
from bpy.props import PointerProperty
from bpy.types import WindowManager
from bpy_extras.script_tool import ScriptToolWindow

from . import operators
from .file_access import ensure_data_dir_integrity
from .properties.preferences import ClarityRizomBridgePreferences
from .properties.property_groups import RizomBridgeGuiTabs, RizomBridgeUVMaps
from .utils import addon_utils, rizom_utils
from .utils.hooks.usd_hook import UsdHookRizom
from .utils.update_callbacks import logging_toggle
from .ui.panels.export_settings_panel import ExportSettingsPanel
from .ui.panels.import_settings_panel import ImportSettingsPanel
from .ui.panels.rizom_bridge_panel import RizomBridgePanel

logger = logging.getLogger(__name__)


PROPERTIES = (ClarityRizomBridgePreferences, RizomBridgeUVMaps, RizomBridgeGuiTabs)

CLARITY_RIZOM_TOOL_ID = "clarity_rizomuv_bridge"
CLARITY_RIZOM_TOOL_INSTANCE = "main"


class ClarityRizomBridgeToolWindow(ScriptToolWindow):
    tool_id = CLARITY_RIZOM_TOOL_ID
    title = "RizomUV Bridge"
    default_width = 420
    default_height = 720
    default_instance_id = CLARITY_RIZOM_TOOL_INSTANCE


for _panel in (RizomBridgePanel, ExportSettingsPanel, ImportSettingsPanel):
    ClarityRizomBridgeToolWindow.panel(_panel)

ensure_data_dir_integrity()


def _unregister_existing_by_name():
    """Remove classes left by the previous shelf invocation."""
    try:
        if hasattr(bpy.ops.wm, "script_tool_window_close"):
            bpy.ops.wm.script_tool_window_close(
                tool_id=CLARITY_RIZOM_TOOL_ID,
                instance_id=CLARITY_RIZOM_TOOL_INSTANCE,
            )
    except Exception:
        pass

    for attribute in (
        "clarity_rizom_bridge_preferences",
        "clarity_rizom_bridge_gui_tabs",
        "clarity_rizom_bridge_uvmaps",
        "RizomBridgeGuiTabs",
        "RizomBridgeUVMaps",
    ):
        if hasattr(WindowManager, attribute):
            try:
                delattr(WindowManager, attribute)
            except Exception:
                pass

    class_names = (
        "PANEL_PT_RizomBridgeImportSettings",
        "PANEL_PT_RizomBridgeExportSettings",
        "PANEL_PT_RizomBridge",
        "RenameUVMaps",
        "RizomAction",
        "LoadInRizom",
        "ImportFromRizom",
        "ExportToRizom",
        "RizomBridgeGuiTabs",
        "RizomBridgeUVMaps",
        "RizomBridgePreferences",
        "ClarityRizomBridgePreferences",
        "UsdHookRizom",
    )
    for name in class_names:
        old_class = getattr(bpy.types, name, None)
        if old_class is not None:
            try:
                bpy.utils.unregister_class(old_class)
            except Exception:
                pass


def register():
    """Register the bridge and its dedicated Clarity Script Tool window."""
    _unregister_existing_by_name()
    bpy.utils.register_class(UsdHookRizom)  # type: ignore

    for prop in PROPERTIES:
        bpy.utils.register_class(prop)

    operators.register()

    setattr(
        WindowManager,
        "clarity_rizom_bridge_preferences",
        PointerProperty(type=ClarityRizomBridgePreferences),
    )
    setattr(
        WindowManager,
        "clarity_rizom_bridge_gui_tabs",
        PointerProperty(type=RizomBridgeGuiTabs),
    )
    setattr(
        WindowManager,
        "clarity_rizom_bridge_uvmaps",
        PointerProperty(type=RizomBridgeUVMaps),
    )

    prefs = addon_utils.get_prefs()

    # Set the initial logging output state.
    logging_toggle(prefs.enable_logging, logger)

    # Set the initial RizomUVLink availability based on the Rizom path.
    prefs.use_livelink = rizom_utils.check_for_livelink(prefs.rizom_path)

    ClarityRizomBridgeToolWindow.register(hot_reload=True)


def unregister():
    """Unregister the bridge and close its tool window."""
    ClarityRizomBridgeToolWindow.unregister(close_windows=True)
    bpy.utils.unregister_class(UsdHookRizom)  # type: ignore

    operators.unregister()

    delattr(WindowManager, "clarity_rizom_bridge_preferences")
    delattr(WindowManager, "clarity_rizom_bridge_gui_tabs")
    delattr(WindowManager, "clarity_rizom_bridge_uvmaps")

    for prop in reversed(PROPERTIES):
        bpy.utils.unregister_class(prop)
