"""Run the bundled Clarity Harden All Edges command."""

import bpy
import tool


tool.register()
bpy.ops.clarity.harden_all_edges()
