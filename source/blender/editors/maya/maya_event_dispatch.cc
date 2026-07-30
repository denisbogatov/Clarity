/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup editors
 */

#include "maya_event_dispatch.hh"

#include "DNA_screen_types.h"
#include "DNA_space_enums.h"
#include "DNA_userdef_types.h"

#include "BLI_assert.h"
#include "BLI_path_utils.hh"
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

bool ED_maya_gizmo_trace_enabled()
{
  static const bool enabled = BLI_getenv("BLENDER_MAYA_GIZMO_TRACE") != nullptr;
  return enabled;
}

bool ED_maya_interaction_preset_enabled(const bContext *C)
{
  const wmWindowManager *wm = CTX_wm_manager(C);
  const bke::WindowManagerRuntime *wm_runtime = wm != nullptr ? wm->runtime : nullptr;
  return wm_runtime != nullptr && U.interaction_preset == INTERACTION_PRESET_MAYA &&
         wm_runtime->maya_interaction_enabled;
}

bool ED_maya_interaction_enabled(const bContext *C)
{
  const ScrArea *area = CTX_wm_area(C);
  return area != nullptr && area->spacetype == SPACE_VIEW3D &&
         ED_maya_interaction_preset_enabled(C);
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
  if (ed::maya::middle_mouse_axis_drag_handle(C, runtime, action)) {
    return ed::maya::MayaDispatchResult::Handled;
  }

  /* Keep the snap preview under the cursor. The update itself is a no-op unless Edit Pivot owns a
   * manipulator and a snap key is held, and it skips the query while the pointer has not moved, so
   * running it for every action costs nothing measurable. */
  ed::maya::pivot_edit_snap_preview_update(C, runtime, action.mouse_region);

  const ed::maya::MayaDispatchResult pivot_click_result =
      ed::maya::pivot_edit_click_handle_action(C, runtime, action);
  if (pivot_click_result != ed::maya::MayaDispatchResult::PassThrough) {
    return pivot_click_result;
  }

  const ed::maya::MayaDispatchResult selection_result =
      ed::maya::selection_handle_action(C, runtime, action);
  if (selection_result != ed::maya::MayaDispatchResult::PassThrough) {
    ed::maya::pivot_edit_selection_changed(C, runtime);
    return selection_result;
  }

  if (action.id == ed::maya::MayaActionID::EditPivotKeyPressed) {
    /* Edit Pivot is a toggle, like in Maya: one press turns the mode on and it stays on until the
     * key is pressed again. Holding the key is not part of the model, so there is no momentary
     * state that could survive a lost key release. */
    if (action.source_event != nullptr &&
        (action.source_event->flag & WM_EVENT_IS_REPEAT) != 0)
    {
      /* Keeping the key down must not flip the mode over and over. */
      return ed::maya::MayaDispatchResult::Handled;
    }
    return ed::maya::pivot_edit_toggle_persistent(C, runtime) ?
               ed::maya::MayaDispatchResult::Handled :
               ed::maya::MayaDispatchResult::PassThrough;
  }
  if (action.id == ed::maya::MayaActionID::EditPivotKeyReleased) {
    /* Consumed so the release cannot reach a Blender keymap; the toggle already happened. */
    return ed::maya::MayaDispatchResult::Handled;
  }
  if (action.id == ed::maya::MayaActionID::Cancel &&
      runtime.pivot_edit.target != ed::maya::MayaPivotEditTarget::None)
  {
    /* Escape leaves Edit Pivot instead of falling through to unrelated cancel handling. */
    ed::maya::pivot_edit_end(C, runtime);
    return ed::maya::MayaDispatchResult::Handled;
  }
  if (action.id == ed::maya::MayaActionID::TogglePersistentPivot) {
    return ed::maya::pivot_edit_toggle_persistent(C, runtime) ?
               ed::maya::MayaDispatchResult::Handled :
               ed::maya::MayaDispatchResult::PassThrough;
  }
  if (action.id == ed::maya::MayaActionID::FocusLost) {
    ed::maya::pivot_edit_input_reset(C, runtime);
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
    /* Switching tools rebuilds the pivot state for the new tool, but Edit Pivot itself survives:
     * in Maya the mode stays on until it is toggled off. */
    const bool resume_pivot_edit = runtime.pivot_edit.target !=
                                   ed::maya::MayaPivotEditTarget::None;
    ed::maya::pivot_edit_end(C, runtime);
    ED_maya_tool_activate(C, action.tool, ed::maya::MayaToolActivationReason::Hotkey);
    if (resume_pivot_edit) {
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
      if (ED_maya_interaction_preset_enabled(C)) {
        /* The Maya model is still active, the pointer just is not over a 3D View. Only the keys can
         * be wrong here: their release will never be delivered to us, so temporary snapping has to
         * be let go of, while Edit Pivot survives the trip outside the viewport. */
        ED_maya_snap_override_release_all(C);
      }
      else {
        /* Leaving the Maya preset must drop the mode, unlike merely losing window focus. */
        ed::maya::pivot_edit_input_reset(C, *runtime);
        ed::maya::pivot_edit_end(C, *runtime);
      }
    }
    return ed::maya::MayaDispatchResult::PassThrough;
  }
  if (runtime != nullptr && event->type == WINDEACTIVATE) {
    if (runtime->active_session) {
      runtime->active_session->cancel(C);
      runtime->active_session.reset();
    }
    ed::maya::pivot_edit_input_reset(C, *runtime);
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

  /* Validate before translating: events that carry no Maya action (undo, mode switch, deleting the
   * active object from another editor) must still be able to end a temporary Edit Pivot instead of
   * leaving it armed until the next recognized action. */
  ed::maya::pivot_edit_validate(C, *runtime);
  ED_maya_tool_gizmo_state_ensure(C, runtime->tool);

  const std::optional<ed::maya::MayaInputAction> action = ED_maya_input_translate(C, *event);
  if (!action) {
    return ed::maya::MayaDispatchResult::PassThrough;
  }

  return maya_dispatch_idle_action(C, *runtime, *action);
}

}  // namespace blender
