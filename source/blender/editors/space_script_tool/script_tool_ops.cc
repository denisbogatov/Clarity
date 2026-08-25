/* SPDX-FileCopyrightText: 2023 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup spscripttool
 *
 * Window lifetime for Script Tool utility windows.
 *
 * A concrete window is identified by the pair `(tool_id, instance_id)` carried on
 * its #SpaceScriptTool, never by a stored pointer. Nothing here knows about any
 * particular tool: scripts pass those two strings in, and get the same window
 * back for as long as it is open.
 */

#include <algorithm>
#include <climits>
#include <cstring>

#include "DNA_screen_types.h"
#include "DNA_space_types.h"
#include "DNA_windowmanager_types.h"

#include "BLI_listbase.h"
#include "BLI_string_utf8.h"
#include "BLI_utildefines.h"

#include "BKE_context.hh"
#include "BKE_report.hh"
#include "BKE_screen.hh"

#include "ED_screen.hh"
#include "ED_script_tool.hh"

#include "UI_interface_types.hh"

#include "RNA_access.hh"
#include "RNA_define.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "wm_window.hh"

#include "script_tool_intern.hh"

namespace blender {

/* -------------------------------------------------------------------- */
/** \name Identity
 * \{ */

/** Size of #SpaceScriptTool::tool_id and #SpaceScriptTool::instance_id. */
#define SCRIPT_TOOL_ID_MAXNAME 64

/** Smallest window a tool may ask for; below this the panels cannot lay out. */
#define SCRIPT_TOOL_WIN_MINX 240
#define SCRIPT_TOOL_WIN_MINY 160

SpaceScriptTool *script_tool_window_space_get(const wmWindow *win)
{
  if (win == nullptr) {
    return nullptr;
  }
  const bScreen *screen = WM_window_get_active_screen(win);
  if (screen == nullptr) {
    return nullptr;
  }
  /* A Script Tool window is created with exactly one area. Anything else - a window
   * the user split, or an ordinary window that merely contains such an area - is
   * deliberately not treated as one of ours, so closing it is never our business. */
  if (!screen->areabase.is_single()) {
    return nullptr;
  }
  ScrArea *area = static_cast<ScrArea *>(screen->areabase.first);
  if (area == nullptr || area->spacetype != SPACE_SCRIPT_TOOL) {
    return nullptr;
  }
  return static_cast<SpaceScriptTool *>(area->spacedata.first);
}

bool ED_script_tool_window_is(const wmWindow *win)
{
  return script_tool_window_space_get(win) != nullptr;
}

const char *ED_script_tool_window_title_get(const wmWindow *win)
{
  const SpaceScriptTool *sscript_tool = script_tool_window_space_get(win);
  return (sscript_tool && sscript_tool->title[0]) ? sscript_tool->title : nullptr;
}

static bool script_tool_space_matches(const SpaceScriptTool *sscript_tool,
                                      const char *tool_id,
                                      const char *instance_id)
{
  if (sscript_tool == nullptr || tool_id == nullptr) {
    return false;
  }
  if (!STREQ(sscript_tool->tool_id, tool_id)) {
    return false;
  }
  /* A null instance matches any: used by #ED_script_tool_window_close_all. */
  return instance_id == nullptr || STREQ(sscript_tool->instance_id, instance_id);
}

wmWindow *ED_script_tool_window_find(wmWindowManager *wm,
                                     const char *tool_id,
                                     const char *instance_id)
{
  if (wm == nullptr) {
    return nullptr;
  }
  for (wmWindow &win : wm->windows) {
    if (script_tool_space_matches(script_tool_window_space_get(&win), tool_id, instance_id)) {
      return &win;
    }
  }
  return nullptr;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Open / Focus / Close
 * \{ */

wmWindow *ED_script_tool_window_open(bContext *C, const ScriptToolWindowParams &params)
{
  if (params.tool_id == nullptr || params.tool_id[0] == '\0') {
    return nullptr;
  }
  const char *instance_id = (params.instance_id && params.instance_id[0]) ? params.instance_id :
                                                                           "main";

  wmWindowManager *wm = CTX_wm_manager(C);
  if (wm == nullptr) {
    return nullptr;
  }
  if (params.reuse) {
    if (wmWindow *win = ED_script_tool_window_find(wm, params.tool_id, instance_id)) {
      wm_window_raise(win);
      return win;
    }
  }

  wmWindow *win_parent = CTX_wm_window(C);
  if (win_parent == nullptr) {
    win_parent = static_cast<wmWindow *>(wm->windows.first);
    if (win_parent == nullptr) {
      return nullptr;
    }
    /* Script entry points can run immediately after a file/window transition, when the
     * global context has already lost its previous window. WM_window_open requires a
     * live parent and changes the context to the newly opened window itself. */
    CTX_wm_window_set(C, win_parent);
  }
  const int size_x = std::max(params.width, SCRIPT_TOOL_WIN_MINX);
  const int size_y = std::max(params.height, SCRIPT_TOOL_WIN_MINY);
  const rcti window_rect = {
      /*xmin*/ win_parent ? win_parent->posx : 0,
      /*xmax*/ (win_parent ? win_parent->posx : 0) + size_x,
      /*ymin*/ win_parent ? win_parent->posy : 0,
      /*ymax*/ (win_parent ? win_parent->posy : 0) + size_y,
  };

  /* `temp` marks the screen temporary, which is what keeps these windows session
   * UI: they are not saved into the workspace and do not come back as editors on
   * the next file read. Note this changes the context. */
  wmWindow *win = WM_window_open(C,
                                 params.title ? params.title : "Script Tool",
                                 &window_rect,
                                 SPACE_SCRIPT_TOOL,
                                 false,
                                 false,
                                 true,
                                 WIN_ALIGN_PARENT_CENTER,
                                 nullptr,
                                 nullptr);
  if (win == nullptr) {
    return nullptr;
  }

  /* The window exists before it has an identity; give it one now, so that the very
   * first layout pass already filters panels by this tool. */
  SpaceScriptTool *sscript_tool = script_tool_window_space_get(win);
  if (sscript_tool == nullptr) {
    /* Should not happen: the window was just opened as `SPACE_SCRIPT_TOOL`. An
     * identity-less window is not findable and so could never be closed through this
     * API again, so do not leave one behind. */
    wm_window_close_request(C, CTX_wm_manager(C), win);
    return nullptr;
  }
  STRNCPY_UTF8(sscript_tool->tool_id, params.tool_id);
  STRNCPY_UTF8(sscript_tool->instance_id, instance_id);
  STRNCPY_UTF8(sscript_tool->title, params.title ? params.title : "Script Tool");

  /* The OS title bar is coloured from the header theme of the space a single-area
   * window holds, but the decoration style applied while the window was being created
   * ran with no screen to look at and settled for the generic fallback colour. Ask for
   * it again now that the window has its area - `NC_WINDOW` is the documented way in,
   * and reaches #WM_window_decoration_style_apply with the screen it needs. */
  WM_event_add_notifier_ex(CTX_wm_manager(C), win, NC_WINDOW, nullptr);

  if (ScrArea *area = static_cast<ScrArea *>(WM_window_get_active_screen(win)->areabase.first)) {
    ED_area_tag_redraw(area);
  }
  return win;
}

bool ED_script_tool_window_focus(wmWindowManager *wm, const char *tool_id, const char *instance_id)
{
  wmWindow *win = ED_script_tool_window_find(wm, tool_id, instance_id);
  if (win == nullptr) {
    return false;
  }
  wm_window_raise(win);
  return true;
}

bool ED_script_tool_window_close(bContext *C,
                                 wmWindowManager *wm,
                                 const char *tool_id,
                                 const char *instance_id)
{
  wmWindow *win = ED_script_tool_window_find(wm, tool_id, instance_id);
  if (win == nullptr) {
    return false;
  }
  /* Request rather than close outright: the window manager owns the teardown order
   * and the context that has to survive it. */
  wm_window_close_request(C, wm, win);
  return true;
}

int ED_script_tool_window_close_all(bContext *C, wmWindowManager *wm, const char *tool_id)
{
  int closed = 0;
  /* Each close mutates the window list, so re-scan from the start every time
   * instead of holding an iterator across the request. */
  while (wmWindow *win = ED_script_tool_window_find(wm, tool_id, nullptr)) {
    wm_window_close_request(C, wm, win);
    closed++;
    if (ED_script_tool_window_find(wm, tool_id, nullptr) == win) {
      /* The request was refused; stop rather than spin. */
      break;
    }
  }
  return closed;
}

int ED_script_tool_windows_close_all(bContext *C, wmWindowManager *wm)
{
  if (wm == nullptr) {
    return 0;
  }

  int closed = 0;
  while (true) {
    wmWindow *script_tool_win = nullptr;
    for (wmWindow &win : wm->windows) {
      if (ED_script_tool_window_is(&win)) {
        script_tool_win = &win;
        break;
      }
    }
    if (script_tool_win == nullptr) {
      break;
    }

    CTX_wm_window_set(C, script_tool_win);
    wm_window_close_request(C, wm, script_tool_win);
    closed++;

    bool close_was_refused = false;
    for (wmWindow &win : wm->windows) {
      if (&win == script_tool_win) {
        close_was_refused = true;
        break;
      }
    }
    if (close_was_refused) {
      break;
    }
  }

  CTX_wm_window_set(C, static_cast<wmWindow *>(wm->windows.first));
  return closed;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Operators
 * \{ */

static wmOperatorStatus script_tool_window_open_exec(bContext *C, wmOperator *op)
{
  char tool_id[SCRIPT_TOOL_ID_MAXNAME];
  char instance_id[SCRIPT_TOOL_ID_MAXNAME];
  char title[UI_MAX_NAME_STR];

  RNA_string_get(op->ptr, "tool_id", tool_id);
  RNA_string_get(op->ptr, "instance_id", instance_id);
  RNA_string_get(op->ptr, "title", title);

  if (tool_id[0] == '\0') {
    BKE_report(op->reports, RPT_ERROR, "Script Tool requires a non-empty tool_id");
    return OPERATOR_CANCELLED;
  }

  ScriptToolWindowParams params;
  params.tool_id = tool_id;
  params.instance_id = instance_id[0] ? instance_id : "main";
  params.title = title[0] ? title : "Script Tool";
  params.width = RNA_int_get(op->ptr, "width");
  params.height = RNA_int_get(op->ptr, "height");
  params.reuse = RNA_boolean_get(op->ptr, "reuse");

  if (ED_script_tool_window_open(C, params) == nullptr) {
    BKE_report(op->reports, RPT_ERROR, "Could not open the Script Tool window");
    return OPERATOR_CANCELLED;
  }
  return OPERATOR_FINISHED;
}

static void WM_OT_script_tool_window_open(wmOperatorType *ot)
{
  ot->name = "Open Script Tool Window";
  ot->description = "Open a Blender-native utility window hosting a script's panels";
  ot->idname = "WM_OT_script_tool_window_open";

  ot->exec = script_tool_window_open_exec;

  RNA_def_string(ot->srna,
                 "tool_id",
                 nullptr,
                 SCRIPT_TOOL_ID_MAXNAME,
                 "Tool ID",
                 "Identifier the window's panels are matched against");
  RNA_def_string(ot->srna,
                 "instance_id",
                 "main",
                 SCRIPT_TOOL_ID_MAXNAME,
                 "Instance ID",
                 "Distinguishes several windows of the same tool");
  RNA_def_string(ot->srna, "title", "Script Tool", UI_MAX_NAME_STR, "Title", "Window title");
  RNA_def_int(ot->srna,
              "width",
              460,
              SCRIPT_TOOL_WIN_MINX,
              SHRT_MAX,
              "Width",
              "Window width in pixels",
              SCRIPT_TOOL_WIN_MINX,
              SHRT_MAX);
  RNA_def_int(ot->srna,
              "height",
              640,
              SCRIPT_TOOL_WIN_MINY,
              SHRT_MAX,
              "Height",
              "Window height in pixels",
              SCRIPT_TOOL_WIN_MINY,
              SHRT_MAX);
  RNA_def_boolean(
      ot->srna, "reuse", true, "Reuse", "Focus an already open window instead of opening a second");
}

static wmOperatorStatus script_tool_window_close_exec(bContext *C, wmOperator *op)
{
  char tool_id[SCRIPT_TOOL_ID_MAXNAME];
  char instance_id[SCRIPT_TOOL_ID_MAXNAME];

  RNA_string_get(op->ptr, "tool_id", tool_id);
  RNA_string_get(op->ptr, "instance_id", instance_id);

  if (tool_id[0] == '\0') {
    BKE_report(op->reports, RPT_ERROR, "Script Tool requires a non-empty tool_id");
    return OPERATOR_CANCELLED;
  }

  wmWindowManager *wm = CTX_wm_manager(C);
  const bool closed = RNA_boolean_get(op->ptr, "all") ?
                          ED_script_tool_window_close_all(C, wm, tool_id) > 0 :
                          ED_script_tool_window_close(
                              C, wm, tool_id, instance_id[0] ? instance_id : "main");
  /* Closing what is already closed is the requested end state, not a failure. */
  UNUSED_VARS(closed);
  return OPERATOR_FINISHED;
}

static void WM_OT_script_tool_window_close(wmOperatorType *ot)
{
  ot->name = "Close Script Tool Window";
  ot->description = "Close a Script Tool utility window";
  ot->idname = "WM_OT_script_tool_window_close";

  ot->exec = script_tool_window_close_exec;

  RNA_def_string(
      ot->srna, "tool_id", nullptr, SCRIPT_TOOL_ID_MAXNAME, "Tool ID", "Tool whose window to close");
  RNA_def_string(ot->srna,
                 "instance_id",
                 "main",
                 SCRIPT_TOOL_ID_MAXNAME,
                 "Instance ID",
                 "Which window of that tool to close");
  RNA_def_boolean(
      ot->srna, "all", false, "All", "Close every open window of this tool, ignoring instance_id");
}

static wmOperatorStatus script_tool_window_focus_exec(bContext *C, wmOperator *op)
{
  char tool_id[SCRIPT_TOOL_ID_MAXNAME];
  char instance_id[SCRIPT_TOOL_ID_MAXNAME];

  RNA_string_get(op->ptr, "tool_id", tool_id);
  RNA_string_get(op->ptr, "instance_id", instance_id);

  if (tool_id[0] == '\0') {
    BKE_report(op->reports, RPT_ERROR, "Script Tool requires a non-empty tool_id");
    return OPERATOR_CANCELLED;
  }

  wmWindowManager *wm = CTX_wm_manager(C);
  if (!ED_script_tool_window_focus(wm, tool_id, instance_id[0] ? instance_id : "main")) {
    return OPERATOR_CANCELLED;
  }
  return OPERATOR_FINISHED;
}

static void WM_OT_script_tool_window_focus(wmOperatorType *ot)
{
  ot->name = "Focus Script Tool Window";
  ot->description = "Raise an open Script Tool utility window";
  ot->idname = "WM_OT_script_tool_window_focus";

  ot->exec = script_tool_window_focus_exec;

  RNA_def_string(
      ot->srna, "tool_id", nullptr, SCRIPT_TOOL_ID_MAXNAME, "Tool ID", "Tool whose window to raise");
  RNA_def_string(ot->srna,
                 "instance_id",
                 "main",
                 SCRIPT_TOOL_ID_MAXNAME,
                 "Instance ID",
                 "Which window of that tool to raise");
}

void script_tool_operatortypes()
{
  WM_operatortype_append(WM_OT_script_tool_window_open);
  WM_operatortype_append(WM_OT_script_tool_window_close);
  WM_operatortype_append(WM_OT_script_tool_window_focus);
}

/** \} */

}  // namespace blender
