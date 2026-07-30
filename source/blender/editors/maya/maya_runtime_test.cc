/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

#include "testing/testing.h"

#include "BKE_context.hh"
#include "BKE_gtest_base.hh"
#include "BKE_lib_id.hh"
#include "BKE_main.hh"
#include "BKE_object.hh"
#include "BKE_object_transform_maya.hh"

#include "ED_maya.hh"

#include "WM_types.hh"
#include "wm_event_types.hh"

#include "maya_input.hh"
#include "maya_runtime.hh"
#include "maya_tools.hh"

namespace blender::ed::maya::tests {

/**
 * Allocating an ID needs the ID type table, so every test in this file runs on the shared Blender
 * fixture. Without it #BKE_object_add_only_object asserts in #BKE_libblock_alloc_notest and takes
 * the whole test binary down with it.
 */
class MayaRuntimeTest : public bke::BlenderGTestBase {};

/** Momentary snap keys: the state machine behind temporary snapping getting stuck. */
TEST(maya_snap_override, HeldKeysStackAndTheLastOneWins)
{
  MayaSnapOverride snap;
  EXPECT_TRUE(snap.is_empty());
  EXPECT_EQ(snap.active(), MayaSnapMode::None);

  EXPECT_TRUE(snap.press(EVT_VKEY, MayaSnapMode::Point));
  EXPECT_EQ(snap.active(), MayaSnapMode::Point);
  EXPECT_TRUE(snap.press(EVT_XKEY, MayaSnapMode::Grid));
  EXPECT_EQ(snap.active(), MayaSnapMode::Grid);

  /* Releasing the newer key falls back to the one still held, it does not clear everything. */
  EXPECT_TRUE(snap.release(EVT_XKEY));
  EXPECT_EQ(snap.active(), MayaSnapMode::Point);
  EXPECT_TRUE(snap.release(EVT_VKEY));
  EXPECT_TRUE(snap.is_empty());
}

/** Key repeats used to stack a second copy, so one release could not end the mode. */
TEST(maya_snap_override, RepeatedPressDoesNotStackAndOneReleaseEndsIt)
{
  MayaSnapOverride snap;
  EXPECT_TRUE(snap.press(EVT_VKEY, MayaSnapMode::Point));
  EXPECT_FALSE(snap.press(EVT_VKEY, MayaSnapMode::Point));
  EXPECT_FALSE(snap.press(EVT_VKEY, MayaSnapMode::Point));
  EXPECT_EQ(snap.held_num(), 1);

  EXPECT_TRUE(snap.release(EVT_VKEY));
  EXPECT_TRUE(snap.is_empty());
  EXPECT_EQ(snap.active(), MayaSnapMode::None);
}

/** A release for a key that is not held must change nothing at all. */
TEST(maya_snap_override, StrayReleaseLeavesTheHeldKeysAlone)
{
  MayaSnapOverride snap;
  EXPECT_TRUE(snap.press(EVT_CKEY, MayaSnapMode::Curve));

  EXPECT_FALSE(snap.release(EVT_VKEY));
  EXPECT_EQ(snap.active(), MayaSnapMode::Curve);
  EXPECT_EQ(snap.held_num(), 1);
}

/** A key holds one mode: repeats never stack and one release frees it. */
TEST(maya_snap_override, StepKeyHoldsOneModeOnly)
{
  MayaSnapOverride snap;
  EXPECT_TRUE(snap.press(EVT_JKEY, MayaSnapMode::Step));
  EXPECT_FALSE(snap.press(EVT_JKEY, MayaSnapMode::Step));
  EXPECT_EQ(snap.held_num(), 1);
  EXPECT_EQ(snap.active(), MayaSnapMode::Step);

  /* The release names the key, not the mode it engaged. */
  EXPECT_TRUE(snap.release(EVT_JKEY));
  EXPECT_TRUE(snap.is_empty());
}

/**
 * A fresh press of a key that is still listed means its release was lost: the press is the newer
 * truth, so it replaces the stale entry instead of stacking behind it.
 */
TEST(maya_snap_override, PressOfAHeldKeyWithAnotherModeRebuildsIt)
{
  MayaSnapOverride snap;
  EXPECT_TRUE(snap.press(EVT_VKEY, MayaSnapMode::Point));
  EXPECT_TRUE(snap.press(EVT_VKEY, MayaSnapMode::Grid));
  EXPECT_EQ(snap.held_num(), 1);
  EXPECT_EQ(snap.active(), MayaSnapMode::Grid);
  EXPECT_TRUE(snap.release(EVT_VKEY));
  EXPECT_TRUE(snap.is_empty());
}

/**
 * The escape hatch for a release the dispatcher never saw: only the key the window reports as held
 * can be proven gone, so an overlapping second key keeps its mode.
 */
TEST(maya_snap_override, OnlyWindowTrackedKeysAreReleasedByReconcile)
{
  MayaSnapOverride snap;
  EXPECT_FALSE(snap.release_window_tracked_keys());

  EXPECT_TRUE(snap.press(EVT_VKEY, MayaSnapMode::Point, true));
  EXPECT_TRUE(snap.press(EVT_XKEY, MayaSnapMode::Grid, false));
  EXPECT_TRUE(snap.release_window_tracked_keys());
  EXPECT_EQ(snap.held_num(), 1);
  EXPECT_EQ(snap.active(), MayaSnapMode::Grid);
  EXPECT_FALSE(snap.release_window_tracked_keys());
}

/**
 * Maya's documented tolerance: on, the target has to be inside the region around the pointer; off,
 * "the snap region is unlimited; you can snap to anything viewable".
 */
TEST(maya_snap_tolerance, LimitedToleranceScalesWithTheInterfaceAndOffMeansTheWholeRegion)
{
  MayaSnapToleranceSettings settings;
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

/**
 * Maya's topological double click: the modifiers pick the set operation and nothing else. Deriving
 * the operation from the gesture instead is what made `Ctrl+Shift` add a full loop where a path was
 * asked for, and `Shift` unable to remove anything.
 */
TEST(maya_topology_select, ModifiersPickTheSetOperation)
{
  MayaInputAction action;

  EXPECT_EQ(topology_select_op_from_action(action), MayaTopologySelectOp::Replace);

  action.shift = true;
  EXPECT_EQ(topology_select_op_from_action(action), MayaTopologySelectOp::Toggle);

  action.shift = false;
  action.ctrl = true;
  EXPECT_EQ(topology_select_op_from_action(action), MayaTopologySelectOp::Subtract);

  action.shift = true;
  EXPECT_EQ(topology_select_op_from_action(action), MayaTopologySelectOp::Add);

  /* `Alt` belongs to viewport navigation, so it never reaches this table; if it does, it changes
   * nothing about the operation. */
  action.alt = true;
  EXPECT_EQ(topology_select_op_from_action(action), MayaTopologySelectOp::Add);
}

/** The key table is the only place that decides which key holds which mode. */
TEST(maya_snap_keys, ReleaseResolvesWhateverModifiersCameWithIt)
{
  EXPECT_EQ(snap_key_event_mode_get(EVT_VKEY, KM_PRESS, 0), MayaSnapMode::Point);
  EXPECT_EQ(snap_key_event_mode_get(EVT_XKEY, KM_PRESS, 0), MayaSnapMode::Grid);
  EXPECT_EQ(snap_key_event_mode_get(EVT_CKEY, KM_PRESS, 0), MayaSnapMode::Curve);

  /* Whether the steps are relative or absolute is a setting, not a second binding of the key, so
   * `Shift` stays available to the drag `J` is held during. */
  EXPECT_EQ(snap_key_event_mode_get(EVT_JKEY, KM_PRESS, 0), MayaSnapMode::Step);
  EXPECT_EQ(snap_key_event_mode_get(EVT_JKEY, KM_PRESS, KM_SHIFT), MayaSnapMode::Step);

  /* A press must not steal a binding that belongs to a modifier combination. */
  EXPECT_EQ(snap_key_event_mode_get(EVT_VKEY, KM_PRESS, KM_CTRL), MayaSnapMode::None);
  EXPECT_EQ(snap_key_event_mode_get(EVT_XKEY, KM_PRESS, KM_SHIFT), MayaSnapMode::None);
  EXPECT_EQ(snap_key_event_mode_get(EVT_JKEY, KM_PRESS, KM_ALT), MayaSnapMode::None);

  /* The release is the only way out of the mode, so no modifier may swallow it. */
  EXPECT_EQ(snap_key_event_mode_get(EVT_JKEY, KM_RELEASE, KM_ALT), MayaSnapMode::Step);
  EXPECT_EQ(snap_key_event_mode_get(EVT_JKEY, KM_RELEASE, uint8_t(KM_CTRL | KM_SHIFT)),
            MayaSnapMode::Step);
  EXPECT_EQ(snap_key_event_mode_get(EVT_VKEY, KM_RELEASE, uint8_t(KM_CTRL | KM_ALT)),
            MayaSnapMode::Point);

  EXPECT_EQ(snap_key_event_mode_get(EVT_ZKEY, KM_PRESS, 0), MayaSnapMode::None);
  EXPECT_EQ(snap_key_event_mode_get(EVT_VKEY, KM_DBL_CLICK, 0), MayaSnapMode::None);
}

/**
 * The escape hatch for a release that can never arrive: the pointer left the 3D View, a popup
 * swallowed the event, the interaction preset changed under the held key.
 */
TEST(maya_snap_override, ClearReleasesEverythingAndReportsWhetherItHadTo)
{
  MayaSnapOverride snap;
  EXPECT_FALSE(snap.clear());

  EXPECT_TRUE(snap.press(EVT_VKEY, MayaSnapMode::Point));
  EXPECT_TRUE(snap.press(EVT_XKEY, MayaSnapMode::Grid));
  EXPECT_TRUE(snap.clear());
  EXPECT_TRUE(snap.is_empty());
  EXPECT_EQ(snap.active(), MayaSnapMode::None);
  EXPECT_FALSE(snap.clear());
}

TEST_F(MayaRuntimeTest, ObjectRuntimeReferenceRejectsDeletedOrReusedObject)
{
  Main *bmain = BKE_main_new();
  Object *object = BKE_object_add_only_object(bmain, OB_EMPTY, "PivotSubject");
  const MayaObjectRuntimeRef reference = ED_maya_object_runtime_ref_create(*object);
  EXPECT_EQ(ED_maya_object_runtime_ref_resolve(*bmain, reference), object);

  BKE_id_delete(bmain, object);
  EXPECT_EQ(ED_maya_object_runtime_ref_resolve(*bmain, reference), nullptr);

  Object *replacement = BKE_object_add_only_object(bmain, OB_EMPTY, "PivotSubject");
  EXPECT_NE(replacement->id.session_uid, reference.session_uid);
  EXPECT_EQ(ED_maya_object_runtime_ref_resolve(*bmain, reference), nullptr);
  BKE_main_free(bmain);
}

TEST_F(MayaRuntimeTest, TransformTransactionRestoresObjectsAndRuntime)
{
  Main *bmain = BKE_main_new();
  Object *root = BKE_object_add_only_object(bmain, OB_EMPTY, "Root");
  Object *child_a = BKE_object_add_only_object(bmain, OB_EMPTY, "ChildA");
  Object *child_b = BKE_object_add_only_object(bmain, OB_EMPTY, "ChildB");
  root->transform_model = OBJECT_TRANSFORM_MAYA;
  child_a->transform_model = OBJECT_TRANSFORM_MAYA;
  child_b->transform_model = OBJECT_TRANSFORM_MAYA;
  BKE_object_maya_transform_ensure(root)->translation[0] = 1.0;
  BKE_object_maya_transform_ensure(child_a)->translation[1] = 2.0;
  BKE_object_maya_transform_ensure(child_b)->translation[2] = 3.0;

  MayaManipulatorPivotState runtime_state;
  runtime_state.position_world = double3(4.0, 5.0, 6.0);
  runtime_state.position_valid = true;
  const MayaManipulatorPivotState runtime_before = runtime_state;

  {
    MayaTransformTransaction transaction(nullptr, nullptr);
    ASSERT_TRUE(transaction.capture_object(*root));
    ASSERT_TRUE(transaction.capture_child(*child_a));
    ASSERT_TRUE(transaction.capture_child(*child_b));
    ASSERT_TRUE(transaction.capture_runtime(runtime_state));
    root->maya_transform->translation[0] = 10.0;
    child_a->maya_transform->translation[1] = 20.0;
    child_b->maya_transform->translation[2] = 30.0;
    runtime_state.position_world = double3(-1.0, -2.0, -3.0);
    runtime_state.position_valid = false;
    transaction.rollback();
  }

  EXPECT_DOUBLE_EQ(root->maya_transform->translation[0], 1.0);
  EXPECT_DOUBLE_EQ(child_a->maya_transform->translation[1], 2.0);
  EXPECT_DOUBLE_EQ(child_b->maya_transform->translation[2], 3.0);
  EXPECT_EQ(runtime_state.position_world, runtime_before.position_world);
  EXPECT_EQ(runtime_state.position_valid, runtime_before.position_valid);
  BKE_main_free(bmain);
}

TEST_F(MayaRuntimeTest, PivotEditTogglePersistsWithoutHostContext)
{
  bContext *C = CTX_create();
  MayaWindowRuntime runtime;

  EXPECT_FALSE(runtime.pivot_edit.persistent);
  EXPECT_EQ(runtime.pivot_edit.phase, MayaPivotEditPhase::Normal);

  EXPECT_TRUE(pivot_edit_toggle_persistent(C, runtime));
  EXPECT_TRUE(runtime.pivot_edit.persistent);
  EXPECT_EQ(runtime.pivot_edit.phase, MayaPivotEditPhase::PersistentPivot);
  EXPECT_EQ(runtime.pivot_edit.target, MayaPivotEditTarget::None);

  EXPECT_TRUE(pivot_edit_toggle_persistent(C, runtime));
  EXPECT_FALSE(runtime.pivot_edit.persistent);
  EXPECT_EQ(runtime.pivot_edit.phase, MayaPivotEditPhase::Normal);
  EXPECT_EQ(runtime.pivot_edit.target, MayaPivotEditTarget::None);

  CTX_free(C);
}

TEST_F(MayaRuntimeTest, PivotEditDragTailDefersExitOrFocusRestart)
{
  bContext *C = CTX_create();

  MayaWindowRuntime exit_runtime;
  exit_runtime.transform_active = true;
  exit_runtime.pivot_edit.persistent = true;
  exit_runtime.pivot_edit.target = MayaPivotEditTarget::ObjectOrigin;
  exit_runtime.pivot_edit.phase = MayaPivotEditPhase::PivotDragging;

  EXPECT_TRUE(pivot_edit_toggle_persistent(C, exit_runtime));
  EXPECT_FALSE(exit_runtime.pivot_edit.persistent);
  EXPECT_TRUE(exit_runtime.pivot_edit.exit_after_drag);
  EXPECT_FALSE(exit_runtime.pivot_edit.restart_after_drag);
  EXPECT_EQ(exit_runtime.pivot_edit.phase, MayaPivotEditPhase::PivotCommitPending);
  EXPECT_EQ(exit_runtime.pivot_edit.target, MayaPivotEditTarget::ObjectOrigin);

  MayaWindowRuntime focus_runtime;
  focus_runtime.pivot_edit.persistent = true;
  focus_runtime.pivot_edit.target = MayaPivotEditTarget::ObjectOrigin;
  focus_runtime.pivot_edit.phase = MayaPivotEditPhase::PersistentPivot;

  pivot_edit_input_reset(C, focus_runtime);
  EXPECT_TRUE(focus_runtime.pivot_edit.persistent);
  EXPECT_FALSE(focus_runtime.pivot_edit.exit_after_drag);
  EXPECT_FALSE(focus_runtime.pivot_edit.restart_after_drag);
  EXPECT_EQ(focus_runtime.pivot_edit.phase, MayaPivotEditPhase::PersistentPivot);
  EXPECT_EQ(focus_runtime.pivot_edit.target, MayaPivotEditTarget::ObjectOrigin);

  MayaWindowRuntime restart_runtime;
  restart_runtime.transform_active = true;
  restart_runtime.pivot_edit.persistent = true;
  restart_runtime.pivot_edit.target = MayaPivotEditTarget::ObjectOrigin;
  restart_runtime.pivot_edit.phase = MayaPivotEditPhase::PivotDragging;
  restart_runtime.temporary.snap.press(EVT_VKEY, MayaSnapMode::Point);
  restart_runtime.pivot_edit.snap_preview.type = MayaPivotSnapTargetType::Vertex;
  restart_runtime.pivot_edit.snap_preview.object_to_world = float4x4::identity();
  restart_runtime.pivot_edit.snap_preview.component_index = 7;
  restart_runtime.pivot_edit.snap_preview_mouse = int2(12, 34);
  restart_runtime.pivot_edit.snap_preview_queried = true;

  pivot_edit_input_reset(C, restart_runtime);
  EXPECT_TRUE(restart_runtime.pivot_edit.persistent);
  EXPECT_FALSE(restart_runtime.pivot_edit.exit_after_drag);
  EXPECT_TRUE(restart_runtime.pivot_edit.restart_after_drag);
  EXPECT_EQ(restart_runtime.pivot_edit.phase, MayaPivotEditPhase::PivotCommitPending);
  EXPECT_EQ(restart_runtime.pivot_edit.target, MayaPivotEditTarget::ObjectOrigin);
  EXPECT_TRUE(restart_runtime.temporary.snap.is_empty());
  EXPECT_EQ(restart_runtime.pivot_edit.snap_preview.type, MayaPivotSnapTargetType::None);
  EXPECT_FALSE(restart_runtime.pivot_edit.snap_preview.object_to_world.has_value());
  EXPECT_EQ(restart_runtime.pivot_edit.snap_preview_mouse, int2(0));
  EXPECT_FALSE(restart_runtime.pivot_edit.snap_preview_queried);

  CTX_free(C);
}

}  // namespace blender::ed::maya::tests
