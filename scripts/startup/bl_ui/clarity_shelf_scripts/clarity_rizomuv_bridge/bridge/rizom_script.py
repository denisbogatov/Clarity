"""File which is loaded into Rizom, completely independent of the rest of the addon.

When running RizomUV with the legacy class this file is executed inside by RizomUV, it runs
on the startup and also when the script timestamp changes. I use os.utime to update the timestamp
without modifying the contents, this allows conditional actions based on the operation defined
inside the blender_output.json file. All communication from Rizom -> Blender goes through
rizom_output.json, all communication from Blender -> Rizom goes through blender_output.json.

rizom_session.json contains a lock property to prevent race conditions. Blender sets an operation,
locks the session and triggers an update, it then watches the lock property and waits for RizomUV to
set it to False.

This file is fairly unorganized because it cannot have any external dependencies as Rizom
will not be able to import them. Any code that Rizom needs to be able to run must go in here, this also means
there is a decent amount of duplicated code here.

## Specific Library omissions
Libraries that do not work for whatever reason.

- Platform. Does not work on MacOS in RizomUV.
- SQLite. Does not work on MacOS in RizomUV.

"""

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional, Type, TypeVar

# Just doing this to appease the type checker, don't have any stubs for Rizom API.
if TYPE_CHECKING:
    from types import ModuleType

    App = ModuleType("App")

# Export nothing from this module to avoid accidentally importing it.
__all__ = []


class RizomScriptExternalExecutionError(Exception):
    """Exception raised when scripts are executed outside of RizomUV."""

    def __init__(self):
        super().__init__("This script is only intended to be loaded in RizomUV.")


if "Rizom" not in sys.executable:
    raise RizomScriptExternalExecutionError()


# Duplicated dataclasses because I can't import modules from the Blender addon in Rizom.
@dataclass
class MeshFilesPrivate:
    """Dataclass representing the mesh files directory structure."""

    fbx: Path
    obj: Path
    usd: Path


@dataclass
class DataDirectoryPrivate:
    """Dataclass representing the data directory structure."""

    root: Path
    mesh_files: MeshFilesPrivate
    rizom_port: Path
    rizom_pid: Path
    rizom_session: Path
    rizom_output: Path
    blender_output: Path


data_path = Path.home() / "Documents" / "RizomUV Bridge"
if not data_path.exists():
    raise FileNotFoundError(f"Could not find the data directory at {data_path}")


data_dir = DataDirectoryPrivate(
    root=data_path,
    rizom_port=data_path / "rizom_port.txt",
    rizom_pid=data_path / "rizom_pid.txt",
    rizom_session=data_path / "rizom_session.json",
    rizom_output=data_path / "rizom_output.json",
    blender_output=data_path / "blender_output.json",
    mesh_files=MeshFilesPrivate(
        fbx=data_path / "mesh_files" / "rizom_transfer.fbx",
        obj=data_path / "mesh_files" / "rizom_transfer.obj",
        usd=data_path / "mesh_files" / "rizom_transfer.usd",
    ),
)


T = TypeVar("T", bound="StoreBasePrivate")


class StoreBasePrivate:
    json_path: Path

    def __init__(self):
        """Initialize the Store."""
        if not self.json_path.exists():
            raise FileNotFoundError(f"Could not find the store file at {self.json_path}")

    def set_properties_with_write(self, **kwargs):
        """Update the data model and its json file.

        Update the class properties and write to the json file
        to persist the changes across the Rizom and Blender sessions.

        No autocompletion because this needs to be compatible with
        Python 3.7 for RizomUV, meaning no TypedDict.

        Args:
            The properties to update.

        """
        for k, v in kwargs.items():
            self.__dict__[k] = v

        try:
            with open(self.json_path, "r") as f:
                data = json.load(f)
        except json.JSONDecodeError:
            data = {}

        data.update(kwargs)

        with open(self.json_path, "w") as f:
            json.dump(data, f)

    def update_from_file(self):
        """Update existing data model from the json file."""
        try:
            with open(self.json_path, "r") as f:
                data = json.load(f)
                self.__dict__.update(**data)
        except json.JSONDecodeError:
            pass

    def serialize(self):
        with open(self.json_path, "w") as f:
            data = {k: v for k, v in self.__dict__.items() if not k.startswith("_") and k != "json_path"}
            json.dump(data, f, indent=2)

    @classmethod
    def deserialize(cls: Type[T]) -> T:
        """Deserialize the data from a json file."""
        try:
            with open(cls.json_path, "r") as f:
                data = json.load(f)
        except json.JSONDecodeError:
            data = {}

        try:
            return cls(**data)
        except TypeError:
            return cls(**{})


