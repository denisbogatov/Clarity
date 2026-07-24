/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup editors
 */

#pragma once

namespace blender {

struct bContext;

namespace ed::maya {
struct MayaWindowRuntime;
}

void ED_maya_tool_presentation_refresh(
    bContext *C, const ed::maya::MayaWindowRuntime &runtime);

}  // namespace blender
