# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Contract of the Script Tool window API.

Runs under `--background`, so it deliberately does not open windows: GHOST has
no display there and `wm.script_tool_window_open` cannot produce one. What is
pinned here is everything that holds without a window - the registration the
Python API depends on, and the panel-binding rule that keeps two tools out of
each other's windows.
"""

import bpy
from bpy_extras.script_tool import ScriptToolWindow


def space_type_is_registered():
    # `ScriptToolWindow._ensure_core` tests exactly these two; a rename on either
    # side turns every tool into a RuntimeError at `register()` time.
    assert hasattr(bpy.types, "SpaceScriptTool")
    assert hasattr(bpy.ops.wm, "script_tool_window_open")
    assert hasattr(bpy.ops.wm, "script_tool_window_close")
    assert hasattr(bpy.ops.wm, "script_tool_window_focus")

    # The space has to be selectable as a `bl_space_type`, or panels cannot be
    # registered against it at all.
    space_type_items = bpy.types.Panel.bl_rna.properties["bl_space_type"].enum_items
    assert "SCRIPT_TOOL" in space_type_items


def space_identity_is_read_only():
    properties = bpy.types.SpaceScriptTool.bl_rna.properties
    for name in ("tool_id", "instance_id"):
        assert name in properties, name
        # Identity is handed out by the open operator. A panel that could rewrite it
        # would change which panels the window draws while it is drawing them.
        assert properties[name].is_readonly, name


def open_operator_properties():
    properties = bpy.types.WM_OT_script_tool_window_open.bl_rna.properties
    for name in ("tool_id", "instance_id", "title", "width", "height", "reuse"):
        assert name in properties, name

    # The Python API passes every one of these by keyword, so the defaults are part
    # of the contract rather than an implementation detail.
    assert properties["instance_id"].default == "main"
    assert properties["reuse"].default is True


def panel_binding_stamps_the_tool_id():
    """The rule the whole design rests on.

    Panels of every Script Tool share one panel-type list, and the region draws
    the ones whose `bl_context` matches its own `tool_id`. Core skips the context
    test entirely for a panel that declares no `bl_context`, so a panel that was
    not stamped would appear in *every* tool's window. `@Tool.panel` is what makes
    that impossible.
    """
    class ToolUnderTest(ScriptToolWindow):
        tool_id = "clarity_test_tool"
        title = "Clarity Test Tool"

    @ToolUnderTest.panel
    class CLARITY_PT_script_tool_under_test(bpy.types.Panel):
        bl_label = "Clarity Test Tool"

        def draw(self, context):
            pass

    assert CLARITY_PT_script_tool_under_test.bl_space_type == 'SCRIPT_TOOL'
    assert CLARITY_PT_script_tool_under_test.bl_region_type == 'WINDOW'
    assert CLARITY_PT_script_tool_under_test.bl_context == "clarity_test_tool"

    # Registration has to survive a real round trip, since that is what a tool does
    # on every shelf click.
    ToolUnderTest.register(hot_reload=True)
    try:
        assert CLARITY_PT_script_tool_under_test.is_registered
        # Nothing is open in background, and asking must not raise.
        assert ToolUnderTest.instances() == ()
        assert ToolUnderTest.is_open() is False
        assert ToolUnderTest.find_window() is None
    finally:
        ToolUnderTest.unregister()
    assert not CLARITY_PT_script_tool_under_test.is_registered


def invalid_tools_are_rejected():
    class NamelessTool(ScriptToolWindow):
        tool_id = "   "

    try:
        NamelessTool.register()
    except ValueError:
        pass
    else:
        raise AssertionError("a blank tool_id must not register")

    class OversizedTool(ScriptToolWindow):
        # `SpaceScriptTool.tool_id` is 64 bytes including the terminator; a longer id
        # would be silently truncated and then never match its own panels.
        tool_id = "t" * 64

    try:
        OversizedTool.register()
    except ValueError:
        pass
    else:
        raise AssertionError("an oversized tool_id must not register")

    class TinyTool(ScriptToolWindow):
        tool_id = "clarity_tiny_tool"
        default_width = 100
        default_height = 100

    try:
        TinyTool.register()
    except ValueError:
        pass
    else:
        raise AssertionError("a window below the core minimum must not register")


def main():
    space_type_is_registered()
    space_identity_is_read_only()
    open_operator_properties()
    panel_binding_stamps_the_tool_id()
    invalid_tools_are_rejected()


if __name__ == "__main__":
    main()
