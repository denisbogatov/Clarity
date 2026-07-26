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
#include "BLI_utildefines.h"

#include "BKE_context.hh"
#include "BKE_wm_runtime.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "UI_interface_c.hh"

#include "maya_input.hh"
#include "maya_navigation.hh"
#include "maya_runtime.hh"
#include "maya_session.hh"
#include "maya_session_context.hh"
#include "maya_tool.hh"
#include "maya_tools.hh"

namespace blender {

bool ED_maya_interaction_enabled(const bContext *C)
{
  const ScrArea *area = CTX_wm_area(C);
  const wmWindowManager *wm = CTX_wm_manager(C);
  return area != nullptr && area->spacetype == SPACE_VIEW3D && wm != nullptr &&
         wm->runtime != nullptr && wm->runtime->maya_interaction_enabled;
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
  ed::maya::pivot_edit_validate(C, runtime);

  const ed::maya::MayaDispatchResult selection_result =
      ed::maya::selection_handle_action(C, runtime, action);
  if (selection_result != ed::maya::MayaDispatchResult::PassThrough) {
    return selection_result;
  }

  if (action.id == ed::maya::MayaActionID::EditPivotKeyPressed) {
    return ed::maya::pivot_edit_key_press(C, runtime) ?
               ed::maya::MayaDispatchResult::Handled :
               ed::maya::MayaDispatchResult::PassThrough;
  }
  if (action.id == ed::maya::MayaActionID::EditPivotKeyReleased) {
    return ed::maya::pivot_edit_key_release(C, runtime) ?
               ed::maya::MayaDispatchResult::Handled :
               ed::maya::MayaDispatchResult::PassThrough;
  }
  if (action.id == ed::maya::MayaActionID::TogglePersistentPivot) {
    return ed::maya::pivot_edit_toggle_persistent(C, runtime) ?
               ed::maya::MayaDispatchResult::Handled :
               ed::maya::MayaDispatchResult::PassThrough;
  }
  if (action.id == ed::maya::MayaActionID::FocusLost) {
    ed::maya::pivot_edit_focus_lost(C, runtime);
    return ed::maya::MayaDispatchResult::PassThrough;
  }
  if (ELEM(action.id,
           ed::maya::MayaActionID::TemporaryGridSnap,
           ed::maya::MayaActionID::TemporaryCurveSnap,
           ed::maya::MayaActionID::TemporaryPointSnap,
           ed::maya::MayaActionID::TemporaryStepSnap))
  {
    ed::maya::MayaSnapMode mode = ed::maya::MayaSnapMode::Grid;
    if (action.id == ed::maya::MayaActionID::TemporaryCurveSnap) {
      mode = ed::maya::MayaSnapMode::Curve;
    }
    else if (action.id == ed::maya::MayaActionID::TemporaryPointSnap) {
      mode = ed::maya::MayaSnapMode::Point;
    }
    else if (action.id == ed::maya::MayaActionID::TemporaryStepSnap) {
      mode = action.phase == ed::maya::MayaActionPhase::End || !action.shift ?
                 ed::maya::MayaSnapMode::StepAbsolute :
                 ed::maya::MayaSnapMode::StepRelative;
    }
    return ED_maya_snap_override_set(
               C, mode, action.phase == ed::maya::MayaActionPhase::Begin) ?
               ed::maya::MayaDispatchResult::Handled :
               ed::maya::MayaDispatchResult::PassThrough;
  }
  if (action.id == ed::maya::MayaActionID::BlockViewportNavigation) {
    return ed::maya::MayaDispatchResult::Handled;
  }
  if (action.id == ed::maya::MayaActionID::ActivateTool) {
    const bool resume_temporary_pivot = runtime.physical_input.edit_pivot &&
                                        !runtime.pivot_edit.persistent;
    const bool resume_persistent_pivot = runtime.pivot_edit.persistent;
    ed::maya::pivot_edit_end(C, runtime);
    ED_maya_tool_activate(C, action.tool, ed::maya::MayaToolActivationReason::Hotkey);
    if (resume_temporary_pivot) {
      ed::maya::pivot_edit_key_press(C, runtime);
    }
    else if (resume_persistent_pivot) {
      ed::maya::pivot_edit_resume_persistent(C, runtime);
    }
    return ed::maya::MayaDispatchResult::Handled;
  }
  if (action.id == ed::maya::MayaActionID::ToolHotkeyReleased) {
    return ed::maya::MayaDispatchResult::Handled;
  }
  if (action.id == ed::maya::MayaActionID::FrameSelected) {
    WM_operator_name_call(
        C, "VIEW3D_OT_view_selected", wm::OpCallContext::ExecDefault, nullptr, nullptr);
    return ed::maya::MayaDispatchResult::Handled;
  }
  if (action.id == ed::maya::MayaActionID::Connect) {
    const wmOperatorStatus status = WM_operator_name_call(
        C,
        "MESH_OT_loopcut_slide",
        wm::OpCallContext::InvokeDefault,
        nullptr,
        action.source_event);
    return (status & OPERATOR_CANCELLED) ? ed::maya::MayaDispatchResult::PassThrough :
                                          ed::maya::MayaDispatchResult::Handled;
  }
  if (action.id == ed::maya::MayaActionID::BridgeOrFill) {
    const wmOperatorStatus status = WM_operator_name_call(
        C, "VIEW3D_OT_maya_bridge_or_fill", wm::OpCallContext::ExecDefault, nullptr, nullptr);
    return (status & OPERATOR_CANCELLED) ? ed::maya::MayaDispatchResult::PassThrough :
                                          ed::maya::MayaDispatchResult::Handled;
  }
  if (action.id == ed::maya::MayaActionID::SubdivisionPreviewOff) {
    WM_operator_name_call(C,
                          "VIEW3D_OT_maya_subdivision_preview_off",
                          wm::OpCallContext::ExecDefault,
                          nullptr,
                          nullptr);
    return ed::maya::MayaDispatchResult::Handled;
  }
  if (action.id == ed::maya::MayaActionID::SubdivisionPreviewOn) {
    WM_operator_name_call(C,
                          "VIEW3D_OT_maya_subdivision_preview_on",
                          wm::OpCallContext::ExecDefault,
                          nullptr,
                          nullptr);
    return ed::maya::MayaDispatchResult::Handled;
  }
  if (action.id == ed::maya::MayaActionID::SubdivisionPreviewSurface) {
    WM_operator_name_call(C,
                          "VIEW3D_OT_maya_subdivision_preview_surface",
                          wm::OpCallContext::ExecDefault,
                          nullptr,
                          nullptr);
    return ed::maya::MayaDispatchResult::Handled;
  }
  if (action.id == ed::maya::MayaActionID::ObjectXRay) {
    WM_operator_name_call(
        C, "VIEW3D_OT_maya_object_xray", wm::OpCallContext::ExecDefault, nullptr, nullptr);
    return ed::maya::MayaDispatchResult::Handled;
  }
  if (action.id == ed::maya::MayaActionID::FaceCenters) {
    WM_operator_name_call(
        C, "VIEW3D_OT_maya_face_centers_toggle", wm::OpCallContext::ExecDefault, nullptr, nullptr);
    return ed::maya::MayaDispatchResult::Handled;
  }
  if (action.id == ed::maya::MayaActionID::WireframeOnShaded) {
    WM_operator_name_call(C,
                          "VIEW3D_OT_maya_wireframe_on_shaded_toggle",
                          wm::OpCallContext::ExecDefault,
                          nullptr,
                          nullptr);
    return ed::maya::MayaDispatchResult::Handled;
  }
  if (action.id == ed::maya::MayaActionID::ComponentMarkingMenu) {
    constexpr float maya_component_menu_threshold = 32.0f;
    const wmOperatorStatus status = ui::pie_menu_invoke_with_threshold(
        C,
        "VIEW3D_MT_maya_component_marking_menu",
        action.source_event,
        maya_component_menu_threshold);
    return (status & OPERATOR_INTERFACE) ? ed::maya::MayaDispatchResult::Handled :
                                          ed::maya::MayaDispatchResult::PassThrough;
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
  if (!ED_maya_interaction_enabled(C)) {
    if (runtime != nullptr) {
      if (runtime->active_session) {
        runtime->active_session->cancel(C);
        runtime->active_session.reset();
      }
      ed::maya::pivot_edit_focus_lost(C, *runtime);
    }
    return ed::maya::MayaDispatchResult::PassThrough;
  }
  if (runtime != nullptr && event->type == WINDEACTIVATE) {
    if (runtime->active_session) {
      runtime->active_session->cancel(C);
      runtime->active_session.reset();
    }
    ed::maya::pivot_edit_focus_lost(C, *runtime);
    return ed::maya::MayaDispatchResult::PassThrough;
  }
  if (runtime != nullptr && runtime->active_session) {
    const std::optional<ed::maya::MayaInputAction> action = ED_maya_input_translate(C, *event);
    if (action && action->id == ed::maya::MayaActionID::ActivateTool &&
        action->phase == ed::maya::MayaActionPhase::Begin)
    {
      runtime->active_session->cancel(C);
      runtime->active_session.reset();
      return maya_dispatch_idle_action(C, *runtime, *action);
    }
    if (!action) {
      return runtime->active_session->blocks_blender_events() ?
                 ed::maya::MayaDispatchResult::Handled :
                 ed::maya::MayaDispatchResult::PassThrough;
    }
    return maya_dispatch_to_active_session(C, *runtime, *action);
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
