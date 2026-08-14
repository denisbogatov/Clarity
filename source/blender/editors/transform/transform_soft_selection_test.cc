/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

#include "testing/testing.h"

#include <limits>

#include "transform.hh"
#include "transform_soft_selection.hh"

namespace blender::ed::transform::tests {

static SoftSelectionSettings two_point_curve(const eTool_SoftSelectionInterpolation interpolation)
{
  SoftSelectionSettings settings;
  settings.curve_point_count = 2;
  settings.curve_points[0] = {1.0f, 0.0f, interpolation, {}};
  settings.curve_points[1] = {0.0f, 1.0f, interpolation, {}};
  return settings;
}

TEST(soft_selection_curve, FactoryCurveUsesPrototypeSmoothRamp)
{
  const SoftSelectionCurve curve{SoftSelectionSettings()};
  EXPECT_FLOAT_EQ(curve.evaluate(0.0f), 1.0f);
  EXPECT_NEAR(curve.evaluate(0.25f), 0.84375f, 1e-6f);
  EXPECT_FLOAT_EQ(curve.evaluate(0.5f), 0.5f);
  EXPECT_NEAR(curve.evaluate(0.75f), 0.15625f, 1e-6f);
  EXPECT_FLOAT_EQ(curve.evaluate(1.0f), 0.0f);
}

TEST(soft_selection_curve, InterpolationBelongsToOutgoingPoint)
{
  SoftSelectionSettings settings = two_point_curve(SOFT_SELECT_INTERP_NONE);
  SoftSelectionCurve none(settings);
  EXPECT_FLOAT_EQ(none.evaluate(0.999f), 1.0f);
  EXPECT_FLOAT_EQ(none.evaluate(1.0f), 0.0f);

  settings.curve_points[0].interpolation = SOFT_SELECT_INTERP_LINEAR;
  SoftSelectionCurve linear(settings);
  EXPECT_FLOAT_EQ(linear.evaluate(0.25f), 0.75f);
  EXPECT_FLOAT_EQ(linear.evaluate(0.75f), 0.25f);
}

TEST(soft_selection_curve, UnsortedAndDuplicateMELPointsAreDeterministic)
{
  SoftSelectionSettings settings;
  settings.curve_point_count = 4;
  settings.curve_points[0] = {0.0f, 1.0f, SOFT_SELECT_INTERP_NONE, {}};
  settings.curve_points[1] = {1.0f, 0.0f, SOFT_SELECT_INTERP_LINEAR, {}};
  settings.curve_points[2] = {0.75f, 0.5f, SOFT_SELECT_INTERP_LINEAR, {}};
  settings.curve_points[3] = {0.25f, 0.5f, SOFT_SELECT_INTERP_LINEAR, {}};
  const SoftSelectionCurve curve(settings);

  EXPECT_FLOAT_EQ(curve.evaluate(0.0f), 1.0f);
  EXPECT_FLOAT_EQ(curve.evaluate(0.5f), 0.25f);
  EXPECT_FLOAT_EQ(curve.evaluate(1.0f), 0.0f);
}

TEST(soft_selection_curve, InvalidPersistentDataFailsClosed)
{
  SoftSelectionSettings settings;
  settings.curve_point_count = 0;
  const SoftSelectionCurve empty(settings);
  EXPECT_FLOAT_EQ(empty.evaluate(0.0f), 1.0f);
  EXPECT_FLOAT_EQ(empty.evaluate(0.1f), 0.0f);
  EXPECT_FLOAT_EQ(empty.evaluate(1.0f), 0.0f);
}

TEST(soft_selection_curve, PersistentDataIsSanitizedBeforeSorting)
{
  SoftSelectionSettings settings;
  settings.curve_point_count = SOFT_SELECTION_CURVE_POINT_MAX + 10;
  settings.curve_points[0].position = std::numeric_limits<float>::quiet_NaN();
  settings.curve_points[0].value = std::numeric_limits<float>::infinity();
  settings.curve_points[0].interpolation = eTool_SoftSelectionInterpolation(127);
  const SoftSelectionCurve curve(settings);

  EXPECT_EQ(curve.size(), SOFT_SELECTION_CURVE_POINT_MAX);
  EXPECT_GE(curve.evaluate(-1.0f), 0.0f);
  EXPECT_LE(curve.evaluate(-1.0f), 1.0f);
  EXPECT_GE(curve.evaluate(std::numeric_limits<float>::quiet_NaN()), 0.0f);
  EXPECT_LE(curve.evaluate(std::numeric_limits<float>::quiet_NaN()), 1.0f);
}

TEST(soft_selection_weight, MatchesTransformBoundaryRules)
{
  const SoftSelectionCurve curve{SoftSelectionSettings()};
  EXPECT_FLOAT_EQ(bke::soft_selection_weight(curve, 100.0f, 5.0f, true), 1.0f);
  EXPECT_FLOAT_EQ(bke::soft_selection_weight(curve, 0.0f, 5.0f, false), 1.0f);
  EXPECT_FLOAT_EQ(bke::soft_selection_weight(curve, 2.5f, 5.0f, false), 0.5f);
  EXPECT_FLOAT_EQ(bke::soft_selection_weight(curve, 5.0f, 5.0f, false), 0.0f);
  EXPECT_FLOAT_EQ(bke::soft_selection_weight(curve, 5.001f, 5.0f, false), 0.0f);
  EXPECT_FLOAT_EQ(bke::soft_selection_weight(curve, 0.0f, 0.0f, false), 0.0f);
  EXPECT_FLOAT_EQ(
      bke::soft_selection_weight(curve, std::numeric_limits<float>::infinity(), 5.0f, false),
      0.0f);
}

TEST(soft_selection_spatial_index, FindsNearestDistanceAndHandlesEmptyInput)
{
  const std::array<float3, 3> positions = {
      float3(-2.0f, 0.0f, 0.0f), float3(2.0f, 0.0f, 0.0f), float3(0.0f, 3.0f, 0.0f)};
  bke::SoftSelectionSpatialIndex *index = bke::soft_selection_spatial_index_create(positions);
  ASSERT_NE(index, nullptr);

  float distance = -1.0f;
  EXPECT_TRUE(bke::soft_selection_spatial_index_nearest_distance(
      index, float3(1.0f, 0.0f, 0.0f), distance));
  EXPECT_FLOAT_EQ(distance, 1.0f);
  bke::soft_selection_spatial_index_free(index);

  EXPECT_EQ(bke::soft_selection_spatial_index_create(Span<float3>()), nullptr);
  EXPECT_FALSE(
      bke::soft_selection_spatial_index_nearest_distance(nullptr, float3(0.0f), distance));
  bke::soft_selection_spatial_index_free(nullptr);
}

TEST(soft_selection_modes, MayaDistancePoliciesAreExplicit)
{
  EXPECT_FALSE(soft_selection_mode_uses_surface_distance(SOFT_SELECT_FALLOFF_VOLUME));
  EXPECT_TRUE(soft_selection_mode_uses_surface_distance(SOFT_SELECT_FALLOFF_SURFACE));
  EXPECT_FALSE(soft_selection_mode_uses_surface_distance(SOFT_SELECT_FALLOFF_GLOBAL));

  EXPECT_FALSE(soft_selection_mode_affects_unselected_containers(SOFT_SELECT_FALLOFF_VOLUME));
  EXPECT_FALSE(soft_selection_mode_affects_unselected_containers(SOFT_SELECT_FALLOFF_SURFACE));
  EXPECT_TRUE(soft_selection_mode_affects_unselected_containers(SOFT_SELECT_FALLOFF_GLOBAL));
}

TEST(soft_selection_feedback, BlenderProportionalCircleIsBackendAware)
{
  EXPECT_FALSE(transform_should_draw_proportional_circle(0));
  EXPECT_TRUE(transform_should_draw_proportional_circle(T_PROP_EDIT));
  EXPECT_FALSE(transform_should_draw_proportional_circle(T_PROP_EDIT | T_SOFT_SELECTION));
  EXPECT_FALSE(transform_should_draw_proportional_circle(T_SOFT_SELECTION));
}

}  // namespace blender::ed::transform::tests
