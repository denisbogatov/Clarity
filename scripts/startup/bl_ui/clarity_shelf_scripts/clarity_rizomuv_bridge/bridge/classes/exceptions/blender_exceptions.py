"""Blender specific exceptions."""

from typing import Optional, Type, TypeVar

from bpy.types import Object, Space, bpy_struct

T = TypeVar("T", bound=bpy_struct)


class UnexpectedObjectTypeError(Exception):
    """Raised when an object is not the expected type."""

    def __init__(self, obj: Object, expected_type: Type[T]):
        super().__init__(f"Expected object '{obj.name}' to be {expected_type.__name__}, got {obj.type}")


class UnexpectedSpaceTypeError(Exception):
    """Raised when space data is not the expected type."""

    def __init__(self, space: Optional[Space], expected_type: Type[T]):
        super().__init__(f"Expected view '{space}' to be {expected_type.__name__}, got {space}")
