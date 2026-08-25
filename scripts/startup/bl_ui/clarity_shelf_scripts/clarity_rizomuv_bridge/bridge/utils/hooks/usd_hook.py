"""Custom USD hook which runs during USD import and exports."""

import logging
from contextlib import contextmanager
from typing import Any, Literal, cast

from bpy.types import USDHook
from pxr import Sdf, Usd  # type: ignore

from ...utils import usd_utils

logger = logging.getLogger(__name__)

UsdTypes = Literal["float[]", "int[]", "string[]", "bool[]", "double[]", "float", "int", "string", "bool", "double"]

USD_TYPE_MAP = {
    "float[]": Sdf.ValueTypeNames.FloatArray,
    "int[]": Sdf.ValueTypeNames.IntArray,
    "string[]": Sdf.ValueTypeNames.StringArray,
    "bool[]": Sdf.ValueTypeNames.BoolArray,
    "double[]": Sdf.ValueTypeNames.DoubleArray,
    "float": Sdf.ValueTypeNames.Float,
    "int": Sdf.ValueTypeNames.Int,
    "string": Sdf.ValueTypeNames.String,
    "bool": Sdf.ValueTypeNames.Bool,
    "double": Sdf.ValueTypeNames.Double,
}


class UsdHookRizom(USDHook):
    bl_idname = "rizom.usd_hook"
    bl_label = "RizomUV USD Hook"

    properties: dict[str, list[dict]] = {}
    is_enabled: bool = False

    @classmethod
    def enable(cls):
        """Enable the hook."""
        cls.is_enabled = True

    @classmethod
    def disable(cls):
        """Disable the hook."""
        cls.is_enabled = False

    @classmethod
    @contextmanager
    def enabled(cls):
        """Context manager to temporarily enable the hook."""
        cls.enable()
        try:
            yield
        finally:
            cls.disable()

    @staticmethod
    def build_editor(stage: Usd.Stage) -> Sdf.BatchNamespaceEdit:
        """Build the usd namespace.

        Args:
            stage: The USD stage.

        Returns:
            The namespace editor.

        """
        editor = Sdf.BatchNamespaceEdit()
        for prim in stage.TraverseAll():
            if prim.IsA("Xform"):
                xform_name = prim.GetName()
                xform_path = prim.GetPath()
                for child in prim.GetChildren():
                    if child.IsA("Mesh"):
                        editor.Add(cast(Usd.Prim, child).GetPath(), f"{xform_path}/{xform_name}")
        return editor

    @staticmethod
    def extract_attributes(prim: Usd.Prim):
        """Extract all RizomUV attributes from the given prim.

        Args:
            prim: The USD prim to extract attributes from.

        """
        prim_path = prim.GetPath().pathString
        for prop in prim.GetPropertyNames():
            if prop.startswith("RizomUV:"):
                attribute = prim.GetAttribute(prop)
                prop_type = str(attribute.GetTypeName())
                if attribute:
                    value = attribute.Get()
                    name, _ = usd_utils.get_name_from_prim(prim_path)
                    if prop_type.endswith("[]"):
                        value = list(value)

                    rizom_prop = {
                        "prop": prop,
                        "type": prop_type,
                        "value": value,
                    }

                    UsdHookRizom.properties.setdefault(name, []).append(rizom_prop)

        for child in prim.GetChildren():
            UsdHookRizom.extract_attributes(child)

    @staticmethod
    def on_export(export_context: Any):
        """Automatically called right before the USD file exports.

        Converts properties saved in the static properties field to USD attributes,
        all properties should be saved to this field before exporting.

        Args:
            export_context (USDSceneExportContext): Internally defined class, undocumented.

        """
        if not UsdHookRizom.is_enabled:
            return False

        stage: Usd.Stage = export_context.get_stage()
        layer = stage.GetRootLayer()

        layer.Apply(UsdHookRizom.build_editor(stage))

        if not UsdHookRizom.properties:
            return True

        for obj_name, prop_array in UsdHookRizom.properties.items():
            prim_path = f"/root/{obj_name}/{obj_name}"
            if not (prim := stage.GetPrimAtPath(prim_path)):
                logger.warning(f"RizomUV Bridge (USD Hook): No prim found for {obj_name}")
                continue

            for prop_dict in prop_array:
                prop_name = prop_dict.get("prop")
                prop_type = prop_dict.get("type")
                value = prop_dict.get("value")

                if not prop_name or not prop_type or not value:
                    logger.warning(f"Skipping processing for {prop_name}, property not found.")
                    continue

                prop_dict = dict(prop_dict)
                if not (usd_type := USD_TYPE_MAP.get(prop_type)):
                    logger.warning(f"Skipping processing for {prop_name}, usd type not found.")
                    continue

                if attr := prim.CreateAttribute(prop_name, usd_type):
                    attr.Set(value)

        return True

    @staticmethod
    def on_import(import_context: Any):
        """Automatically called after the USD file imports.

        Converts Rizom USD attributes into Python properties then stores them using the object name
        as a dictionary key. Can be accessed from the static properties field and stored in the Blender
        scene.

        property = {
            "prop": <property name>,
            "type": <property identifier>,
            "value": <property value>,
        }

        Args:
            import_context (USDSceneImportContext): Internally defined class, undocumented.

        """
        if not UsdHookRizom.is_enabled:
            return False

        stage: Usd.Stage = import_context.get_stage()
        root_prim = stage.GetPseudoRoot()
        UsdHookRizom.extract_attributes(root_prim)

        return True
