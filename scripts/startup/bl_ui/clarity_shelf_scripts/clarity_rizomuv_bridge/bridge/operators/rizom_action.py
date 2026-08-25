"""Operator to run remote actions in RizomUV via the RizomUVLink module."""

from bpy.props import EnumProperty
from bpy.types import Context, Operator

from .. import addon_constants
from ..classes.exceptions.rizom_exeptions import RizomLinkUnsupportedError
from ..classes.rizom.modern.rizom_link import RizomLink
from ..file_access import get_data_directory
from ..utils import addon_utils


class RizomAction(Operator):
    """Operator to run remote actions in RizomUV via the RizomUVLink module."""

    bl_idname = "wm.rizom_action"
    bl_label = "Rizom Action"
    bl_options = {"REGISTER", "INTERNAL"}

    action: EnumProperty(
        name="Export Actions",
        items=(
            addon_constants.ACTIONS["RESET_UVS"],
            addon_constants.ACTIONS["SHARP_EDGES"],
            addon_constants.ACTIONS["MOSAIC"],
            addon_constants.ACTIONS["PELT"],
            addon_constants.ACTIONS["BOX"],
            ("CLOSE", "Close Rizom", "Close RizomUV"),
        ),
        description="Actions to execute on the exported meshes",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.prefs = addon_utils.get_prefs()
        self.data_dir = get_data_directory()

    @classmethod
    def poll(cls, context: Context):
        """Check that livelink is enabled."""
        return addon_utils.get_prefs().use_livelink

    def _reset_uvmaps(self, rizom: RizomLink):
        """Reset the UV maps in RizomUV.

        Args:
            rizom: The RizomLink instance.

        """
        if self.prefs.target_all_uvmaps:
            uvmaps = rizom.uvmaps.get_uvmap_names()
            rizom.uvmaps.reset_uvmaps(uvmaps)
        else:
            current_uvmap = rizom.uvmaps.get_selected_uvmap()
            rizom.uvmaps.reset_uvmap(current_uvmap)

    def execute(self, context) -> set:
        """Run the action."""
        try:
            print("hell")
            rizom = RizomLink(self.prefs.rizom_path, self.data_dir, self.prefs.connection_timeout)
        except RizomLinkUnsupportedError:
            self.report({"ERROR"}, "Your RizomUV version does not support RizomUVLink, livelink is disabled")
            return {"CANCELLED"}

        connected = rizom.connection_manager.connect()
        if not connected:
            self.report({"ERROR"}, "RizomLink is not connected, please connect to RizomUV")
            return {"CANCELLED"}

        match self.action:
            case "RESET_UVS":
                self._reset_uvmaps(rizom)
            case "CLOSE":
                rizom.quit()

        return {"FINISHED"}
