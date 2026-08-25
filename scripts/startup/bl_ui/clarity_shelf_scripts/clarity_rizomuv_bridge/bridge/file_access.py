"""Functions for accessing external data files."""

import json
import logging
import os
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional, Type, TypeVar
from uuid import uuid4

logger = logging.getLogger(__name__)

data_path = Path.home() / "Documents" / "RizomUV Bridge"


DATA_FILE_NAMES = ("rizom_port.txt", "rizom_pid.text", "rizom_session.json", "rizom_output.json", "blender_output.json")


@dataclass
class MeshFiles:
    """Dataclass representing the mesh files directory structure."""

    fbx: Path
    obj: Path
    usd: Path


@dataclass
class DataDirectory:
    """Dataclass representing the data directory structure."""

    root: Path
    mesh_files: MeshFiles
    rizom_port: Path
    rizom_pid: Path
    rizom_session: Path
    rizom_output: Path
    blender_output: Path


def get_data_directory() -> DataDirectory:
    """Get the data directory structure."""
    mesh_files = MeshFiles(
        fbx=data_path / "mesh_files" / "rizom_transfer.fbx",
        obj=data_path / "mesh_files" / "rizom_transfer.obj",
        usd=data_path / "mesh_files" / "rizom_transfer.usd",
    )

    return DataDirectory(
        root=data_path,
        rizom_port=data_path / "rizom_port.txt",
        rizom_pid=data_path / "rizom_pid.txt",
        rizom_session=data_path / "rizom_session.json",
        rizom_output=data_path / "rizom_output.json",
        blender_output=data_path / "blender_output.json",
        mesh_files=mesh_files,
    )


def ensure_data_dir_integrity():
    """Ensure that the data directory is setup.

    Creates the directories and files that the addon
    needs to function.

    """
    # Ensure the data directory exists
    os.makedirs(data_path, exist_ok=True)

    # Ensure the mesh export directory exists
    os.makedirs(data_path / "mesh_files", exist_ok=True)

    # Ensure data files exist
    for file_name in DATA_FILE_NAMES:
        (data_path / file_name).touch()


def read_port_file() -> int | None:
    """Read the port file and return the port number."""
    try:
        with open(data_path / "rizom_port.txt", "r") as file:
            contents = file.read()
            if contents:
                return int(contents)
            return None
    except Exception as e:
        logger.warning(f"Error reading port file: {e}")
        return None


def write_port_file(port: int):
    """Write the port file with the given port number."""
    try:
        with open(data_path / "rizom_port.txt", "w") as file:
            file.write(str(port))
    except Exception:
        logger.warning(traceback.format_exc())


def read_pid_file() -> int | None:
    """Read the pid file and return the pid number."""
    try:
        with open(data_path / "rizom_pid.txt", "r") as file:
            contents = file.read()
            if contents:
                return int(contents)
            return None
    except Exception:
        logger.warning(traceback.format_exc())
        return None


data_dir = get_data_directory()


T = TypeVar("T", bound="StoreBase")


class StoreBase:
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
        """Serialise all public class properties to the json file with the exception the json path.

        Public properties are those that are not prefixed with an underscore.

        """
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


class RizomOutput(StoreBase):
    json_path: Path = data_dir.rizom_output

    def __init__(self):
        """Initialize the RizomOutput class."""
        super().__init__()

        self.file_path: str
        self.uvmaps: list[str]
        self.loaded_objects: list[str]

        self.update_from_file()


class BlenderOutput(StoreBase):
    json_path: Path = data_dir.blender_output

    def __init__(
        self, file_path: Optional[str], uvmap: Optional[str], operation: Literal["EXPORT", "IMPORT", "REQUEST_STATE"]
    ):
        """Initialize the BlenderOutput class.

        Args:
            file_path: Path to the mesh file.
            uvmap: Name of the active uvmap.
            operation: Key of the operation to run.

        """
        super().__init__()
        self.file_path: Optional[str] = file_path
        self.uvmap: Optional[str] = uvmap
        self.operation: str = operation

    def start_export(self):
        """Set the operation to export."""
        self.operation = "EXPORT"
        self.serialize()

    def start_import(self):
        """Set the operation to import."""
        self.operation = "IMPORT"
        self.serialize()

    def __str__(self):  # noqa: D105
        return f"File Path: {self.file_path}\nUV Map: {self.uvmap}\nOperation: {self.operation}"


class Session(StoreBase):
    json_path: Path = data_dir.rizom_session

    def __init__(self, request_id=str(uuid4()), pid=-1, locked=True):
        super().__init__()
        self.pid: int = pid
        self.locked: bool = locked
        self.request_id: str = request_id

    def lock(self):
        """Lock the session file."""
        if "Rizom" in sys.executable:
            raise Exception("Blender is responsible for locking the session file.")

        self.locked = True
        self.serialize()

    def __str__(self):  # noqa: D105
        return f"Locked: {self.locked}, Pid: {self.pid}"
