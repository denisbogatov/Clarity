"""Preferences for handling import setting configuration."""

from bpy.props import BoolProperty


class ImportPreferences:
    """Preferences for handling import setting configuration."""

    replace_objects: BoolProperty(
        name="Replace Objects",
        default=False,
        description=(
            "Replace objects in the scene with the imported ones.\n"
            "This is a last resort option for if UV transfer fails, the default behavior is to "
            "transfer only the UV maps."
        ),
    )

    create_missing_uvmaps: BoolProperty(
        name="Create Missing UV Maps",
        default=False,
        description="Create UV maps on Blender objects if new ones were added in RizomUV",
    )

    delete_unmatched_uvmaps: BoolProperty(
        name="Delete Unmatched UV Maps",
        default=False,
        description="Remove UV maps from Blender objects if they don't exist in RizomUV",
    )

    reveal_hidden: BoolProperty(
        name="Reveal Hidden",
        default=False,
        description="Unhide objects in the scene if their UVs need to be updated",
    )

    mark_seams: BoolProperty(
        name="Mark Seams",
        default=False,
        description="Mark UV island boundaries as seams when importing UV maps from RizomUV",
    )

    mark_sharp: BoolProperty(
        name="Mark Sharp",
        default=False,
        description="Mark UV island boundaries as sharp when importing UV maps from RizomUV",
    )
