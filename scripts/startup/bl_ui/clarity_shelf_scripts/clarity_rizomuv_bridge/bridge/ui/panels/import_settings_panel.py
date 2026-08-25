"""Import settings panel which docks under the main RizomBridge panel."""

from bpy.types import Context, Panel

from ...utils import addon_utils, gui_utils


class ImportSettingsPanel(Panel):
    """The export settings panel."""

    bl_idname = "PANEL_PT_RizomBridgeImportSettings"
    bl_space_type = "VIEW_3D"
    bl_region_type = "WINDOW"
    bl_context = "objectmode"
    bl_label = "Import Settings"
    bl_parent_id = "PANEL_PT_RizomBridge"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.prefs = addon_utils.get_prefs()
        self.uvmaps_prop = addon_utils.get_uvmaps_prop()
        self.tabs_prop = addon_utils.get_gui_tabs_prop()

    @classmethod
    def poll(cls, context: Context):
        """Check if the panel should be displayed."""
        return addon_utils.get_gui_tabs_prop().names == "OPERATIONS"

    def draw(self, context: Context):
        """Render method."""
        box = self.layout.box()

        row = gui_utils.scaled_row(box)
        row.prop(self.prefs, "delete_unmatched_uvmaps", text="Remove UV Maps")
        row.prop(self.prefs, "create_missing_uvmaps", text="Add UV Maps")

        row = gui_utils.scaled_row(box)
        row.prop(self.prefs, "reveal_hidden")
        row.prop(self.prefs, "replace_objects")

        row = gui_utils.scaled_row(box)
        row.prop(self.prefs, "mark_seams")
        row.prop(self.prefs, "mark_sharp")
