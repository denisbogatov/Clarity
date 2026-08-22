/* SPDX-FileCopyrightText: 2023 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup spscripttool
 */

#pragma once

namespace blender {

struct SpaceScriptTool;
struct ScrArea;
struct wmWindow;

/** Registered from the space type; see `script_tool_ops.cc`. */
void script_tool_operatortypes();

/**
 * The `SpaceScriptTool` of a window opened by #ED_script_tool_window_open, or null
 * for any other window. A Script Tool window owns exactly one area, so this both
 * identifies such a window and reaches its space in one step.
 */
SpaceScriptTool *script_tool_window_space_get(const wmWindow *win);

}  // namespace blender
