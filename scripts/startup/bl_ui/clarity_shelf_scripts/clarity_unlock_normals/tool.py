"""Remove locked custom normals from the selected mesh objects."""

import bpy


def _selected_unique_mesh_objects(context):
    if context.mode == 'EDIT_MESH':
        candidates = list(getattr(context, "objects_in_mode_unique_data", ()) or ())
    else:
        candidates = list(context.selected_objects)

    objects = []
    seen_meshes = set()
    for obj in candidates:
        if obj.type != 'MESH' or not obj.data.is_editable:
            continue
        mesh_key = obj.data.as_pointer()
        if mesh_key in seen_meshes:
            continue
        seen_meshes.add(mesh_key)
        objects.append(obj)
    return objects


class CLARITY_OT_unlock_normals(bpy.types.Operator):
    bl_idname = "clarity.unlock_normals"
    bl_label = "Unlock Normals"
    bl_description = (
        "Remove custom split normals from selected meshes and return them to automatic normals"
    )
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        if context.mode not in {'OBJECT', 'EDIT_MESH'}:
            self.report({'WARNING'}, "Use Unlock Normals in Object or Mesh Edit Mode")
            return {'CANCELLED'}

        objects = _selected_unique_mesh_objects(context)
        if not objects:
            self.report({'WARNING'}, "Select at least one editable mesh")
            return {'CANCELLED'}

        original_active = context.view_layer.objects.active
        unlocked = 0
        already_unlocked = 0
        failed = []

        try:
            for obj in objects:
                if not obj.data.has_custom_normals:
                    already_unlocked += 1
                    continue

                override = {
                    "object": obj,
                    "active_object": obj,
                    "selected_objects": [obj],
                    "selected_editable_objects": [obj],
                }
                if obj.mode == 'EDIT':
                    override["edit_object"] = obj

                try:
                    context.view_layer.objects.active = obj
                    with context.temp_override(**override):
                        result = bpy.ops.mesh.customdata_custom_splitnormals_clear()
                    if 'FINISHED' in result:
                        unlocked += 1
                    else:
                        failed.append(obj.name)
                except RuntimeError:
                    failed.append(obj.name)
        finally:
            if original_active is not None and original_active.name in context.view_layer.objects:
                context.view_layer.objects.active = original_active

        if failed:
            self.report({'WARNING'}, "Could not unlock normals: " + ", ".join(failed))
        if unlocked:
            suffix = "mesh" if unlocked == 1 else "meshes"
            self.report({'INFO'}, f"Unlocked normals on {unlocked} {suffix}")
            return {'FINISHED'}
        if already_unlocked:
            self.report({'INFO'}, "Selected meshes already use automatic normals")
            return {'FINISHED'}
        return {'CANCELLED'}


CLASSES = (CLARITY_OT_unlock_normals,)


def register():
    for cls in CLASSES:
        try:
            bpy.utils.register_class(cls)
        except ValueError:
            pass


def unregister():
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass


def run_now():
    return bpy.ops.clarity.unlock_normals()


if __name__ == "__main__":
    register()
    run_now()
