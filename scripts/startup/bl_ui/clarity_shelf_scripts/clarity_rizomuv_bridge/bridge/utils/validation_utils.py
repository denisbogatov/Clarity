"""Utility functions for validating blender objects against custom rules."""

import re
from typing import cast
from uuid import uuid4

from bpy.types import Mesh, Object

from ..addon_constants import (
    BANNED_FBX_SUBSTRINGS,
    BANNED_OBJ_SUBSTRINGS,
    BANNED_UVMAP_SUBSTRINGS,
)
from ..classes.data.validation_results import (
    ObjectNameValidationResult,
    UVValidationResult,
)
from ..classes.exceptions.blender_exceptions import UnexpectedObjectTypeError
from ..classes.exceptions.validation_exceptions import (
    InvalidObjectNamesError,
    InvalidUVSetNamesError,
    InvalidUVSetsError,
    NonMatchingTopologyError,
)
from ..types import ExportTypes
from ..utils import uv_utils
from . import log_utils

uvmap_banned_substring_regex = re.compile("|".join(re.escape(s) for s in BANNED_UVMAP_SUBSTRINGS))
obj_banned_substring_regex = re.compile("|".join(re.escape(s) for s in BANNED_OBJ_SUBSTRINGS))
fbx_banned_substring_regex = re.compile("|".join(re.escape(s) for s in BANNED_FBX_SUBSTRINGS))
usd_alphanumeric_regex = re.compile(r"[^a-zA-Z0-9]")


def assert_has_equal_polycount(a: Object, b: Object):
    """Check if two objects have the same number of polygons.

    Args:
        a: The first mesh object.
        b: The second mesh object.

    Raises:
        NonMatchingTopologyError: If the objects do not have the same number of polygons.

    """
    if not len(cast(Mesh, a.data).polygons) == len(cast(Mesh, b.data).polygons):
        raise NonMatchingTopologyError(a, b)


def fix_invalid_uvmap_names(mesh_data: Mesh, invalid_names: dict[str, list[str]]):
    """Fix invalid uv map names from assert_valid_uvmap_names.

    Args:
        mesh_data: The mesh data of the object to containing the uvmaps.
        invalid_names: The invalid uvmaps from validate_uvmap_names.

    """
    # TODO: Handle collisions with existing uvmap names.
    for uvmap_name, invalid_substrings in invalid_names.items():
        object_uvmap = mesh_data.uv_layers[uvmap_name]
        for sub_string in invalid_substrings:
            object_uvmap.name = object_uvmap.name.replace(sub_string, "_")


def assert_valid_uvmap_names(mesh_data: Mesh):
    """Assert that uv map names are valid.

    Compares the uv map names to a list of banned substrings.

    Args:
        mesh_data: The mesh data of the object to containing the uvmaps.

    Raises:
        InvalidUVSetNamesError: If the uv map names are invalid.

    """
    invalid_names: dict[str, list[str]] = {}

    for uvmap in mesh_data.uv_layers:
        if match := uvmap_banned_substring_regex.findall(uvmap.name):
            invalid_names[uvmap.name] = match

    if invalid_names:
        raise InvalidUVSetNamesError(invalid_names)


def fix_nonmatching_uvmap_sets(base_uvmaps: list[str], object: Object, remove_extra_uvmaps: bool):
    """Fix invalid uv map names from assert_matching_uvmap_sets.

    Args:
        base_uvmaps: The uv map names of the base object.
        object: The object to fix the uv map names of.
        remove_extra_uvmaps: Whether to remove extra uvmaps.

    Raises:
        UnexpectedObjectTypeError: If the object is not a mesh.

    """
    data = object.data
    if not isinstance(data, Mesh):
        raise UnexpectedObjectTypeError(object, Mesh)

    # If the object doesn't have enough uvmaps, add them.
    if len(data.uv_layers) < len(base_uvmaps):
        uv_utils.add_uvmaps(object, len(base_uvmaps) - len(data.uv_layers))

    # Make sure the uvmaps names match and are in the correct order.
    for i, expected_name in enumerate(base_uvmaps):
        object_uvmap = data.uv_layers[i]
        if expected_name != object_uvmap.name:
            if conflicting_uvmap := data.uv_layers.get(expected_name):
                conflicting_uvmap.name = str(uuid4())
            object_uvmap.name = expected_name

    # Remove any extra uvmaps.
    if len(data.uv_layers) > len(base_uvmaps) and remove_extra_uvmaps:
        uv_utils.pop_uvmaps(object, len(data.uv_layers) - len(base_uvmaps))


