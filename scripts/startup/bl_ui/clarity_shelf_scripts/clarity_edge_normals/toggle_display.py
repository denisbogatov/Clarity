"""Toggle the bundled Clarity hard-edge overlay."""

import bpy
import tool


tool.register()
bpy.ops.clarity.toggle_hard_edge_display()
