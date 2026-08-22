/* SPDX-License-Identifier: GPL-2.0-or-later */
#pragma once
namespace blender {
struct bContext;
struct wmWindow;
struct wmWindowManager;

struct ScriptToolWindowParams {
  const char *tool_id = nullptr;
  const char *instance_id = "main";
  const char *title = "Script Tool";
  int width = 460;
  int height = 640;
  bool reuse = true;
};

bool ED_script_tool_window_is(const wmWindow *win);
wmWindow *ED_script_tool_window_find(wmWindowManager *wm,
                                     const char *tool_id,
                                     const char *instance_id);
wmWindow *ED_script_tool_window_open(bContext *C,
                                     const ScriptToolWindowParams &params);
bool ED_script_tool_window_focus(wmWindowManager *wm,
                                 const char *tool_id,
                                 const char *instance_id);
bool ED_script_tool_window_close(bContext *C,
                                 wmWindowManager *wm,
                                 const char *tool_id,
                                 const char *instance_id);
int ED_script_tool_window_close_all(bContext *C,
                                    wmWindowManager *wm,
                                    const char *tool_id);
}  // namespace blender
