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

namespace ed::clarity {

enum class ClarityDispatchResult : uint8_t;
enum class ClarityCameraBasedSelection : uint8_t;
struct ClarityInputAction;
struct ClarityWindowRuntime;

/**
 * Which base set operation a topological double click asks for. The component mode and gesture
 * decide whether a shell, loop or path is affected; an adjacent Shift-face gesture remains
 * additive because its preceding click has already selected the shared edge.
 */
enum class ClarityTopologySelectOp : uint8_t {
  /** Plain double click: the topology target becomes the selection. */
  Replace,
  /** `Shift`: flip the state of the components, so the same gesture adds and removes. */
  Toggle,
  /** `Ctrl`: take the loop or path out of the selection, whatever its state was. */
  Subtract,
  /** `Ctrl+Shift`: the base additive operation; the click chord itself belongs to the marquee. */
  Add,
};

ClarityTopologySelectOp topology_select_op_from_action(const ClarityInputAction &action);

/** Whether marquee selection must reject components occluded from the current view. */
bool camera_based_selection_use_depth(ClarityCameraBasedSelection mode,
                                      bool is_shaded,
                                      bool is_xray);

/**
 * Whether the action is the additive marquee's own chord and must be swallowed rather than reach
 * the pickers. Only the click belongs to the marquee; the double click of the same chord is the
 * topology gesture.
 */
bool selection_action_is_reserved_for_marquee(const ClarityInputAction &action);

void register_tool_operators();
ClarityDispatchResult selection_handle_action(bContext *C,
                                            ClarityWindowRuntime &runtime,
                                            const ClarityInputAction &action);
/**
 * Start the Clarity marquee when the left button crosses the drag threshold. Blender only ever
 * synthesizes its own drag event inside the key-map pass, which runs after the Clarity dispatcher, so
 * the rectangle has to be recognized from the motion itself or the key-map of the active tool
 * inherits the drag.
 */
bool left_mouse_marquee_drag_handle(bContext *C,
                                    ClarityWindowRuntime &runtime,
                                    const ClarityInputAction &action);
bool middle_mouse_axis_drag_handle(bContext *C,
                                   ClarityWindowRuntime &runtime,
                                   const ClarityInputAction &action);
/**
 * Run the standing selection constraint over what a finished marquee selected. Does nothing unless
 * a marquee left something to constrain, so it is cheap to call for every action.
 */
bool selection_constraint_apply_pending(bContext *C, ClarityWindowRuntime &runtime);
bool shift_transform_prepare(bContext *C, wmOperator *op, const wmEvent *event);
void shift_transform_end(bContext *C, ClarityWindowRuntime &runtime, bool cancelled);

}  // namespace ed::clarity
}  // namespace blender
