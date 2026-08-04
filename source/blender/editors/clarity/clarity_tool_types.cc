/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup editors
 */

#include "clarity_tool.hh"

#include <optional>

#include "DNA_screen_types.h"
#include "DNA_space_enums.h"
#include "DNA_view3d_types.h"
#include "DNA_windowmanager_types.h"
#include "DNA_workspace_types.h"

#include "BLI_listbase_iterator.hh"
#include "BLI_utildefines.h"

#include "BKE_context.hh"

#include "ED_screen.hh"

#include "WM_api.hh"
#include "WM_toolsystem.hh"

#include "clarity_runtime.hh"

namespace blender {

static bool clarity_view3d_tool_poll(const bContext *C,
                                  const ed::clarity::ClarityWindowRuntime & /*runtime*/)
{
  const ScrArea *area = CTX_wm_area(C);
  const ARegion *region = CTX_wm_region(C);
  return area != nullptr && area->spacetype == SPACE_VIEW3D && region != nullptr &&
         region->regiontype == RGN_TYPE_WINDOW;
}

static eView3D_GizmoShowObject clarity_tool_gizmo_type_get(const ed::clarity::ClarityToolID tool_id)
{
  switch (tool_id) {
    case ed::clarity::ClarityToolID::Move:
      return V3D_GIZMO_SHOW_OBJECT_TRANSLATE;
    case ed::clarity::ClarityToolID::Rotate:
      return V3D_GIZMO_SHOW_OBJECT_ROTATE;
    case ed::clarity::ClarityToolID::Scale:
      return V3D_GIZMO_SHOW_OBJECT_SCALE;
    case ed::clarity::ClarityToolID::None:
    case ed::clarity::ClarityToolID::Select:
    case ed::clarity::ClarityToolID::MultiCut:
    case ed::clarity::ClarityToolID::TargetWeld:
    case ed::clarity::ClarityToolID::QuadDraw:
      break;
  }
  /* No manipulator, like Clarity's Select tool. */
  return eView3D_GizmoShowObject(0);
}

/** True when this 3D View already presents \a gizmo_type as the Clarity manipulator. */
static bool clarity_view3d_gizmo_state_matches(const View3D &v3d,
                                            const eView3D_GizmoShowObject gizmo_type)
{
  return v3d.gizmo_show_object == gizmo_type &&
         (v3d.gizmo_flag & V3D_GIZMO_HIDE_CONTEXT) == 0 &&
         (v3d.gizmo_flag & V3D_GIZMO_HIDE_TOOL) != 0;
}

static bool clarity_view3d_gizmo_state_apply(ScrArea &area,
                                          const eView3D_GizmoShowObject gizmo_type)
{
  if (area.spacetype != SPACE_VIEW3D) {
    return false;
  }
  View3D *v3d = static_cast<View3D *>(area.spacedata.first);
  if (v3d == nullptr || clarity_view3d_gizmo_state_matches(*v3d, gizmo_type)) {
    return false;
  }

  v3d->gizmo_show_object = gizmo_type;
  v3d->gizmo_flag &= ~V3D_GIZMO_HIDE_CONTEXT;
  v3d->gizmo_flag |= V3D_GIZMO_HIDE_TOOL;

  for (ARegion &region : area.regionbase) {
    if (region.regiontype == RGN_TYPE_WINDOW) {
      ED_region_tag_redraw(&region);
    }
  }
  return true;
}

/**
 * The Clarity tool is global: every 3D View has to show the same manipulator. Keeping it per-area
 * would let a second viewport or another workspace present a manipulator that does not match the
 * active tool.
 */
static void clarity_transform_gizmo_activate(bContext *C,
                                          const eView3D_GizmoShowObject gizmo_type)
{
  const wmWindowManager *wm = CTX_wm_manager(C);
  if (wm == nullptr) {
    return;
  }
  for (const wmWindow &window : wm->windows) {
    bScreen *screen = WM_window_get_active_screen(&window);
    if (screen == nullptr) {
      continue;
    }
    for (ScrArea &area : screen->areabase) {
      clarity_view3d_gizmo_state_apply(area, gizmo_type);
    }
  }
}

/**
 * The Clarity transform tools own the viewport, so no Blender tool may stay active underneath: its
 * tool gizmo would compete with the Clarity manipulator and its tool settings would show in the
 * header. Notably `D` cycles to Annotate in the Blender keymap, which is exactly what must not
 * survive here. Box select is the neutral equivalent of Clarity's Select tool.
 */
static void clarity_blender_tool_neutralize(bContext *C)
{
  const bToolRef *tref = WM_toolsystem_ref_from_context(C);
  if (tref != nullptr && STREQ(tref->idname, "builtin.select_box")) {
    return;
  }
  WM_toolsystem_ref_set_by_id(C, "builtin.select_box");
}

static void clarity_select_tool_activate(bContext *C,
                                      ed::clarity::ClarityWindowRuntime & /*runtime*/)
{
  clarity_blender_tool_neutralize(C);
  clarity_transform_gizmo_activate(C, clarity_tool_gizmo_type_get(ed::clarity::ClarityToolID::Select));
}

static void clarity_move_tool_activate(bContext *C,
                                    ed::clarity::ClarityWindowRuntime & /*runtime*/)
{
  clarity_blender_tool_neutralize(C);
  clarity_transform_gizmo_activate(C, clarity_tool_gizmo_type_get(ed::clarity::ClarityToolID::Move));
}

static void clarity_rotate_tool_activate(bContext *C,
                                      ed::clarity::ClarityWindowRuntime & /*runtime*/)
{
  clarity_blender_tool_neutralize(C);
  clarity_transform_gizmo_activate(C, clarity_tool_gizmo_type_get(ed::clarity::ClarityToolID::Rotate));
}

static void clarity_scale_tool_activate(bContext *C,
                                     ed::clarity::ClarityWindowRuntime & /*runtime*/)
{
  clarity_blender_tool_neutralize(C);
  clarity_transform_gizmo_activate(C, clarity_tool_gizmo_type_get(ed::clarity::ClarityToolID::Scale));
}

static void clarity_tool_deactivate_noop(bContext * /*C*/,
                                      ed::clarity::ClarityWindowRuntime & /*runtime*/)
{
}

static constexpr ed::clarity::ClarityToolCapability selection_capabilities =
    ed::clarity::ClarityToolCapability::UsesSelection |
    ed::clarity::ClarityToolCapability::SupportsObject |
    ed::clarity::ClarityToolCapability::SupportsComponents;

static constexpr ed::clarity::ClarityToolCapability transform_capabilities =
    selection_capabilities | ed::clarity::ClarityToolCapability::UsesManipulator;

static const ed::clarity::ClarityToolType tool_types[] = {
    {ed::clarity::ClarityToolID::Select,
     "clarity.select",
     "Select",
     selection_capabilities,
     clarity_view3d_tool_poll,
     clarity_select_tool_activate,
     clarity_tool_deactivate_noop},
    {ed::clarity::ClarityToolID::Move,
     "clarity.move",
     "Move",
     transform_capabilities,
     clarity_view3d_tool_poll,
     clarity_move_tool_activate,
     clarity_tool_deactivate_noop},
    {ed::clarity::ClarityToolID::Rotate,
     "clarity.rotate",
     "Rotate",
     transform_capabilities,
     clarity_view3d_tool_poll,
     clarity_rotate_tool_activate,
     clarity_tool_deactivate_noop},
    {ed::clarity::ClarityToolID::Scale,
     "clarity.scale",
     "Scale",
     transform_capabilities,
     clarity_view3d_tool_poll,
     clarity_scale_tool_activate,
     clarity_tool_deactivate_noop},
};

/**
 * Inverse of #clarity_tool_gizmo_type_get. Only an unambiguous single-manipulator view maps back to a
 * tool; anything else (no manipulator, or a combination no Clarity tool can produce) is left alone so
 * a view configured outside the Clarity tools is never reinterpreted.
 */
static std::optional<ed::clarity::ClarityToolID> clarity_tool_from_gizmo_state(const View3D &v3d)
{
  if ((v3d.gizmo_flag & V3D_GIZMO_HIDE_CONTEXT) != 0) {
    return std::nullopt;
  }
  switch (v3d.gizmo_show_object & (V3D_GIZMO_SHOW_OBJECT_TRANSLATE |
                                   V3D_GIZMO_SHOW_OBJECT_ROTATE |
                                   V3D_GIZMO_SHOW_OBJECT_SCALE))
  {
    case V3D_GIZMO_SHOW_OBJECT_TRANSLATE:
      return ed::clarity::ClarityToolID::Move;
    case V3D_GIZMO_SHOW_OBJECT_ROTATE:
      return ed::clarity::ClarityToolID::Rotate;
    case V3D_GIZMO_SHOW_OBJECT_SCALE:
      return ed::clarity::ClarityToolID::Scale;
    default:
      return std::nullopt;
  }
}

void ED_clarity_tool_gizmo_state_ensure(bContext *C, ed::clarity::ClarityToolState &tool)
{
  ScrArea *area = CTX_wm_area(C);
  if (area == nullptr || area->spacetype != SPACE_VIEW3D) {
    return;
  }
  const View3D *v3d = static_cast<const View3D *>(area->spacedata.first);
  if (v3d == nullptr) {
    return;
  }

  if (!tool.adopted_from_view) {
    tool.adopted_from_view = true;
    if (const std::optional<ed::clarity::ClarityToolID> adopted = clarity_tool_from_gizmo_state(*v3d)) {
      tool.active = *adopted;
      tool.previous = *adopted;
      ed::clarity::tool_mirror_sync(C, tool.active);
    }
  }

  /* Clarity owns the manipulator while its interaction preset is active: the tool gizmo of the active
   * Blender tool has to stay hidden so the persistent context gizmo group takes over. Only that
   * group follows the Clarity tool and switches to the pivot manipulator during Edit Pivot. */
  const eView3D_GizmoShowObject gizmo_type = clarity_tool_gizmo_type_get(tool.active);
  if (clarity_view3d_gizmo_state_apply(*area, gizmo_type)) {
    /* A newly opened 3D View, a workspace switch, or a gizmo change made outside the Clarity tools
     * desynchronized this area. Bring every other view back in sync so the tool stays global. */
    clarity_transform_gizmo_activate(C, gizmo_type);
  }
}

const ed::clarity::ClarityToolType *ED_clarity_tool_type_find(const ed::clarity::ClarityToolID tool_id)
{
  for (const ed::clarity::ClarityToolType &tool_type : tool_types) {
    if (tool_type.id == tool_id) {
      return &tool_type;
    }
  }
  return nullptr;
}

}  // namespace blender
