"""Handles object operations in RizomUV."""

from .....utils import usd_utils
from ..base.rizom_api import RizomApi
from .file_commands import FileCommands


class ObjectCommands:
    def __init__(self, api: RizomApi, files: FileCommands):
        """Initialize the ObjectCommands class.

        Args:
            api: The Rizom API class.
            files: The FileCommands class.

        """
        self.api = api
        self.files = files

    def get_object_names(self) -> list[str]:
        """Get the names of all objects in the scene.

        Returns:
            A list of object names in the Rizom scene.

        """
        objects: list[str] = self.api.get("Lib.Mesh.ObjectsNames")

        # DefaultObject is a fake object created by Rizom, I'm not sure why it exists.
        # Assume it's not a real object and exclude it.
        if "DefaultObject" in objects:
            objects.remove("DefaultObject")

        if self.files.get_file_type() == "USD":
            objects = [usd_utils.get_name_from_prim(obj)[0] for obj in objects]

        return objects
