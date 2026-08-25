"""Export settings panel which docks under the main RizomBridge panel."""

from bpy.types import Context, Panel

from ...addon_constants import AUTOSEAMS_ACTIONS
from ...utils import addon_utils, gui_utils


class ExportSettingsPanel(Panel):
    """The export settings panel."""

    bl_idname = "PANEL_PT_RizomBridgeExportSettings"
    bl_space_type = "VIEW_3D"
    bl_region_type = "WINDOW"
    bl_context = "objectmode"
    bl_label = "Export Settings"
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

    def action_settings(self):
        """Draw settings common to all actions."""
        is_autoseams = self.prefs.export_action in AUTOSEAMS_ACTIONS.keys()

        box = self.layout.box()

        row = gui_utils.scaled_row(box, align=True)

        # Obj can only have 1 UV map, so disable the target all UV maps option.
        if self.prefs.export_format != "OBJ":
            row.prop(self.prefs, "target_all_uvmaps", text="All UV Maps", toggle=True)
        if is_autoseams:
            row.prop(self.prefs, "reset_before", toggle=True)

        if is_autoseams:
            row = gui_utils.scaled_row(box, align=True)
            row.prop(self.prefs, "cut_handles", toggle=True)
            row.prop(self.prefs, "link_gaps", toggle=True)
            row.prop(self.prefs, "open_cylinders", toggle=True)

            row = gui_utils.scaled_row(box, align=True)
            row.prop(self.prefs, "stretch_limiter")

            match self.prefs.export_action:
                case "SHARP_EDGES":
                    row.prop(self.prefs, "sharp_angle")
                case "MOSAIC":
                    row.prop(self.prefs, "mosaic_force")
                case "PELT":
                    row = gui_utils.scaled_row(box, align=True)
                    row.prop(self.prefs, "pelt_trunk")
                    row.prop(self.prefs, "pelt_branch")
                    row.prop(self.prefs, "pelt_leaf")

    def draw(self, context: Context):
        """Render method."""
        if self.prefs.use_livelink and self.prefs.export_action != "EXPORT":
            self.action_settings()

        box = self.layout.box()

        row = gui_utils.scaled_row(box)
        row.prop(self.prefs, "exclude_clones")
        row.prop(self.prefs, "confirm_export")

        row = gui_utils.scaled_row(box)
        row.prop(self.prefs, "triangulate")
        row.prop(self.prefs, "fix_object_names")

        if self.prefs.use_livelink:
            row = gui_utils.scaled_row(box)
            row.prop(self.prefs, "normals")
            row.prop(self.prefs, "weld_uvs")

        if self.prefs.export_format != "USD":
            row = gui_utils.scaled_row(box)
            row.prop(self.prefs, "apply_modifiers")

            if self.prefs.use_livelink:
                row.prop(self.prefs, "export_texture")
