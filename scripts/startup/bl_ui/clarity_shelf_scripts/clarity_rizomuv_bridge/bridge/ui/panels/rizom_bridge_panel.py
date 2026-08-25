"""Main panel for the addon."""

import platform
from typing import cast

from bpy.types import Context, Panel

from ...operators.rizom_action import RizomAction
from ...utils import addon_utils, gui_utils


class RizomBridgePanel(Panel):
    """The main UI panel for the addon."""

    bl_idname = "PANEL_PT_RizomBridge"
    bl_space_type = "VIEW_3D"
    bl_region_type = "WINDOW"
    bl_context = "objectmode"
    bl_label = "RizomUV Bridge - Ultimate Edition"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.prefs = addon_utils.get_prefs()
        self.uvmaps_prop = addon_utils.get_uvmaps_prop()
        self.tabs_prop = addon_utils.get_gui_tabs_prop()

    def draw_operations_ui(self):
        """Draw the operations UI box."""
        box = self.layout.box()
        box.label(text="Main Operations", icon="UV_DATA")

        row = gui_utils.scaled_row(box)
        row.operator("wm.rizom_export", icon="EXPORT", text="Export")
        row.operator("wm.rizom_import", icon="IMPORT", text="Import")

        if self.prefs.use_livelink:
            row = gui_utils.scaled_row(box)
            op = row.operator("wm.rizom_action", icon="QUIT", text="Close Rizom")
            cast(RizomAction, op).action = "CLOSE"

        row = gui_utils.split_scaled_row(box, 0.65)
        row.prop(self.uvmaps_prop, "uv_map", text="")
        row.operator("object.rename_uvmaps", text="Rename")

        row = gui_utils.split_scaled_row(box, 0.65)
        row.prop(self.prefs, "export_format", text="")
        row.operator("wm.rizom_load", text="Load")

        if self.prefs.use_livelink:
            row = gui_utils.scaled_row(box)
            row.prop(self.prefs, "export_action", text="Action")

            if self.prefs.export_texture:
                box = self.layout.box()
                row = gui_utils.scaled_row(box)
                row.prop(self.prefs, "rizom_texture", text="Texture File")

                box.label(text="Texture Display:")
                grid = box.grid_flow(row_major=True, columns=2, even_columns=True)
                grid.scale_y = 1.5
                grid.prop(self.prefs, "background_texture", text="Background")
                grid.prop(self.prefs, "uv_texture", text="UV Islands")
                grid.prop(self.prefs, "mesh_texture", text="Meshes")

    def draw_addon_settings_ui(self):
        """Draw the addon settings UI box."""
        box = self.layout.box()
        box.label(text="Bridge Settings", icon="PREFERENCES")

        row = gui_utils.scaled_row(box)
        row.prop(self.prefs, "rizom_path", text="Rizom Path")

        row = gui_utils.scaled_row(box)
        row.prop(self.prefs, "use_livelink", text="Use RizomUVLink Connection")
        if platform.system() == "Darwin":
            row.enabled = False

        box = self.layout.box()
        row = gui_utils.scaled_row(box)
        row.prop(self.prefs, "enable_logging", text="Enable Logging")

        box = self.layout.box()
        row = gui_utils.scaled_row(box)
        row.prop(self.prefs, "up_axis", text="Up Axis")

        row = gui_utils.scaled_row(box)
        row.prop(self.prefs, "forward_axis", text="Forward Axis")

        row = gui_utils.scaled_row(box)
        row.prop(self.prefs, "connection_timeout", text="RizomUV Timeout (s)")

    def draw(self, context: Context):
        """Render method."""
        box = self.layout.box()
        row = gui_utils.scaled_row(box)
        row.scale_x = 2

        row.prop(self.tabs_prop, "names", icon_only=True, expand=True)

        match self.tabs_prop.names:
            case "OPERATIONS":
                row.label(text="UV Transfer")
                self.draw_operations_ui()
            case "ADDON_SETTINGS":
                self.draw_addon_settings_ui()