class RizomOutputPrivate(StoreBasePrivate):
    json_path: Path = data_dir.rizom_output

    def __init__(self):
        """Initialize the RizomOutput class.

        Args:
            uvmaps: Name of the uvmaps in Rizom.
            loaded_objects: Names of the meshes in Rizom.

        """
        super().__init__()

        self.file_path: str
        self.uvmaps: List[str]
        self.loaded_objects: List[str]

        if "Rizom" in sys.executable:
            self.file_path: str = App.Get("Prefs.LastLoadedFile")
            self.uvmaps: List[str] = App.ItemNames("Lib.UVSets")
            self.loaded_objects: List[str] = App.Get("Lib.Mesh.ObjectsNames")
        else:
            self.update_from_file()

    def update_state_from_rizom(self, serialize: bool):
        """Populate the RizomOutput class with the current state from RizomUV.

        Args:
            serialize: Whether to serialize the data immediately.

        Raises:
            RizomApiExternalError: If the Rizom API is called outside of RizomUV.

        """
        self.file_path: str = App.Get("Prefs.LastLoadedFile")
        self.uvmaps = App.ItemNames("Lib.UVSets")

        loaded_objects = App.Get("Lib.Mesh.ObjectsNames")
        if "DefaultObject" in loaded_objects:
            loaded_objects.remove("DefaultObject")
        if self.get_format() == "USD":
            # Extract the object name from the USD prim.
            loaded_objects = [obj.split("/")[-1] for obj in loaded_objects]
        self.loaded_objects = loaded_objects

        if serialize:
            self.serialize()

    def get_format(self) -> str:
        """Return the format of the mesh file.

        Formats the extension into 3 letter suffix matching addon enums.

        - fbx -> FBX
        - obj -> OBJ
        - usdc -> USD

        Returns:
            str: Format suffix of the mesh file. (FBX | OBJ | USD)

        """
        return os.path.splitext(self.file_path)[1][1:][:3].upper()

    def __str__(self):
        return f"File Path: {self.file_path}\nUV Map: {self.uvmaps}"


class BlenderOutputPrivate(StoreBasePrivate):
    json_path: Path = data_dir.blender_output

    def __init__(self, file_path: Optional[str], uvmap: Optional[str], operation: str):
        """Initialize the BlenderOutput class.

        Operation should be a literal of ("EXPORT", "LOAD", "IMPORT", "REQUEST_STATE")
        but Literal was added after Python 3.7 so I can't use it here.

        Args:
            file_path: Path to the mesh file.
            uvmap: Name of the active uvmap.
            operation: Key of the operation to run.

        """
        super().__init__()
        self.file_path: Optional[str] = file_path
        self.uvmap: Optional[str] = uvmap
        self.operation: str = operation

    def __str__(self):
        return f"File Path: {self.file_path}\nUV Map: {self.uvmap}\nOperation: {self.operation}"


class SessionPrivate(StoreBasePrivate):
    json_path: Path = data_dir.rizom_session

    def __init__(self, request_id: str, pid=-1, locked=True):
        super().__init__()
        self.pid: int = pid
        self.locked: bool = locked
        self.request_id: str = request_id

    def unlock(self):
        """Unlock the session file."""
        self.locked = False
        self.serialize()
        print("Session unlocked")

    def __str__(self):
        return f"Locked: {self.locked}, Pid: {self.pid}"


session = SessionPrivate.deserialize()
print(f"Processing request: {session.request_id}")

try:
    rizom_output = RizomOutputPrivate.deserialize()
    blender_output = BlenderOutputPrivate.deserialize()

    remote_file = App.Get("Prefs.RemoteControlFilePath")
    if not remote_file:
        raise FileNotFoundError("Could not find the remote control file.")

    if blender_output.operation in ("EXPORT", "LOAD"):
        App.Load(
            {
                "File": {
                    "Path": blender_output.file_path,
                    "ImportGroups": True,
                    "XYZUVW": True,
                    "FBX": {"UseUVSetNames": True},
                    "AutoWeld": True,
                    "Meta": True,
                    "Normals": True,
                },
                "__Focus": True,
            }
        )

        if blender_output.operation == "EXPORT":
            # OBJ format causes the UV Map to lose its name, so restore it here.
            if blender_output.file_path.lower().endswith(".obj"):
                App.Uvset({"Mode": "Rename", "Name": blender_output.uvmap})
        rizom_output.update_state_from_rizom(True)

    elif blender_output.operation == "IMPORT":
        rizom_output.update_state_from_rizom(True)
        App.Save(
            {
                "File": {
                    rizom_output.get_format(): {"UseUVSetNames": True},
                    "Path": rizom_output.file_path,
                    "UVWProps": True,
                }
            }
        )
except Exception as e:
    print(f"Error processing request {session.request_id}: {e}")

# Release the lock once RizomUV has finished executing, safe to do stuff in Blender.
finally:
    session.unlock()
    print(f"Completed request: {session.request_id}")
