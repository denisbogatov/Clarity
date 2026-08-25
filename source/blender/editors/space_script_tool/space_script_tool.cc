/* SPDX-FileCopyrightText: 2023 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup spscripttool
 *
 * Host space for script-defined Blender-native utility windows.
 *
 * The space itself is deliberately empty of behaviour: it owns a single
 * #RGN_TYPE_WINDOW region that draws whatever panels a script registered for
 * this space, filtered down to the panels whose `bl_context` matches the
 * space's own #SpaceScriptTool::tool_id. Everything else - what those panels
 * contain, which operators they call, what the tool actually does - belongs to
 * the script, not here.
 *
 * Windows are opened through #ED_script_tool_window_open (see
 * `script_tool_ops.cc`), which is what gives a space its `tool_id` and
 * `instance_id`.
 */

#include "DNA_space_types.h"
#include "MEM_guardedalloc.h"

#include "BLI_listbase.h"
#include "BLI_string_utf8.h"

#include "BKE_context.hh"
#include "BKE_screen.hh"

#include "ED_screen.hh"
#include "ED_space_api.hh"

#include "UI_interface.hh"

#include "BLO_read_write.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "script_tool_intern.hh"

namespace blender {

/* -------------------------------------------------------------------- */
/** \name Space Callbacks
 * \{ */

static SpaceLink *script_tool_create(const ScrArea * /*area*/, const Scene * /*scene*/)
{
  SpaceScriptTool *sscript_tool = MEM_new<SpaceScriptTool>("init script tool space");
  sscript_tool->spacetype = SPACE_SCRIPT_TOOL;

  /* Main region. This space has no header: a utility window is all content. */
  ARegion *region = BKE_area_region_new();
  BLI_addtail(&sscript_tool->regionbase, region);
  region->regiontype = RGN_TYPE_WINDOW;

  return reinterpret_cast<SpaceLink *>(sscript_tool);
}

/* Doesn't free the space-link itself. */
static void script_tool_free(SpaceLink * /*sl*/) {}

static void script_tool_init(wmWindowManager * /*wm*/, ScrArea * /*area*/) {}

static SpaceLink *script_tool_duplicate(SpaceLink *sl)
{
  /* Identity and title are copied with the struct on purpose: a duplicated area keeps
   * showing the same tool. Window identity is derived from `tool_id` and `instance_id`
   * by #ED_script_tool_window_find, so a duplicate that ends up in a second window is
   * found by it just like the original. */
  return reinterpret_cast<SpaceLink *>(MEM_dupalloc(reinterpret_cast<SpaceScriptTool *>(sl)));
}

static void script_tool_keymap(wmKeyConfig * /*keyconf*/) {}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Main Region
 * \{ */

static void script_tool_main_region_init(wmWindowManager *wm, ARegion *region)
{
  ED_region_panels_init(wm, region);

  /* Utility windows are resized by the user to whatever fits; when it does not,
   * the region has to say so rather than silently clip its panels. */
  region->flag |= RGN_FLAG_INDICATE_OVERFLOW;
}

static void script_tool_main_region_layout(const bContext *C, ARegion *region)
{
  const ScrArea *area = CTX_wm_area(C);
  const SpaceScriptTool *sscript_tool = area ? static_cast<const SpaceScriptTool *>(
                                                   area->spacedata.first) :
                                               nullptr;

  /* The whole filtering rule of this space: a panel is drawn when its `bl_context`
   * equals this space's `tool_id`. Two windows hosting different tools therefore
   * never draw each other's panels, even though both are `SPACE_SCRIPT_TOOL` and
   * share one panel-type list.
   *
   * Note #panel_add_check skips the context test entirely for a panel that declares
   * no `bl_context`, so such a panel appears in every Script Tool window. That is
   * why `ScriptToolWindow.panel()` always stamps `bl_context` with the tool's id -
   * registering a panel for this space by hand, without one, is what it looks like
   * when a tool shows up in someone else's window. */
  const char *contexts[] = {sscript_tool ? sscript_tool->tool_id : "", nullptr};
  ED_region_panels_layout_ex(C,
                             region,
                             &region->runtime->type->paneltypes,
                             wm::OpCallContext::InvokeRegionWin,
                             contexts,
                             nullptr);
}

static void script_tool_main_region_draw(const bContext *C, ARegion *region)
{
  ED_region_panels_draw(C, region);
}

static void script_tool_main_region_listener(const wmRegionListenerParams *params)
{
  ARegion *region = params->region;
  const wmNotifier *wmn = params->notifier;

  /* Deliberately narrow, matching the Properties editor - the other panel host that
   * shows scene state. Redrawing this region means re-running every panel's Python
   * `draw()`, which for a real tool is a large UI. Subscribing to whole categories
   * would pay that on every `NC_OBJECT` of a transform and every `NC_SCENE` of a
   * frame step, so simply dragging an object in the viewport would drag the tool's
   * entire layout along with it.
   *
   * What a tool actually needs is already covered without this: editing a button in
   * the window redraws it as any button does, and a tool that changes state behind
   * Blender's back redraws itself with `area.tag_redraw()` from Python - which is
   * what TreeVDB does to drive its bake progress. `ND_JOB` is kept because job
   * progress has no other path into this window and is infrequent. */
  switch (wmn->category) {
    case NC_SCREEN:
      if (wmn->data == ND_LAYER) {
        ED_region_tag_redraw(region);
      }
      break;
    case NC_WM:
      if (wmn->data == ND_JOB) {
        ED_region_tag_redraw(region);
      }
      break;
  }
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Blend File I/O
 * \{ */

static void script_tool_space_blend_write(BlendWriter *writer, SpaceLink *sl)
{
  writer->write_struct_cast<SpaceScriptTool>(sl);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Registration
 * \{ */

void ED_spacetype_script_tool()
{
  std::unique_ptr<SpaceType> st = std::make_unique<SpaceType>();

  st->spaceid = SPACE_SCRIPT_TOOL;
  STRNCPY_UTF8(st->name, "Script Tool");

  st->create = script_tool_create;
  st->free = script_tool_free;
  st->init = script_tool_init;
  st->duplicate = script_tool_duplicate;
  st->operatortypes = script_tool_operatortypes;
  st->keymap = script_tool_keymap;
  st->blend_write = script_tool_space_blend_write;

  ARegionType *art = MEM_new_zeroed<ARegionType>("spacetype script tool main region");
  art->regionid = RGN_TYPE_WINDOW;
  art->keymapflag = ED_KEYMAP_UI;
  art->init = script_tool_main_region_init;
  art->layout = script_tool_main_region_layout;
  art->draw = script_tool_main_region_draw;
  art->listener = script_tool_main_region_listener;
  BLI_addhead(&st->regiontypes, art);

  BKE_spacetype_register(std::move(st));
}

/** \} */

}  // namespace blender
