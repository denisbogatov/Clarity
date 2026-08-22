# SPDX-License-Identifier: GPL-2.0-or-later
"""High-level Python API for Blender-native Script Tool windows."""
from __future__ import annotations
import bpy

class ScriptToolWindow:
    tool_id = ""
    title = "Script Tool"
    default_width = 460
    default_height = 640
    default_instance_id = "main"

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        cls._panels = []

    @classmethod
    def _ensure_core(cls):
        if not hasattr(bpy.types, "SpaceScriptTool"):
            raise RuntimeError("This Blender build has no SpaceScriptTool core API")
        if not hasattr(bpy.ops.wm, "script_tool_window_open"):
            raise RuntimeError("This Blender build has no wm.script_tool_window_open")

    @classmethod
    def _validate(cls):
        cls._ensure_core()
        if not isinstance(cls.tool_id, str) or not cls.tool_id.strip():
            raise ValueError(f"{cls.__name__}.tool_id must be a non-empty string")
        if len(cls.tool_id.encode("utf-8")) >= 64:
            raise ValueError("tool_id must fit in 63 UTF-8 bytes")
        if cls.default_width < 240 or cls.default_height < 160:
            raise ValueError("default window size is below the core minimum")

    @classmethod
    def panel(cls, panel_cls):
        if not issubclass(panel_cls, bpy.types.Panel):
            raise TypeError("@Tool.panel expects bpy.types.Panel")
        panel_cls.bl_space_type = "SCRIPT_TOOL"
        panel_cls.bl_region_type = "WINDOW"
        panel_cls.bl_context = cls.tool_id
        cls._panels.append(panel_cls)
        return panel_cls

    @classmethod
    def register(cls, *, hot_reload=False):
        cls._validate()
        for panel_cls in cls._panels:
            if hot_reload:
                old = getattr(bpy.types, panel_cls.__name__, None)
                if old is not None and old is not panel_cls:
                    try:
                        bpy.utils.unregister_class(old)
                    except Exception:
                        pass
            if not getattr(panel_cls, "is_registered", False):
                bpy.utils.register_class(panel_cls)

    @classmethod
    def unregister(cls, *, close_windows=True):
        if close_windows:
            cls.close_all()
        for panel_cls in reversed(cls._panels):
            if getattr(panel_cls, "is_registered", False):
                try:
                    bpy.utils.unregister_class(panel_cls)
                except RuntimeError:
                    pass

    @classmethod
    def _iter_spaces(cls):
        for window in bpy.context.window_manager.windows:
            if window.screen is None:
                continue
            for area in window.screen.areas:
                if area.type != "SCRIPT_TOOL":
                    continue
                space = area.spaces.active
                if getattr(space, "tool_id", "") == cls.tool_id:
                    yield window, area, space

    @classmethod
    def instances(cls):
        return tuple(getattr(space, "instance_id", "main") for _, _, space in cls._iter_spaces())

    @classmethod
    def find_window(cls, instance_id=None):
        instance = instance_id or cls.default_instance_id
        for window, _, space in cls._iter_spaces():
            if getattr(space, "instance_id", "main") == instance:
                return window
        return None

    @classmethod
    def find_area(cls, instance_id=None):
        instance = instance_id or cls.default_instance_id
        for _, area, space in cls._iter_spaces():
            if getattr(space, "instance_id", "main") == instance:
                return area
        return None

    @classmethod
    def find_space(cls, instance_id=None):
        instance = instance_id or cls.default_instance_id
        for _, _, space in cls._iter_spaces():
            if getattr(space, "instance_id", "main") == instance:
                return space
        return None

    @classmethod
    def is_open(cls, instance_id=None):
        return cls.find_window(instance_id) is not None

    @classmethod
    def open(cls, *, instance_id=None, title=None, width=None, height=None, reuse=True):
        cls._validate()
        instance = instance_id or cls.default_instance_id
        result = bpy.ops.wm.script_tool_window_open(
            tool_id=cls.tool_id,
            instance_id=instance,
            title=cls.title if title is None else title,
            width=cls.default_width if width is None else width,
            height=cls.default_height if height is None else height,
            reuse=reuse,
        )
        if "FINISHED" not in result:
            raise RuntimeError(f"Could not open Script Tool {cls.tool_id!r}")
        return cls.find_window(instance)

    @classmethod
    def close(cls, instance_id=None):
        cls._ensure_core()
        instance = instance_id or cls.default_instance_id
        result = bpy.ops.wm.script_tool_window_close(tool_id=cls.tool_id, instance_id=instance)
        return "FINISHED" in result

    @classmethod
    def close_all(cls):
        count = 0
        for instance in list(cls.instances()):
            if cls.close(instance):
                count += 1
        return count

    @classmethod
    def focus(cls, instance_id=None):
        cls._ensure_core()
        instance = instance_id or cls.default_instance_id
        result = bpy.ops.wm.script_tool_window_focus(tool_id=cls.tool_id, instance_id=instance)
        return "FINISHED" in result

    @classmethod
    def show(cls, instance_id=None):
        instance = instance_id or cls.default_instance_id
        if cls.is_open(instance):
            cls.focus(instance)
            return cls.find_window(instance)
        return cls.open(instance_id=instance)

    @classmethod
    def toggle(cls, instance_id=None):
        instance = instance_id or cls.default_instance_id
        if cls.is_open(instance):
            cls.close(instance)
            return None
        return cls.open(instance_id=instance)
