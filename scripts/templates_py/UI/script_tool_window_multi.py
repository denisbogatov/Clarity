import bpy
from bpy_extras.script_tool import ScriptToolWindow

class InspectorTool(ScriptToolWindow):
    tool_id = "inspector_tool"
    title = "Inspector"
    default_width = 360
    default_height = 260

@InspectorTool.panel
class INSPECTOR_PT_Main(bpy.types.Panel):
    bl_label = "Inspector"
    bl_options = {"HIDE_HEADER"}
    def draw(self, context):
        space = context.space_data
        self.layout.label(text=f"Instance: {space.instance_id}")
        self.layout.label(text=f"Tool ID: {space.tool_id}")
        if context.object:
            self.layout.prop(context.object, "name")

def register():
    InspectorTool.register(hot_reload=True)
    InspectorTool.open(instance_id="left", title="Inspector Left")
    InspectorTool.open(instance_id="right", title="Inspector Right")

def unregister():
    InspectorTool.unregister()

if __name__ == "__main__":
    register()
