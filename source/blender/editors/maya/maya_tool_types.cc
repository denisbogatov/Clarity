/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup editors
 */

#include "maya_tool.hh"

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

#include "maya_runtime.hh"

namespace blender {

static bool maya_view3d_tool_poll(const bContext *C,
                                  const ed::maya::MayaWindowRuntime & /*runtime*/)
{
  const ScrArea *area = CTX_wm_area(C);
  const ARegion *region = CTX_wm_region(C);
  return area != nullptr && area->spacetype == SPACE_VIEW3D && region != nullptr &&
         region->regiontype == RGN_TYPE_WINDOW;
}

static eView3D_GizmoShowObject maya_tool_gizmo_type_get(const ed::maya::MayaToolID tool_id)
{
  switch (tool_id) {
    case ed::maya::MayaToolID::Move:
      return V3D_GIZMO_SHOW_OBJECT_TRANSLATE;
    case ed::maya::MayaToolID::Rotate:
      return V3D_GIZMO_SHOW_OBJECT_ROTATE;
    case ed::maya::MayaToolID::Scale:
      return V3D_GIZMO_SHOW_OBJECT_SCALE;
    case ed::maya::MayaToolID::None:
    case ed::maya::MayaToolID::Select:
    case ed::maya::MayaToolID::MultiCut:
    case ed::maya::MayaToolID::TargetWeld:
    case ed::maya::MayaToolID::QuadDraw:
      break;
  }
  /* No manipulator, like Maya's Select tool. */
  return eView3D_GizmoShowObject(0);
}

/** True when this 3D View already presents \a gizmo_type as the Maya manipulator. */
static bool maya_view3d_gizmo_state_matches(const View3D &v3d,
                                            const eView3D_GizmoShowObject gizmo_type)
{
  return v3d.gizmo_show_object == gizmo_type &&
         (v3d.gizmo_flag & V3D_GIZMO_HIDE_CONTEXT) == 0 &&
         (v3d.gizmo_flag & V3D_GIZMO_HIDE_TOOL) != 0;
}

static bool maya_view3d_gizmo_state_apply(ScrArea &area,
                                          const eView3D_GizmoShowObject gizmo_type)
{
  if (area.spacetype != SPACE_VIEW3D) {
    return false;
  }
  View3D *v3d = static_cast<View3D *>(area.spacedata.first);
  if (v3d == nullptr || maya_view3d_gizmo_state_matches(*v3d, gizmo_type)) {
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
 * The Maya tool is global: every 3D View has to show the same manipulator. Keeping it per-area
 * would let a second viewport or another workspace present a manipulator that does not match the
 * active tool.
 */
static void maya_transform_gizmo_activate(bContext *C,
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
      maya_view3d_gizmo_state_apply(area, gizmo_type);
    }
  }
}

/**
 * The Maya transform tools own the viewport, so no Blender tool may stay active underneath: its
 * tool gizmo would compete with the Maya manipulator and its tool settings would show in the
 * header. Notably `D` cycles to Annotate in the Blender keymap, which is exactly what must not
 * survive here. Box select is the neutral equivalent of Maya's Select tool.
 */
static void maya_blender_tool_neutralize(bContext *C)
{
  const bToolRef *tref = WM_toolsystem_ref_from_context(C);
  if (tref != nullptr && STREQ(tref->idname, "builtin.select_box")) {
    return;
  }
  WM_toolsystem_ref_set_by_id(C, "builtin.select_box");
}

static void maya_select_tool_activate(bContext *C,
                                      ed::maya::MayaWindowRuntime & /*runtime*/)
{
  maya_blender_tool_neutralize(C);
  maya_transform_gizmo_activate(C, maya_tool_gizmo_type_get(ed::maya::MayaToolID::Select));
}

static void maya_move_tool_activate(bContext *C,
                                    ed::maya::MayaWindowRuntime & /*runtime*/)
{
  maya_blender_tool_neutralize(C);
  maya_transform_gizmo_activate(C, maya_tool_gizmo_type_get(ed::maya::MayaToolID::Move));
}

static void maya_rotate_tool_activate(bContext *C,
                                      ed::maya::MayaWindowRuntime & /*runtime*/)
{
  maya_blender_tool_neutralize(C);
  maya_transform_gizmo_activate(C, maya_tool_gizmo_type_get(ed::maya::MayaToolID::Rotate));
}

static void maya_scale_tool_activate(bContext *C,
                                     ed::maya::MayaWindowRuntime & /*runtime*/)
{
  maya_blender_tool_neutralize(C);
  maya_transform_gizmo_activate(C, maya_tool_gizmo_type_get(ed::maya::MayaToolID::Scale));
}

static void maya_tool_deactivate_noop(bContext * /*C*/,
                                      ed::maya::MayaWindowRuntime & /*runtime*/)
{
}

static constexpr ed::maya::MayaToolCapability selection_capabilities =
    ed::maya::MayaToolCapability::UsesSelection |
    ed::maya::MayaToolCapability::SupportsObject |
    ed::maya::MayaToolCapability::SupportsComponents;

static constexpr ed::maya::MayaToolCapability transform_capabilities =
    selection_capabilities | ed::maya::MayaToolCapability::UsesManipulator;

static const ed::maya::MayaToolType tool_types[] = {
    {ed::maya::MayaToolID::Select,
     "maya.select",
     "Select",
     selection_capabilities,
     maya_view3d_tool_poll,
     maya_select_tool_activate,
     maya_tool_deactivate_noop},
    {ed::maya::MayaToolID::Move,
     "maya.move",
     "Move",
     transform_capabilities,
     maya_view3d_tool_poll,
     maya_move_tool_activate,
     maya_tool_deactivate_noop},
    {ed::maya::MayaToolID::Rotate,
     "maya.rotate",
     "Rotate",
     transform_capabilities,
     maya_view3d_tool_poll,
     maya_rotate_tool_activate,
     maya_tool_deactivate_noop},
    {ed::maya::MayaToolID::Scale,
     "maya.scale",
     "Scale",
     transform_capabilities,
     maya_view3d_tool_poll,
     maya_scale_tool_activate,
     maya_tool_deactivate_noop},
};

/**
 * Inverse of #maya_tool_gizmo_type_get. Only an unambiguous single-manipulator view maps back to a
 * tool; anything else (no manipulator, or a combination no Maya tool can produce) is left alone so
 * a view configured outside the Maya tools is never reinterpreted.
 */
static std::optional<ed::maya::MayaToolID> maya_tool_from_gizmo_state(const View3D &v3d)
{
  if ((v3d.gizmo_flag & V3D_GIZMO_HIDE_CONTEXT) != 0) {
    return std::nullopt;
  }
  switch (v3d.gizmo_show_object & (V3D_GIZMO_SHOW_OBJECT_TRANSLATE |
                                   V3D_GIZMO_SHOW_OBJECT_ROTATE |
                                   V3D_GIZMO_SHOW_OBJECT_SCALE))
  {
    case V3D_GIZMO_SHOW_OBJECT_TRANSLATE:
      return ed::maya::MayaToolID::Move;
    case V3D_GIZMO_SHOW_OBJECT_ROTATE:
      return ed::maya::MayaToolID::Rotate;
    case V3D_GIZMO_SHOW_OBJECT_SCALE:
      return ed::maya::MayaToolID::Scale;
    default:
      return std::nullopt;
  }
}

void ED_maya_tool_gizmo_state_ensure(bContext *C, ed::maya::MayaToolState &tool)
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
    if (const std::optional<ed::maya::MayaToolID> adopted = maya_tool_from_gizmo_state(*v3d)) {
      tool.active = *adopted;
      tool.previous = *adopted;
    }
  }

  /* Maya owns the manipulator while its interaction preset is active: the tool gizmo of the active
   * Blender tool has to stay hidden so the persistent context gizmo group takes over. Only that
   * group follows the Maya tool and switches to the pivot manipulator during Edit Pivot. */
  const eView3D_GizmoShowObject gizmo_type = maya_tool_gizmo_type_get(tool.active);
  if (maya_view3d_gizmo_state_apply(*area, gizmo_type)) {
    /* A newly opened 3D View, a workspace switch, or a gizmo change made outside the Maya tools
     * desynchronized this area. Bring every other view back in sync so the tool stays global. */
    maya_transform_gizmo_activate(C, gizmo_type);
  }
}

const ed::maya::MayaToolType *ED_maya_tool_type_find(const ed::maya::MayaToolID tool_id)
{
  for (const ed::maya::MayaToolType &tool_type : tool_types) {
    if (tool_type.id == tool_id) {
      return &tool_type;
    }
  }
  return nullptr;
}

}  // namespace blender
