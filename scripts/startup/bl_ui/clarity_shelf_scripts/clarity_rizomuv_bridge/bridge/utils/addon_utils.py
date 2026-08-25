"""Utility functions for accessing addon preferences and properties."""

from typing import TYPE_CHECKING, cast

import bpy

from .. import addon_constants

if TYPE_CHECKING:
    from ..properties.preferences import ClarityRizomBridgePreferences
    from ..properties.property_groups import RizomBridgeGuiTabs, RizomBridgeUVMaps


def get_prefs() -> "ClarityRizomBridgePreferences":
    """Get the addon preferences.

    Returns:
        The addon preferences.

    """
    return cast(
        "ClarityRizomBridgePreferences",
        bpy.context.window_manager.clarity_rizom_bridge_preferences,
    )


def get_uvmaps_prop() -> "RizomBridgeUVMaps":
    """Access to the UVMaps property.

    Returns:
       The WindowManager UVMap property for displaying UVMaps in UI.

    """
    return bpy.context.window_manager.clarity_rizom_bridge_uvmaps


def get_gui_tabs_prop() -> "RizomBridgeGuiTabs":
    """Access to the GUI Tabs property.

    Returns:
       The WindowManager Gui Tabs property for displaying Gui tabs.

    """
    return bpy.context.window_manager.clarity_rizom_bridge_gui_tabs


def export_formats():
    """Export options.

    Get available export format options based on the current Blender version.

    Returns:
        The export format options for the export_format EnumProperty.

    """
    return (
        ("FBX", "FBX", ""),
        ("OBJ", "OBJ", ""),
        ("USD", "USD", ""),
    )
