"""Handles selection operations in RizomUV."""

from ..base.rizom_api import RizomApi


class SelectCommands:
    def __init__(self, api: RizomApi):
        self.api = api

    def select_uvmap(self, uvmap: str):
        """Select a UV map in RizomUV.

        Args:
            uvmap: The name of the UV map to select.

        """
        if uvmap == "NO_OBJ":
            return

        self.api.uv_set({"Mode": "SetCurrent", "Name": uvmap})
