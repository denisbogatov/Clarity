"""Exceptions raised by RizomUV related errors."""


class RizomLinkModuleNotFoundError(Exception):
    """Exception raised when the RizomUVLink module is not found."""

    def __init__(self):
        super().__init__("The RizomUVLink module was not found under the RizomUV installation.")


class RizomNotFoundError(Exception):
    """Exception raised when the rizom path does not lead to a RizomUV executable."""

    def __init__(self, path: str):
        super().__init__(f"The Rizom path {path} does not lead to the RizomUV executable.")


class RizomTimeoutError(Exception):
    """Exception raised when the RizomUVLink connection times out."""

    pass


class RizomLinkUnsupportedError(Exception):
    """Exception raised when the RizomLink module is not supported."""

    pass


class RizomLinkConnectionError(Exception):
    """Exception raised when the connection to the RizomLink module fails."""

    pass


class RizomUVLinkNotImportedError(Exception):
    """Exception raised when the RizomUVLink module is called before it is imported."""

    pass


class RizomUVLinkTimeoutError(Exception):
    """Exception raised when the RizomUVLink connection times out."""

    def __init__(self, tries: int):
        super().__init__(f"RizomUVLink connection timed out waiting for RizomUV to load after {tries} attempts")


class RizomLegacyConnectionError(Exception):
    """Exception raised when the app cannot find an open instance of RizomUV."""

    def __init__(self, message="Could not find an open instance of RizomUV"):
        super().__init__(message)
