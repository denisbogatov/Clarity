"""Run the bundled Clarity Soften All Edges command."""

import bpy
import tool


tool.register()
bpy.ops.clarity.soften_all_edges()
