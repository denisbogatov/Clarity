"""Maya-style soften/harden edge tools for the Clarity shelf."""

import math

import bpy
import bmesh
from bpy.props import BoolProperty, FloatProperty
from bpy.types import Panel
from bpy_extras.script_tool import ScriptToolWindow


SHARP_OVERLAY_COLOR = (0.62, 0.16, 1.0)
UV_EPSILON_SQUARED = 1.0e-12
OVERLAY_HANDLER_KEY = "clarity_hard_edge_overlay_handler"
OVERLAY_ENABLED_KEY = "clarity_hard_edge_overlay_enabled"
TOOL_CONTEXT = "clarity_edge_normals"


class EdgeNormalsToolWindow(ScriptToolWindow):
    tool_id = TOOL_CONTEXT
    title = "Soften/Harden Edges by Angle"
    default_width = 520
    default_height = 210


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


def _validate_mesh_context(operator, context):
    if context.mode not in {'OBJECT', 'EDIT_MESH'}:
        operator.report({'WARNING'}, "Use this tool in Object or Mesh Edit Mode")
        return []
    objects = _selected_unique_mesh_objects(context)
    if not objects:
        operator.report({'WARNING'}, "Select at least one editable mesh")
    return objects


def _bmesh_edge_is_uv_border(edge, uv_layer):
    if uv_layer is None or len(edge.link_faces) != 2:
        return False

    face_uvs = []
    for face in edge.link_faces:
        edge_loop = next((loop for loop in face.loops if loop.edge == edge), None)
        if edge_loop is None:
            return False
        face_uvs.append({
            edge_loop.vert: edge_loop[uv_layer].uv.copy(),
            edge_loop.link_loop_next.vert: edge_loop.link_loop_next[uv_layer].uv.copy(),
        })

    for vert in edge.verts:
        if vert not in face_uvs[0] or vert not in face_uvs[1]:
            return False
        if (face_uvs[0][vert] - face_uvs[1][vert]).length_squared > UV_EPSILON_SQUARED:
            return True
    return False


def _prepare_soft_edges(edges):
    soft_edges = set(edges)
    faces_to_smooth = {face for edge in soft_edges for face in edge.link_faces}
    for face in faces_to_smooth:
        if face.smooth:
            continue
        # Changing a flat face to smooth would otherwise soften its unselected
        # boundary edges too. Preserve their previous hard appearance explicitly.
        for edge in face.edges:
            if edge not in soft_edges:
                edge.smooth = False
        face.smooth = True


def _set_edit_mesh_by_angle(obj, angle, texture_borders):
    bm = bmesh.from_edit_mesh(obj.data)
    uv_layer = bm.loops.layers.uv.active if texture_borders else None
    targets = []
    changed = 0
    for edge in bm.edges:
        if not edge.select:
            continue
        is_boundary = len(edge.link_faces) != 2
        face_angle = edge.calc_face_angle(0.0) if not is_boundary else math.pi
        sharp = (
            is_boundary or
            face_angle > angle or
            (texture_borders and _bmesh_edge_is_uv_border(edge, uv_layer))
        )
        targets.append((edge, sharp))

    _prepare_soft_edges(edge for edge, sharp in targets if not sharp)
    for edge, sharp in targets:
        if edge.smooth == sharp:
            edge.smooth = not sharp
            changed += 1
    bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
    return changed


def _object_mesh_uv_borders(mesh):
    uv_layer = mesh.uv_layers.active
    if uv_layer is None:
        return set()

    first_uv_by_edge_vert = {}
    borders = set()
    for polygon in mesh.polygons:
        loop_indices = list(polygon.loop_indices)
        for polygon_loop_index, loop_index in enumerate(loop_indices):
            loop = mesh.loops[loop_index]
            edge_index = loop.edge_index
            next_loop_index = loop_indices[(polygon_loop_index + 1) % len(loop_indices)]
            for endpoint_loop_index in (loop_index, next_loop_index):
                endpoint_loop = mesh.loops[endpoint_loop_index]
                uv = uv_layer.data[endpoint_loop_index].uv
                key = (edge_index, endpoint_loop.vertex_index)
                previous = first_uv_by_edge_vert.get(key)
                if previous is None:
                    first_uv_by_edge_vert[key] = uv.copy()
                elif (previous - uv).length_squared > UV_EPSILON_SQUARED:
                    borders.add(edge_index)
    return borders


