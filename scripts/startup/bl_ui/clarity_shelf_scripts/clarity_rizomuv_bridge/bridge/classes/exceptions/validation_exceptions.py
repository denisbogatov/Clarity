"""Exceptions raised by validation errors."""

from bpy.types import Object

from ..data.validation_results import ObjectNameValidationResult, UVValidationResult


class NonMatchingTopologyError(Exception):
    """Exception raised when 2 meshes do not have the same topology."""

    def __init__(self, a: Object, b: Object):
        super().__init__(f"Objects do not have matching topology: {a.name} and {b.name}")


class InvalidUVSetNamesError(Exception):
    """Exception raised when the active object has invalid UV map names."""

    def __init__(self, invalid_uvmaps: dict[str, list[str]]):
        self.invalid_uvmaps = invalid_uvmaps
        super().__init__("The active object has invalid UV map names, see console for details")


class InvalidUVSetsError(Exception):
    """Exception raised when objects have invalid UV maps."""

    def __init__(self, results: list[UVValidationResult]):
        self.results = results
        super().__init__("Some objects do not have valid UV maps, see console for details")


class InvalidObjectNamesError(Exception):
    """Exception raised when objects have invalid names."""

    def __init__(self, results: list[ObjectNameValidationResult]):
        self.results = results
        super().__init__("Some objects do not have valid names, see console for details")
