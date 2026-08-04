/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup editors
 */

#include "clarity_tool.hh"

#include "BLI_time.h"
#include "BLI_utildefines.h"

#include "clarity_runtime.hh"

namespace blender {

ed::clarity::ClarityToolActivationResult ED_clarity_tool_activate(
    bContext *C,
    const ed::clarity::ClarityToolID tool_id,
    const ed::clarity::ClarityToolActivationReason reason)
{
  ed::clarity::ClarityWindowRuntime *runtime = ed::clarity::runtime_ensure(C);
  if (runtime == nullptr) {
    return ed::clarity::ClarityToolActivationResult::Rejected;
  }
  if (runtime->active_session) {
    return ed::clarity::ClarityToolActivationResult::BlockedBySession;
  }

  const ed::clarity::ClarityToolType *next = ED_clarity_tool_type_find(tool_id);
  if (next == nullptr || (next->poll != nullptr && !next->poll(C, *runtime))) {
    return ed::clarity::ClarityToolActivationResult::Rejected;
  }
  if (runtime->tool.active == tool_id) {
    const double activation_start = BLI_time_now_seconds();
    if (next->activate != nullptr) {
      next->activate(C, *runtime);
    }
    runtime->last_tool_activation_time = BLI_time_now_seconds();
    runtime->last_tool_activation_duration_ms =
        (runtime->last_tool_activation_time - activation_start) * 1000.0;
    return ed::clarity::ClarityToolActivationResult::AlreadyActive;
  }

  const double activation_start = BLI_time_now_seconds();
  const ed::clarity::ClarityToolType *previous = ED_clarity_tool_type_find(runtime->tool.active);
  if (previous != nullptr && previous->deactivate != nullptr) {
    previous->deactivate(C, *runtime);
  }

  runtime->tool.previous = runtime->tool.active;
  runtime->tool.active = tool_id;
  runtime->tool.revision++;
  ed::clarity::tool_mirror_sync(C, runtime->tool.active);

  if (next->activate != nullptr) {
    next->activate(C, *runtime);
  }
  runtime->last_tool_activation_time = BLI_time_now_seconds();
  runtime->last_tool_activation_duration_ms =
      (runtime->last_tool_activation_time - activation_start) * 1000.0;

  UNUSED_VARS(reason);
  return ed::clarity::ClarityToolActivationResult::Activated;
}

}  // namespace blender
