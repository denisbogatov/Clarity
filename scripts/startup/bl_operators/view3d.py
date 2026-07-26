# SPDX-FileCopyrightText: 2011-2023 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

import bpy
from bpy.types import (
    Operator,
    FileHandler,
)
from bpy.props import (
    BoolProperty,
    EnumProperty,
)

bl_file_extensions_image_and_movie = ";".join((
    *bpy.path.extensions_image,
    *bpy.path.extensions_movie,
))


class VIEW3D_OT_edit_mesh_extrude_individual_move(Operator):
    """Extrude each individual face separately along local normals"""
    bl_label = "Extrude Individual and Move"
    bl_idname = "view3d.edit_mesh_extrude_individual_move"

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def execute(self, context):
        from bpy_extras.object_utils import object_report_if_active_shape_key_is_locked

        ob = context.object
        if object_report_if_active_shape_key_is_locked(ob, self):
            return {'CANCELLED'}

        mesh = ob.data
        select_mode = context.tool_settings.mesh_select_mode

        totface = mesh.total_face_sel
        totedge = mesh.total_edge_sel
        # totvert = mesh.total_vert_sel

        if select_mode[2] and totface == 1:
            bpy.ops.mesh.extrude_region_move(
                'INVOKE_REGION_WIN',
                TRANSFORM_OT_translate={
                    "orient_type": 'NORMAL',
                    "constraint_axis": (False, False, True),
                    "release_confirm": False,
                },
            )
        elif select_mode[2] and totface > 1:
            bpy.ops.mesh.extrude_faces_move(
                'INVOKE_REGION_WIN',
                TRANSFORM_OT_shrink_fatten={
                    "release_confirm": False,
                },
            )
        elif select_mode[1] and totedge >= 1:
            bpy.ops.mesh.extrude_edges_move(
                'INVOKE_REGION_WIN',
                TRANSFORM_OT_translate={
                    "release_confirm": False,
                },
            )
        else:
            bpy.ops.mesh.extrude_vertices_move(
                'INVOKE_REGION_WIN',
                TRANSFORM_OT_translate={
                    "release_confirm": False,
                },
            )

        # ignore return from operators above because they are 'RUNNING_MODAL',
        # and cause this one not to be freed. #24671.
        return {'FINISHED'}

    def invoke(self, context, _event):
        return self.execute(context)


class VIEW3D_OT_edit_mesh_extrude_move(Operator):
    """Extrude region together along the average normal"""
    bl_label = "Extrude and Move on Normals"
    bl_idname = "view3d.edit_mesh_extrude_move_normal"

    dissolve_and_intersect: BoolProperty(
        name="Dissolve and Intersect",
        default=False,
        description="Dissolves adjacent faces and intersects new geometry",
    )

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    @staticmethod
    def extrude_region(operator, context, use_vert_normals, dissolve_and_intersect):
        from bpy_extras.object_utils import object_report_if_active_shape_key_is_locked

        ob = context.object
        if object_report_if_active_shape_key_is_locked(ob, operator):
            return {'CANCELLED'}

        mesh = ob.data

        totface = mesh.total_face_sel
        totedge = mesh.total_edge_sel
        # totvert = mesh.total_vert_sel

        if totface >= 1:
            if use_vert_normals:
                bpy.ops.mesh.extrude_region_shrink_fatten(
                    'INVOKE_REGION_WIN',
                    TRANSFORM_OT_shrink_fatten={
                        "release_confirm": False,
                    },
                )
            elif dissolve_and_intersect:
                bpy.ops.mesh.extrude_manifold(
                    'INVOKE_REGION_WIN',
                    MESH_OT_extrude_region={
                        "use_dissolve_ortho_edges": True,
                    },
                    TRANSFORM_OT_translate={
                        "orient_type": 'NORMAL',
                        "constraint_axis": (False, False, True),
                        "release_confirm": False,
                    },
                )
            else:
                bpy.ops.mesh.extrude_region_move(
                    'INVOKE_REGION_WIN',
                    TRANSFORM_OT_translate={
                        "orient_type": 'NORMAL',
                        "constraint_axis": (False, False, True),
                        "release_confirm": False,
                    },
                )

        elif totedge == 1:
            bpy.ops.mesh.extrude_region_move(
                'INVOKE_REGION_WIN',
                TRANSFORM_OT_translate={
                    # Don't set the constraint axis since users will expect MMB
                    # to use the user setting, see: #61637
                    # "orient_type": 'NORMAL',
                    # Not a popular choice, too restrictive for retopology.
                    # "constraint_axis": (True, True, False),
                    "constraint_axis": (False, False, False),
                    "release_confirm": False,
                })
        else:
            bpy.ops.mesh.extrude_region_move(
                'INVOKE_REGION_WIN',
                TRANSFORM_OT_translate={
                    "release_confirm": False,
                },
            )

        # ignore return from operators above because they are 'RUNNING_MODAL',
        # and cause this one not to be freed. #24671.
        return {'FINISHED'}

    def execute(self, context):
        return VIEW3D_OT_edit_mesh_extrude_move.extrude_region(self, context, False, self.dissolve_and_intersect)

    def invoke(self, context, _event):
        return self.execute(context)


