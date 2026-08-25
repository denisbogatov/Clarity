"""Utility functions for DRY UI code."""

from bpy.types import UILayout


def scaled_row(layout: UILayout, scale=1.5, align=False) -> UILayout:
    """Create a row with specified y scale."""
    row = layout.row(align=align)
    row.scale_y = scale
    return row


def split_scaled_row(layout: UILayout, factor: float, scale=1.5) -> UILayout:
    """Create a split row with specified split factor."""
    row = scaled_row(layout, scale)
    return row.split(factor=factor, align=True)
