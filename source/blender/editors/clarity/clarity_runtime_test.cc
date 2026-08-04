/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

#include "testing/testing.h"

#include <utility>

#include "BKE_context.hh"
#include "BKE_gtest_base.hh"
#include "BKE_lib_id.hh"
#include "BKE_main.hh"
#include "BKE_object.hh"
#include "BKE_object_transform_clarity.hh"
#include "BKE_scene.hh"

#include "ED_clarity.hh"

#include "WM_types.hh"
#include "wm_event_types.hh"

#include "clarity_input.hh"
#include "clarity_marking_menu.hh"
#include "clarity_runtime.hh"
#include "clarity_tools.hh"

namespace blender::ed::clarity::tests {

/**
 * Allocating an ID needs the ID type table, so every test in this file runs on the shared Blender
 * fixture. Without it #BKE_object_add_only_object asserts in #BKE_libblock_alloc_notest and takes
 * the whole test binary down with it.
 */
class ClarityRuntimeTest : public bke::BlenderGTestBase {};

/** Momentary snap keys: the state machine behind temporary snapping getting stuck. */
TEST(clarity_snap_override, HeldKeysStackAndTheLastOneWins)
{
  ClaritySnapOverride snap;
  EXPECT_TRUE(snap.is_empty());
  EXPECT_EQ(snap.active(), ClaritySnapMode::None);

  EXPECT_TRUE(snap.press(EVT_VKEY, ClaritySnapMode::Point));
  EXPECT_EQ(snap.active(), ClaritySnapMode::Point);
  EXPECT_TRUE(snap.press(EVT_XKEY, ClaritySnapMode::Grid));
  EXPECT_EQ(snap.active(), ClaritySnapMode::Grid);

  /* Releasing the newer key falls back to the one still held, it does not clear everything. */
  EXPECT_TRUE(snap.release(EVT_XKEY));
  EXPECT_EQ(snap.active(), ClaritySnapMode::Point);
  EXPECT_TRUE(snap.release(EVT_VKEY));
  EXPECT_TRUE(snap.is_empty());
}

/** Key repeats used to stack a second copy, so one release could not end the mode. */
TEST(clarity_snap_override, RepeatedPressDoesNotStackAndOneReleaseEndsIt)
{
  ClaritySnapOverride snap;
  EXPECT_TRUE(snap.press(EVT_VKEY, ClaritySnapMode::Point));
  EXPECT_FALSE(snap.press(EVT_VKEY, ClaritySnapMode::Point));
  EXPECT_FALSE(snap.press(EVT_VKEY, ClaritySnapMode::Point));
  EXPECT_EQ(snap.held_num(), 1);

  EXPECT_TRUE(snap.release(EVT_VKEY));
  EXPECT_TRUE(snap.is_empty());
  EXPECT_EQ(snap.active(), ClaritySnapMode::None);
}

/** A release for a key that is not held must change nothing at all. */
TEST(clarity_snap_override, StrayReleaseLeavesTheHeldKeysAlone)
{
  ClaritySnapOverride snap;
  EXPECT_TRUE(snap.press(EVT_CKEY, ClaritySnapMode::Curve));

  EXPECT_FALSE(snap.release(EVT_VKEY));
  EXPECT_EQ(snap.active(), ClaritySnapMode::Curve);
  EXPECT_EQ(snap.held_num(), 1);
}

/** A key holds one mode: repeats never stack and one release frees it. */
TEST(clarity_snap_override, StepKeyHoldsOneModeOnly)
{
  ClaritySnapOverride snap;
  EXPECT_TRUE(snap.press(EVT_JKEY, ClaritySnapMode::Step));
  EXPECT_FALSE(snap.press(EVT_JKEY, ClaritySnapMode::Step));
  EXPECT_EQ(snap.held_num(), 1);
  EXPECT_EQ(snap.active(), ClaritySnapMode::Step);

  /* The release names the key, not the mode it engaged. */
  EXPECT_TRUE(snap.release(EVT_JKEY));
  EXPECT_TRUE(snap.is_empty());
}

/**
 * A fresh press of a key that is still listed means its release was lost: the press is the newer
 * truth, so it replaces the stale entry instead of stacking behind it.
 */
TEST(clarity_snap_override, PressOfAHeldKeyWithAnotherModeRebuildsIt)
{
  ClaritySnapOverride snap;
  EXPECT_TRUE(snap.press(EVT_VKEY, ClaritySnapMode::Point));
  EXPECT_TRUE(snap.press(EVT_VKEY, ClaritySnapMode::Grid));
  EXPECT_EQ(snap.held_num(), 1);
  EXPECT_EQ(snap.active(), ClaritySnapMode::Grid);
  EXPECT_TRUE(snap.release(EVT_VKEY));
  EXPECT_TRUE(snap.is_empty());
}

/**
 * The escape hatch for a release the dispatcher never saw: only the key the window reports as held
 * can be proven gone, so an overlapping second key keeps its mode.
 */
TEST(clarity_snap_override, OnlyWindowTrackedKeysAreReleasedByReconcile)
{
  ClaritySnapOverride snap;
  EXPECT_FALSE(snap.release_window_tracked_keys());

  EXPECT_TRUE(snap.press(EVT_VKEY, ClaritySnapMode::Point, true));
  EXPECT_TRUE(snap.press(EVT_XKEY, ClaritySnapMode::Grid, false));
  EXPECT_TRUE(snap.release_window_tracked_keys());
  EXPECT_EQ(snap.held_num(), 1);
  EXPECT_EQ(snap.active(), ClaritySnapMode::Grid);
  EXPECT_FALSE(snap.release_window_tracked_keys());
}

/**
 * Clarity's documented tolerance: on, the target has to be inside the region around the pointer; off,
 * "the snap region is unlimited; you can snap to anything viewable".
 */
TEST(clarity_snap_tolerance, LimitedToleranceScalesWithTheInterfaceAndOffMeansTheWholeRegion)
{
  ClaritySnapToleranceSettings settings;
  settings.limited = true;
  settings.size_px = 10;
  EXPECT_FLOAT_EQ(snap_tolerance_radius_px(settings, 1200, 1.0f), 10.0f);
  EXPECT_FLOAT_EQ(snap_tolerance_radius_px(settings, 1200, 2.0f), 20.0f);

  settings.limited = false;
  EXPECT_FLOAT_EQ(snap_tolerance_radius_px(settings, 1200, 2.0f), 1200.0f);

  /* Degenerate input must never disable snapping by asking for a zero radius. */
  settings.limited = true;
  settings.size_px = 0;
  EXPECT_FLOAT_EQ(snap_tolerance_radius_px(settings, 0, 0.0f), 1.0f);
  settings.limited = false;
  EXPECT_FLOAT_EQ(snap_tolerance_radius_px(settings, 0, 1.0f), 1.0f);
}

TEST(clarity_selection, CameraBasedSelectionDefaultsToAutomatic)
{
  const ClaritySelectionSettings settings;
  EXPECT_EQ(settings.camera_based_selection, ClarityCameraBasedSelection::Auto);

  EXPECT_TRUE(camera_based_selection_use_depth(ClarityCameraBasedSelection::Auto, true, false));
  EXPECT_FALSE(camera_based_selection_use_depth(ClarityCameraBasedSelection::Auto, true, true));
  EXPECT_FALSE(camera_based_selection_use_depth(ClarityCameraBasedSelection::Auto, false, false));
  EXPECT_FALSE(camera_based_selection_use_depth(ClarityCameraBasedSelection::Off, true, false));
  EXPECT_TRUE(camera_based_selection_use_depth(ClarityCameraBasedSelection::On, false, false));
  EXPECT_FALSE(camera_based_selection_use_depth(ClarityCameraBasedSelection::On, true, true));
}

/**
 * Base topological set operations derived from modifiers. The dispatcher reserves the
 * `Ctrl+Shift+LMB` click chord for the additive marquee before topology selection reaches this
 * table, but keeping the mapping total makes its lower-level rule explicit.
 */
TEST(clarity_topology_select, ModifiersPickTheSetOperation)
{
  ClarityInputAction action;

  EXPECT_EQ(topology_select_op_from_action(action), ClarityTopologySelectOp::Replace);

  action.shift = true;
  EXPECT_EQ(topology_select_op_from_action(action), ClarityTopologySelectOp::Toggle);

  action.shift = false;
  action.ctrl = true;
  EXPECT_EQ(topology_select_op_from_action(action), ClarityTopologySelectOp::Subtract);

  action.shift = true;
  EXPECT_EQ(topology_select_op_from_action(action), ClarityTopologySelectOp::Add);

  /* `Alt` belongs to viewport navigation, so it never reaches this table; if it does, it changes
   * nothing about the operation. */
  action.alt = true;
  EXPECT_EQ(topology_select_op_from_action(action), ClarityTopologySelectOp::Add);
}

/** The key table is the only place that decides which key holds which mode. */
TEST(clarity_snap_keys, ReleaseResolvesWhateverModifiersCameWithIt)
{
  EXPECT_EQ(snap_key_event_mode_get(EVT_VKEY, KM_PRESS, 0), ClaritySnapMode::Point);
  EXPECT_EQ(snap_key_event_mode_get(EVT_XKEY, KM_PRESS, 0), ClaritySnapMode::Grid);
  EXPECT_EQ(snap_key_event_mode_get(EVT_CKEY, KM_PRESS, 0), ClaritySnapMode::Curve);

  /* Whether the steps are relative or absolute is a setting, not a second binding of the key, so
   * `Shift` stays available to the drag `J` is held during. */
  EXPECT_EQ(snap_key_event_mode_get(EVT_JKEY, KM_PRESS, 0), ClaritySnapMode::Step);
  EXPECT_EQ(snap_key_event_mode_get(EVT_JKEY, KM_PRESS, KM_SHIFT), ClaritySnapMode::Step);

  /* A press must not steal a binding that belongs to a modifier combination. */
  EXPECT_EQ(snap_key_event_mode_get(EVT_VKEY, KM_PRESS, KM_CTRL), ClaritySnapMode::None);
  EXPECT_EQ(snap_key_event_mode_get(EVT_XKEY, KM_PRESS, KM_SHIFT), ClaritySnapMode::None);
  EXPECT_EQ(snap_key_event_mode_get(EVT_JKEY, KM_PRESS, KM_ALT), ClaritySnapMode::None);

  /* The release is the only way out of the mode, so no modifier may swallow it. */
  EXPECT_EQ(snap_key_event_mode_get(EVT_JKEY, KM_RELEASE, KM_ALT), ClaritySnapMode::Step);
  EXPECT_EQ(snap_key_event_mode_get(EVT_JKEY, KM_RELEASE, uint8_t(KM_CTRL | KM_SHIFT)),
            ClaritySnapMode::Step);
  EXPECT_EQ(snap_key_event_mode_get(EVT_VKEY, KM_RELEASE, uint8_t(KM_CTRL | KM_ALT)),
            ClaritySnapMode::Point);

  EXPECT_EQ(snap_key_event_mode_get(EVT_ZKEY, KM_PRESS, 0), ClaritySnapMode::None);
  EXPECT_EQ(snap_key_event_mode_get(EVT_VKEY, KM_DBL_CLICK, 0), ClaritySnapMode::None);
}

TEST(clarity_input, CtrlEMapsExclusivelyToExtrude)
{
  wmEvent event{};
  event.type = EVT_EKEY;
  event.val = KM_PRESS;
  event.modifier = KM_CTRL;

  std::optional<ClarityInputAction> action = ED_clarity_input_translate(nullptr, event);
  ASSERT_TRUE(action.has_value());
  EXPECT_EQ(action->id, ClarityActionID::Extrude);

  event.modifier = wmEventModifierFlag(KM_CTRL | KM_SHIFT);
  action = ED_clarity_input_translate(nullptr, event);
  ASSERT_TRUE(action.has_value());
  EXPECT_EQ(action->id, ClarityActionID::None);

  event.modifier = KM_CTRL;
  event.val = KM_RELEASE;
  action = ED_clarity_input_translate(nullptr, event);
  ASSERT_TRUE(action.has_value());
  EXPECT_EQ(action->id, ClarityActionID::ToolHotkeyReleased);
}

TEST(clarity_input, MarkingMenuGesturesMapToTheirOwnActions)
{
  wmEvent event{};
  event.type = RIGHTMOUSE;
  event.val = KM_PRESS;

  std::optional<ClarityInputAction> action = ED_clarity_input_translate(nullptr, event);
  ASSERT_TRUE(action.has_value());
  EXPECT_EQ(action->id, ClarityActionID::ComponentMarkingMenu);

  event.modifier = KM_CTRL;
  action = ED_clarity_input_translate(nullptr, event);
  ASSERT_TRUE(action.has_value());
  EXPECT_EQ(action->id, ClarityActionID::SelectionMarkingMenu);

  event.modifier = wmEventModifierFlag(KM_CTRL | KM_SHIFT);
  action = ED_clarity_input_translate(nullptr, event);
  ASSERT_TRUE(action.has_value());
  EXPECT_EQ(action->id, ClarityActionID::ToolMarkingMenu);
  EXPECT_EQ(action->tool, ClarityToolID::None);

  wmEvent tool_press_under_edit_pivot{};
  tool_press_under_edit_pivot.type = EVT_WKEY;
  tool_press_under_edit_pivot.val = KM_PRESS;
  tool_press_under_edit_pivot.keymodifier = EVT_DKEY;
  action = ED_clarity_input_translate(nullptr, tool_press_under_edit_pivot);
  ASSERT_TRUE(action.has_value());
  EXPECT_EQ(action->id, ClarityActionID::ActivateTool);
  EXPECT_EQ(action->tool, ClarityToolID::Move);

  event.type = LEFTMOUSE;
  event.modifier = wmEventModifierFlag(0);
  const std::pair<wmEventType, ClarityToolID> tool_gestures[] = {
      {EVT_QKEY, ClarityToolID::Select},
      {EVT_WKEY, ClarityToolID::Move},
      {EVT_EKEY, ClarityToolID::Rotate},
      {EVT_RKEY, ClarityToolID::Scale},
  };
  for (const auto &[keymodifier, expected_tool] : tool_gestures) {
    event.keymodifier = keymodifier;
    action = ED_clarity_input_translate(nullptr, event);
    ASSERT_TRUE(action.has_value());
    EXPECT_EQ(action->id, ClarityActionID::ToolMarkingMenu);
    EXPECT_EQ(action->tool, expected_tool);
  }

  EXPECT_STREQ(tool_marking_menu_idname(ClarityToolID::Select),
               "VIEW3D_MT_clarity_select_marking_menu");
  EXPECT_STREQ(tool_marking_menu_idname(ClarityToolID::Move),
               "VIEW3D_MT_clarity_move_marking_menu");
  EXPECT_STREQ(tool_marking_menu_idname(ClarityToolID::Rotate),
               "VIEW3D_MT_clarity_rotate_marking_menu");
  EXPECT_STREQ(tool_marking_menu_idname(ClarityToolID::Scale),
               "VIEW3D_MT_clarity_scale_marking_menu");
  EXPECT_STREQ(tool_marking_menu_idname(ClarityToolID::MultiCut),
               "VIEW3D_MT_clarity_multi_cut_marking_menu");
  EXPECT_EQ(tool_marking_menu_idname(ClarityToolID::None), nullptr);
}

TEST_F(ClarityRuntimeTest, TransformMarkingMenusKeepOrientationsIndependent)
{
  Main *bmain = BKE_main_new();
  Scene *scene = BKE_scene_add(bmain, "ClarityMarkingMenuScene");
  bContext *context = CTX_create();
  CTX_data_main_set(context, bmain);
  CTX_data_scene_set(context, scene);

  EXPECT_TRUE(
      transform_orientation_set(context, ClarityToolID::Move, ClarityMoveOrientation::Object));
  EXPECT_TRUE(
      transform_orientation_set(context, ClarityToolID::Rotate, ClarityMoveOrientation::Component));
  EXPECT_TRUE(
      transform_orientation_set(context, ClarityToolID::Scale, ClarityMoveOrientation::World));

  EXPECT_EQ(transform_orientation_get(context, ClarityToolID::Move), ClarityMoveOrientation::Object);
  EXPECT_EQ(transform_orientation_get(context, ClarityToolID::Rotate),
            ClarityMoveOrientation::Component);
  EXPECT_EQ(transform_orientation_get(context, ClarityToolID::Scale), ClarityMoveOrientation::World);

  EXPECT_TRUE(
      transform_orientation_set(context, ClarityToolID::Rotate, ClarityMoveOrientation::Gimbal));
  EXPECT_EQ(transform_orientation_get(context, ClarityToolID::Move), ClarityMoveOrientation::Object);
  EXPECT_EQ(transform_orientation_get(context, ClarityToolID::Rotate), ClarityMoveOrientation::Gimbal);
  EXPECT_FALSE(
      transform_orientation_set(context, ClarityToolID::Select, ClarityMoveOrientation::Component));
  EXPECT_FALSE(
      transform_orientation_set(context, ClarityToolID::Scale, ClarityMoveOrientation::Gimbal));

  CTX_free(context);
  BKE_main_free(bmain);
}

/**
 * The escape hatch for a release that can never arrive: the pointer left the 3D View, a popup
 * swallowed the event, the interaction preset changed under the held key.
 */
TEST(clarity_snap_override, ClearReleasesEverythingAndReportsWhetherItHadTo)
{
  ClaritySnapOverride snap;
  EXPECT_FALSE(snap.clear());

  EXPECT_TRUE(snap.press(EVT_VKEY, ClaritySnapMode::Point));
  EXPECT_TRUE(snap.press(EVT_XKEY, ClaritySnapMode::Grid));
  EXPECT_TRUE(snap.clear());
  EXPECT_TRUE(snap.is_empty());
  EXPECT_EQ(snap.active(), ClaritySnapMode::None);
  EXPECT_FALSE(snap.clear());
}

TEST_F(ClarityRuntimeTest, ObjectRuntimeReferenceRejectsDeletedOrReusedObject)
{
  Main *bmain = BKE_main_new();
  Object *object = BKE_object_add_only_object(bmain, OB_EMPTY, "PivotSubject");
  const ClarityObjectRuntimeRef reference = ED_clarity_object_runtime_ref_create(*object);
  EXPECT_EQ(ED_clarity_object_runtime_ref_resolve(*bmain, reference), object);

  BKE_id_delete(bmain, object);
  EXPECT_EQ(ED_clarity_object_runtime_ref_resolve(*bmain, reference), nullptr);

  Object *replacement = BKE_object_add_only_object(bmain, OB_EMPTY, "PivotSubject");
  EXPECT_NE(replacement->id.session_uid, reference.session_uid);
  EXPECT_EQ(ED_clarity_object_runtime_ref_resolve(*bmain, reference), nullptr);
  BKE_main_free(bmain);
}

TEST_F(ClarityRuntimeTest, TransformTransactionRestoresObjectsAndRuntime)
{
  Main *bmain = BKE_main_new();
  Object *root = BKE_object_add_only_object(bmain, OB_EMPTY, "Root");
  Object *child_a = BKE_object_add_only_object(bmain, OB_EMPTY, "ChildA");
  Object *child_b = BKE_object_add_only_object(bmain, OB_EMPTY, "ChildB");
  root->transform_model = OBJECT_TRANSFORM_CLARITY;
  child_a->transform_model = OBJECT_TRANSFORM_CLARITY;
  child_b->transform_model = OBJECT_TRANSFORM_CLARITY;
  BKE_object_clarity_transform_ensure(root)->translation[0] = 1.0;
  BKE_object_clarity_transform_ensure(child_a)->translation[1] = 2.0;
  BKE_object_clarity_transform_ensure(child_b)->translation[2] = 3.0;

  ClarityManipulatorPivotState runtime_state;
  runtime_state.position_world = double3(4.0, 5.0, 6.0);
  runtime_state.position_valid = true;
  const ClarityManipulatorPivotState runtime_before = runtime_state;

  {
    ClarityTransformTransaction transaction(nullptr, nullptr);
    ASSERT_TRUE(transaction.capture_object(*root));
    ASSERT_TRUE(transaction.capture_child(*child_a));
    ASSERT_TRUE(transaction.capture_child(*child_b));
    ASSERT_TRUE(transaction.capture_runtime(runtime_state));
    root->clarity_transform->translation[0] = 10.0;
    child_a->clarity_transform->translation[1] = 20.0;
    child_b->clarity_transform->translation[2] = 30.0;
    runtime_state.position_world = double3(-1.0, -2.0, -3.0);
    runtime_state.position_valid = false;
    transaction.rollback();
  }

  EXPECT_DOUBLE_EQ(root->clarity_transform->translation[0], 1.0);
  EXPECT_DOUBLE_EQ(child_a->clarity_transform->translation[1], 2.0);
  EXPECT_DOUBLE_EQ(child_b->clarity_transform->translation[2], 3.0);
  EXPECT_EQ(runtime_state.position_world, runtime_before.position_world);
  EXPECT_EQ(runtime_state.position_valid, runtime_before.position_valid);
  BKE_main_free(bmain);
}

TEST_F(ClarityRuntimeTest, PivotEditTogglePersistsWithoutHostContext)
{
  bContext *C = CTX_create();
  ClarityWindowRuntime runtime;

  EXPECT_FALSE(runtime.pivot_edit.persistent);
  EXPECT_EQ(runtime.pivot_edit.phase, ClarityPivotEditPhase::Normal);

  EXPECT_TRUE(pivot_edit_toggle_persistent(C, runtime));
  EXPECT_TRUE(runtime.pivot_edit.persistent);
  EXPECT_EQ(runtime.pivot_edit.phase, ClarityPivotEditPhase::PersistentPivot);
  EXPECT_EQ(runtime.pivot_edit.target, ClarityPivotEditTarget::None);

  EXPECT_TRUE(pivot_edit_toggle_persistent(C, runtime));
  EXPECT_FALSE(runtime.pivot_edit.persistent);
  EXPECT_EQ(runtime.pivot_edit.phase, ClarityPivotEditPhase::Normal);
  EXPECT_EQ(runtime.pivot_edit.target, ClarityPivotEditTarget::None);

  CTX_free(C);
}

TEST(clarity_pivot_edit, ToolChangePreservesTheActiveTarget)
{
  ClarityWindowRuntime runtime;
  runtime.pivot_edit.persistent = true;
  runtime.pivot_edit.target = ClarityPivotEditTarget::ObjectOrigin;
  runtime.pivot_edit.phase = ClarityPivotEditPhase::PersistentPivot;
  runtime.tool.active = ClarityToolID::Rotate;
  runtime.tool.revision = 17;

  pivot_edit_tool_changed(nullptr, runtime);

  EXPECT_TRUE(runtime.pivot_edit.persistent);
  EXPECT_EQ(runtime.pivot_edit.target, ClarityPivotEditTarget::ObjectOrigin);
  EXPECT_EQ(runtime.pivot_edit.phase, ClarityPivotEditPhase::PersistentPivot);
  EXPECT_EQ(runtime.pivot_edit.tool, ClarityToolID::Rotate);
  EXPECT_EQ(runtime.pivot_edit.tool_revision, 17);
}

TEST_F(ClarityRuntimeTest, PivotEditDragTailDefersExitOrFocusRestart)
{
  bContext *C = CTX_create();

  ClarityWindowRuntime exit_runtime;
  exit_runtime.transform_active = true;
  exit_runtime.pivot_edit.persistent = true;
  exit_runtime.pivot_edit.target = ClarityPivotEditTarget::ObjectOrigin;
  exit_runtime.pivot_edit.phase = ClarityPivotEditPhase::PivotDragging;

  EXPECT_TRUE(pivot_edit_toggle_persistent(C, exit_runtime));
  EXPECT_FALSE(exit_runtime.pivot_edit.persistent);
  EXPECT_TRUE(exit_runtime.pivot_edit.exit_after_drag);
  EXPECT_FALSE(exit_runtime.pivot_edit.restart_after_drag);
  EXPECT_EQ(exit_runtime.pivot_edit.phase, ClarityPivotEditPhase::PivotCommitPending);
  EXPECT_EQ(exit_runtime.pivot_edit.target, ClarityPivotEditTarget::ObjectOrigin);

  ClarityWindowRuntime focus_runtime;
  focus_runtime.pivot_edit.persistent = true;
  focus_runtime.pivot_edit.target = ClarityPivotEditTarget::ObjectOrigin;
  focus_runtime.pivot_edit.phase = ClarityPivotEditPhase::PersistentPivot;

  pivot_edit_input_reset(C, focus_runtime);
  EXPECT_TRUE(focus_runtime.pivot_edit.persistent);
  EXPECT_FALSE(focus_runtime.pivot_edit.exit_after_drag);
  EXPECT_FALSE(focus_runtime.pivot_edit.restart_after_drag);
  EXPECT_EQ(focus_runtime.pivot_edit.phase, ClarityPivotEditPhase::PersistentPivot);
  EXPECT_EQ(focus_runtime.pivot_edit.target, ClarityPivotEditTarget::ObjectOrigin);

  ClarityWindowRuntime restart_runtime;
  restart_runtime.transform_active = true;
  restart_runtime.pivot_edit.persistent = true;
  restart_runtime.pivot_edit.target = ClarityPivotEditTarget::ObjectOrigin;
  restart_runtime.pivot_edit.phase = ClarityPivotEditPhase::PivotDragging;
  restart_runtime.temporary.snap.press(EVT_VKEY, ClaritySnapMode::Point);
  restart_runtime.pivot_edit.snap_preview.type = ClarityPivotSnapTargetType::Vertex;
  restart_runtime.pivot_edit.snap_preview.object_to_world = float4x4::identity();
  restart_runtime.pivot_edit.snap_preview.component_index = 7;
  restart_runtime.pivot_edit.snap_preview_mouse = int2(12, 34);
  restart_runtime.pivot_edit.snap_preview_queried = true;

  pivot_edit_input_reset(C, restart_runtime);
  EXPECT_TRUE(restart_runtime.pivot_edit.persistent);
  EXPECT_FALSE(restart_runtime.pivot_edit.exit_after_drag);
  EXPECT_TRUE(restart_runtime.pivot_edit.restart_after_drag);
  EXPECT_EQ(restart_runtime.pivot_edit.phase, ClarityPivotEditPhase::PivotCommitPending);
  EXPECT_EQ(restart_runtime.pivot_edit.target, ClarityPivotEditTarget::ObjectOrigin);
  EXPECT_TRUE(restart_runtime.temporary.snap.is_empty());
  EXPECT_EQ(restart_runtime.pivot_edit.snap_preview.type, ClarityPivotSnapTargetType::None);
  EXPECT_FALSE(restart_runtime.pivot_edit.snap_preview.object_to_world.has_value());
  EXPECT_EQ(restart_runtime.pivot_edit.snap_preview_mouse, int2(0));
  EXPECT_FALSE(restart_runtime.pivot_edit.snap_preview_queried);

  CTX_free(C);
}

}  // namespace blender::ed::clarity::tests
