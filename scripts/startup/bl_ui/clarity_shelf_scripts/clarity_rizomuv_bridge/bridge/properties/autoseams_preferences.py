"""Preferences for the Autoseams actions."""

from bpy.props import BoolProperty


class AutoseamsPreferences:
    """Preferences for the Autoseams actions."""

    reset_before: BoolProperty(
        name="Reset UVs",
        default=True,
        description="Reset the UV map before running autoseams",
    )
