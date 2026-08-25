"""Result objects from validation functions."""

from dataclasses import dataclass

from bpy.types import Object


@dataclass
class UVValidationResult:
    """Result object from UV validation functions."""

    target_object: Object
    extra_uvmaps: list[str]
    missing_uvmaps: list[str]


@dataclass
class ObjectNameValidationResult:
    """Result object from object name validation functions."""

    target_object: Object
    invalid_name_substrings: list[str]
