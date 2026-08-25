"""Data classes for storing scene data."""

from dataclasses import dataclass

from bpy.types import Object


@dataclass(frozen=True)
class BlenderSceneState:
    """Dataclass for storing the state of the Blender scene so it can be changed and restored."""

    active_object: Object | None
    selected_objects: list[Object]
