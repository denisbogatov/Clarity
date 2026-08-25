"""Helper functions for working with USD files."""

import json

from bpy.types import Object

from .hooks.usd_hook import UsdHookRizom


def get_name_from_prim(prim: str):
    """Get the name of the object from the prim path.

    Args:
        prim: The prim path.

    Returns:
        tuple: The name of the object and the data name.

    """
    split = prim.split("/")
    if len(split) > 1:
        return split[-2], split[-1]
    return split[-1], split[-1]


def name_to_xform(name: str):
    """Convert the name of the object to a valid USD transform name.

    Args:
       name: The name of the object.

    Returns:
       The name for the xform.

    """
    if not name[0].isalpha():
        new_name = "_"
        return new_name.join("_" if not c.isalnum() else c for c in name[1:])

    return "".join("_" if not c.isalnum() else c for c in name)


def import_usd_props(objects: list[Object]):
    """Import USD properties from the USD hook and store them on Blender objects.

    Args:
        objects: The objects to import properties for.

    """
    props = UsdHookRizom.properties
    for obj in objects:
        if obj.name in props:
            obj["rizomuv_attributes"] = json.dumps(props[obj.name])


def export_usd_props(objects: list[Object]):
    """Export USD properties from Blender objects to the USD hook.

    Args:
        objects: The objects to export properties for.

    """
    for obj in objects:
        props = obj.get("rizomuv_attributes")
        if props:
            UsdHookRizom.properties[obj.name] = json.loads(props)
