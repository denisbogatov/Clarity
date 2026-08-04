/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup editors
 */

#pragma once

#include "DNA_screen_types.h"
#include "DNA_space_enums.h"

namespace blender {

struct ARegion;
struct ScrArea;
struct WorkSpace;
struct bContext;
struct wmWindow;

namespace ed::clarity {

struct ClaritySessionContext {
  wmWindow *window = nullptr;
  WorkSpace *workspace = nullptr;
  ScrArea *area = nullptr;
  ARegion *region = nullptr;

  int space_type = SPACE_EMPTY;
  int region_type = RGN_TYPE_WINDOW;
};

}  // namespace ed::clarity

ed::clarity::ClaritySessionContext ED_clarity_session_context_from_context(const bContext *C);
bool ED_clarity_session_context_matches_context(
    const bContext *C, const ed::clarity::ClaritySessionContext &session_context);
bool ED_clarity_session_context_is_valid(
    const bContext *C, const ed::clarity::ClaritySessionContext &session_context);

}  // namespace blender
