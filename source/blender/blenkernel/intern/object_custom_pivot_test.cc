/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

#include "MEM_guardedalloc.h"

#include <cmath>

#include "DNA_object_types.h"

#include "BLI_math_matrix.hh"
#include "BLI_math_quaternion.hh"
#include "BLI_math_vector.hh"

#include "BKE_object_custom_pivot.hh"
#include "BKE_object_types.hh"

#include "testing/testing.h"

namespace blender::bke::tests {

TEST(object_custom_pivot, LazyLocalStorageAndWorldRoundTrip)
{
  Object object{};
  object.runtime = MEM_new<ObjectRuntime>(__func__);
  object.runtime->object_to_world = float4x4::identity();
  object.runtime->object_to_world[0][0] = -2.0f;
  object.runtime->object_to_world[1][0] = 0.35f;
  object.runtime->object_to_world[1][1] = 3.0f;
  object.runtime->object_to_world[2][2] = 0.5f;
  object.runtime->object_to_world.location() = float3(4.0f, -3.0f, 2.0f);

  double3 position;
  EXPECT_FALSE(BKE_object_custom_pivot_position_world_get(object, false, position));
  EXPECT_EQ(object.custom_pivot, nullptr);

  const double3 rotate_world(8.0, 2.0, -1.0);
  const double3 scale_world(-3.0, 6.0, 4.0);
  EXPECT_TRUE(BKE_object_custom_pivot_position_world_set(object, false, rotate_world));
  EXPECT_TRUE(BKE_object_custom_pivot_position_world_set(object, true, scale_world));
  EXPECT_TRUE(BKE_object_custom_pivot_position_world_get(object, false, position));
  EXPECT_NEAR(math::distance(position, rotate_world), 0.0, 1.0e-6);
  EXPECT_TRUE(BKE_object_custom_pivot_position_world_get(object, true, position));
  EXPECT_NEAR(math::distance(position, scale_world), 0.0, 1.0e-6);

  const math::QuaternionBase<double> orientation = math::normalize(
      math::QuaternionBase<double>(0.8, 0.2, -0.4, 0.35));
  EXPECT_TRUE(BKE_object_custom_pivot_orientation_world_set(object, orientation));
  math::QuaternionBase<double> orientation_result;
  EXPECT_TRUE(BKE_object_custom_pivot_orientation_world_get(object, orientation_result));
  EXPECT_NEAR(std::abs(math::dot(orientation, orientation_result)), 1.0, 1.0e-6);

  BKE_object_custom_pivot_reset(object);
  EXPECT_EQ(object.custom_pivot, nullptr);
  MEM_delete(object.runtime);
}

TEST(object_custom_pivot, RotateAndScaleValidityAreIndependent)
{
  Object object{};
  object.runtime = MEM_new<ObjectRuntime>(__func__);
  object.runtime->object_to_world = float4x4::identity();

  /* Writing the rotate pivot must not activate the scale pivot. */
  const double3 rotate_world(1.0, 2.0, 3.0);
  EXPECT_TRUE(BKE_object_custom_pivot_position_world_set(object, false, rotate_world));
  EXPECT_TRUE(BKE_object_custom_pivot_position_valid(object, false));
  EXPECT_FALSE(BKE_object_custom_pivot_position_valid(object, true));
  double3 position;
  EXPECT_FALSE(BKE_object_custom_pivot_position_world_get(object, true, position));

  /* Writing the scale pivot leaves the rotate pivot untouched. */
  const double3 scale_world(-4.0, 0.5, 6.0);
  EXPECT_TRUE(BKE_object_custom_pivot_position_world_set(object, true, scale_world));
  EXPECT_TRUE(BKE_object_custom_pivot_position_valid(object, false));
  EXPECT_TRUE(BKE_object_custom_pivot_position_valid(object, true));
  EXPECT_TRUE(BKE_object_custom_pivot_position_world_get(object, false, position));
  EXPECT_NEAR(math::distance(position, rotate_world), 0.0, 1.0e-6);

  /* Clearing one pivot keeps the other one and its storage. */
  BKE_object_custom_pivot_position_clear(object, false, true);
  ASSERT_NE(object.custom_pivot, nullptr);
  EXPECT_TRUE(BKE_object_custom_pivot_position_valid(object, false));
  EXPECT_FALSE(BKE_object_custom_pivot_position_valid(object, true));

  /* An orientation keeps the storage alive after both positions are cleared. */
  EXPECT_TRUE(BKE_object_custom_pivot_orientation_world_set(
      object, math::normalize(math::QuaternionBase<double>(0.5, 0.5, 0.5, 0.5))));
  BKE_object_custom_pivot_position_clear(object, true, true);
  ASSERT_NE(object.custom_pivot, nullptr);
  EXPECT_TRUE(BKE_object_custom_pivot_orientation_valid(object));

  BKE_object_custom_pivot_orientation_clear(object);
  EXPECT_EQ(object.custom_pivot, nullptr);
  MEM_delete(object.runtime);
}

TEST(object_custom_pivot, MirroredMatrixRoundTripKeepsQuaternionHemisphere)
{
  Object object{};
  object.runtime = MEM_new<ObjectRuntime>(__func__);
  object.runtime->object_to_world = float4x4::identity();
  object.runtime->object_to_world[0][0] = -1.5f;
  object.runtime->object_to_world[0][1] = 0.25f;
  object.runtime->object_to_world[1][0] = 0.4f;
  object.runtime->object_to_world[1][1] = 2.0f;
  object.runtime->object_to_world[2][0] = -0.1f;
  object.runtime->object_to_world[2][2] = 0.75f;
  object.runtime->object_to_world.location() = float3(-5.0f, 3.0f, 7.0f);

  const double3 position_world(2.5, -4.0, 9.0);
  EXPECT_TRUE(BKE_object_custom_pivot_position_world_set(object, false, position_world));
  double3 position_result;
  EXPECT_TRUE(BKE_object_custom_pivot_position_world_get(object, false, position_result));
  EXPECT_NEAR(math::distance(position_result, position_world), 0.0, 1.0e-6);

  const math::QuaternionBase<double> orientation_world = math::normalize(
      math::QuaternionBase<double>(0.2157, -0.5292, 0.7651, 0.2969));
  EXPECT_TRUE(BKE_object_custom_pivot_orientation_world_set(object, orientation_world));

  math::QuaternionBase<double> first_result;
  EXPECT_TRUE(BKE_object_custom_pivot_orientation_world_get(object, first_result));
  EXPECT_GT(math::dot(orientation_world, first_result), 1.0 - 1.0e-6);

  EXPECT_TRUE(BKE_object_custom_pivot_orientation_world_set(object, first_result));
  math::QuaternionBase<double> second_result;
  EXPECT_TRUE(BKE_object_custom_pivot_orientation_world_get(object, second_result));
  EXPECT_GT(math::dot(first_result, second_result), 1.0 - 1.0e-6);

  BKE_object_custom_pivot_reset(object);
  MEM_delete(object.runtime);
}

}  // namespace blender::bke::tests
