"""Preferences for handling export setting configuration."""

from bpy.props import BoolProperty, EnumProperty

from .. import addon_constants
from ..utils.addon_utils import export_formats


class ExportPreferences:
    """Preferences for handling export setting configuration."""

    export_texture: BoolProperty(
        name="Texture File", default=False, description="Export a user-defined texture file into RizomUV"
    )

    normals: BoolProperty(
        name="Normals",
        default=True,
        description="Export normals to RizomUV",
    )

    exclude_clones: BoolProperty(
        name="Exclude Clones",
        default=True,
        description="Skip objects that share mesh data (linked duplicates)",
    )

    confirm_export: BoolProperty(
        name="Confirm Export",
        default=False,
        description="Show a confirmation dialog before exporting",
    )

    export_format: EnumProperty(
        name="Export Format",
        items=export_formats(),
        description="File format to export and load into RizomUV",
        default="FBX",
    )

    fix_object_names: BoolProperty(
        name="Fix Names",
        default=True,
        description="Rename objects with characters that cause issues in RizomUV (e.g. dots, special characters)",
    )

    apply_modifiers: BoolProperty(
        name="Apply Modifiers",
        default=False,
        description="Apply modifiers to the selected meshes before exporting",
    )

    triangulate: BoolProperty(
        name="Triangulate",
        default=False,
        description="Triangulate meshes before exporting to RizomUV",
    )

    target_all_uvmaps: BoolProperty(
        name="Target All UV Maps",
        default=False,
        description="Apply the export action to all UV maps instead of only the active one",
    )

    weld_uvs: BoolProperty(
        name="Weld UVs",
        default=True,
        description="Weld overlapping UV boundaries in RizomUV",
    )

    export_action: EnumProperty(
        name="Export Actions",
        items=(
            addon_constants.ACTIONS["EXPORT"],
            addon_constants.ACTIONS["USE_SEAMS"],
            addon_constants.ACTIONS["RESET_UVS"],
        ),
        description="Action to run on meshes after they are loaded in RizomUV",
        default="EXPORT",
    )

    up_axis: EnumProperty(
        name="Up Axis",
        description="The axis to use for the up direction",
        default="Z",
        items=(
            ("X", "X Axis", ""),
            ("Y", "Y Axis", ""),
            ("Z", "Z Axis", ""),
            ("NEGATIVE_X", "-X Axis", ""),
            ("NEGATIVE_Y", "-Y Axis", ""),
            ("NEGATIVE_Z", "-Z Axis", ""),
        ),
    )

    forward_axis: EnumProperty(
        name="Forward Axis",
        description="The axis to use for the forward direction",
        default="NEGATIVE_Y",
        items=(
            ("X", "X Axis", ""),
            ("Y", "Y Axis", ""),
            ("Z", "Z Axis", ""),
            ("NEGATIVE_X", "-X Axis", ""),
            ("NEGATIVE_Y", "-Y Axis", ""),
            ("NEGATIVE_Z", "-Z Axis", ""),
        ),
    )
