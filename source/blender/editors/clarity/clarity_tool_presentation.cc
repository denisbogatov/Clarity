/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup editors
 */

#include "clarity_tool_presentation.hh"

#include "DNA_screen_types.h"
#include "DNA_space_enums.h"

#include "BLI_listbase.h"

#include "BKE_context.hh"
#include "BKE_screen.hh"

#include "ED_screen.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "clarity_runtime.hh"

namespace blender {

void ED_clarity_tool_presentation_refresh(
    bContext *C, const ed::clarity::ClarityWindowRuntime & /*runtime*/)
{
  wmWindow *win = CTX_wm_window(C);
  bScreen *screen = win != nullptr ? WM_window_get_active_screen(win) : nullptr;
  if (screen == nullptr) {
    return;
  }

  for (ScrArea &area : screen->areabase) {
    if (area.spacetype != SPACE_VIEW3D) {
      continue;
    }
    ED_area_tag_redraw(&area);
    for (ARegion &region : area.regionbase) {
      if (region.runtime != nullptr && region.runtime->gizmo_map != nullptr) {
        WM_gizmomap_tag_refresh(region.runtime->gizmo_map);
      }
    }
  }
}

}  // namespace blender
