"""Preferences for handling addon gui configuration."""

import logging
from typing import TYPE_CHECKING

import bpy
from bpy.props import EnumProperty, StringProperty
from bpy.types import Context

from ..ui.constants import PANEL_IDS

if TYPE_CHECKING:
    from ..properties.preferences import RizomBridgePreferences

logger = logging.getLogger(__name__)


def addon_tab_update(self: "RizomBridgePreferences", context: Context) -> None:
    """Update callback for the addon tab name property.

    When the property is changed all panels will be unregistered and then
    reregistered to the new tab name.

    """
    if not self.addon_tab_name:
        self.addon_tab_name = "RizomUV"

    for panel_id in PANEL_IDS:
        try:
            panel = getattr(bpy.types, panel_id)
        except AttributeError:
            continue
        if panel.is_registered:
            bpy.utils.unregister_class(panel)
            panel.bl_category = self.addon_tab_name
            bpy.utils.register_class(panel)


# TODO: Implement once Blender issue is resolved.
# https://projects.blender.org/blender/blender/issues/123232
def tab_location_update(self: "RizomBridgePreferences", context: Context) -> None:
    """Update callback for the dock location property.

    When the property is changed all panels will be unregistered and then reregistered to the new location.

    """
    pass


class GuiPreferences:
    """Preferences for handling addon gui configuration."""

    dock_location: EnumProperty(
        name="UI Dock Location",
        items=(("SIDE", "Side Panel", ""), ("HEADER", "Header", "")),
        default="SIDE",
        description="Dock location for the RizomUV Bridge panel (requires restart)",
        update=tab_location_update,
    )

    addon_tab_name: StringProperty(
        name="Tab Name",
        default="RizomUV",
        description="Name of the sidebar tab where the addon panel appears",
        update=addon_tab_update,
    )
