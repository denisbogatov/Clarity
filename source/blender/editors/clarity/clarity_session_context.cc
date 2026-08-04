/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup editors
 */

#include "clarity_session_context.hh"

#include "BLI_listbase.h"

#include "BKE_context.hh"

#include "WM_api.hh"

namespace blender {

ed::clarity::ClaritySessionContext ED_clarity_session_context_from_context(const bContext *C)
{
  ed::clarity::ClaritySessionContext session_context;
  session_context.window = CTX_wm_window(C);
  session_context.workspace = CTX_wm_workspace(C);
  session_context.area = CTX_wm_area(C);
  session_context.region = CTX_wm_region(C);
  if (session_context.area != nullptr) {
    session_context.space_type = session_context.area->spacetype;
  }
  if (session_context.region != nullptr) {
    session_context.region_type = session_context.region->regiontype;
  }
  return session_context;
}

bool ED_clarity_session_context_is_valid(
    const bContext *C, const ed::clarity::ClaritySessionContext &session_context)
{
  if (!ED_clarity_session_context_matches_context(C, session_context)) {
    return false;
  }

  const bScreen *screen = WM_window_get_active_screen(session_context.window);
  if (screen == nullptr || BLI_findindex(&screen->areabase, session_context.area) == -1) {
    return false;
  }

  const ScrArea *area = session_context.area;
  if (area->spacetype != session_context.space_type ||
      BLI_findindex(&area->regionbase, session_context.region) == -1)
  {
    return false;
  }

  return session_context.region->regiontype == session_context.region_type;
}

bool ED_clarity_session_context_matches_context(
    const bContext *C, const ed::clarity::ClaritySessionContext &session_context)
{
  return session_context.window != nullptr && CTX_wm_window(C) == session_context.window &&
         CTX_wm_workspace(C) == session_context.workspace &&
         CTX_wm_area(C) == session_context.area && CTX_wm_region(C) == session_context.region;
}

}  // namespace blender
