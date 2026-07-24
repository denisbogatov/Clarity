/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup editors
 */

#include "maya_tool.hh"

#include "DNA_screen_types.h"
#include "DNA_space_enums.h"
#include "DNA_view3d_types.h"

#include "BKE_context.hh"

#include "ED_screen.hh"

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

static void maya_transform_gizmo_activate(bContext *C,
                                          const eView3D_GizmoShowObject gizmo_type)
{
  View3D *v3d = CTX_wm_view3d(C);
  ARegion *region = CTX_wm_region(C);
  if (v3d == nullptr || region == nullptr) {
    return;
  }

  v3d->gizmo_show_object = gizmo_type;
  v3d->gizmo_flag &= ~V3D_GIZMO_HIDE_CONTEXT;
  v3d->gizmo_flag |= V3D_GIZMO_HIDE_TOOL;

  ED_region_tag_redraw(region);
}

static void maya_select_tool_activate(bContext *C,
                                      ed::maya::MayaWindowRuntime & /*runtime*/)
{
  maya_transform_gizmo_activate(C, eView3D_GizmoShowObject(0));
}

static void maya_move_tool_activate(bContext *C,
                                    ed::maya::MayaWindowRuntime & /*runtime*/)
{
  maya_transform_gizmo_activate(C, V3D_GIZMO_SHOW_OBJECT_TRANSLATE);
}

static void maya_rotate_tool_activate(bContext *C,
                                      ed::maya::MayaWindowRuntime & /*runtime*/)
{
  maya_transform_gizmo_activate(C, V3D_GIZMO_SHOW_OBJECT_ROTATE);
}

static void maya_scale_tool_activate(bContext *C,
                                     ed::maya::MayaWindowRuntime & /*runtime*/)
{
  maya_transform_gizmo_activate(C, V3D_GIZMO_SHOW_OBJECT_SCALE);
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
