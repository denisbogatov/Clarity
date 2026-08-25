"""Global constants."""

from pathlib import Path
from typing import cast

PACKAGE = cast(str, __package__)
RIZOM_SCRIPT = Path(__file__).parent / "rizom_script.py"


# These are substrings that are not allowed in uvmap names because they cause issues in RizomUV.
BANNED_UVMAP_SUBSTRINGS = {"___dot___": "_", ".": "_"}

# . Isnt liked by OBJ so im just banning it everywhere for consistency.
# / Is used to express hierarchy in names when exporting FBX so banning it to avoid complications with name matching.
BANNED_USD_SUBSTRINGS = {".", "/"}
BANNED_OBJ_SUBSTRINGS = {".", "/"}
BANNED_FBX_SUBSTRINGS = {".", "/"}


RIZOMUV_LINK_PACKAGE = str(Path(__file__).parent / "lib" / "RizomUVLink")

AUTOSEAMS_ACTIONS = {
    "SHARP_EDGES": (
        "SHARP_EDGES",
        "Autoseams - Sharp Edges",
        "Unwrap using Sharp Edges Autoseams algorithm",
    ),
    "MOSAIC": ("MOSAIC", "Autoseams - Mosaic", "Unwrap using Mosaic Autoseams algorithm"),
    "PELT": ("PELT", "Autoseams - Pelt", "Unwrap using Pelt Autoseams algorithm"),
    "BOX": ("BOX", "Autoseams - Box", "Unwrap using Box Autoseams algorithm"),
}

ACTIONS = {
    "EXPORT": ("EXPORT", "Export UVs", "Export existing UV data with no changes"),
    "USE_SEAMS": ("USE_SEAMS", "Unwrap Seams", "Use seams to unwrap the UVs inside Blender before sending to RizomUV"),
    "RESET_UVS": ("RESET_UVS", "Reset UVs", "Reset UVs (weld all seams)"),
    "CLOSE": ("CLOSE", "Close Rizom", "Close RizomUV"),
    "APPLY_RIZOM_SETTINGS": (
        "APPLY_RIZOM_SETTINGS",
        "Apply Rizom Settings",
        "Overwrite RizomUV preferences with those set in the bridge UI",
    ),
    **AUTOSEAMS_ACTIONS,
}
