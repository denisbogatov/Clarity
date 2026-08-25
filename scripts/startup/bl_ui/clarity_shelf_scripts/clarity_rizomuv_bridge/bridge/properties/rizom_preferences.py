"""Preferences for handling RizomUV app settings."""

from bpy.props import BoolProperty, FloatProperty, IntProperty, StringProperty


class RizomPreferences:
    """Preferences for handling RizomUV app settings."""

    link_gaps: BoolProperty(name="Link Gaps", description="Cut edges that bridge gaps in the mesh topology")
    open_cylinders: BoolProperty(name="Open Cylinders", description="Cut cylinder caps and one connecting edge to unfold them")
    cut_handles: BoolProperty(name="Cut Handles", description="Cut edges along handle-shaped geometry (e.g. arches, loops)")
    sharp_angle: IntProperty(
        name="Sharp Angle",
        default=70,
        min=0,
        max=180,
        description="Cut edges where the angle between adjacent face normals exceeds this value",
    )
    mosaic_force: FloatProperty(
        name="Force", default=0.5, min=0, max=1, description="Higher values will lead to more UV shells", step=0.05
    )
    pelt_trunk: BoolProperty(name="Trunk", description="Cut seams along trunk sections of the mesh")
    pelt_branch: BoolProperty(name="Branch", description="Cut seams along branch sections of the mesh")
    pelt_leaf: BoolProperty(name="Leaf", description="Cut seams along leaf (terminal) sections of the mesh")
    texture_path: StringProperty(
        name="Texture Path", description="Path to a texture file which will be loaded in RizomUV", default=""
    )
    stretch_limiter: FloatProperty(
        name="Stretch Limiter",
        default=0.25,
        min=0,
        max=0.99,
        step=0.1,
        description="High values give less stretching but more islands",
    )
    rizom_texture: StringProperty(
        name="Texture", description="Texture file to load into RizomUV", default="", subtype="FILE_PATH"
    )
    background_texture: BoolProperty(
        name="Background Texture", description="Show the texture as a background in the UV viewport"
    )

    uv_texture: BoolProperty(name="UV Texture", description="Display the loaded texture on UV islands", default=False)
    mesh_texture: BoolProperty(name="Mesh Texture", description="Display the loaded texture on the 3D meshes", default=False)
