"""Functions for exporting meshes out of Blender."""

import time

import bpy
from bpy.types import Context, Object

from ..classes.exceptions.io_exceptions import FileImportError
from ..file_access import DataDirectory
from ..types import Axis, ExportTypes
from .hooks.usd_hook import UsdHookRizom

# The OBJ and USD API use different axis conventions
AXIS_CONVERSION: dict = {
    "X": "X",
    "Y": "Y",
    "Z": "Z",
    "NEGATIVE_X": "-X",
    "NEGATIVE_Y": "-Y",
    "NEGATIVE_Z": "-Z",
}


def export_obj(path: str, forward_axis: Axis, up_axis: Axis):
    """Export meshes to OBJ.

    Args:
        path: The path to export to.
        forward_axis: The forward axis to use.
        up_axis: The up axis to use.

    """
    bpy.ops.wm.obj_export(
        filepath=path,
        export_selected_objects=True,
        export_materials=False,
        export_smooth_groups=True,
        apply_modifiers=False,
        forward_axis=forward_axis,
        up_axis=up_axis,
    )


def export_fbx(path: str, forward_axis: Axis, up_axis: Axis):
    """Export meshes to FBX.

    Args:
        path: The path to export to.
        forward_axis: The forward axis to use.
        up_axis: The up axis to use.

    """
    bpy.ops.export_scene.fbx(
        filepath=path,
        use_selection=True,
        use_visible=False,
        object_types={"MESH", "EMPTY"},
        use_mesh_edges=False,
        use_custom_props=False,
        apply_scale_options="FBX_SCALE_NONE",
        use_space_transform=True,
        bake_space_transform=False,
        use_mesh_modifiers=False,
        apply_unit_scale=True,
        axis_up=AXIS_CONVERSION[up_axis],
        axis_forward=AXIS_CONVERSION[forward_axis],
        bake_anim=False,
    )


def export_usd(path: str, forward_axis: Axis, up_axis: Axis):
    """Export the selected objects to a USD file."""
    bpy.ops.wm.usd_export(
        filepath=path,
        check_existing=False,
        selected_objects_only=True,
        export_uvmaps=True,
        export_mesh_colors=False,
        export_normals=True,
        export_materials=False,
        rename_uvmaps=False,
        export_custom_properties=True,
        root_prim_path="/root",
        convert_orientation=True,
        export_global_forward_selection=forward_axis,
        export_global_up_selection=up_axis,
        evaluation_mode="VIEWPORT",
    )


def import_file(context: Context, format: ExportTypes, data_dir: DataDirectory) -> list[Object]:
    """Import a file into Blender.

    Args:
        context: The current Blender context.
        format: The format of the file to import.
        data_dir: The data directory model.

    Returns:
        A list of imported objects.

    Raises:
        FileImportError: If the file import fails.

    """
    scene = context.scene
    mesh_dir = data_dir.mesh_files
    pre_import_objects = set(scene.objects)

    def attempt_import():
        match format:
            case "OBJ":
                bpy.ops.wm.obj_import(filepath=str(mesh_dir.obj))
            case "FBX":
                if bpy.app.version >= (4, 5, 0):
                    bpy.ops.wm.fbx_import(filepath=str(mesh_dir.fbx))
                else:
                    bpy.ops.import_scene.fbx(filepath=str(mesh_dir.fbx))
            case "USD":
                with UsdHookRizom.enabled():
                    bpy.ops.wm.usd_import(filepath=str(mesh_dir.usd), import_materials=False)

    max_attempts = 5
    time_between_attempts = 2.5

    # Importing large files can result in a RuntimeError, i don't know why, retrying fixes it.
    for attempt in range(max_attempts):
        try:
            attempt_import()
            break
        except RuntimeError as e:
            time.sleep(time_between_attempts)
            if attempt == max_attempts:
                raise FileImportError() from e

    post_import_objects = set(scene.objects)
    new_objects = post_import_objects - pre_import_objects

    if not context.active_object:
        context.view_layer.objects.active = context.scene.objects[0]

    return list(new_objects)
