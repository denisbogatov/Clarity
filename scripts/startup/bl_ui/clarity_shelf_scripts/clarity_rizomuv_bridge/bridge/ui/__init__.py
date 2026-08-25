"""UI module."""

from typing import cast

import bpy
from bpy.types import Context, UILayout

from ..utils import addon_utils
from .panels.export_settings_panel import ExportSettingsPanel
from .panels.import_settings_panel import ImportSettingsPanel
from .panels.rizom_bridge_panel import RizomBridgePanel

UI_LAYOUTS = [RizomBridgePanel, ExportSettingsPanel, ImportSettingsPanel]


def define_ui_popover(self, context: Context):
    """Define popover for header docking."""
    layout = cast(UILayout, self.layout)
    layout.popover(
        panel="PANEL_PT_RizomBridge",
        text="RizomUV",
        icon="WORLD_DATA",
    )


def register():
    """Register UI."""
    prefs = addon_utils.get_prefs()
    if prefs.dock_location == "HEADER":
        region_type = "WINDOW"
    else:
        region_type = "UI"

    for ui in UI_LAYOUTS:
        ui.bl_region_type = region_type
        if ui.bl_region_type == "UI":
            ui.bl_category = prefs.addon_tab_name
        bpy.utils.register_class(ui)

    if region_type == "WINDOW":
        bpy.types.VIEW3D_HT_tool_header.append(define_ui_popover)


def unregister():
    """Unregister UI."""
    prefs = addon_utils.get_prefs()
    if prefs.dock_location == "HEADER":
        region_type = "WINDOW"
    else:
        region_type = "UI"

    if region_type == "WINDOW":
        bpy.types.VIEW3D_HT_tool_header.remove(define_ui_popover)

    for ui in UI_LAYOUTS:
        bpy.utils.unregister_class(ui)
