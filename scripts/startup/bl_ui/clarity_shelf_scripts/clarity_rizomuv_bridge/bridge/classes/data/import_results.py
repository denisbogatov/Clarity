"""Data classes for storing import results."""

from dataclasses import dataclass

from bpy.types import Object


@dataclass
class UVTransferResult:
    """Result of transferring UV maps."""

    missing_objects: list[str]
    missing_uvmaps: dict[Object, list[str]]
