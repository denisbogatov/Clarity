/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup editors
 */

#pragma once

#include <cstdint>

namespace blender {

struct bContext;
struct wmEvent;
struct wmOperator;
struct wmOperatorType;

namespace ed::maya {

enum class MayaDispatchResult : uint8_t;
struct MayaInputAction;
struct MayaWindowRuntime;

void register_tool_operators();
MayaDispatchResult selection_handle_action(bContext *C,
                                            MayaWindowRuntime &runtime,
                                            const MayaInputAction &action);
bool middle_mouse_axis_drag_handle(bContext *C,
                                   MayaWindowRuntime &runtime,
                                   const MayaInputAction &action);
bool shift_transform_prepare(bContext *C, wmOperator *op, const wmEvent *event);
void shift_transform_end(bContext *C, MayaWindowRuntime &runtime, bool cancelled);

}  // namespace ed::maya
}  // namespace blender
