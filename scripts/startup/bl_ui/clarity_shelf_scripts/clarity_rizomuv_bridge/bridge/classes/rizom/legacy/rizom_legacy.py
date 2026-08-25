"""Connection manager class for connecting to RizomUV using legacy methods.

Only supports basic functionality and is never intended to be expanded with more features.
This isn't a nice solution but it works and is used by a shrinking number of users
and I don't want to spend more time on it.

RizomUVLink should be used on all compatible systems instead.

"""

import os
import platform
import subprocess
import time
import traceback
from typing import Optional
from venv import logger

from ....addon_constants import RIZOM_SCRIPT
from ....file_access import BlenderOutput, DataDirectory, RizomOutput, Session
from ....types import ExportTypes
from ....utils.rizom_utils import validate_and_transform_rizom_path
from ...data.import_models import RizomData
from ..rizom_base import RizomBase


class RizomLegacy(RizomBase):
    """Connection manager class for connecting to RizomUV using legacy methods."""

    pid: Optional[int] = None
    process: Optional[subprocess.Popen[bytes]] = None

    def __init__(self, rizom_path: str, data_dir: DataDirectory, import_timeout: int):
        self.rizom_path = validate_and_transform_rizom_path(rizom_path)
        self.mesh_files = data_dir.mesh_files
        self.rizom_output = data_dir.rizom_output
        self.blender_output = data_dir.blender_output
        self.rizom_session = data_dir.rizom_session
        self.pid_file = data_dir.rizom_pid
        self.remote_file = RIZOM_SCRIPT
        self.lock_timeout = import_timeout

        self.files = {
            "OBJ": data_dir.mesh_files.obj,
            "FBX": data_dir.mesh_files.fbx,
            "USD": data_dir.mesh_files.usd,
        }

    def _check_output(self, encoding: str) -> bool:
        """Check if the Rizom process is still running.

        Args:
            encode: Encoding to use.

        Returns:
            True if the Rizom process is still running.

        """
        output = subprocess.check_output(["tasklist", "/fi", f"PID eq {self.pid}"], text=True, encoding=encoding)
        return str(self.pid) in output

    def is_connected(self) -> bool:
        """Check if RizomUV is open and connectable.

        Works for both Windows and MacOS.

        Returns:
            True if RizomUV is open and connectable.

        """
        if self.pid is None:
            session = Session.deserialize()
            self.pid = session.pid

        if self.pid is not None:
            if platform.system() == "Darwin":
                try:
                    result = subprocess.run(["ps", "-p", str(self.pid)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    if str(self.pid) in result.stdout.decode():
                        return True
                    return False
                except subprocess.SubprocessError:
                    return False

            if platform.system() == "Windows":
                # Had problems before with different languages where switching encoding fixed it.
                try:
                    return self._check_output("latin-1")
                except UnicodeDecodeError:
                    return self._check_output("utf-8")
                except subprocess.CalledProcessError:
                    return False
        return False

    def connect_or_start(self) -> Session:
        """Attempt to connect to RizomUV, starting a new process if needed.

        Returns:
           Session instance.

        """
        if self.is_connected():
            return self._trigger_rizomuv_update()

        try:
            self.process = subprocess.Popen([self.rizom_path, "-cfi", self.remote_file])
        except Exception as e:  # TODO: Custom exception
            logger.error(traceback.format_exc())
            raise Exception(f"Failed to start RizomUV: {e}")

        self.pid = self.process.pid
        session = Session.deserialize()
        session.set_properties_with_write(pid=self.pid, locked=True)

        return session

    def _trigger_rizomuv_update(self) -> Session:
        """Get the data from the current RizomUV session.

        Rizom remote file works by watching the command file for changes.
        Can fake a change by updating the timestamp which will trigger a refresh.

        So we update the operation in the json then trigger RizomUV to read the file,
        it will then run the corresponding code in the command file.

        Session locks the file so that Blender will not try to proceed until RizomUV unlocks it.

        Returns:
           RizomUV session object.

        """
        session = Session.deserialize()
        session.lock()
        new_time = time.time()
        os.utime(self.remote_file, (new_time, new_time))
        return session

    def _await_rizom_update(self, session: Session) -> RizomOutput:
        """Wait for RizomUV to release the session lock.

        Rizom is responsible for unlocking the file when it has finished writing data,
        at that point Blender can safely read the JSON file and act on the data.

        Args:
            session: The current RizomUV session object.

        Returns:
            The RizomUV output object.

        """
        sleep_time = 0.25
        time_slept = 0

        logger.info(f"Waiting for RizomUV to release the session lock for request {session.request_id}")
        while session.locked:
            time.sleep(sleep_time)
            session.update_from_file()
            time_slept += sleep_time

            if time_slept >= self.lock_timeout:
                raise Exception(f"RizomUV is not releasing the session lock for request {session.request_id}.")

        logger.info(f"RizomUV released the session lock for request {session.request_id}")

        return RizomOutput.deserialize()

    def get_scene_data(self) -> RizomData:
        """Trigger RizomUV to execute code returning data about the current scene.

        Returns:
            A dataclass containing the object names and active UV map name from the current RizomUV session.

        """
        blender = BlenderOutput.deserialize()
        blender.start_import()
        session = self._trigger_rizomuv_update()
        rizom_output = self._await_rizom_update(session)
        return RizomData(rizom_output.loaded_objects, rizom_output.uvmaps, rizom_output.file_path)

    def load_file(self, uvmap: str, file_format: ExportTypes):
        """Load a file into RizomUV.

        Args:
            uvmap: The name of the active uvmap.
            file_format: The format of the file to load.

        Raises:
            FileNotFoundError: If the mesh file does not exist.

        """
        file_path = self.files[file_format]
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        blender_output = BlenderOutput(str(file_path), uvmap, "EXPORT")
        blender_output.serialize()
        self._trigger_rizomuv_update()
        # self._await_rizom_update(session)