def assert_matching_uvmap_sets(base_uvmaps: set[str], objects: list[Object]):
    """Assert that a list of objects have the same uv map names as a base object."""
    results: list[UVValidationResult] = []

    for obj in objects:
        if obj.type != "MESH":
            raise UnexpectedObjectTypeError(obj, Mesh)

        obj_uvmaps = {uvmap.name for uvmap in cast(Mesh, obj.data).uv_layers}
        extra_uvmaps = list(obj_uvmaps - base_uvmaps)
        missing_uvmaps = list(base_uvmaps - obj_uvmaps)

        if extra_uvmaps or missing_uvmaps:
            result = UVValidationResult(obj, extra_uvmaps, missing_uvmaps)
            results.append(result)

    if results:
        raise InvalidUVSetsError(results)


def assert_matching_uvmap_sets_single(base_uvmaps: set[str], obj: Object):
    """Assert that an object has the same uv map names as a base object.

    Wrapper around assert_matching_uvmap_sets that only checks a single object.

    Args:
        base_uvmaps: The uv map names of the base object.
        obj: The object to check the uv map names of.

    Raises:
        InvalidUVSetsError: If the object does not have the same UV map names.
        UnexpectedObjectTypeError: If the object is not a mesh.

    """
    assert_matching_uvmap_sets(base_uvmaps, [obj])


def assert_valid_object_names(objects: list[Object], export_format: ExportTypes):
    """Assert that a list of objects have valid names for export to Rizom.

    Args:
        objects: The objects to check the names of.
        export_format: The format to export to.

    Raises:
        InvalidObjectNamesError: If the objects do not have valid names.

    """
    format_regex_map = {
        "OBJ": obj_banned_substring_regex,
        "FBX": fbx_banned_substring_regex,
        "USD": usd_alphanumeric_regex,
    }

    regex = format_regex_map[export_format]

    results: list[ObjectNameValidationResult] = []
    for obj in objects:
        if match := regex.findall(obj.name):
            result = ObjectNameValidationResult(obj, match)
            results.append(result)

    if results:
        raise InvalidObjectNamesError(results)


def assert_valid_for_export(
    active_object: Object,
    objects: list[Object],
    export_format: ExportTypes,
    all_objects: list[Object] | None = None,
):
    """Run all validation checks needed to ensure a mesh is suitable for export.

    Args:
        active_object: The active mesh object.
        objects: The mesh objects to validate.
        export_format: The format to export to.
        all_objects: All objects being exported (meshes + empties) for name validation.
            If None, defaults to objects.

    Raises:
        InvalidUVSetNamesError: If the active object has invalid UV map names.
        InvalidUVSetsError: If the objects do not have the same UV map names.
        InvalidObjectNamesError: If the objects do not have valid names.

    """
    active_data = active_object.data
    if not isinstance(active_data, Mesh):
        raise UnexpectedObjectTypeError(active_object, Mesh)

    assert_valid_uvmap_names(active_data)

    base_uvs = {uvmap.name for uvmap in active_data.uv_layers}
    assert_matching_uvmap_sets(base_uvs, objects)
    assert_valid_object_names(all_objects if all_objects is not None else objects, export_format)


def log_invalid_uvmap_names(invalid_uvmap_names: dict[str, list[str]]):
    """Print invalid uvmap names to the console.

    Args:
        invalid_uvmap_names: The invalid uvmaps from validate_uvmap_names.

    """
    table_rows = []
    for uvmap, substrings in invalid_uvmap_names.items():
        table_rows.append([uvmap, substrings])

    table = log_utils.Table("RizomUV Bridge - Invalid UV Map Names", ["UV Map", "Invalid Substrings"])
    table.add_rows(table_rows)
    table.print()


def log_non_matching_uvmaps(uvmap_results: list[UVValidationResult]):
    """Print non-matching uvmaps to the console.

    Args:
        uvmap_results: The uvmap results from validate_uvmap_sets.

    """
    table_rows = [[result.target_object.name, result.extra_uvmaps, result.missing_uvmaps] for result in uvmap_results]
    table = log_utils.Table(
        "RizomUV Bridge - Non-Matching UV Maps", ["Target Object", "Extra UV Maps", "Missing UV Maps"]
    )
    table.add_rows(table_rows)
    table.print()


def log_invalid_object_names(object_results: list[ObjectNameValidationResult]):
    """Print invalid object names to the console.

    Args:
        object_results: The object results from validate_object_names.

    """
    table_rows = [[result.target_object.name, ", ".join(result.invalid_name_substrings)] for result in object_results]
    table = log_utils.Table("RizomUV Bridge - Invalid Object Names", ["Target Object", "Invalid Substrings"])
    table.add_rows(table_rows)
    table.print()
