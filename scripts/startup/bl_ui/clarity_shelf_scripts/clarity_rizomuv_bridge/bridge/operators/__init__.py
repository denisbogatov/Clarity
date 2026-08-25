"""Operators module."""

import bpy

from .rename_uvmaps import RenameUVMaps
from .rizom_action import RizomAction
from .rizom_export import ExportToRizom
from .rizom_import import ImportFromRizom
from .rizom_load import LoadInRizom

OPERATORS = (ExportToRizom, ImportFromRizom, LoadInRizom, RizomAction, RenameUVMaps)


def register():
    """Register operators."""
    for op in OPERATORS:
        bpy.utils.register_class(op)


def unregister():
    """Unregister operators."""
    for op in OPERATORS:
        bpy.utils.unregister_class(op)
