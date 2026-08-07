/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

#include "testing/testing.h"

#include "BLI_math_vector.h"

#include "transform.hh"
#include "transform_snap.hh"
#include "transform_snap_clarity.hh"

namespace blender::ed::transform::tests {

static TransSnap clarity_snap_state(const bool clarity_mode_active,
                                 const bool pivot_valid,
                                 const float pivot[3])
{
  TransSnap tsnap = {};
  tsnap.clarity_mode_active = clarity_mode_active;
  tsnap.clarity_pivot_source_valid = pivot_valid;
  copy_v3_v3(tsnap.clarity_pivot_source, pivot);
  return tsnap;
}

/** Plain Blender snapping keeps moving the center of the selection onto the target. */
TEST(transform_snap, SourceCenterIgnoresPivotWithoutClaritySnapping)
{
  const float pivot[3] = {5.0f, 6.0f, 7.0f};
  const float center[3] = {1.0f, 2.0f, 3.0f};
  const TransSnap tsnap = clarity_snap_state(false, true, pivot);

  float source[3];
  transform_snap_source_center_calc(tsnap, center, source);
  EXPECT_EQ_ARRAY(center, source, 3);
}

/** Clarity puts the pivot the user sees onto the target, whatever the selection center is. */
TEST(transform_snap, SourceCenterUsesCapturedPivotWithClaritySnapping)
{
  const float pivot[3] = {5.0f, 6.0f, 7.0f};
  const float center[3] = {1.0f, 2.0f, 3.0f};
  const TransSnap tsnap = clarity_snap_state(true, true, pivot);

  float source[3];
  transform_snap_source_center_calc(tsnap, center, source);
  EXPECT_EQ_ARRAY(pivot, source, 3);
}

/** No pivot was captured (no custom pivot, or the pivot itself is being edited). */
TEST(transform_snap, SourceCenterFallsBackToCenterWithoutCapturedPivot)
{
  const float pivot[3] = {5.0f, 6.0f, 7.0f};
  const float center[3] = {1.0f, 2.0f, 3.0f};
  const TransSnap tsnap = clarity_snap_state(true, false, pivot);

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

  const TransSnap captured = clarity_snap_state(true, true, pivot);
  const float *excluded = transform_snap_excluded_pivot_get(captured, center);
  ASSERT_NE(excluded, nullptr);
  EXPECT_EQ_ARRAY(pivot, excluded, 3);

  /* Editing the pivot captures nothing, there the transform center already is the pivot. */
  const TransSnap pivot_edit = clarity_snap_state(true, false, pivot);
  excluded = transform_snap_excluded_pivot_get(pivot_edit, center);
  ASSERT_NE(excluded, nullptr);
  EXPECT_EQ_ARRAY(center, excluded, 3);
}

/* -------------------------------------------------------------------- */
/** \name Clarity Snap Plan
 *
 * The decision the Clarity snapping state hands to a transform. Everything the viewport does with
 * snapping follows from these, so they are pinned here instead of being re-derived by hand.
 * \{ */

static ClaritySnapPlanInput clarity_translate_input(const clarity::ClaritySnapMode mode)
{
  ClaritySnapPlanInput input;
  input.mode = mode;
  input.is_translation = true;
  input.orientation_is_global = true;
  input.space_is_view3d = true;
  return input;
}

/**
 * The regression this whole plan exists for: with no Clarity mode engaged nothing snaps at all.
 * Leaving Blender's own magnet in charge is what kept quantizing every transform to the increment
 * grid while no key was held.
 */
TEST(transform_snap_clarity_plan, NothingSnapsWithoutAClarityMode)
{
  const ClaritySnapPlan plan = transform_snap_clarity_plan_get(
      clarity_translate_input(clarity::ClaritySnapMode::None));

  EXPECT_FALSE(plan.use_snap);
  EXPECT_EQ(plan.snap_to, SCE_SNAP_TO_NONE);
  EXPECT_FALSE(plan.absolute_grid);
  EXPECT_FALSE(plan.view_plane);
  EXPECT_FALSE(plan.source_is_center);
  EXPECT_EQ(plan.increment, 0.0f);
}

/** The Move Tool marking menu holds components on the edges they were moved along. */
TEST(transform_snap_clarity_plan, EdgeConstraintKeepsComponentsOnEdges)
{
  ClaritySnapPlanInput input = clarity_translate_input(clarity::ClaritySnapMode::None);
  input.transform_constraint = clarity::ClarityTransformConstraint::Edge;
  input.is_component_edit = true;

  const ClaritySnapPlan plan = transform_snap_clarity_plan_get(input);

  EXPECT_TRUE(plan.use_snap);
  EXPECT_EQ(plan.snap_to, SCE_SNAP_TO_EDGE);
  /* The component lands on the edge itself, so the pivot has no say. */
  EXPECT_FALSE(plan.source_is_center);
  EXPECT_FALSE(plan.curve_targets_only);
}

TEST(transform_snap_clarity_plan, SurfaceConstraintKeepsComponentsOnFaces)
{
  ClaritySnapPlanInput input = clarity_translate_input(clarity::ClaritySnapMode::None);
  input.transform_constraint = clarity::ClarityTransformConstraint::Surface;
  input.is_component_edit = true;

  const ClaritySnapPlan plan = transform_snap_clarity_plan_get(input);

  EXPECT_TRUE(plan.use_snap);
  EXPECT_EQ(plan.snap_to, SCE_SNAP_TO_FACE);
}

/** Clarity constrains components, never whole objects. */
TEST(transform_snap_clarity_plan, TransformConstraintsLeaveObjectModeAlone)
{
  ClaritySnapPlanInput input = clarity_translate_input(clarity::ClaritySnapMode::None);
  input.transform_constraint = clarity::ClarityTransformConstraint::Edge;
  input.is_component_edit = false;

  const ClaritySnapPlan plan = transform_snap_clarity_plan_get(input);

  EXPECT_FALSE(plan.use_snap);
  EXPECT_EQ(plan.snap_to, SCE_SNAP_TO_NONE);
}

/** A held snap key is a deliberate one-off, so it outranks a constraint that is always on. */
TEST(transform_snap_clarity_plan, AHeldSnapKeyOutranksTheTransformConstraint)
{
  ClaritySnapPlanInput input = clarity_translate_input(clarity::ClaritySnapMode::Point);
  input.transform_constraint = clarity::ClarityTransformConstraint::Edge;
  input.is_component_edit = true;

  const ClaritySnapPlan plan = transform_snap_clarity_plan_get(input);

  EXPECT_EQ(plan.snap_to, SCE_SNAP_TO_VERTEX);
}

/** A constraint holds a component while it travels; it has nothing to say about a rotation. */
TEST(transform_snap_clarity_plan, TransformConstraintsOnlyReachTranslation)
{
  ClaritySnapPlanInput input = clarity_translate_input(clarity::ClaritySnapMode::None);
  input.is_translation = false;
  input.is_rotation = true;
  input.transform_constraint = clarity::ClarityTransformConstraint::Edge;
  input.is_component_edit = true;

  const ClaritySnapPlan plan = transform_snap_clarity_plan_get(input);

  EXPECT_FALSE(plan.use_snap);
}

/** Clarity moves the pivot onto the point under the pointer, and object pivots are points too. */
TEST(transform_snap_clarity_plan, PointSnapTargetsVerticesAndPivotsFromTheCenter)
{
  const ClaritySnapPlan plan = transform_snap_clarity_plan_get(
      clarity_translate_input(clarity::ClaritySnapMode::Point));

  EXPECT_TRUE(plan.use_snap);
  EXPECT_EQ(plan.snap_to, SCE_SNAP_TO_VERTEX);
  EXPECT_TRUE(plan.include_object_pivots);
  EXPECT_TRUE(plan.source_is_center);
  EXPECT_FALSE(plan.curve_targets_only);
  EXPECT_EQ(plan.increment, 0.0f);
}

TEST(transform_snap_clarity_plan, CurveGridAndMeshCenterPickTheirOwnTargets)
{
  const ClaritySnapPlan curve = transform_snap_clarity_plan_get(
      clarity_translate_input(clarity::ClaritySnapMode::Curve));
  EXPECT_TRUE(curve.use_snap);
  EXPECT_EQ(curve.snap_to, SCE_SNAP_TO_EDGE);
  EXPECT_TRUE(curve.curve_targets_only);
  EXPECT_TRUE(curve.source_is_center);

  const ClaritySnapPlan grid = transform_snap_clarity_plan_get(
      clarity_translate_input(clarity::ClaritySnapMode::Grid));
  EXPECT_TRUE(grid.use_snap);
  EXPECT_EQ(grid.snap_to, SCE_SNAP_TO_GRID);
  EXPECT_FALSE(grid.absolute_grid);

  const ClaritySnapPlan mesh_center = transform_snap_clarity_plan_get(
      clarity_translate_input(clarity::ClaritySnapMode::MeshCenter));
  EXPECT_TRUE(mesh_center.use_snap);
  EXPECT_EQ(mesh_center.snap_to, SCE_SNAP_TO_VOLUME);
  EXPECT_TRUE(mesh_center.mesh_center);
}

/** The view plane constrains the movement; it has no target to snap onto. */
TEST(transform_snap_clarity_plan, ViewPlaneConstrainsWithoutSnapping)
{
  const ClaritySnapPlan plan = transform_snap_clarity_plan_get(
      clarity_translate_input(clarity::ClaritySnapMode::ViewPlane));

  EXPECT_TRUE(plan.view_plane);
  EXPECT_FALSE(plan.use_snap);
  EXPECT_EQ(plan.snap_to, SCE_SNAP_TO_NONE);
}

/** Step snapping uses the size from the Step Snap widget, not the grid of the scene. */
TEST(transform_snap_clarity_plan, StepSnapUsesTheConfiguredSize)
{
  ClaritySnapPlanInput input = clarity_translate_input(clarity::ClaritySnapMode::Step);
  input.step.mode = clarity::CLARITY_STEP_SNAP_RELATIVE;
  input.step.size = 0.25f;

  const ClaritySnapPlan plan = transform_snap_clarity_plan_get(input);
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
TEST(transform_snap_clarity_plan, AbsoluteStepsNeedGlobalSpace)
{
  ClaritySnapPlanInput input = clarity_translate_input(clarity::ClaritySnapMode::Step);
  input.step.mode = clarity::CLARITY_STEP_SNAP_ABSOLUTE;

  EXPECT_TRUE(transform_snap_clarity_plan_get(input).absolute_grid);

  input.orientation_is_global = false;
  EXPECT_FALSE(transform_snap_clarity_plan_get(input).absolute_grid);
}

/** Clarity steps a rotation or a scale, but never snaps one onto a point, a curve or the grid. */
TEST(transform_snap_clarity_plan, OnlyStepsReachRotationAndScale)
{
  ClaritySnapPlanInput point = clarity_translate_input(clarity::ClaritySnapMode::Point);
  point.is_translation = false;
  const ClaritySnapPlan point_plan = transform_snap_clarity_plan_get(point);
  EXPECT_FALSE(point_plan.use_snap);
  EXPECT_EQ(point_plan.snap_to, SCE_SNAP_TO_NONE);

  ClaritySnapPlanInput step = clarity_translate_input(clarity::ClaritySnapMode::Step);
  step.is_translation = false;
  step.step.size = 15.0f;
  const ClaritySnapPlan step_plan = transform_snap_clarity_plan_get(step);
  EXPECT_TRUE(step_plan.use_snap);
  EXPECT_EQ(step_plan.snap_to, SCE_SNAP_TO_INCREMENT);
  /* A scale counts neither in units nor in radians, so it keeps the increment of its own mode. */
  EXPECT_EQ(step_plan.increment, 0.0f);
}

/**
 * Each transform counts its steps in its own unit: the distance drives a translation, the angle
 * drives a rotation. Handing a rotation the distance is what made a 1 unit step mean 57 degrees.
 */
TEST(transform_snap_clarity_plan, RotationStepsUseTheAngleAndTranslationTheDistance)
{
  ClaritySnapPlanInput input = clarity_translate_input(clarity::ClaritySnapMode::Step);
  input.step.size = 2.0f;
  input.step.angle = 0.5f;

  EXPECT_EQ(transform_snap_clarity_plan_get(input).increment, 2.0f);

  input.is_translation = false;
  input.is_rotation = true;
  EXPECT_EQ(transform_snap_clarity_plan_get(input).increment, 0.5f);

  /* Outside the 3D View the increment belongs to that editor either way. */
  input.space_is_view3d = false;
  EXPECT_EQ(transform_snap_clarity_plan_get(input).increment, 0.0f);
}

/** Outside the 3D View the increment carries the aspect of that editor, so it is left alone. */
TEST(transform_snap_clarity_plan, StepSizeOnlyReplacesTheIncrementInTheViewport)
{
  ClaritySnapPlanInput input = clarity_translate_input(clarity::ClaritySnapMode::Step);
  input.space_is_view3d = false;
  input.step.size = 2.0f;

  EXPECT_EQ(transform_snap_clarity_plan_get(input).increment, 0.0f);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Pivot Snapping
 *
 * Where a drag of the Edit Pivot manipulator leaves the pivot. These are the rules the Clarity capture
 * shows, pinned here so the behavior stops being re-derived from a video.
 * \{ */

static ClarityPivotSnapInput clarity_pivot_input()
{
  ClarityPivotSnapInput input;
  input.applied_position = double3(1.0, 1.0, 1.0);
  input.pointer_position = double3(2.0, 2.0, 2.0);
  input.target_position = double3(5.0, 6.0, 7.0);
  return input;
}

/**
 * Outside the snap tolerance there is no target, and Clarity keeps the pivot on the pointer. Holding it
 * on the last target instead is what looked like a pivot magnetized to a vertex it had left.
 */
TEST(transform_snap_clarity_pivot, PivotFollowsThePointerWithoutATarget)
{
  ClarityPivotSnapInput input = clarity_pivot_input();
  input.has_target = false;

  const ClarityPivotSnapDecision decision = clarity_pivot_snap_decision_get(input);
  EXPECT_EQ(decision.position, input.applied_position);
  EXPECT_FALSE(decision.from_target);
}

/** The magnet: the pivot lands on the target itself, never offset by the drag that took it there. */
TEST(transform_snap_clarity_pivot, PivotLandsExactlyOnTheTarget)
{
  ClarityPivotSnapInput input = clarity_pivot_input();
  input.has_target = true;

  const ClarityPivotSnapDecision decision = clarity_pivot_snap_decision_get(input);
  EXPECT_EQ(decision.position, input.target_position);
  EXPECT_TRUE(decision.from_target);
}

/**
 * A dragged axis or plane handle owns the direction: the pivot slides along it up to the target
 * instead of leaving it. Taking the target verbatim is what moved a pivot dragged by the Z arrow to
 * a vertex beside the axis, which the manipulator trace showed as `applied=(0 0 1)` while the
 * decision returned `(1 1 1)`.
 */
TEST(transform_snap_clarity_pivot, AConstrainedDragKeepsThePivotOnItsConstraint)
{
  ClarityPivotSnapInput input = clarity_pivot_input();
  input.has_target = true;
  input.has_constraint = true;
  /* The Z arrow: only the target's Z reaches the pivot. */
  input.constrained_target_position = double3(0.0, 0.0, 7.0);

  const ClarityPivotSnapDecision decision = clarity_pivot_snap_decision_get(input);
  EXPECT_EQ(decision.position, input.constrained_target_position);
  EXPECT_TRUE(decision.from_target);

  /* Without a constraint the whole target still wins. */
  input.has_constraint = false;
  EXPECT_EQ(clarity_pivot_snap_decision_get(input).position, input.target_position);
}

/** Position snapping off keeps the pointer in charge of the move. */
TEST(transform_snap_clarity_pivot, PositionSnapOffLeavesThePointerInChargeOfTheMove)
{
  ClarityPivotSnapInput input = clarity_pivot_input();
  input.has_target = true;
  input.snap_position = false;

  const ClarityPivotSnapDecision decision = clarity_pivot_snap_decision_get(input);
  EXPECT_EQ(decision.position, input.pointer_position);
  EXPECT_FALSE(decision.from_target);
}

/**
 * A drag places the pivot and never turns it, whatever it snapped to. Clarity keeps the two apart:
 * "hold C or V and middle-drag ... to snap the pivot to that object's edges or vertices" against
 * "click a component to snap and align the pivot to the selected component". Aiming the pivot at
 * every snapped update gave it a new frame each time the element under the pointer changed, so a
 * drag that crossed a corner left the axes turned and the drag could not turn them back.
 *
 * The decision therefore carries a position and the flag saying where it came from, and the drag has
 * nothing else to apply.
 */
TEST(transform_snap_clarity_pivot, ADragPlacesThePivotWithoutTurningIt)
{
  ClarityPivotSnapInput input = clarity_pivot_input();
  input.has_target = true;

  const ClarityPivotSnapDecision snapped = clarity_pivot_snap_decision_get(input);
  EXPECT_EQ(snapped.position, input.target_position);
  EXPECT_TRUE(snapped.from_target);

  /* The same target one update later, after the pointer left it: still only a position. */
  input.has_target = false;
  const ClarityPivotSnapDecision released = clarity_pivot_snap_decision_get(input);
  EXPECT_EQ(released.position, input.applied_position);
  EXPECT_FALSE(released.from_target);
}

/**
 * The click that aligns the pivot with a component reads one vector per hit, and it means something
 * different for each element: a face and a vertex return a normal, an edge returns the direction
 * between its two vertices, a grid intersection returns nothing. Clarity aligns all of them with the
 * pivot's X axis - "the manipulator's X-axis aims at the selected vertex, aligns along the selected
 * edge, and aligns along the face normal of the selected face" - but the kinds still have to be told
 * apart, because only an edge may be reported from either end.
 */
TEST(transform_snap_clarity_pivot, EachElementAimsTheAxisItsVectorBelongsTo)
{
  EXPECT_EQ(clarity_pivot_snap_vector_get(SCE_SNAP_TO_FACE),
            ClarityPivotSnapVector::SurfaceNormal);
  EXPECT_EQ(clarity_pivot_snap_vector_get(SCE_SNAP_TO_FACE_MIDPOINT),
            ClarityPivotSnapVector::SurfaceNormal);
  EXPECT_EQ(clarity_pivot_snap_vector_get(SCE_SNAP_TO_VOLUME),
            ClarityPivotSnapVector::SurfaceNormal);
  /* `cb_snap_edge` stores `v1 - v0`, and the endpoint case deliberately keeps the vertex normal. */
  EXPECT_EQ(clarity_pivot_snap_vector_get(SCE_SNAP_TO_EDGE),
            ClarityPivotSnapVector::EdgeDirection);
  EXPECT_EQ(clarity_pivot_snap_vector_get(SCE_SNAP_TO_EDGE_MIDPOINT),
            ClarityPivotSnapVector::EdgeDirection);
  EXPECT_EQ(clarity_pivot_snap_vector_get(SCE_SNAP_TO_EDGE_PERPENDICULAR),
            ClarityPivotSnapVector::EdgeDirection);
  EXPECT_EQ(clarity_pivot_snap_vector_get(SCE_SNAP_TO_POINT),
            ClarityPivotSnapVector::SurfaceNormal);
  EXPECT_EQ(clarity_pivot_snap_vector_get(SCE_SNAP_TO_EDGE_ENDPOINT),
            ClarityPivotSnapVector::SurfaceNormal);
  /* A grid intersection is a bare position. */
  EXPECT_EQ(clarity_pivot_snap_vector_get(SCE_SNAP_TO_GRID), ClarityPivotSnapVector::None);
  EXPECT_EQ(clarity_pivot_snap_vector_get(SCE_SNAP_TO_NONE), ClarityPivotSnapVector::None);

  EXPECT_EQ(clarity_pivot_snap_aim_axis_get(ClarityPivotSnapVector::SurfaceNormal), 0);
  EXPECT_EQ(clarity_pivot_snap_aim_axis_get(ClarityPivotSnapVector::EdgeDirection), 0);
  EXPECT_EQ(clarity_pivot_snap_aim_axis_get(ClarityPivotSnapVector::None), -1);
}

/**
 * An edge is the one element whose vector cannot be used as it stands: the search returns the line
 * between its two vertices, while the pivot needs the edge's normal - the mean of the faces beside
 * it. The kind says so, and `clarity_pivot_edge_normal_get` rebuilds it before the aim.
 */
TEST(transform_snap_clarity_pivot, OnlyAnEdgeNeedsItsNormalRebuilt)
{
  for (const eSnapMode mode :
       {SCE_SNAP_TO_EDGE, SCE_SNAP_TO_EDGE_MIDPOINT, SCE_SNAP_TO_EDGE_PERPENDICULAR})
  {
    EXPECT_EQ(clarity_pivot_snap_vector_get(mode), ClarityPivotSnapVector::EdgeDirection);
    EXPECT_EQ(clarity_pivot_snap_aim_axis_get(clarity_pivot_snap_vector_get(mode)), 0);
  }
  for (const eSnapMode mode : {SCE_SNAP_TO_FACE,
                               SCE_SNAP_TO_FACE_MIDPOINT,
                               SCE_SNAP_TO_VOLUME,
                               SCE_SNAP_TO_POINT,
                               SCE_SNAP_TO_EDGE_ENDPOINT})
  {
    EXPECT_EQ(clarity_pivot_snap_vector_get(mode), ClarityPivotSnapVector::SurfaceNormal);
  }
}

/** \} */

}  // namespace blender::ed::transform::tests
