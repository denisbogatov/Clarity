import bpy
from bpy_extras.script_tool import ScriptToolWindow

class ExampleTool(ScriptToolWindow):
    tool_id = "example_tool"
    title = "Example Tool"
    default_width = 420
    default_height = 320

@ExampleTool.panel
class EXAMPLETOOL_PT_Main(bpy.types.Panel):
    bl_label = "Example Tool"
    bl_options = {"HIDE_HEADER"}
    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.label(text="Real Blender UILayout")
        layout.prop(context.scene.render, "resolution_percentage")
        layout.prop(context.scene, "frame_start")
        layout.prop(context.scene, "frame_end")

def register():
    ExampleTool.register(hot_reload=True)
    ExampleTool.show()

def unregister():
    ExampleTool.unregister()

if __name__ == "__main__":
    register()
