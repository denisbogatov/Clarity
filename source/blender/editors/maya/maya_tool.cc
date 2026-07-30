/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup editors
 */

#include "maya_tool.hh"

#include "BLI_time.h"
#include "BLI_utildefines.h"

#include "maya_runtime.hh"

namespace blender {

ed::maya::MayaToolActivationResult ED_maya_tool_activate(
    bContext *C,
    const ed::maya::MayaToolID tool_id,
    const ed::maya::MayaToolActivationReason reason)
{
  ed::maya::MayaWindowRuntime *runtime = ed::maya::runtime_ensure(C);
  if (runtime == nullptr) {
    return ed::maya::MayaToolActivationResult::Rejected;
  }
  if (runtime->active_session) {
    return ed::maya::MayaToolActivationResult::BlockedBySession;
  }

  const ed::maya::MayaToolType *next = ED_maya_tool_type_find(tool_id);
  if (next == nullptr || (next->poll != nullptr && !next->poll(C, *runtime))) {
    return ed::maya::MayaToolActivationResult::Rejected;
  }
  if (runtime->tool.active == tool_id) {
    const double activation_start = BLI_time_now_seconds();
    if (next->activate != nullptr) {
      next->activate(C, *runtime);
    }
    runtime->last_tool_activation_time = BLI_time_now_seconds();
    runtime->last_tool_activation_duration_ms =
        (runtime->last_tool_activation_time - activation_start) * 1000.0;
    return ed::maya::MayaToolActivationResult::AlreadyActive;
  }

  const double activation_start = BLI_time_now_seconds();
  const ed::maya::MayaToolType *previous = ED_maya_tool_type_find(runtime->tool.active);
  if (previous != nullptr && previous->deactivate != nullptr) {
    previous->deactivate(C, *runtime);
  }

  runtime->tool.previous = runtime->tool.active;
  runtime->tool.active = tool_id;
  runtime->tool.revision++;
  ed::maya::tool_mirror_sync(C, runtime->tool.active);

  if (next->activate != nullptr) {
    next->activate(C, *runtime);
  }
  runtime->last_tool_activation_time = BLI_time_now_seconds();
  runtime->last_tool_activation_duration_ms =
      (runtime->last_tool_activation_time - activation_start) * 1000.0;

  UNUSED_VARS(reason);
  return ed::maya::MayaToolActivationResult::Activated;
}

}  // namespace blender
