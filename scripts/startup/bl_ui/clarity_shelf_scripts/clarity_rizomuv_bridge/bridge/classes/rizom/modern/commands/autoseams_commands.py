"""Handles autoseams operations in RizomUV."""

from .....utils import addon_utils
from ..base.rizom_api import RizomApi
from .uvmap_commands import UvmapCommands


class AutoseamsCommands:
    def __init__(self, api: RizomApi, uvmaps: UvmapCommands):
        self.api = api

    def _select_edges(self):
        pass

    def sharp_edges(self, uvmap: str):
        prefs = addon_utils.get_prefs()

        self.api.set({"Path": "Vars.AutoSelect.SharpEdges.Angle", "Value": prefs.sharp_angle})

    def box(self, uvmap: str):
        pass

    def mosaic(self, uvmap: str):
        pass

    def pelt(self, uvmap: str):
        pass
