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

#include "maya_runtime.hh"

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

  EXPECT_TRUE(snap.press(MayaSnapMode::Point));
  EXPECT_EQ(snap.active(), MayaSnapMode::Point);
  EXPECT_TRUE(snap.press(MayaSnapMode::Grid));
  EXPECT_EQ(snap.active(), MayaSnapMode::Grid);

  /* Releasing the newer key falls back to the one still held, it does not clear everything. */
  EXPECT_TRUE(snap.release(MayaSnapMode::Grid));
  EXPECT_EQ(snap.active(), MayaSnapMode::Point);
  EXPECT_TRUE(snap.release(MayaSnapMode::Point));
  EXPECT_TRUE(snap.is_empty());
}

/** Key repeats used to stack a second copy, so one release could not end the mode. */
TEST(maya_snap_override, RepeatedPressDoesNotStackAndOneReleaseEndsIt)
{
  MayaSnapOverride snap;
  EXPECT_TRUE(snap.press(MayaSnapMode::Point));
  EXPECT_FALSE(snap.press(MayaSnapMode::Point));
  EXPECT_FALSE(snap.press(MayaSnapMode::Point));
  EXPECT_EQ(snap.held_num(), 1);

  EXPECT_TRUE(snap.release(MayaSnapMode::Point));
  EXPECT_TRUE(snap.is_empty());
  EXPECT_EQ(snap.active(), MayaSnapMode::None);
}

/** A release for a key that is not held must change nothing at all. */
TEST(maya_snap_override, StrayReleaseLeavesTheHeldKeysAlone)
{
  MayaSnapOverride snap;
  EXPECT_TRUE(snap.press(MayaSnapMode::Curve));

  EXPECT_FALSE(snap.release(MayaSnapMode::Point));
  EXPECT_FALSE(snap.release(MayaSnapMode::None));
  EXPECT_EQ(snap.active(), MayaSnapMode::Curve);
  EXPECT_EQ(snap.held_num(), 1);
}

/** `J` and `Shift+J` are one key: they never stack, and either release frees it. */
TEST(maya_snap_override, StepModesShareTheirKey)
{
  EXPECT_TRUE(MayaSnapOverride::modes_share_key(MayaSnapMode::StepAbsolute,
                                                MayaSnapMode::StepRelative));
  EXPECT_FALSE(
      MayaSnapOverride::modes_share_key(MayaSnapMode::Point, MayaSnapMode::Grid));

  MayaSnapOverride snap;
  EXPECT_TRUE(snap.press(MayaSnapMode::StepAbsolute));
  EXPECT_FALSE(snap.press(MayaSnapMode::StepRelative));
  EXPECT_EQ(snap.held_num(), 1);
  EXPECT_EQ(snap.active(), MayaSnapMode::StepAbsolute);

  /* The release reports the absolute variant even when the key went down with Shift. */
  EXPECT_TRUE(snap.release(MayaSnapMode::StepAbsolute));
  EXPECT_TRUE(snap.is_empty());

  MayaSnapOverride relative;
  EXPECT_TRUE(relative.press(MayaSnapMode::StepRelative));
  EXPECT_TRUE(relative.release(MayaSnapMode::StepAbsolute));
  EXPECT_TRUE(relative.is_empty());
}

/**
 * The escape hatch for a release that can never arrive: the pointer left the 3D View, a popup
 * swallowed the event, the interaction preset changed under the held key.
 */
TEST(maya_snap_override, ClearReleasesEverythingAndReportsWhetherItHadTo)
{
  MayaSnapOverride snap;
  EXPECT_FALSE(snap.clear());

  EXPECT_TRUE(snap.press(MayaSnapMode::Point));
  EXPECT_TRUE(snap.press(MayaSnapMode::Grid));
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
  restart_runtime.temporary.snap.press(MayaSnapMode::Point);
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
