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

/**
 * Which set operation a topological double click asks for. The gesture decides whether a loop or a
 * path is affected; the modifiers decide only this.
 */
enum class MayaTopologySelectOp : uint8_t {
  /** Plain double click: the loop becomes the selection. */
  Replace,
  /** `Shift`: flip the state of the components, so the same gesture adds and removes. */
  Toggle,
  /** `Ctrl`: take the loop or path out of the selection, whatever its state was. */
  Subtract,
  /** `Ctrl+Shift`: put it in, without touching anything already selected. */
  Add,
};

MayaTopologySelectOp topology_select_op_from_action(const MayaInputAction &action);

void register_tool_operators();
MayaDispatchResult selection_handle_action(bContext *C,
                                            MayaWindowRuntime &runtime,
                                            const MayaInputAction &action);
/**
 * Start the Maya marquee when the left button crosses the drag threshold. Blender only ever
 * synthesizes its own drag event inside the key-map pass, which runs after the Maya dispatcher, so
 * the rectangle has to be recognized from the motion itself or the key-map of the active tool
 * inherits the drag.
 */
bool left_mouse_marquee_drag_handle(bContext *C,
                                    MayaWindowRuntime &runtime,
                                    const MayaInputAction &action);
bool middle_mouse_axis_drag_handle(bContext *C,
                                   MayaWindowRuntime &runtime,
                                   const MayaInputAction &action);
bool shift_transform_prepare(bContext *C, wmOperator *op, const wmEvent *event);
void shift_transform_end(bContext *C, MayaWindowRuntime &runtime, bool cancelled);

}  // namespace ed::maya
}  // namespace blender
