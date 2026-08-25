"""Manager class for the RizomUV connection."""

import logging
import time
from typing import TYPE_CHECKING, cast

from .....file_access import DataDirectory
from ....exceptions.rizom_exeptions import RizomNotFoundError, RizomUVLinkTimeoutError
from ..common.version import Version
from .rizom_module_loader import RizomModuleLoader

if TYPE_CHECKING:
    from .....lib.RizomUVLink import RizomUVLink

logger = logging.getLogger(__name__)


class RizomConnectionManager:
    """Wraps the RizomUVLink connection."""

    def __init__(
        self, module_loader: RizomModuleLoader, data_dir: DataDirectory, rizom_path: str, connection_timeout: int
    ):
        self.module_loader = module_loader
        self.port_cache_path = data_dir.rizom_port
        self._link: "RizomUVLink.CRizomUVLink"
        self.port: int
        self.version: Version | None = None
        self.rizom_path = rizom_path

        self._connection_timeout = connection_timeout

    def is_connected(self) -> bool:
        """Check if there is an active connection.

        Returns:
            True if there is an active connection.

        """
        if not self._link or not self.port:
            return False

        try:
            if self._link.TCPPortIsOpen(self.port):
                self.version = Version(self._link.RizomUVVersion())
                return True
        except Exception:
            pass
        return False

    def connect(self) -> bool:
        """Connect to existing RizomUV instance.

        Returns:
            True if the connection was successful.

        """
        self._link: "RizomUVLink.CRizomUVLink" = self.module_loader.module.CRizomUVLink()

        port = self._read_cached_port()
        if not port:
            return False

        self.port = port
        self._link.Connect(self.port)
        return self.is_connected()

    def start_new_instance(self) -> None:
        """Start a new RizomUV instance.

        Raises:
            RizomNotFoundError: If the RizomUV executable could not be found or is not valid.

        """
        if not self._link:
            self._link = self.module_loader.module.CRizomUVLink()
            logger.info(f"RizomUVLink module loaded from: {self.module_loader.module.__file__}")

        try:
            self.port = self._start_rizom_process()
            self.version = Version(self._link.RizomUVVersion())
            self._cache_port(self.port)
            logger.info(f"RizomUV process started on port {self.port!s}")
        except (FileNotFoundError, OSError):
            raise RizomNotFoundError(self.rizom_path)

    def connect_or_start(self):
        """Connect to existing instance or start new one.

        Raises:
            RizomNotFoundError: If the Rizom path does not lead to a RizomUV executable.

        """
        if self.connect():
            return

        self.start_new_instance()

    def quit(self) -> None:
        """Close the RizomUV instance."""
        if self._link:
            self._link.Quit()

    def _read_cached_port(self) -> int | None:
        """Read cached port from file.

        Returns:
            The cached port as an integer or None if no port is cached.

        """
        with open(self.port_cache_path, "r", encoding="utf-8") as f:
            contents = f.read().strip()

            try:
                return int(contents)
            except ValueError:
                return None

    def _cache_port(self, port: int):
        """Cache port to file.

        Args:
            port: The port to cache.

        """
        with open(self.port_cache_path, "w", encoding="utf-8") as f:
            f.write(str(port))

    def _start_rizom_process(self) -> int:
        """Start RizomUV process with timeout workaround.

        Raises:
            RizomNotFoundError: If the RizomUV executable could not be found or is not valid.
            TimeoutError: If the connection times out.

        """
        start_time = time.time()
        connection_attempts = 1

        try:
            logger.info(f"Connection attempt {connection_attempts}...")
            port = self._link.RunRizomUV(self.rizom_path)
            self.version = Version(self._link.RizomUVVersion())
            return port
        except Exception as e:
            if type(e).__name__ == "ZEx":
                # RizomUVVersion() will block until the connection is established or it times out so no sleep needed
                while time.time() - start_time < self._connection_timeout:
                    try:
                        connection_attempts += 1
                        logger.info(f"Connection attempt {connection_attempts}...")
                        port = cast(int, self._link.port)
                        self._link.Connect(port)
                        self.version = Version(self._link.RizomUVVersion())
                        return port
                    except Exception:
                        continue

                raise RizomUVLinkTimeoutError(connection_attempts)
            raise e
