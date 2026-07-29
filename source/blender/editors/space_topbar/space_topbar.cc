/* SPDX-FileCopyrightText: 2017 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup sptopbar
 */

#include <algorithm>
#include <cstdio>
#include <cstring>
#include <optional>
#include <string>

#include "MEM_guardedalloc.h"

#include "BLI_listbase.h"
#include "BLI_math_color.h"
#include "BLI_rect.h"
#include "BLI_string_utf8.h"
#include "BLI_uuid.h"
#include "BLI_utildefines.h"

#include "BLT_translation.hh"

#include "BKE_context.hh"
#include "BKE_screen.hh"
#include "BKE_undo_system.hh"
#include "BKE_wm_runtime.hh"

#include "DNA_windowmanager_types.h"

#include "ED_screen.hh"
#include "ED_space_api.hh"

#include "GPU_state.hh"

#include "UI_interface.hh"
#include "UI_interface_layout.hh"
#include "UI_resources.hh"
#include "UI_view2d.hh"

#include "BLO_read_write.hh"

#include "RNA_access.hh"

#include "WM_api.hh"
#include "WM_message.hh"
#include "WM_types.hh"

namespace blender {

/* ******************** default callbacks for topbar space ***************** */

static SpaceLink *topbar_create(const ScrArea * /*area*/, const Scene * /*scene*/)
{
  ARegion *region;
  SpaceTopBar *stopbar;

  stopbar = MEM_new<SpaceTopBar>("init topbar");
  stopbar->spacetype = SPACE_TOPBAR;

  /* header */
  region = BKE_area_region_new();
  BLI_addtail(&stopbar->regionbase, region);
  region->regiontype = RGN_TYPE_HEADER;
  region->alignment = RGN_ALIGN_TOP;
  region = BKE_area_region_new();
  BLI_addtail(&stopbar->regionbase, region);
  region->regiontype = RGN_TYPE_HEADER;
  region->alignment = RGN_ALIGN_RIGHT | RGN_SPLIT_PREV;

  /* Upper shelf row. */
  region = BKE_area_region_new();
  BLI_addtail(&stopbar->regionbase, region);
  region->regiontype = RGN_TYPE_FOOTER;
  region->alignment = RGN_ALIGN_TOP;
  region->flag |= RGN_FLAG_NO_USER_RESIZE;

  /* main regions */
  region = BKE_area_region_new();
  BLI_addtail(&stopbar->regionbase, region);
  region->regiontype = RGN_TYPE_WINDOW;

  return reinterpret_cast<SpaceLink *>(stopbar);
}

static SpaceLink *shelf_create(const ScrArea * /*area*/, const Scene * /*scene*/)
{
  SpaceTopBar *shelf = MEM_new<SpaceTopBar>("init shelf");
  shelf->spacetype = SPACE_SHELF;
  BLI_uuid_format(shelf->shelf_id, BLI_uuid_generate_random());

  ARegion *region = BKE_area_region_new();
  BLI_addtail(&shelf->regionbase, region);
  region->regiontype = RGN_TYPE_HEADER;
  region->alignment = RGN_ALIGN_TOP;

  region = BKE_area_region_new();
  BLI_addtail(&shelf->regionbase, region);
  region->regiontype = RGN_TYPE_WINDOW;

  return reinterpret_cast<SpaceLink *>(shelf);
}

/* Doesn't free the space-link itself. */
static void topbar_free(SpaceLink * /*sl*/) {}

/* spacetype; init callback */
static void topbar_init(wmWindowManager * /*wm*/, ScrArea *area)
{
  if (area->spacetype != SPACE_SHELF) {
    return;
  }
  SpaceTopBar *shelf = static_cast<SpaceTopBar *>(area->spacedata.first);
  if (shelf != nullptr && shelf->shelf_id[0] == '\0') {
    BLI_uuid_format(shelf->shelf_id, BLI_uuid_generate_random());
  }
}

static SpaceLink *topbar_duplicate(SpaceLink *sl)
{
  SpaceTopBar *stopbarn = MEM_dupalloc(reinterpret_cast<SpaceTopBar *>(sl));

  /* clear or remove stuff from old */

  return reinterpret_cast<SpaceLink *>(stopbarn);
}

/**
 * Live state of a Maya-shelf icon drag, resolved from the buttons that are really laid out so the
 * insertion marker and the drop position always agree with the cursor.
 *
 * `TOPBAR_OT_maya_shelf_drag` drives this by calling `TOPBAR_OT_maya_shelf_drag_probe` from its
 * modal handler. It cannot be driven from the shelf region event handlers instead: a modal
 * operator returning `RUNNING_MODAL | PASS_THROUGH` still yields `WM_HANDLER_BREAK`, and
 * `wm_event_do_handlers` skips every region handler once that flag is set.
 */
struct ShelfDragRuntime {
  bool active = false;
  /** Region the drop would happen in, null while the cursor is over no shelf. */
  const ARegion *target_region = nullptr;
  /** False together with a non-null region means the shelf holds no entry to align to. */
  bool target_valid = false;
  bool target_after = false;
  std::string target_item_id;
  /** Window space bounds of the target entry. */
  rctf target_rect = {0.0f, 0.0f, 0.0f, 0.0f};
};

static ShelfDragRuntime shelf_drag_runtime;

static void shelf_drag_runtime_clear()
{
  shelf_drag_runtime.active = false;
  shelf_drag_runtime.target_region = nullptr;
  shelf_drag_runtime.target_valid = false;
  shelf_drag_runtime.target_after = false;
  shelf_drag_runtime.target_item_id.clear();
  BLI_rctf_init(&shelf_drag_runtime.target_rect, 0.0f, 0.0f, 0.0f, 0.0f);
}

/** Every shelf surface shows the marker, so a drag between them cannot leave a stale one behind. */
static void topbar_shelf_areas_tag_redraw(const bContext *C)
{
  wmWindowManager *wm = CTX_wm_manager(C);
  if (wm == nullptr) {
    return;
  }
  for (wmWindow &window : wm->windows) {
    for (ScrArea &area : window.global_areas.areabase) {
      if (area.spacetype == SPACE_TOPBAR) {
        ED_area_tag_redraw(&area);
      }
    }
    bScreen *screen = WM_window_get_active_screen(&window);
    if (screen == nullptr) {
      continue;
    }
    for (ScrArea &area : screen->areabase) {
      if (area.spacetype == SPACE_SHELF) {
        ED_area_tag_redraw(&area);
      }
    }
  }
}

/**
 * Hand the entry under the cursor to the running drag operator, which owns the reorder.
 * `found` is false while the cursor is over no shelf at all, which cancels the drop.
 */
static void topbar_shelf_drag_hover_notify(bContext *C,
                                           const ui::ShelfDropTarget *target,
                                           const bool found)
{
  wmOperatorType *ot = WM_operatortype_find("TOPBAR_OT_maya_shelf_drag_hover", true);
  if (ot == nullptr) {
    return;
  }
  PointerRNA properties = WM_operator_properties_create_ptr(ot);
  RNA_boolean_set(&properties, "found", found);
  RNA_string_set(&properties, "item_id", target != nullptr ? target->item_id.c_str() : "");
  RNA_boolean_set(&properties, "after", target != nullptr && target->after);
  WM_operator_name_call_ptr(C, ot, wm::OpCallContext::ExecDefault, &properties, nullptr);
  WM_operator_properties_free(&properties);
}

static int topbar_shelf_region_event_handler(bContext *C,
                                             const wmEvent *event,
                                             void * /*user_data*/)
{
  if (!ELEM(event->type, MIDDLEMOUSE, RIGHTMOUSE) || event->val != KM_PRESS) {
    return WM_UI_HANDLER_CONTINUE;
  }

  ARegion *region = CTX_wm_region(C);
  if (region == nullptr) {
    return WM_UI_HANDLER_CONTINUE;
  }

  ui::Button *button = region ? ui::but_find_mouse_over(region, event) : nullptr;
  std::optional<StringRefNull> item_id;
  if (button != nullptr) {
    item_id = ui::button_context_string_get(button, "maya_shelf_item_id");
  }

  if (event->type == RIGHTMOUSE) {
    wmOperatorType *ot = WM_operatortype_find("TOPBAR_OT_maya_shelf_context_menu", false);
    if (ot == nullptr) {
      return WM_UI_HANDLER_CONTINUE;
    }

    PointerRNA properties = WM_operator_properties_create_ptr(ot);
    const ScrArea *area = CTX_wm_area(C);
    RNA_int_set(&properties,
                "row",
                area && area->spacetype == SPACE_SHELF ?
                    0 :
                    (region->regiontype == RGN_TYPE_FOOTER ? 0 : 1));
    if (item_id) {
      RNA_string_set(&properties, "item_id", item_id->c_str());
    }
    const wmOperatorStatus status = WM_operator_name_call_ptr(
        C, ot, wm::OpCallContext::InvokeDefault, &properties, event);
    WM_operator_properties_free(&properties);
    return (status & (OPERATOR_FINISHED | OPERATOR_RUNNING_MODAL | OPERATOR_INTERFACE)) ?
               WM_UI_HANDLER_BREAK :
               WM_UI_HANDLER_CONTINUE;
  }

  if (!item_id) {
    return WM_UI_HANDLER_CONTINUE;
  }

  wmOperatorType *ot = WM_operatortype_find("TOPBAR_OT_maya_shelf_drag", false);
  if (ot == nullptr) {
    return WM_UI_HANDLER_CONTINUE;
  }

  PointerRNA properties = WM_operator_properties_create_ptr(ot);
  RNA_string_set(&properties, "item_id", item_id->c_str());
  const wmOperatorStatus status = WM_operator_name_call_ptr(
      C, ot, wm::OpCallContext::InvokeDefault, &properties, event);
  WM_operator_properties_free(&properties);
  if (status & OPERATOR_RUNNING_MODAL) {
    shelf_drag_runtime_clear();
    shelf_drag_runtime.active = true;
    return WM_UI_HANDLER_BREAK;
  }
  return WM_UI_HANDLER_CONTINUE;
}

/** Shelf region under `xy`, plus the area owning it. */
static ARegion *topbar_shelf_region_find_at(bContext *C, const int xy[2], ScrArea **r_area)
{
  wmWindow *window = CTX_wm_window(C);
  if (window == nullptr) {
    return nullptr;
  }

  auto shelf_region_at = [&](ScrArea *area) -> ARegion * {
    for (ARegion &region : area->regionbase) {
      if (!ELEM(region.regiontype, RGN_TYPE_WINDOW, RGN_TYPE_FOOTER) ||
          (region.flag & RGN_FLAG_HIDDEN) != 0)
      {
        continue;
      }
      if (BLI_rcti_isect_pt_v(&region.winrct, xy)) {
        *r_area = area;
        return &region;
      }
    }
    return nullptr;
  };

  for (ScrArea &area : window->global_areas.areabase) {
    if (area.spacetype != SPACE_TOPBAR) {
      continue;
    }
    if (ARegion *region = shelf_region_at(&area)) {
      return region;
    }
  }
  bScreen *screen = WM_window_get_active_screen(window);
  if (screen != nullptr) {
    for (ScrArea &area : screen->areabase) {
      if (area.spacetype != SPACE_SHELF) {
        continue;
      }
      if (ARegion *region = shelf_region_at(&area)) {
        return region;
      }
    }
  }
  return nullptr;
}

static wmOperatorStatus shelf_drag_probe_exec(bContext *C, wmOperator * /*op*/)
{
  if (!shelf_drag_runtime.active) {
    return OPERATOR_CANCELLED;
  }
  const wmWindow *window = CTX_wm_window(C);
  if (window == nullptr || window->runtime == nullptr ||
      window->runtime->eventstate == nullptr)
  {
    return OPERATOR_CANCELLED;
  }

  const int *xy = window->runtime->eventstate->xy;
  ScrArea *area = nullptr;
  ARegion *region = topbar_shelf_region_find_at(C, xy, &area);
  std::optional<ui::ShelfDropTarget> target;
  if (region != nullptr) {
    target = ui::shelf_drop_target_find(region, xy);
  }

  const bool valid = target.has_value();
  const std::string item_id = valid ? std::string(target->item_id) : std::string();
  const bool after = valid && target->after;
  /* The marker snaps to entry boundaries, so it only needs a redraw once the boundary or the
   * hovered region changes rather than on every pixel of motion. */
  if (region != shelf_drag_runtime.target_region || valid != shelf_drag_runtime.target_valid ||
      item_id != shelf_drag_runtime.target_item_id || after != shelf_drag_runtime.target_after)
  {
    shelf_drag_runtime.target_region = region;
    shelf_drag_runtime.target_valid = valid;
    shelf_drag_runtime.target_item_id = item_id;
    shelf_drag_runtime.target_after = after;
    if (valid) {
      shelf_drag_runtime.target_rect = target->rect;
    }
    topbar_shelf_areas_tag_redraw(C);
  }

  if (region == nullptr) {
    topbar_shelf_drag_hover_notify(C, nullptr, false);
    return OPERATOR_CANCELLED;
  }

  /* The hover operator derives the shelf scope and row from the context, so point it at the
   * hovered shelf rather than at the region the drag started in. */
  ScrArea *area_prev = CTX_wm_area(C);
  ARegion *region_prev = CTX_wm_region(C);
  CTX_wm_area_set(C, area);
  CTX_wm_region_set(C, region);
  topbar_shelf_drag_hover_notify(C, valid ? &*target : nullptr, true);
  CTX_wm_area_set(C, area_prev);
  CTX_wm_region_set(C, region_prev);
  return OPERATOR_FINISHED;
}

static void TOPBAR_OT_maya_shelf_drag_probe(wmOperatorType *ot)
{
  ot->name = "Probe Shelf Drop Target";
  ot->idname = "TOPBAR_OT_maya_shelf_drag_probe";
  ot->description = "Resolve the shelf entry under the cursor for the running drag";
  ot->exec = shelf_drag_probe_exec;
  ot->flag = OPTYPE_INTERNAL;
}

/**
 * Draw the insertion marker of a running shelf drag: a caret at the boundary the entry snaps to
 * once the middle mouse button is released. The target comes from the last probe so the marker
 * cannot disagree with where the drop will actually go.
 */
static void topbar_shelf_drag_marker_draw(const bContext * /*C*/, const ARegion *region)
{
  if (!shelf_drag_runtime.active || shelf_drag_runtime.target_region != region) {
    return;
  }

  const float scale = UI_SCALE_FAC;
  const float half_width = std::max(1.5f * scale, 1.0f);
  rctf marker;
  if (shelf_drag_runtime.target_valid) {
    const rctf &rect = shelf_drag_runtime.target_rect;
    const float boundary = shelf_drag_runtime.target_after ? rect.xmax : rect.xmin;
    marker.xmin = boundary - half_width;
    marker.xmax = boundary + half_width;
    /* Overshoot the entry a little so the caret reads as a gap rather than as an icon border. */
    marker.ymin = rect.ymin - 2.0f * scale;
    marker.ymax = rect.ymax + 2.0f * scale;
  }
  else {
    /* An empty shelf has no entry to align to, mark its first slot instead. */
    marker.xmin = float(region->winrct.xmin) + 3.0f * scale;
    marker.xmax = marker.xmin + 2.0f * half_width;
    marker.ymin = float(region->winrct.ymin) + 3.0f * scale;
    marker.ymax = float(region->winrct.ymax) - 3.0f * scale;
  }
  BLI_rctf_translate(&marker, -region->winrct.xmin, -region->winrct.ymin);
  /* Keep the caret inside the region when the target sits against one of its edges. */
  const float overflow_left = -marker.xmin;
  const float overflow_right = marker.xmax - float(BLI_rcti_size_x(&region->winrct));
  if (overflow_left > 0.0f) {
    BLI_rctf_translate(&marker, overflow_left, 0.0f);
  }
  else if (overflow_right > 0.0f) {
    BLI_rctf_translate(&marker, -overflow_right, 0.0f);
  }
  marker.ymin = std::max(marker.ymin, 0.0f);
  marker.ymax = std::min(marker.ymax, float(BLI_rcti_size_y(&region->winrct)));

  /* An I-beam rather than a plain bar: the serifs read as "the icon goes between these two"
   * even when the caret lands right against an icon edge. */
  const float serif_half_width = std::max(4.5f * scale, 3.0f);
  const float serif_height = std::max(2.0f * scale, 1.0f);
  /* Left at the caret center even next to a region edge: the region clips the overhang, and a
   * serif shifted off the bar would read worse than a clipped one. */
  const float serif_x = BLI_rctf_cent_x(&marker);
  rctf serif_top = {serif_x - serif_half_width,
                    serif_x + serif_half_width,
                    marker.ymax - serif_height,
                    marker.ymax};
  rctf serif_bottom = {serif_x - serif_half_width,
                       serif_x + serif_half_width,
                       marker.ymin,
                       marker.ymin + serif_height};

  const float color[4] = {0.16f, 0.52f, 1.0f, 1.0f};
  GPU_blend(GPU_BLEND_ALPHA);
  ui::draw_roundbox_corner_set(ui::CNR_ALL);
  ui::draw_roundbox_aa(&marker, true, BLI_rctf_size_x(&marker) * 0.5f, color);
  ui::draw_roundbox_aa(&serif_top, true, serif_height * 0.5f, color);
  ui::draw_roundbox_aa(&serif_bottom, true, serif_height * 0.5f, color);
  GPU_blend(GPU_BLEND_NONE);
}

static wmOperatorStatus shelf_drag_end_exec(bContext *C, wmOperator * /*op*/)
{
  shelf_drag_runtime_clear();
  topbar_shelf_areas_tag_redraw(C);
  return OPERATOR_FINISHED;
}

static void TOPBAR_OT_maya_shelf_drag_end(wmOperatorType *ot)
{
  ot->name = "End Shelf Icon Drag";
  ot->idname = "TOPBAR_OT_maya_shelf_drag_end";
  ot->description = "Stop tracking the shelf drag insertion marker";
  ot->exec = shelf_drag_end_exec;
  ot->flag = OPTYPE_INTERNAL;
}

/* add handlers, stuff you only do once or on area/region changes */
static void topbar_shelf_region_init(wmWindowManager * /*wm*/, ARegion *region)
{
  ED_region_header_init(region);
  WM_event_remove_ui_handler(&region->runtime->handlers,
                             topbar_shelf_region_event_handler,
                             nullptr,
                             nullptr,
                             false);
  WM_event_add_ui_handler(nullptr,
                          &region->runtime->handlers,
                          topbar_shelf_region_event_handler,
                          nullptr,
                          nullptr,
                          eWM_EventHandlerFlag(0));
}

static void shelf_main_region_init(wmWindowManager *wm, ARegion *region)
{
  region->v2d.scroll = V2D_SCROLL_RIGHT | V2D_SCROLL_VERTICAL_HIDE;
  ED_region_panels_init(wm, region);
  WM_event_remove_ui_handler(&region->runtime->handlers,
                             topbar_shelf_region_event_handler,
                             nullptr,
                             nullptr,
                             false);
  WM_event_add_ui_handler(nullptr,
                          &region->runtime->handlers,
                          topbar_shelf_region_event_handler,
                          nullptr,
                          nullptr,
                          eWM_EventHandlerFlag(0));
}

static bool topbar_shelf_color_parse(const std::optional<StringRefNull> &value, uchar color[4])
{
  if (!value) {
    return false;
  }
  float rgba[4];
  if (std::sscanf(value->c_str(), "%f,%f,%f,%f", &rgba[0], &rgba[1], &rgba[2], &rgba[3]) !=
      4)
  {
    return false;
  }
  rgba_float_to_uchar(color, rgba);
  color[3] = std::max(color[3], uchar(1));
  return true;
}

static void topbar_shelf_button_colors_apply(ui::Button *button, void * /*user_data*/)
{
  uchar color[4];
  if (topbar_shelf_color_parse(
          ui::button_context_string_get(button, "maya_shelf_icon_color"), color))
  {
    ui::button_color_set(button, color);
  }
  if (topbar_shelf_color_parse(
          ui::button_context_string_get(button, "maya_shelf_background_color"), color))
  {
    ui::button_background_color_set(button, color);
  }
}

static void topbar_shelf_region_layout(const bContext *C, ARegion *region)
{
  ED_region_header_layout(C, region);

  const int bottom_padding = int(4.0f * UI_SCALE_FAC + 0.5f);
  const int offset_y = bottom_padding -
                       ui::blocklist_min_y_get(&region->runtime->uiblocks);
  if (offset_y > 0) {
    for (ui::Block &block : region->runtime->uiblocks) {
      ui::block_translate(&block, 0, offset_y);
    }
  }
  ui::blocklist_buttons_foreach(
      &region->runtime->uiblocks, topbar_shelf_button_colors_apply, nullptr);
}

static void topbar_shelf_region_draw(const bContext *C, ARegion *region)
{
  ui::theme::bThemeState theme_state;
  ui::theme::theme_store(&theme_state);
  ui::theme::theme_set(SPACE_OUTLINER, RGN_TYPE_WINDOW);
  ED_region_header_draw(C, region);
  ui::theme::theme_restore(&theme_state);
  topbar_shelf_drag_marker_draw(C, region);
}

static void shelf_main_region_draw(const bContext *C, ARegion *region)
{
  ED_region_panels_draw(C, region);
  topbar_shelf_drag_marker_draw(C, region);
}

static void shelf_main_region_layout(const bContext *C, ARegion *region)
{
  ED_region_panels_layout(C, region);
  ui::blocklist_buttons_foreach(
      &region->runtime->uiblocks, topbar_shelf_button_colors_apply, nullptr);
}

static wmOperatorStatus shelf_global_redraw_exec(bContext *C, wmOperator * /*op*/)
{
  wmWindowManager *wm = CTX_wm_manager(C);
  if (wm != nullptr) {
    for (wmWindow &window : wm->windows) {
      for (ScrArea &area : window.global_areas.areabase) {
        if (area.spacetype == SPACE_TOPBAR) {
          ED_area_tag_redraw(&area);
        }
      }
    }
  }
  return OPERATOR_FINISHED;
}

static void TOPBAR_OT_shelf_global_redraw(wmOperatorType *ot)
{
  ot->name = "Redraw Global Shelf";
  ot->idname = "TOPBAR_OT_shelf_global_redraw";
  ot->description = "Redraw the global Top Bar shelf immediately";
  ot->exec = shelf_global_redraw_exec;
  ot->flag = OPTYPE_INTERNAL;
}

static void topbar_operatortypes()
{
  WM_operatortype_append(TOPBAR_OT_shelf_global_redraw);
  WM_operatortype_append(TOPBAR_OT_maya_shelf_drag_probe);
  WM_operatortype_append(TOPBAR_OT_maya_shelf_drag_end);
}

static void topbar_keymap(wmKeyConfig * /*keyconf*/) {}

/* add handlers, stuff you only do once or on area/region changes */
static void topbar_header_region_init(wmWindowManager * /*wm*/, ARegion *region)
{
  if (RGN_ALIGN_ENUM_FROM_MASK(region->alignment) == RGN_ALIGN_RIGHT) {
    region->flag |= RGN_FLAG_DYNAMIC_SIZE;
  }
  ED_region_header_init(region);
}

static void topbar_main_region_listener(const wmRegionListenerParams *params)
{
  ARegion *region = params->region;
  const wmNotifier *wmn = params->notifier;

  /* context changes */
  switch (wmn->category) {
    case NC_WM:
      if (wmn->data == ND_HISTORY) {
        ED_region_tag_redraw(region);
      }
      break;
    case NC_SCENE:
      if (wmn->data == ND_MODE) {
        ED_region_tag_redraw(region);
      }
      break;
    case NC_SPACE:
      if (wmn->data == ND_SPACE_VIEW3D) {
        ED_region_tag_redraw(region);
      }
      break;
    case NC_GPENCIL:
      if (wmn->data == ND_DATA) {
        ED_region_tag_redraw(region);
      }
      break;
  }
}

static void topbar_header_listener(const wmRegionListenerParams *params)
{
  ARegion *region = params->region;
  const wmNotifier *wmn = params->notifier;

  /* context changes */
  switch (wmn->category) {
    case NC_WM:
      if (wmn->data == ND_JOB) {
        ED_region_tag_redraw(region);
      }
      break;
    case NC_WORKSPACE:
      ED_region_tag_redraw(region);
      break;
    case NC_SPACE:
      if (wmn->data == ND_SPACE_INFO) {
        ED_region_tag_redraw(region);
      }
      break;
    case NC_SCREEN:
      if (wmn->data == ND_LAYER) {
        ED_region_tag_redraw(region);
      }
      break;
    case NC_SCENE:
      if (wmn->data == ND_SCENEBROWSE) {
        ED_region_tag_redraw(region);
      }
      break;
  }
}

static void topbar_header_region_message_subscribe(const wmRegionMessageSubscribeParams *params)
{
  wmMsgBus *mbus = params->message_bus;
  WorkSpace *workspace = params->workspace;
  ARegion *region = params->region;

  wmMsgSubscribeValue msg_sub_value_region_tag_redraw{};
  msg_sub_value_region_tag_redraw.owner = region;
  msg_sub_value_region_tag_redraw.user_data = region;
  msg_sub_value_region_tag_redraw.notify = ED_region_do_msg_notify_tag_redraw;

  WM_msg_subscribe_rna_prop(
      mbus, &workspace->id, workspace, WorkSpace, tools, &msg_sub_value_region_tag_redraw);
}

static void recent_files_menu_draw(const bContext *C, Menu *menu)
{
  ui::Layout &layout = *menu->layout;
  layout.operator_context_set(wm::OpCallContext::InvokeDefault);
  const bool is_menu_search = CTX_data_int_get(C, "is_menu_search").value_or(false);
  if (is_menu_search) {
    template_recent_files(&layout, U.recent_files);
  }
  else {
    const int limit = std::min<int>(U.recent_files, 20);
    if (template_recent_files(&layout, limit) != 0) {
      layout.separator();
      PointerRNA search_props = layout.op(
          "WM_OT_search_single_menu", IFACE_("More..."), ICON_VIEWZOOM);
      RNA_string_set(&search_props, "menu_idname", "TOPBAR_MT_file_open_recent");
      layout.op("WM_OT_clear_recent_files", IFACE_("Clear Recent Files List..."), ICON_TRASH);
    }
    else {
      layout.label(IFACE_("No Recent Files"), ICON_NONE);
    }
  }
}

static void recent_files_menu_register()
{
  MenuType *mt;

  mt = MEM_new_zeroed<MenuType>("spacetype info menu recent files");
  STRNCPY_UTF8(mt->idname, "TOPBAR_MT_file_open_recent");
  STRNCPY_UTF8(mt->label, N_("Open Recent"));
  STRNCPY_UTF8(mt->translation_context, BLT_I18NCONTEXT_DEFAULT_BPYRNA);
  mt->draw = recent_files_menu_draw;
  WM_menutype_add(mt);
}

static void undo_history_draw_menu(const bContext *C, Menu *menu)
{
  wmWindowManager *wm = CTX_wm_manager(C);
  if (wm->runtime->undo_stack == nullptr) {
    return;
  }

  int undo_step_count = 0;
  int undo_step_count_all = 0;
  for (UndoStep &us : wm->runtime->undo_stack->steps.items_reversed()) {
    undo_step_count_all += 1;
    if (us.skip) {
      continue;
    }
    undo_step_count += 1;
  }

  ui::Layout &split = menu->layout->split(0.0f, false);
  ui::Layout *column = nullptr;

  const int col_size = 20 + (undo_step_count / 12);

  undo_step_count = 0;

  /* Reverse the order so the most recent state is first in the menu. */
  int i = undo_step_count_all - 1;
  for (UndoStep *us = static_cast<UndoStep *>(wm->runtime->undo_stack->steps.last); us;
       us = us->prev, i--)
  {
    if (us->skip) {
      continue;
    }
    if (!(undo_step_count % col_size)) {
      column = &split.column(false);
    }
    const bool is_active = (us == wm->runtime->undo_stack->step_active);
    ui::Layout &row = column->row(false);
    row.enabled_set(!is_active);
    PointerRNA op_ptr = row.op("ED_OT_undo_history",
                               CTX_IFACE_(BLT_I18NCONTEXT_OPERATOR_DEFAULT, us->name),
                               is_active ? ICON_LAYER_ACTIVE : ICON_NONE);
    RNA_int_set(&op_ptr, "item", i);
    undo_step_count += 1;
  }
}

static void undo_history_menu_register()
{
  MenuType *mt;

  mt = MEM_new_zeroed<MenuType>(__func__);
  STRNCPY_UTF8(mt->idname, "TOPBAR_MT_undo_history");
  STRNCPY_UTF8(mt->label, N_("Undo History"));
  STRNCPY_UTF8(mt->translation_context, BLT_I18NCONTEXT_DEFAULT_BPYRNA);
  mt->draw = undo_history_draw_menu;
  WM_menutype_add(mt);
}

static void topbar_space_blend_write(BlendWriter *writer, SpaceLink *sl)
{
  writer->write_struct_cast<SpaceTopBar>(sl);
}

void ED_spacetype_topbar()
{
  std::unique_ptr<SpaceType> st = std::make_unique<SpaceType>();
  ARegionType *art;

  st->spaceid = SPACE_TOPBAR;
  STRNCPY_UTF8(st->name, "Top Bar");

  st->create = topbar_create;
  st->free = topbar_free;
  st->init = topbar_init;
  st->duplicate = topbar_duplicate;
  st->operatortypes = topbar_operatortypes;
  st->keymap = topbar_keymap;
  st->blend_write = topbar_space_blend_write;

  /* regions: main window */
  art = MEM_new_zeroed<ARegionType>("spacetype topbar main region");
  art->regionid = RGN_TYPE_WINDOW;
  art->init = topbar_shelf_region_init;
  art->layout = topbar_shelf_region_layout;
  art->draw = topbar_shelf_region_draw;
  art->listener = topbar_main_region_listener;
  art->prefsizex = UI_UNIT_X * 5; /* Mainly to avoid glitches */
  art->keymapflag = ED_KEYMAP_UI | ED_KEYMAP_HEADER;

  BLI_addhead(&st->regiontypes, art);

  /* regions: shelf tabs */
  art = MEM_new_zeroed<ARegionType>("spacetype topbar shelf tabs region");
  art->regionid = RGN_TYPE_TOOL_HEADER;
  art->prefsizey = HEADERY;
  art->prefsizex = UI_UNIT_X * 5;
  art->keymapflag = ED_KEYMAP_UI | ED_KEYMAP_HEADER;
  art->listener = topbar_header_listener;
  art->message_subscribe = topbar_header_region_message_subscribe;
  art->init = topbar_header_region_init;
  art->layout = ED_region_header_layout;
  art->draw = ED_region_header_draw;

  BLI_addhead(&st->regiontypes, art);

  /* regions: upper shelf row */
  art = MEM_new_zeroed<ARegionType>("spacetype topbar shelf footer region");
  art->regionid = RGN_TYPE_FOOTER;
  art->prefsizey = HEADERY + 9;
  art->prefsizex = UI_UNIT_X * 5;
  art->keymapflag = ED_KEYMAP_UI | ED_KEYMAP_FOOTER;
  art->listener = topbar_main_region_listener;
  art->init = topbar_shelf_region_init;
  art->layout = ED_region_header_layout;
  art->draw = topbar_shelf_region_draw;

  BLI_addhead(&st->regiontypes, art);

  /* regions: header */
  art = MEM_new_zeroed<ARegionType>("spacetype topbar header region");
  art->regionid = RGN_TYPE_HEADER;
  art->prefsizey = HEADERY;
  art->prefsizex = UI_UNIT_X * 5; /* Mainly to avoid glitches */
  art->keymapflag = ED_KEYMAP_UI | ED_KEYMAP_VIEW2D | ED_KEYMAP_HEADER;
  art->listener = topbar_header_listener;
  art->message_subscribe = topbar_header_region_message_subscribe;
  art->init = topbar_header_region_init;
  art->layout = ED_region_header_layout;
  art->draw = ED_region_header_draw;

  BLI_addhead(&st->regiontypes, art);

  recent_files_menu_register();
  undo_history_menu_register();

  BKE_spacetype_register(std::move(st));
}

void ED_spacetype_shelf()
{
  std::unique_ptr<SpaceType> st = std::make_unique<SpaceType>();

  st->spaceid = SPACE_SHELF;
  STRNCPY_UTF8(st->name, "Shelf");
  st->create = shelf_create;
  st->free = topbar_free;
  st->init = topbar_init;
  st->duplicate = topbar_duplicate;
  st->operatortypes = nullptr;
  st->keymap = topbar_keymap;
  st->blend_write = topbar_space_blend_write;

  ARegionType *art = MEM_new_zeroed<ARegionType>("spacetype shelf main region");
  art->regionid = RGN_TYPE_WINDOW;
  art->init = shelf_main_region_init;
  art->layout = shelf_main_region_layout;
  art->draw = shelf_main_region_draw;
  art->listener = topbar_main_region_listener;
  art->prefsizex = UI_UNIT_X * 5;
  art->keymapflag = ED_KEYMAP_UI | ED_KEYMAP_HEADER;
  BLI_addhead(&st->regiontypes, art);

  art = MEM_new_zeroed<ARegionType>("spacetype shelf header region");
  art->regionid = RGN_TYPE_HEADER;
  art->prefsizey = HEADERY;
  art->prefsizex = UI_UNIT_X * 5;
  art->keymapflag = ED_KEYMAP_UI | ED_KEYMAP_VIEW2D | ED_KEYMAP_HEADER;
  art->listener = topbar_header_listener;
  art->message_subscribe = topbar_header_region_message_subscribe;
  art->init = topbar_header_region_init;
  art->layout = ED_region_header_layout;
  art->draw = ED_region_header_draw;
  BLI_addhead(&st->regiontypes, art);

  BKE_spacetype_register(std::move(st));
}

}  // namespace blender