def _set_object_mesh_by_angle(obj, angle, texture_borders):
    mesh = obj.data
    edge_faces = [[] for _edge in mesh.edges]
    for polygon in mesh.polygons:
        polygon.use_smooth = True
        for loop_index in polygon.loop_indices:
            edge_faces[mesh.loops[loop_index].edge_index].append(polygon.index)
    uv_borders = _object_mesh_uv_borders(mesh) if texture_borders else set()

    changed = 0
    for edge in mesh.edges:
        linked_faces = edge_faces[edge.index]
        is_boundary = len(linked_faces) != 2
        if is_boundary:
            sharp = True
        else:
            normal_a = mesh.polygons[linked_faces[0]].normal
            normal_b = mesh.polygons[linked_faces[1]].normal
            face_angle = normal_a.angle(normal_b, 0.0)
            sharp = face_angle > angle or edge.index in uv_borders
        if edge.use_edge_sharp != sharp:
            edge.use_edge_sharp = sharp
            changed += 1
    mesh.update()
    return changed


def _set_all_edges(objects, sharp):
    changed = 0
    for obj in objects:
        mesh = obj.data
        if obj.mode == 'EDIT':
            bm = bmesh.from_edit_mesh(mesh)
            selected_edges = [edge for edge in bm.edges if edge.select]
            if not sharp:
                _prepare_soft_edges(selected_edges)
            for edge in selected_edges:
                if edge.smooth == sharp:
                    edge.smooth = not sharp
                    changed += 1
            bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)
        else:
            for polygon in mesh.polygons:
                polygon.use_smooth = True
            for edge in mesh.edges:
                if edge.use_edge_sharp != sharp:
                    edge.use_edge_sharp = sharp
                    changed += 1
            mesh.update()
    return changed


def _tag_all_view3d_redraw(context):
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


class CLARITY_OT_soften_harden_edges(bpy.types.Operator):
    bl_idname = "clarity.soften_harden_edges"
    bl_label = "Soften/Harden Edges"
    bl_description = "Set soft and hard edges from face angle, optionally preserving UV borders"
    bl_options = {'REGISTER', 'UNDO'}

    angle: FloatProperty(
        name="Angle",
        description="Edges above this angle become hard; edges at or below it become soft",
        subtype='ANGLE',
        min=0.0,
        max=math.pi,
        default=math.radians(30.0),
    )
    texture_borders: BoolProperty(
        name="Texture Borders",
        description="Keep UV island borders hard",
        default=False,
    )

    def execute(self, context):
        objects = _validate_mesh_context(self, context)
        if not objects:
            return {'CANCELLED'}
        changed = 0
        for obj in objects:
            if obj.mode == 'EDIT':
                changed += _set_edit_mesh_by_angle(obj, self.angle, self.texture_borders)
            else:
                changed += _set_object_mesh_by_angle(obj, self.angle, self.texture_borders)
        self.report({'INFO'}, f"Updated {changed} edge(s)")
        return {'FINISHED'}


class CLARITY_OT_soften_all_edges(bpy.types.Operator):
    bl_idname = "clarity.soften_all_edges"
    bl_label = "Soften Edges"
    bl_description = "Soften selected edges in Edit Mode or all edges of selected objects"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        objects = _validate_mesh_context(self, context)
        if not objects:
            return {'CANCELLED'}
        changed = _set_all_edges(objects, False)
        self.report({'INFO'}, f"Softened {changed} edge(s)")
        return {'FINISHED'}


class CLARITY_OT_harden_all_edges(bpy.types.Operator):
    bl_idname = "clarity.harden_all_edges"
    bl_label = "Harden Edges"
    bl_description = "Harden selected edges in Edit Mode or all edges of selected objects"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        objects = _validate_mesh_context(self, context)
        if not objects:
            return {'CANCELLED'}
        changed = _set_all_edges(objects, True)
        self.report({'INFO'}, f"Hardened {changed} edge(s)")
        return {'FINISHED'}