class VIEW3D_OT_edit_mesh_extrude_shrink_fatten(Operator):
    """Extrude region together along local normals"""
    bl_label = "Extrude and Move on Individual Normals"
    bl_idname = "view3d.edit_mesh_extrude_move_shrink_fatten"

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def execute(self, context):
        return VIEW3D_OT_edit_mesh_extrude_move.extrude_region(self, context, True, False)

    def invoke(self, context, _event):
        return self.execute(context)


class VIEW3D_OT_edit_mesh_extrude_manifold_normal(Operator):
    """Extrude manifold region along normals"""
    bl_label = "Extrude Manifold Along Normals"
    bl_idname = "view3d.edit_mesh_extrude_manifold_normal"

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def execute(self, context):
        from bpy_extras.object_utils import object_report_if_active_shape_key_is_locked

        if object_report_if_active_shape_key_is_locked(context.object, self):
            return {'CANCELLED'}
        bpy.ops.mesh.extrude_manifold(
            'INVOKE_REGION_WIN',
            MESH_OT_extrude_region={
                "use_dissolve_ortho_edges": True,
            },
            TRANSFORM_OT_translate={
                "orient_type": 'NORMAL',
                "constraint_axis": (False, False, True),
                "release_confirm": False,
            },
        )
        return {'FINISHED'}

    def invoke(self, context, _event):
        return self.execute(context)


class VIEW3D_OT_transform_gizmo_set(Operator):
    """Set the current transform gizmo"""
    bl_label = "Transform Gizmo Set"
    bl_options = {'REGISTER', 'UNDO'}
    bl_idname = "view3d.transform_gizmo_set"

    extend: BoolProperty(
        name="Extend",
        default=False,
    )
    type: EnumProperty(
        name="Type",
        items=(
            ('TRANSLATE', "Move", ""),
            ('ROTATE', "Rotate", ""),
            ('SCALE', "Scale", ""),
        ),
        options={'ENUM_FLAG'},
    )

    @classmethod
    def poll(cls, context):
        area = context.area
        return area and (area.type == 'VIEW_3D')

    def execute(self, context):
        space_data = context.space_data
        space_data.show_gizmo = True
        attrs = ("show_gizmo_object_translate", "show_gizmo_object_rotate", "show_gizmo_object_scale")
        attr_active = tuple(
            attrs[('TRANSLATE', 'ROTATE', 'SCALE').index(t)]
            for t in self.type
        )
        if self.extend:
            for attr in attrs:
                if attr in attr_active:
                    setattr(space_data, attr, True)
        else:
            for attr in attrs:
                setattr(space_data, attr, attr in attr_active)
        return {'FINISHED'}

    def invoke(self, context, event):
        if not self.properties.is_property_set("extend"):
            self.extend = event.shift
        return self.execute(context)


class VIEW3D_OT_maya_object_xray(Operator):
    """Toggle transparent X-Ray drawing for selected objects"""
    bl_label = "Object X-Ray"
    bl_idname = "view3d.maya_object_xray"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(context.area and context.area.type == 'VIEW_3D' and context.active_object)

    def execute(self, context):
        active_object = context.active_object
        enable = not active_object.show_transparent
        objects = context.selected_objects or (active_object,)
        for obj in objects:
            obj.show_transparent = enable
        return {'FINISHED'}


class VIEW3D_OT_maya_bridge_or_fill(Operator):
    """Bridge two selected edge loops, or fill a single selected boundary"""
    bl_label = "Bridge or Fill"
    bl_idname = "view3d.maya_bridge_or_fill"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def execute(self, context):
        import bmesh

        bm = bmesh.from_edit_mesh(context.edit_object.data)
        selected_edges = {edge for edge in bm.edges if edge.select and not edge.hide}
        if not selected_edges:
            self.report({'WARNING'}, "Select an edge boundary")
            return {'CANCELLED'}

        component_count = 0
        remaining_edges = set(selected_edges)
        while remaining_edges:
            component_count += 1
            pending = [remaining_edges.pop()]
            while pending:
                edge = pending.pop()
                for vert in edge.verts:
                    for connected_edge in vert.link_edges:
                        if connected_edge in remaining_edges:
                            remaining_edges.remove(connected_edge)
                            pending.append(connected_edge)

        if component_count == 2:
            return bpy.ops.mesh.bridge_edge_loops()

        boundary_edges = {
            edge for edge in bm.edges if not edge.hide and len(edge.link_faces) == 1
        }
        boundary_seeds = selected_edges & boundary_edges
        if boundary_seeds:
            selected_edges = set(boundary_seeds)
            pending = list(boundary_seeds)
            while pending:
                edge = pending.pop()
                for vert in edge.verts:
                    for connected_edge in vert.link_edges:
                        if connected_edge in boundary_edges and connected_edge not in selected_edges:
                            selected_edges.add(connected_edge)
                            pending.append(connected_edge)

            for edge in bm.edges:
                edge.select = edge in selected_edges
            for edge in selected_edges:
                for vert in edge.verts:
                    vert.select = True

        return bpy.ops.mesh.edge_face_add()


