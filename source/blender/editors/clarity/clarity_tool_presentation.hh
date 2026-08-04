/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup editors
 */

#pragma once

namespace blender {

struct bContext;

namespace ed::clarity {
struct ClarityWindowRuntime;
}

void ED_clarity_tool_presentation_refresh(
    bContext *C, const ed::clarity::ClarityWindowRuntime &runtime);

}  // namespace blender
