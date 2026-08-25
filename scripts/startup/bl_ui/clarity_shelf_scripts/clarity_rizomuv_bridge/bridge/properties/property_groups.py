"""Addon property groups.

All properties are saved to the Blender scene, they do not persist between Blender sessions.

"""

from typing import Iterable, cast

from bpy.props import EnumProperty
from bpy.types import Context, Mesh, PropertyGroup


class RizomBridgeGuiTabs(PropertyGroup):
    """Property group defining the tabs in the RizomBridge panel."""

    names: EnumProperty(
        name="Tabs",
        description="Tabs in the RizomBridge panel",
        items=[
            ("OPERATIONS", "Operations", "", "EXPORT", 0),
            ("ADDON_SETTINGS", "Addon Settings", "", "PREFERENCES", 2),
        ],
    )


def get_uvmaps(self, context: Context) -> Iterable[tuple[str, str, str]]:
    """Getter for the UVMaps property group."""
    act_object = context.active_object
    if not act_object or not act_object.type == "MESH":
        return [("NO_OBJ", "[No object selected]", "")]

    uv_layers = cast(Mesh, act_object.data).uv_layers
    if uv_layers:
        uvmaps = [(uv_layer.name, uv_layer.name, "") for uv_layer in uv_layers]
        RizomBridgeUVMaps._uv_maps_list = uvmaps
        return uvmaps

    return [("NO_UV", "[The active object has no UV maps]", "")]


def uvmaps_update(self, context: Context):
    """Update callback for the UVMaps property group."""
    act_object = context.active_object
    if not act_object or act_object.type != "MESH":
        return

    uv_layers = cast(Mesh, act_object.data).uv_layers
    selected = self.uv_map
    if selected in uv_layers:
        uv_layers.active = uv_layers[selected]


class RizomBridgeUVMaps(PropertyGroup):
    """Wraps the UVMap Blender data structure.

    Exists for the purpose of displaying and setting the active
    UVMap from the addon gui. Otherwise users would have to open
    a separate panel.

    """

    # Keep an internal reference to the UVMap list
    # This is required due to a bug with the blender API
    # https://docs.blender.org/api/master/bpy.props.html#bpy.props.EnumProperty
    _uv_maps_list = []

    uv_map: EnumProperty(
        name="UV Map",
        items=lambda self, ctx: get_uvmaps(self, ctx) if ctx else [],
        update=uvmaps_update,
    )
