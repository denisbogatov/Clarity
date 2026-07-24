/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup editors
 */

#include "maya_event_dispatch.hh"

#include "DNA_screen_types.h"
#include "DNA_space_enums.h"

#include "BLI_assert.h"
#include "BLI_time.h"

#include "BKE_context.hh"

#include "ED_view3d_navigation.hh"

#include "maya_input.hh"
#include "maya_navigation.hh"
#include "maya_runtime.hh"
#include "maya_session.hh"
#include "maya_session_context.hh"
#include "maya_tool.hh"

namespace blender {

bool ED_maya_interaction_enabled(const bContext *C)
{
  const ScrArea *area = CTX_wm_area(C);
  return area != nullptr && area->spacetype == SPACE_VIEW3D;
}

static ed::maya::MayaDispatchResult maya_dispatch_to_active_session(
    bContext *C,
    ed::maya::MayaWindowRuntime &runtime,
    const ed::maya::MayaInputAction &action)
{
  ed::maya::MayaInteractionSession &session = *runtime.active_session;
  const bool context_is_valid =
      action.id == ed::maya::MayaActionID::PointerMove ?
          ED_maya_session_context_matches_context(C, session.context()) :
          ED_maya_session_context_is_valid(C, session.context());
  if (!context_is_valid) {
    session.cancel(C);
    runtime.active_session.reset();
    return ed::maya::MayaDispatchResult::PassThrough;
  }

  switch (session.handle_event(C, action)) {
    case ed::maya::MayaSessionResult::Running:
      return ed::maya::MayaDispatchResult::Handled;
    case ed::maya::MayaSessionResult::Finished:
    case ed::maya::MayaSessionResult::Cancelled:
      runtime.active_session.reset();
      return ed::maya::MayaDispatchResult::Handled;
    case ed::maya::MayaSessionResult::PassThrough:
      return session.blocks_blender_events() ? ed::maya::MayaDispatchResult::Handled :
                                              ed::maya::MayaDispatchResult::PassThrough;
  }

  BLI_assert_unreachable();
  return ed::maya::MayaDispatchResult::PassThrough;
}

static ed::maya::MayaDispatchResult maya_dispatch_idle_action(
    bContext *C,
    ed::maya::MayaWindowRuntime &runtime,
    const ed::maya::MayaInputAction &action)
{
  if (action.id == ed::maya::MayaActionID::BlockViewportNavigation) {
    return ed::maya::MayaDispatchResult::Handled;
  }
  if (action.id == ed::maya::MayaActionID::ActivateTool) {
    ED_maya_tool_activate(
        C, action.tool, ed::maya::MayaToolActivationReason::Hotkey);
    return ed::maya::MayaDispatchResult::Handled;
  }
  if (action.id == ed::maya::MayaActionID::ToolHotkeyReleased) {
    return ed::maya::MayaDispatchResult::Handled;
  }
  if (action.id == ed::maya::MayaActionID::FrameSelected) {
    ed::view3d::navigation_frame_selected(C, false, 0);
    return ed::maya::MayaDispatchResult::Handled;
  }

  std::optional<ed::maya::MayaNavigationMode> navigation_mode;
  switch (action.id) {
    case ed::maya::MayaActionID::BeginOrbit:
      navigation_mode = ed::maya::MayaNavigationMode::Orbit;
      break;
    case ed::maya::MayaActionID::BeginPan:
      navigation_mode = ed::maya::MayaNavigationMode::Pan;
      break;
    case ed::maya::MayaActionID::BeginDolly:
      navigation_mode = ed::maya::MayaNavigationMode::Dolly;
      break;
    default:
      break;
  }

  if (navigation_mode) {
    runtime.navigation_settings.debug_logging =
        ed::maya::navigation_debug_logging_enabled(C);
    runtime.navigation_settings.frame_rate_limit =
        ed::maya::navigation_frame_rate_limit_setting(C);
    runtime.navigation_settings.tool_activation_age_ms =
        runtime.last_tool_activation_time > 0.0 ?
            (BLI_time_now_seconds() - runtime.last_tool_activation_time) * 1000.0 :
            -1.0;
    runtime.navigation_settings.tool_activation_duration_ms =
        runtime.last_tool_activation_duration_ms;
    runtime.active_session = ed::maya::MayaNavigationSession::begin(
        C, *navigation_mode, action, runtime.navigation_settings);
    return runtime.active_session ? ed::maya::MayaDispatchResult::Handled :
                                    ed::maya::MayaDispatchResult::PassThrough;
  }

  if (action.id == ed::maya::MayaActionID::DebugDrag &&
      action.phase == ed::maya::MayaActionPhase::Begin)
  {
    runtime.active_session = std::make_unique<ed::maya::MayaDebugDragSession>(
        ED_maya_session_context_from_context(C), action.mouse);
    return ed::maya::MayaDispatchResult::Handled;
  }

  return ed::maya::MayaDispatchResult::PassThrough;
}

ed::maya::MayaDispatchResult ED_maya_event_dispatch(bContext *C, const wmEvent *event)
{
  if (event == nullptr) {
    return ed::maya::MayaDispatchResult::PassThrough;
  }

  ed::maya::MayaWindowRuntime *runtime = ed::maya::runtime_get(C);
  if (runtime != nullptr && runtime->active_session) {
    const std::optional<ed::maya::MayaInputAction> action = ED_maya_input_translate(C, *event);
    if (!action) {
      return runtime->active_session->blocks_blender_events() ?
                 ed::maya::MayaDispatchResult::Handled :
                 ed::maya::MayaDispatchResult::PassThrough;
    }
    return maya_dispatch_to_active_session(C, *runtime, *action);
  }

  if (!ED_maya_interaction_enabled(C)) {
    return ed::maya::MayaDispatchResult::PassThrough;
  }

  runtime = ed::maya::runtime_ensure(C);
  if (runtime == nullptr) {
    return ed::maya::MayaDispatchResult::PassThrough;
  }

  const std::optional<ed::maya::MayaInputAction> action = ED_maya_input_translate(C, *event);
  if (!action) {
    return ed::maya::MayaDispatchResult::PassThrough;
  }

  return maya_dispatch_idle_action(C, *runtime, *action);
}

}  // namespace blender