class CLARITY_OT_close_edge_normals_window(bpy.types.Operator):
    bl_idname = "clarity.close_edge_normals_window"
    bl_label = "Close"
    bl_description = "Close the Soften/Harden Edges tool window"
    bl_options = {'INTERNAL'}

    def execute(self, _context):
        EdgeNormalsToolWindow.close()
        return {'FINISHED'}


class CLARITY_OT_toggle_hard_edge_display(bpy.types.Operator):
    bl_idname = "clarity.toggle_hard_edge_display"
    bl_label = "Toggle Hard Edge Display"
    bl_description = "Show or hide hard edges in purple in all 3D View editors"

    def execute(self, context):
        theme = context.preferences.themes[0].view_3d
        theme.sharp = SHARP_OVERLAY_COLOR

        spaces = [
            area.spaces.active
            for window in context.window_manager.windows
            for area in window.screen.areas
            if area.type == 'VIEW_3D'
        ]
        if not spaces:
            self.report({'WARNING'}, "No 3D View is open")
            return {'CANCELLED'}

        namespace = bpy.app.driver_namespace
        old_handler = namespace.pop(OVERLAY_HANDLER_KEY, None)
        if old_handler is not None:
            bpy.types.SpaceView3D.draw_handler_remove(old_handler, 'WINDOW')
        enable = not namespace.get(OVERLAY_ENABLED_KEY, False)
        namespace[OVERLAY_ENABLED_KEY] = enable
        for space in spaces:
            space.overlay.show_overlays = True
            space.overlay.show_edge_sharp = enable
        _tag_all_view3d_redraw(context)
        message = "Hard edge display enabled" if enable else "Hard edge display disabled"
        self.report({'INFO'}, message)
        return {'FINISHED'}


@EdgeNormalsToolWindow.panel
class CLARITY_PT_edge_normals(Panel):
    bl_idname = "CLARITY_PT_edge_normals"
    bl_label = "Soften/Harden Edges"
    bl_options = {'HIDE_HEADER'}

    def draw(self, context):
        layout = self.layout
        settings = context.window_manager

        method = layout.row(align=True)
        method.label(text="Method:")
        method.label(text="Angle", icon='RADIOBUT_ON')

        layout.prop(settings, "clarity_edge_normals_angle", text="Angle", slider=True)
        layout.prop(settings, "clarity_edge_normals_texture_borders", text="Texture Borders")

        layout.separator()
        action = layout.operator(
            "clarity.soften_harden_edges",
            text="Apply",
        )
        action.angle = settings.clarity_edge_normals_angle
        action.texture_borders = settings.clarity_edge_normals_texture_borders


CLASSES = (
    CLARITY_OT_soften_harden_edges,
    CLARITY_OT_soften_all_edges,
    CLARITY_OT_harden_all_edges,
    CLARITY_OT_close_edge_normals_window,
    CLARITY_OT_toggle_hard_edge_display,
)


def register():
    if not hasattr(bpy.types.WindowManager, "clarity_edge_normals_angle"):
        bpy.types.WindowManager.clarity_edge_normals_angle = FloatProperty(
            name="Angle",
            description="Edges above this angle become hard",
            subtype='ANGLE',
            min=0.0,
            max=math.pi,
            default=math.radians(30.0),
        )
    if not hasattr(bpy.types.WindowManager, "clarity_edge_normals_texture_borders"):
        bpy.types.WindowManager.clarity_edge_normals_texture_borders = BoolProperty(
            name="Texture Borders",
            description="Keep UV island borders hard",
            default=False,
        )

    for cls in CLASSES:
        old_cls = getattr(bpy.types, cls.__name__, None)
        if old_cls is not None and old_cls is not cls:
            try:
                bpy.utils.unregister_class(old_cls)
            except RuntimeError:
                pass
        try:
            bpy.utils.register_class(cls)
        except ValueError:
            pass
    EdgeNormalsToolWindow.register(hot_reload=True)


def unregister():
    EdgeNormalsToolWindow.unregister(close_windows=True)
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
    if hasattr(bpy.types.WindowManager, "clarity_edge_normals_texture_borders"):
        del bpy.types.WindowManager.clarity_edge_normals_texture_borders
    if hasattr(bpy.types.WindowManager, "clarity_edge_normals_angle"):
        del bpy.types.WindowManager.clarity_edge_normals_angle
