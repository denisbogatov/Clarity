"""Operator for batch renaming UV maps.

Main use is quickly fixing UV map names that are invalid in RizomUV.

"""

from typing import cast

from bpy.props import BoolProperty, CollectionProperty
from bpy.types import Context, Event, Mesh, Operator, PropertyGroup

from ..classes.exceptions.validation_exceptions import InvalidUVSetNamesError, InvalidUVSetsError
from ..utils import addon_utils, selection_utils, validation_utils
from ..utils.exceptions_utils import cancel_with_logged_exception


class RenameUVMaps(Operator):
    """Utility opeartor for btach renaming/creating UV maps."""

    bl_description = "Batch edit UV map names"
    bl_idname = "object.rename_uvmaps"
    bl_label = "Rename UV Maps"
    bl_options = {"REGISTER", "INTERNAL", "UNDO"}

    uvmap_names: CollectionProperty(name="UV Maps", type=PropertyGroup)
    fix_names: BoolProperty(
        name="Fix Names",
        default=True,
        description="Automatically fix UV map names containing substrings that would be invalid in RizomUV",
    )
    remove_extra_uvmaps: BoolProperty(
        name="Remove Extra UV Maps",
        default=True,
        description="Automatically remove UV maps from objects if they have more UV maps than the active object",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.prefs = addon_utils.get_prefs()

    @classmethod
    def poll(cls, context: Context) -> bool:
        """Check if there is an active object and that it is a mesh."""
        return context.active_object is not None and context.active_object.type == "MESH"

    def _set_uvmaps_prop(self, uvmaps: list[str]):
        """Set the uvmaps prop to the given list of uvmap names."""
        self.uvmap_names.clear()
        for uvmap in uvmaps:
            item = self.uvmap_names.add()
            item.name = uvmap

    def invoke(self, context: Context, event: Event) -> set:
        """Run before the operator is executed."""
        active_data = cast(Mesh, context.active_object.data)
        self._set_uvmaps_prop(active_data.uv_layers.keys())
        return self.execute(context)

    def execute(self, context: Context) -> set:
        """Operator call method."""
        selected_objects = selection_utils.get_selected_meshes()
        active_object = context.active_object
        active_data = cast(Mesh, active_object.data)

        for item, uvmap in zip(self.uvmap_names, active_data.uv_layers):
            uvmap.name = item.name

        try:
            validation_utils.assert_valid_uvmap_names(active_data)
        except InvalidUVSetNamesError as e:
            if self.fix_names:
                validation_utils.fix_invalid_uvmap_names(active_data, e.invalid_uvmaps)
            else:
                validation_utils.log_invalid_uvmap_names(e.invalid_uvmaps)
                return cancel_with_logged_exception(self, e)

        self._set_uvmaps_prop(active_data.uv_layers.keys())

        base_uvs = {uvmap.name for uvmap in active_data.uv_layers}

        for obj in selected_objects:
            if obj == active_object:
                continue

            try:
                validation_utils.assert_matching_uvmap_sets_single(base_uvs, obj)
            except InvalidUVSetsError:
                validation_utils.fix_nonmatching_uvmap_sets(active_data.uv_layers.keys(), obj, self.remove_extra_uvmaps)

        return {"FINISHED"}

    def draw(self, context: Context):
        """Render properties panel for the operator."""
        box = self.layout.box()

        col = box.column(align=True)
        col.scale_y = 1.5
        col.prop(self, "fix_names")
        col.prop(self, "remove_extra_uvmaps")

        box = self.layout.box()
        col = box.column(align=True)
        col.scale_y = 1.5
        for i, uvmap in enumerate(self.uvmap_names, 1):
            col.prop(uvmap, "name", text=f"UV Map {i}")
