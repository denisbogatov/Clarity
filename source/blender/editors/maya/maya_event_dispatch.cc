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
#include "DNA_vec_types.h"
#include "DNA_workspace_types.h"

#include "BLI_assert.h"
#include "BLI_path_utils.hh"
#include "BLI_time.h"
#include "BLI_utildefines.h"

#include "BKE_context.hh"
#include "BKE_wm_runtime.hh"

#include "WM_api.hh"
#include "WM_toolsystem.hh"
#include "WM_types.hh"
#include "wm_event_types.hh"

#include "UI_interface_c.hh"

#include "maya_input.hh"
#include "maya_marking_menu.hh"
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

static bool maya_viewport_window_interaction_enabled(const bContext *C)
{
  const ARegion *region = CTX_wm_region(C);
  return ED_maya_interaction_enabled(C) && region != nullptr &&
         region->regiontype == RGN_TYPE_WINDOW;
}

static bool maya_active_blender_tool_is(const bContext *C, const char *idname)
{
  const bToolRef *tref = WM_toolsystem_ref_from_context(C);
  return tref != nullptr && STREQ(tref->idname, idname);
}

static bool maya_selection_modifier_cursor_poll(bContext *C)
{
  if (!maya_viewport_window_interaction_enabled(C)) {
    return false;
  }

  const wmWindow *win = CTX_wm_window(C);
  const wmEvent *event_state = win != nullptr ? win->runtime->eventstate : nullptr;
  if (event_state == nullptr || (event_state->modifier & KM_CTRL) == 0 ||
      (event_state->modifier & KM_ALT) != 0)
  {
    return false;
  }

  const ed::maya::MayaWindowRuntime *runtime = ed::maya::runtime_get(C);
  return runtime != nullptr && !runtime->active_session && !runtime->transform_active &&
         runtime->pivot_edit.target == ed::maya::MayaPivotEditTarget::None;
}

static void maya_selection_modifier_cursor_draw(bContext *C,
                                                const int2 &xy,
                                                const float2 & /*tilt*/,
                                                void *customdata)
{
  const wmWindow *win = static_cast<wmWindow *>(customdata);
  if (CTX_wm_window(C) != win || win->runtime->eventstate == nullptr) {
    return;
  }

  const bool is_add = (win->runtime->eventstate->modifier & KM_SHIFT) != 0;
  const float scale = U.scale_factor;
  const float x_min = float(xy.x) + 13.0f * scale;
  const float x_max = float(xy.x) + 22.0f * scale;
  const float x_center = (x_min + x_max) * 0.5f;
  const float y = float(xy.y) - 12.0f * scale;
  const rctf horizontal_outline = {
      x_min - scale, x_max + scale, y - 3.0f * scale, y + 3.0f * scale};
  const rctf horizontal = {x_min, x_max, y - scale, y + scale};
  const rctf vertical_outline = {x_center - 3.0f * scale,
                                 x_center + 3.0f * scale,
                                 y - 5.5f * scale,
                                 y + 5.5f * scale};
  const rctf vertical = {x_center - scale,
                         x_center + scale,
                         y - 4.5f * scale,
                         y + 4.5f * scale};
  const float outline_color[4] = {0.02f, 0.02f, 0.02f, 0.9f};
  const float operation_color[4] = {
      is_add ? 0.2f : 1.0f, is_add ? 0.9f : 0.18f, is_add ? 0.3f : 0.12f, 1.0f};
  ui::draw_roundbox_4fv(&horizontal_outline, true, 0.0f, outline_color);
  if (is_add) {
    ui::draw_roundbox_4fv(&vertical_outline, true, 0.0f, outline_color);
  }
  ui::draw_roundbox_4fv(&horizontal, true, 0.0f, operation_color);
  if (is_add) {
    ui::draw_roundbox_4fv(&vertical, true, 0.0f, operation_color);
  }
}

