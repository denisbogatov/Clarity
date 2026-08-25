"""Exceptions raised by Blender IO operations."""

from ...utils.addon_utils import export_formats


class FileImportError(Exception):
    """Exception raised when a file import fails."""

    def __init__(self):
        super().__init__("Failed to import file")


class InvalidFileFormatError(Exception):
    """Exception raised when the file format is not supported."""

    def __init__(self, format: str):
        super().__init__(f"The file format {format} is not supported, expected one of {export_formats()}")