class VIEW3D_OT_maya_connect(Operator):
    """Interactively insert and slide an edge loop"""
    bl_label = "Loop Cut and Slide"
    bl_idname = "view3d.maya_connect"

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def execute(self, context):
        return bpy.ops.mesh.loopcut_slide('INVOKE_REGION_WIN')

    def invoke(self, context, _event):
        return self.execute(context)


def _maya_subdivision_preview_set(context, mode):
    objects = [obj for obj in context.selected_objects if obj.type == 'MESH']
    active_object = context.active_object
    if active_object and active_object.type == 'MESH' and active_object not in objects:
        objects.append(active_object)
    if not objects:
        return {'CANCELLED'}

    enabled = mode != 0
    for obj in objects:
        modifiers = [modifier for modifier in obj.modifiers if modifier.type == 'SUBSURF']
        if enabled and not modifiers:
            modifier = obj.modifiers.new(name="Maya Smooth Preview", type='SUBSURF')
            modifier.levels = 2
            modifier.render_levels = 2
            modifiers.append(modifier)
        for modifier in modifiers:
            modifier.show_viewport = enabled
            if enabled:
                modifier.show_in_editmode = True
                modifier.show_on_cage = mode == 2
                modifier.show_only_control_edges = True
        obj.show_wire = mode == 1
    return {'FINISHED'}


class VIEW3D_OT_maya_subdivision_preview_off(Operator):
    """Show the original control mesh without subdivision preview"""
    bl_label = "Subdivision Preview Off"
    bl_idname = "view3d.maya_subdivision_preview_off"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        return _maya_subdivision_preview_set(context, 0)


class VIEW3D_OT_maya_subdivision_preview_on(Operator):
    """Show subdivision preview together with the original control cage"""
    bl_label = "Subdivision Preview with Cage"
    bl_idname = "view3d.maya_subdivision_preview_on"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        return _maya_subdivision_preview_set(context, 1)


class VIEW3D_OT_maya_subdivision_preview_surface(Operator):
    """Show subdivision preview with the cage fitted to the smooth surface"""
    bl_label = "Subdivision Preview Surface"
    bl_idname = "view3d.maya_subdivision_preview_surface"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        return _maya_subdivision_preview_set(context, 2)


class VIEW3D_FH_empty_image(FileHandler):
    bl_idname = "VIEW3D_FH_empty_image"
    bl_label = "Add empty image"
    bl_import_operator = "OBJECT_OT_empty_image_add"
    bl_file_extensions = bl_file_extensions_image_and_movie

    @classmethod
    def poll_drop(cls, context):
        if not context.space_data or context.space_data.type != 'VIEW_3D':
            return False
        rv3d = context.space_data.region_3d
        return rv3d.view_perspective == 'PERSP' or rv3d.view_perspective == 'ORTHO'


class VIEW3D_FH_camera_background_image(FileHandler):
    bl_idname = "VIEW3D_FH_camera_background_image"
    bl_label = "Add camera background image"
    bl_import_operator = "VIEW3D_OT_camera_background_image_add"
    bl_file_extensions = bl_file_extensions_image_and_movie

    @classmethod
    def poll_drop(cls, context):
        if not context.space_data or context.space_data.type != 'VIEW_3D':
            return False
        rv3d = context.space_data.region_3d
        return rv3d.view_perspective == 'CAMERA'


class VIEW3D_FH_vdb_volume(FileHandler):
    bl_idname = "VIEW3D_FH_vdb_volume"
    bl_label = "OpenVDB volume"
    bl_import_operator = "OBJECT_OT_volume_import"
    bl_file_extensions = ".vdb"

    @classmethod
    def poll_drop(cls, context):
        return context.space_data and context.space_data.type == 'VIEW_3D'


classes = (
    VIEW3D_OT_edit_mesh_extrude_individual_move,
    VIEW3D_OT_edit_mesh_extrude_move,
    VIEW3D_OT_edit_mesh_extrude_shrink_fatten,
    VIEW3D_OT_edit_mesh_extrude_manifold_normal,
    VIEW3D_OT_transform_gizmo_set,
    VIEW3D_OT_maya_object_xray,
    VIEW3D_OT_maya_bridge_or_fill,
    VIEW3D_OT_maya_connect,
    VIEW3D_OT_maya_subdivision_preview_off,
    VIEW3D_OT_maya_subdivision_preview_on,
    VIEW3D_OT_maya_subdivision_preview_surface,
    VIEW3D_FH_camera_background_image,
    VIEW3D_FH_empty_image,
    VIEW3D_FH_vdb_volume,
)