static void maya_selection_cursor_ensure(bContext *C,
                                         ed::maya::MayaWindowRuntime &runtime,
                                         const wmEvent &event)
{
  bool cursor_created = false;
  if (runtime.selection_cursor == nullptr) {
    wmWindow *win = CTX_wm_window(C);
    if (win == nullptr) {
      return;
    }
    runtime.selection_cursor = WM_paint_cursor_activate(SPACE_VIEW3D,
                                                        RGN_TYPE_WINDOW,
                                                        maya_selection_modifier_cursor_poll,
                                                        maya_selection_modifier_cursor_draw,
                                                        win);
    cursor_created = true;
  }
  if (cursor_created || ISKEYMODIFIER(event.type)) {
    WM_paint_cursor_tag_redraw(CTX_wm_window(C), CTX_wm_region(C));
  }
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

/**
 * Menu a marking-menu action asks for, or null when this fork has none for it yet.
 *
 * Component and selection-conversion menus are gesture-specific. Tool gestures resolve through
 * the active or explicitly held Maya tool so `Q/W/E/R + LMB` and `Ctrl+Shift+RMB` share one path.
 */
static const char *maya_marking_menu_idname(const ed::maya::MayaWindowRuntime &runtime,
                                            const ed::maya::MayaInputAction &action)
{
  if (action.id == ed::maya::MayaActionID::ComponentMarkingMenu) {
    return "VIEW3D_MT_maya_component_marking_menu";
  }
  if (action.id == ed::maya::MayaActionID::SelectionMarkingMenu) {
    return "VIEW3D_MT_maya_selection_marking_menu";
  }
  const ed::maya::MayaToolID tool = action.tool != ed::maya::MayaToolID::None ? action.tool :
                                                                                runtime.tool.active;
  return ed::maya::tool_marking_menu_idname(tool);
}

static ed::maya::MayaDispatchResult maya_marking_menu_open(
    bContext *C,
    ed::maya::MayaWindowRuntime &runtime,
    const ed::maya::MayaInputAction &action)
{
  const char *idname = maya_marking_menu_idname(runtime, action);
  if (idname == nullptr) {
    return ed::maya::MayaDispatchResult::PassThrough;
  }

  /* The menu owns the keyboard until it closes, so a snap key released over it never reaches the
   * dispatcher. Letting the held keys go with the menu is the only state that stays truthful. */
  ED_maya_snap_override_release_all(C);
  runtime.tool.held_hotkey = ed::maya::MayaToolID::None;

  /* Keep Maya's compact dead zone and radius, but draw the menu on the invoking press. Hiding it
   * behind Maya's 0.3 second popup delay made a tap reveal it immediately while a held invocation
   * stayed blank, so the same gesture appeared to work only intermittently. */
  ui::MarkingMenuStyle style;
  style.threshold = 10.0f;
  style.radius = 76.0f;
  style.popup_delay = 0.0f;
  const wmOperatorStatus status = ui::marking_menu_invoke(C, idname, action.source_event, style);
  return (status & OPERATOR_INTERFACE) ? ed::maya::MayaDispatchResult::Handled :
                                        ed::maya::MayaDispatchResult::PassThrough;
}

static ed::maya::MayaDispatchResult maya_dispatch_idle_action(
    bContext *C,
    ed::maya::MayaWindowRuntime &runtime,
    const ed::maya::MayaInputAction &action)
{
  /* A marquee that has ended leaves its result to be constrained. The gesture keeps the left button
   * to itself while it runs, so the first action that arrives here again means it is over. */
  if (action.source_event != nullptr &&
      !(action.source_event->type == LEFTMOUSE && action.source_event->val == KM_PRESS))
  {
    ed::maya::selection_constraint_apply_pending(C, runtime);
  }

  const bool active_tool_owns_pointer = maya_active_blender_tool_is(C, "builtin.knife");
  if (!active_tool_owns_pointer && ed::maya::left_mouse_marquee_drag_handle(C, runtime, action)) {
    return ed::maya::MayaDispatchResult::Handled;
  }
  if (!active_tool_owns_pointer && ed::maya::middle_mouse_axis_drag_handle(C, runtime, action)) {
    return ed::maya::MayaDispatchResult::Handled;
  }

  /* Blender remembers only one ordinary key as `keymodifier`. While `D` is held for Edit Pivot,
   * a later `W` press activates Move but cannot replace `D` there, so its following LMB press has
   * to use the independently tracked Maya tool key. */
  if (action.id == ed::maya::MayaActionID::None &&
      action.pointer_button == ed::maya::MayaPointerButton::Left &&
      action.phase == ed::maya::MayaActionPhase::Begin && !action.shift && !action.ctrl &&
      !action.alt && action.source_event != nullptr && action.source_event->val == KM_PRESS &&
      runtime.tool.held_hotkey != ed::maya::MayaToolID::None)
  {
    ed::maya::MayaInputAction menu_action = action;
    menu_action.id = ed::maya::MayaActionID::ToolMarkingMenu;
    menu_action.tool = runtime.tool.held_hotkey;
    return maya_marking_menu_open(C, runtime, menu_action);
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

  if (!active_tool_owns_pointer) {
    const ed::maya::MayaDispatchResult selection_result =
        ed::maya::selection_handle_action(C, runtime, action);
    if (selection_result != ed::maya::MayaDispatchResult::PassThrough) {
      ed::maya::pivot_edit_selection_changed(C, runtime);
      return selection_result;
    }
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
    runtime.tool.held_hotkey = ed::maya::MayaToolID::None;
    return ed::maya::MayaDispatchResult::PassThrough;
  }
  if (action.id == ed::maya::MayaActionID::TemporarySnap) {
    const wmEvent *event = action.source_event;
    return event != nullptr && ED_maya_snap_key_event_apply(
                                   C, int(event->type), event->val, event->modifier) ?
               ed::maya::MayaDispatchResult::Handled :
               ed::maya::MayaDispatchResult::PassThrough;
  }
  if (action.id == ed::maya::MayaActionID::BlockViewportNavigation) {
    if (maya_active_blender_tool_is(C, "builtin.knife")) {
      return ed::maya::MayaDispatchResult::PassThrough;
    }
    return ed::maya::MayaDispatchResult::Handled;
  }
  if (action.id == ed::maya::MayaActionID::ActivateTool) {
    /* Key repeat is state-preserving input, not a request to rebuild Edit Pivot. A non-repeat press
     * still goes through activation so the Maya tool can neutralize a desynchronized Blender tool. */
    if (action.source_event != nullptr &&
        (action.source_event->flag & WM_EVENT_IS_REPEAT) != 0)
    {
      return ed::maya::MayaDispatchResult::Handled;
    }
    runtime.tool.held_hotkey = action.tool;
    const ed::maya::MayaToolActivationResult result = ED_maya_tool_activate(
        C, action.tool, ed::maya::MayaToolActivationReason::Hotkey);
    /* #MayaToolActivationResult::AlreadyActive still ran the activation callback, which neutralizes
     * the Blender tool and rewrites the gizmo visibility of every 3D View. That leaves the Edit
     * Pivot manipulator needing the same refresh a real tool change needs, and validation cannot
     * stand in for it: re-activating the active tool does not bump #MayaToolState::revision. */
    if (ELEM(result,
             ed::maya::MayaToolActivationResult::Activated,
             ed::maya::MayaToolActivationResult::AlreadyActive) &&
        runtime.pivot_edit.target != ed::maya::MayaPivotEditTarget::None)
    {
      ed::maya::pivot_edit_tool_changed(C, runtime);
    }
    return ed::maya::MayaDispatchResult::Handled;
  }
  if (action.id == ed::maya::MayaActionID::ToolHotkeyReleased) {
    if (runtime.tool.held_hotkey == action.tool) {
      runtime.tool.held_hotkey = ed::maya::MayaToolID::None;
    }
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
        C,
        "MESH_OT_bridge_edge_loops",
        wm::OpCallContext::InvokeDefault,
        nullptr,
        action.source_event);
    return (status & OPERATOR_CANCELLED) ? ed::maya::MayaDispatchResult::PassThrough :
                                          ed::maya::MayaDispatchResult::Handled;
  }
  if (action.id == ed::maya::MayaActionID::Extrude) {
    WM_operator_name_call(C,
                          "MESH_OT_extrude_context_move",
                          wm::OpCallContext::InvokeDefault,
                          nullptr,
                          action.source_event);
    /* `Ctrl+E` belongs exclusively to Extrude. Even a failed poll must not fall through to the
     * Industry Compatible tool-cycle binding or Blender's Edge menu. */
    return ed::maya::MayaDispatchResult::Handled;
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
  if (ELEM(action.id,
           ed::maya::MayaActionID::ComponentMarkingMenu,
           ed::maya::MayaActionID::ToolMarkingMenu,
           ed::maya::MayaActionID::SelectionMarkingMenu))
  {
    return maya_marking_menu_open(C, runtime, action);
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
  if (!maya_viewport_window_interaction_enabled(C)) {
    if (runtime != nullptr) {
      /* This also recovers a session that outlived its own end condition: it is the one place that
       * reliably runs while one is stuck, and leaving it running would starve selection of the left
       * mouse button, which the keymap then turns into `transform.translate` on a drag. */
      if (runtime->active_session) {
        runtime->active_session->cancel(C);
        runtime->active_session.reset();
      }
      if (ED_maya_interaction_preset_enabled(C)) {
        /* The Maya model is still active, the pointer just is not over a viewport window. Only the
         * keys can be wrong here: their release will never be delivered to us, so temporary
         * snapping has to be let go of, while Edit Pivot survives the trip outside the viewport. */
        ED_maya_snap_override_release_all(C);
        runtime->tool.held_hotkey = ed::maya::MayaToolID::None;
      }
      else {
        /* Leaving the Maya preset must drop the mode, unlike merely losing window focus. */
        ed::maya::pivot_edit_input_reset(C, *runtime);
        ed::maya::pivot_edit_end(C, *runtime);
        runtime->tool.held_hotkey = ed::maya::MayaToolID::None;
      }
    }
    return ed::maya::MayaDispatchResult::PassThrough;
  }
  if (runtime != nullptr) {
    maya_selection_cursor_ensure(C, *runtime, *event);
  }
  if (runtime != nullptr && event->type == WINDEACTIVATE) {
    if (runtime->active_session) {
      runtime->active_session->cancel(C);
      runtime->active_session.reset();
    }
    ed::maya::pivot_edit_input_reset(C, *runtime);
    runtime->tool.held_hotkey = ed::maya::MayaToolID::None;
    return ed::maya::MayaDispatchResult::PassThrough;
  }
  if (runtime != nullptr) {
    /* First event after a swallowed release: drop the modes before anything reads them. */
    ed::maya::snap_override_key_state_reconcile(C, *runtime);
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
  maya_selection_cursor_ensure(C, *runtime, *event);

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
