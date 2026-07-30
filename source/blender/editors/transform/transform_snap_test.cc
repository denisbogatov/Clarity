/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

#include "testing/testing.h"

#include "BLI_math_vector.h"

#include "transform.hh"
#include "transform_snap.hh"
#include "transform_snap_maya.hh"

namespace blender::ed::transform::tests {

static TransSnap maya_snap_state(const bool maya_mode_active,
                                 const bool pivot_valid,
                                 const float pivot[3])
{
  TransSnap tsnap = {};
  tsnap.maya_mode_active = maya_mode_active;
  tsnap.maya_pivot_source_valid = pivot_valid;
  copy_v3_v3(tsnap.maya_pivot_source, pivot);
  return tsnap;
}

/** Plain Blender snapping keeps moving the center of the selection onto the target. */
TEST(transform_snap, SourceCenterIgnoresPivotWithoutMayaSnapping)
{
  const float pivot[3] = {5.0f, 6.0f, 7.0f};
  const float center[3] = {1.0f, 2.0f, 3.0f};
  const TransSnap tsnap = maya_snap_state(false, true, pivot);

  float source[3];
  transform_snap_source_center_calc(tsnap, center, source);
  EXPECT_EQ_ARRAY(center, source, 3);
}

/** Maya puts the pivot the user sees onto the target, whatever the selection center is. */
TEST(transform_snap, SourceCenterUsesCapturedPivotWithMayaSnapping)
{
  const float pivot[3] = {5.0f, 6.0f, 7.0f};
  const float center[3] = {1.0f, 2.0f, 3.0f};
  const TransSnap tsnap = maya_snap_state(true, true, pivot);

  float source[3];
  transform_snap_source_center_calc(tsnap, center, source);
  EXPECT_EQ_ARRAY(pivot, source, 3);
}

/** No pivot was captured (no custom pivot, or the pivot itself is being edited). */
TEST(transform_snap, SourceCenterFallsBackToCenterWithoutCapturedPivot)
{
  const float pivot[3] = {5.0f, 6.0f, 7.0f};
  const float center[3] = {1.0f, 2.0f, 3.0f};
  const TransSnap tsnap = maya_snap_state(true, false, pivot);

  float source[3];
  transform_snap_source_center_calc(tsnap, center, source);
  EXPECT_EQ_ARRAY(center, source, 3);
}

/**
 * The pivot the source sits on is excluded from the pivot targets in every mode. Returning null
 * here is what created the dead zone in which the selection snapped onto its own pivot.
 */
TEST(transform_snap, ExcludedPivotFollowsTheSnapSource)
{
  const float pivot[3] = {5.0f, 6.0f, 7.0f};
  const float center[3] = {1.0f, 2.0f, 3.0f};

  const TransSnap captured = maya_snap_state(true, true, pivot);
  const float *excluded = transform_snap_excluded_pivot_get(captured, center);
  ASSERT_NE(excluded, nullptr);
  EXPECT_EQ_ARRAY(pivot, excluded, 3);

  /* Editing the pivot captures nothing, there the transform center already is the pivot. */
  const TransSnap pivot_edit = maya_snap_state(true, false, pivot);
  excluded = transform_snap_excluded_pivot_get(pivot_edit, center);
  ASSERT_NE(excluded, nullptr);
  EXPECT_EQ_ARRAY(center, excluded, 3);
}

/* -------------------------------------------------------------------- */
/** \name Maya Snap Plan
 *
 * The decision the Maya snapping state hands to a transform. Everything the viewport does with
 * snapping follows from these, so they are pinned here instead of being re-derived by hand.
 * \{ */

static MayaSnapPlanInput maya_translate_input(const maya::MayaSnapMode mode)
{
  MayaSnapPlanInput input;
  input.mode = mode;
  input.is_translation = true;
  input.orientation_is_global = true;
  input.space_is_view3d = true;
  return input;
}

/**
 * The regression this whole plan exists for: with no Maya mode engaged nothing snaps at all.
 * Leaving Blender's own magnet in charge is what kept quantizing every transform to the increment
 * grid while no key was held.
 */
TEST(transform_snap_maya_plan, NothingSnapsWithoutAMayaMode)
{
  const MayaSnapPlan plan = transform_snap_maya_plan_get(
      maya_translate_input(maya::MayaSnapMode::None));

  EXPECT_FALSE(plan.use_snap);
  EXPECT_EQ(plan.snap_to, SCE_SNAP_TO_NONE);
  EXPECT_FALSE(plan.absolute_grid);
  EXPECT_FALSE(plan.view_plane);
  EXPECT_FALSE(plan.source_is_center);
  EXPECT_EQ(plan.increment, 0.0f);
}

/** Maya moves the pivot onto the point under the pointer, and object pivots are points too. */
TEST(transform_snap_maya_plan, PointSnapTargetsVerticesAndPivotsFromTheCenter)
{
  const MayaSnapPlan plan = transform_snap_maya_plan_get(
      maya_translate_input(maya::MayaSnapMode::Point));

  EXPECT_TRUE(plan.use_snap);
  EXPECT_EQ(plan.snap_to, SCE_SNAP_TO_VERTEX);
  EXPECT_TRUE(plan.include_object_pivots);
  EXPECT_TRUE(plan.source_is_center);
  EXPECT_FALSE(plan.curve_targets_only);
  EXPECT_EQ(plan.increment, 0.0f);
}

TEST(transform_snap_maya_plan, CurveGridAndMeshCenterPickTheirOwnTargets)
{
  const MayaSnapPlan curve = transform_snap_maya_plan_get(
      maya_translate_input(maya::MayaSnapMode::Curve));
  EXPECT_TRUE(curve.use_snap);
  EXPECT_EQ(curve.snap_to, SCE_SNAP_TO_EDGE);
  EXPECT_TRUE(curve.curve_targets_only);
  EXPECT_TRUE(curve.source_is_center);

  const MayaSnapPlan grid = transform_snap_maya_plan_get(
      maya_translate_input(maya::MayaSnapMode::Grid));
  EXPECT_TRUE(grid.use_snap);
  EXPECT_EQ(grid.snap_to, SCE_SNAP_TO_GRID);
  EXPECT_FALSE(grid.absolute_grid);

  const MayaSnapPlan mesh_center = transform_snap_maya_plan_get(
      maya_translate_input(maya::MayaSnapMode::MeshCenter));
  EXPECT_TRUE(mesh_center.use_snap);
  EXPECT_EQ(mesh_center.snap_to, SCE_SNAP_TO_VOLUME);
  EXPECT_TRUE(mesh_center.mesh_center);
}

/** The view plane constrains the movement; it has no target to snap onto. */
TEST(transform_snap_maya_plan, ViewPlaneConstrainsWithoutSnapping)
{
  const MayaSnapPlan plan = transform_snap_maya_plan_get(
      maya_translate_input(maya::MayaSnapMode::ViewPlane));

  EXPECT_TRUE(plan.view_plane);
  EXPECT_FALSE(plan.use_snap);
  EXPECT_EQ(plan.snap_to, SCE_SNAP_TO_NONE);
}

/** Step snapping uses the size from the Step Snap widget, not the grid of the scene. */
TEST(transform_snap_maya_plan, StepSnapUsesTheConfiguredSize)
{
  MayaSnapPlanInput input = maya_translate_input(maya::MayaSnapMode::Step);
  input.step.mode = maya::MAYA_STEP_SNAP_RELATIVE;
  input.step.size = 0.25f;

  const MayaSnapPlan plan = transform_snap_maya_plan_get(input);
  EXPECT_TRUE(plan.use_snap);
  EXPECT_EQ(plan.snap_to, SCE_SNAP_TO_INCREMENT);
  EXPECT_FALSE(plan.absolute_grid);
  EXPECT_EQ(plan.increment, 0.25f);
  /* Steps quantize the movement itself, they do not put the pivot anywhere. */
  EXPECT_FALSE(plan.source_is_center);
}

/**
 * Absolute steps are counted from the world origin, so they can only be honored while the
 * translation runs in global space.
 */
TEST(transform_snap_maya_plan, AbsoluteStepsNeedGlobalSpace)
{
  MayaSnapPlanInput input = maya_translate_input(maya::MayaSnapMode::Step);
  input.step.mode = maya::MAYA_STEP_SNAP_ABSOLUTE;

  EXPECT_TRUE(transform_snap_maya_plan_get(input).absolute_grid);

  input.orientation_is_global = false;
  EXPECT_FALSE(transform_snap_maya_plan_get(input).absolute_grid);
}

/** Maya steps a rotation or a scale, but never snaps one onto a point, a curve or the grid. */
TEST(transform_snap_maya_plan, OnlyStepsReachRotationAndScale)
{
  MayaSnapPlanInput point = maya_translate_input(maya::MayaSnapMode::Point);
  point.is_translation = false;
  const MayaSnapPlan point_plan = transform_snap_maya_plan_get(point);
  EXPECT_FALSE(point_plan.use_snap);
  EXPECT_EQ(point_plan.snap_to, SCE_SNAP_TO_NONE);

  MayaSnapPlanInput step = maya_translate_input(maya::MayaSnapMode::Step);
  step.is_translation = false;
  step.step.size = 15.0f;
  const MayaSnapPlan step_plan = transform_snap_maya_plan_get(step);
  EXPECT_TRUE(step_plan.use_snap);
  EXPECT_EQ(step_plan.snap_to, SCE_SNAP_TO_INCREMENT);
  /* A scale counts neither in units nor in radians, so it keeps the increment of its own mode. */
  EXPECT_EQ(step_plan.increment, 0.0f);
}

/**
 * Each transform counts its steps in its own unit: the distance drives a translation, the angle
 * drives a rotation. Handing a rotation the distance is what made a 1 unit step mean 57 degrees.
 */
TEST(transform_snap_maya_plan, RotationStepsUseTheAngleAndTranslationTheDistance)
{
  MayaSnapPlanInput input = maya_translate_input(maya::MayaSnapMode::Step);
  input.step.size = 2.0f;
  input.step.angle = 0.5f;

  EXPECT_EQ(transform_snap_maya_plan_get(input).increment, 2.0f);

  input.is_translation = false;
  input.is_rotation = true;
  EXPECT_EQ(transform_snap_maya_plan_get(input).increment, 0.5f);

  /* Outside the 3D View the increment belongs to that editor either way. */
  input.space_is_view3d = false;
  EXPECT_EQ(transform_snap_maya_plan_get(input).increment, 0.0f);
}

/** Outside the 3D View the increment carries the aspect of that editor, so it is left alone. */
TEST(transform_snap_maya_plan, StepSizeOnlyReplacesTheIncrementInTheViewport)
{
  MayaSnapPlanInput input = maya_translate_input(maya::MayaSnapMode::Step);
  input.space_is_view3d = false;
  input.step.size = 2.0f;

  EXPECT_EQ(transform_snap_maya_plan_get(input).increment, 0.0f);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Pivot Snapping
 *
 * Where a drag of the Edit Pivot manipulator leaves the pivot. These are the rules the Maya capture
 * shows, pinned here so the behavior stops being re-derived from a video.
 * \{ */

static MayaPivotSnapInput maya_pivot_input()
{
  MayaPivotSnapInput input;
  input.applied_position = double3(1.0, 1.0, 1.0);
  input.pointer_position = double3(2.0, 2.0, 2.0);
  input.target_position = double3(5.0, 6.0, 7.0);
  return input;
}

/**
 * Outside the snap tolerance there is no target, and Maya keeps the pivot on the pointer. Holding it
 * on the last target instead is what looked like a pivot magnetized to a vertex it had left.
 */
TEST(transform_snap_maya_pivot, PivotFollowsThePointerWithoutATarget)
{
  MayaPivotSnapInput input = maya_pivot_input();
  input.has_target = false;
  input.target_has_normal = true;

  const MayaPivotSnapDecision decision = maya_pivot_snap_decision_get(input);
  EXPECT_EQ(decision.position, input.applied_position);
  EXPECT_FALSE(decision.from_target);
  EXPECT_FALSE(decision.aim_at_normal);
}

/** The magnet: the pivot lands on the target itself, never offset by the drag that took it there. */
TEST(transform_snap_maya_pivot, PivotLandsExactlyOnTheTarget)
{
  MayaPivotSnapInput input = maya_pivot_input();
  input.has_target = true;

  const MayaPivotSnapDecision decision = maya_pivot_snap_decision_get(input);
  EXPECT_EQ(decision.position, input.target_position);
  EXPECT_TRUE(decision.from_target);
}

/**
 * A dragged axis or plane handle owns the direction: the pivot slides along it up to the target
 * instead of leaving it. Taking the target verbatim is what moved a pivot dragged by the Z arrow to
 * a vertex beside the axis, which the manipulator trace showed as `applied=(0 0 1)` while the
 * decision returned `(1 1 1)`.
 */
TEST(transform_snap_maya_pivot, AConstrainedDragKeepsThePivotOnItsConstraint)
{
  MayaPivotSnapInput input = maya_pivot_input();
  input.has_target = true;
  input.has_constraint = true;
  /* The Z arrow: only the target's Z reaches the pivot. */
  input.constrained_target_position = double3(0.0, 0.0, 7.0);

  const MayaPivotSnapDecision decision = maya_pivot_snap_decision_get(input);
  EXPECT_EQ(decision.position, input.constrained_target_position);
  EXPECT_TRUE(decision.from_target);

  /* Without a constraint the whole target still wins. */
  input.has_constraint = false;
  EXPECT_EQ(maya_pivot_snap_decision_get(input).position, input.target_position);
}

/** Position snapping off keeps the pointer in charge, and the target may still aim the pivot. */
TEST(transform_snap_maya_pivot, PositionSnapOffLeavesThePointerInChargeOfTheMove)
{
  MayaPivotSnapInput input = maya_pivot_input();
  input.has_target = true;
  input.target_has_normal = true;
  input.snap_position = false;

  const MayaPivotSnapDecision decision = maya_pivot_snap_decision_get(input);
  EXPECT_EQ(decision.position, input.pointer_position);
  EXPECT_FALSE(decision.from_target);
  EXPECT_TRUE(decision.aim_at_normal);
}

/** A vertex has no surface normal, so a snap onto one places the pivot without turning it. */
TEST(transform_snap_maya_pivot, AimingNeedsANormalAndItsOwnSetting)
{
  MayaPivotSnapInput input = maya_pivot_input();
  input.has_target = true;

  input.target_has_normal = false;
  EXPECT_FALSE(maya_pivot_snap_decision_get(input).aim_at_normal);

  input.target_has_normal = true;
  EXPECT_TRUE(maya_pivot_snap_decision_get(input).aim_at_normal);

  input.snap_orientation = false;
  const MayaPivotSnapDecision decision = maya_pivot_snap_decision_get(input);
  EXPECT_FALSE(decision.aim_at_normal);
  /* Turning the aim off must not stop the pivot from being placed. */
  EXPECT_EQ(decision.position, input.target_position);
}

/** \} */

}  // namespace blender::ed::transform::tests
