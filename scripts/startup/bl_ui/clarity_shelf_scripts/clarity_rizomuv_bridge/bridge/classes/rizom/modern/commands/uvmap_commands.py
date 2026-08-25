"""Handles UV map operations in RizomUV."""

from uuid import uuid4

from .....addon_constants import BANNED_UVMAP_SUBSTRINGS
from ..base.rizom_api import RizomApi
from .select_commands import SelectCommands


class UvmapCommands:
    def __init__(self, select: SelectCommands, api: RizomApi):
        self.api = api
        self.select = select

    def get_uvmap_names(self) -> list[str]:
        """Get the names of all UV maps in the scene.

        Returns:
            A list of UV map names in the Rizom scene.

        """
        return self.api.item_names("Lib.UVSets")

    def select_uvmap(self, uvmap_name: str):
        """Select the UV map in the RizomUV scene.

        Args:
            uvmap_name: The name of the UV map to select.

        """
        if uvmap_name == "NO_OBJ":
            return

        self.api.uv_set({"Mode": "SetCurrent", "Name": uvmap_name})

    def reset_uvmap(self, uvmap_name: str):
        """Reset the UV map by welding all seams.

        Args:
            uvmap_name: The name of the UV map to reset.

        """
        dummy_map = self.create_uvmap(str(uuid4()))
        self.select_uvmap(dummy_map)

        self.api.uv_set({"Mode": "Delete", "Name": uvmap_name})
        self.api.uv_set({"Mode": "Create", "Name": uvmap_name})
        self.select_uvmap(uvmap_name)
        self.api.reset_to_3d()

        self.delete_uvmap(dummy_map)

    def create_uvmap(self, uvmap_name: str) -> str:
        """Create a new UV map.

        Args:
            uvmap_name: The name of the UV map to create.

        Returns:
            The name of the newly created UV map.

        """
        self.api.uv_set({"Mode": "Create", "Name": uvmap_name})
        return uvmap_name

    def delete_uvmap(self, uvmap_name: str):
        """Delete an existing UV map.

        Args:
            uvmap_name: The name of the UV map to delete.

        """
        self.api.uv_set({"Mode": "Delete", "Name": uvmap_name})

    def get_selected_uvmap(self) -> str:
        """Get the name of the selected UV map.

        Returns:
            The name of the selected UV map.

        """
        name: str = self.api.get("Lib.CurrentUVSetName")
        for banned_string, replacement in BANNED_UVMAP_SUBSTRINGS.items():
            for banned_string in name:
                name = name.replace(banned_string, replacement)
        return name

    def reset_uvmaps(self, uvmaps: list[str]):
        """Reset the UV maps by welding all seams.

        Args:
            uvmaps: The names of the UV maps to reset.

        """
        for uvmap in uvmaps:
            self.reset_uvmap(uvmap)
