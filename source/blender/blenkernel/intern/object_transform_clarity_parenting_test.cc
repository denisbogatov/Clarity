/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

#include <algorithm>
#include <array>
#include <cmath>
#include <cstring>

#include "DNA_action_types.h"
#include "DNA_armature_types.h"
#include "DNA_object_types.h"

#include "BLI_listbase.h"
#include "BLI_math_matrix.h"
#include "BLI_math_matrix.hh"
#include "BLI_math_vector.h"
#include "BLI_string.h"

#include "BKE_action.hh"
#include "BKE_armature.hh"
#include "BKE_lib_id.hh"
#include "BKE_main.hh"
#include "BKE_object.hh"
#include "BKE_object_transform_clarity.hh"
#include "BKE_object_types.hh"

#include "MEM_guardedalloc.h"

#include "testing/testing.h"

namespace blender::bke::tests {

static void expect_matrix_near(const double4x4 &actual,
                               const double4x4 &expected,
                               const double epsilon = 1.0e-11)
{
  for (int index = 0; index < 16; index++) {
    EXPECT_NEAR(actual.base_ptr()[index], expected.base_ptr()[index], epsilon);
  }
}

static double4x4 translation_matrix(const double3 &translation)
{
  double4x4 matrix = double4x4::identity();
  matrix.location() = translation;
  return matrix;
}

static ClarityObjectTransform *clarity_transform_create(Object &object)
{
  object.transform_model = OBJECT_TRANSFORM_CLARITY;
  return BKE_object_clarity_transform_ensure(&object);
}

TEST(object_transform_clarity_parenting, MatrixLayers)
{
  ClarityObjectTransform transform;
  transform.translation[0] = 1.0;
  transform.translation[1] = -2.0;
  transform.translation[2] = 3.0;
  const double4x4 offset_parent_matrix = translation_matrix({4.0, 5.0, -6.0});
  std::copy_n(offset_parent_matrix.base_ptr(), 16, &transform.offset_parent_matrix[0][0]);

  const double4x4 channel_matrix = BKE_clarity_transform_channel_matrix(transform);
  const double4x4 dag_local_matrix = BKE_clarity_transform_dag_local_matrix(transform);
  expect_matrix_near(dag_local_matrix, offset_parent_matrix * channel_matrix);

  const double4x4 parent_effect_matrix = translation_matrix({10.0, 20.0, 30.0});
  expect_matrix_near(BKE_clarity_transform_world_matrix(transform, parent_effect_matrix),
                     parent_effect_matrix * dag_local_matrix);

  transform.inherits_transform = false;
  expect_matrix_near(BKE_clarity_transform_world_matrix(transform, parent_effect_matrix),
                     dag_local_matrix);
}

TEST(object_transform_clarity_parenting, ObjectPathsUseSameMatrix)
{
  Object parent;
  Object child;
  ObjectRuntime parent_runtime;
  ObjectRuntime child_runtime;
  parent.runtime = &parent_runtime;
  child.runtime = &child_runtime;

  parent.runtime->object_to_world = float4x4(translation_matrix({3.0, -4.0, 5.0}));
  child.partype = PAROBJECT;
  ClarityObjectTransform *transform = clarity_transform_create(child);
  transform->translation[0] = 1.25;
  transform->translation[1] = 2.5;
  transform->translation[2] = -3.75;

  const double4x4 dag_local_matrix = BKE_clarity_transform_dag_local_matrix(*transform);
  expect_matrix_near(BKE_object_local_matrix_get_double(&child), dag_local_matrix);
  float local_matrix[4][4];
  BKE_object_local_matrix_get(&child, local_matrix);
  expect_matrix_near(double4x4(float4x4(local_matrix)), dag_local_matrix, 1.0e-6);

  float matrix[4][4];
  BKE_object_where_is_calc_mat4(&child, matrix);
  expect_matrix_near(double4x4(float4x4(matrix)), dag_local_matrix, 1.0e-6);

  child.parent = &parent;
  BKE_object_where_is_calc_mat4(&child, matrix);
  const double4x4 expected = double4x4(parent.object_to_world()) * dag_local_matrix;
  expect_matrix_near(double4x4(float4x4(matrix)), expected, 1.0e-6);
  BKE_object_matrix_local_get(&child, matrix);
  expect_matrix_near(double4x4(float4x4(matrix)), dag_local_matrix, 1.0e-6);

  transform->inherits_transform = false;
  BKE_object_where_is_calc_mat4(&child, matrix);
  expect_matrix_near(
      double4x4(float4x4(matrix)), BKE_clarity_transform_dag_local_matrix(*transform), 1.0e-6);

  MEM_SAFE_DELETE(child.clarity_transform);
}

TEST(object_transform_clarity_parenting, ParentAndClearKeepWorldTransform)
{
  Object first_parent;
  Object second_parent;
  Object child;
  ObjectRuntime first_parent_runtime;
  ObjectRuntime second_parent_runtime;
  ObjectRuntime child_runtime;
  first_parent.runtime = &first_parent_runtime;
  second_parent.runtime = &second_parent_runtime;
  child.runtime = &child_runtime;

  double4x4 first_parent_effect = translation_matrix({7.0, -3.0, 2.0});
  first_parent_effect[0][0] = -2.0;
  first_parent_effect[1][1] = 0.5;
  first_parent_effect[2][2] = 1.5;
  first_parent.runtime->object_to_world = float4x4(first_parent_effect);

  double4x4 second_parent_effect = translation_matrix({-2.0, 8.0, -5.0});
  second_parent_effect[0][0] = 0.75;
  second_parent_effect[1][1] = 1.25;
  second_parent_effect[2][2] = -1.5;
  second_parent.runtime->object_to_world = float4x4(second_parent_effect);

  ClarityObjectTransform *transform = clarity_transform_create(child);
  transform->translation[0] = -4.0;
  transform->translation[1] = 6.0;
  transform->translation[2] = 1.0;
  transform->rotation[0] = 0.2;
  transform->rotation[1] = -0.4;
  transform->rotation[2] = 0.7;
  transform->scale[0] = 1.5;
  transform->scale[1] = -0.75;
  transform->scale[2] = 2.0;

  const double4x4 world_before = BKE_clarity_transform_dag_local_matrix(*transform);
  child.parent = &first_parent;
  child.partype = PAROBJECT;
  ASSERT_TRUE(BKE_object_clarity_parent_keep_transform(&child, first_parent_effect, world_before));

  float world_after_parenting[4][4];
  BKE_object_where_is_calc_mat4(&child, world_after_parenting);
  expect_matrix_near(double4x4(float4x4(world_after_parenting)), world_before, 1.0e-5);
  expect_matrix_near(double4x4(float4x4(child.parentinv)), double4x4::identity(), 1.0e-7);
  EXPECT_LT(math::determinant(double4x4(float4x4(world_after_parenting))), 0.0);

  child.parent = &second_parent;
  ASSERT_TRUE(BKE_object_clarity_parent_keep_transform(&child, second_parent_effect, world_before));
  float world_after_reparenting[4][4];
  BKE_object_where_is_calc_mat4(&child, world_after_reparenting);
  expect_matrix_near(double4x4(float4x4(world_after_reparenting)), world_before, 1.0e-5);
  expect_matrix_near(double4x4(float4x4(child.parentinv)), double4x4::identity(), 1.0e-7);

  const double4x4 parented_world{float4x4(world_after_reparenting)};
  child.parent = nullptr;
  ASSERT_TRUE(BKE_object_clarity_clear_parent_keep_transform(&child, parented_world));

  float world_after_clear[4][4];
  BKE_object_where_is_calc_mat4(&child, world_after_clear);
  expect_matrix_near(double4x4(float4x4(world_after_clear)), parented_world, 1.0e-5);

  MEM_SAFE_DELETE(child.clarity_transform);
}

TEST(object_transform_clarity_parenting, TransformChannelCopyIsDeep)
{
  Object source;
  Object destination;
  ClarityObjectTransform *source_transform = clarity_transform_create(source);
  source_transform->translation[0] = 8.0;
  source_transform->rotate_axis[1] = 0.25;
  source_transform->rotation_order = CLARITY_ROT_ORDER_YZX;

  BKE_object_tfm_copy(&destination, &source);

  ASSERT_TRUE(BKE_object_uses_clarity_transform(&destination));
  ASSERT_NE(destination.clarity_transform, source.clarity_transform);
  EXPECT_DOUBLE_EQ(destination.clarity_transform->translation[0], 8.0);
  EXPECT_DOUBLE_EQ(destination.clarity_transform->rotate_axis[1], 0.25);
  EXPECT_EQ(destination.clarity_transform->rotation_order, CLARITY_ROT_ORDER_YZX);

  source.clarity_transform->translation[0] = -10.0;
  EXPECT_DOUBLE_EQ(destination.clarity_transform->translation[0], 8.0);

  MEM_SAFE_DELETE(source.clarity_transform);
  MEM_SAFE_DELETE(destination.clarity_transform);
}

TEST(object_transform_clarity_parenting, PivotCentersAndAxesUseClarityPrefixes)
{
  Object object;
  ClarityObjectTransform *transform = clarity_transform_create(object);
  transform->translation[0] = 2.0;
  transform->translation[1] = -3.0;
  transform->rotate_pivot_translate[0] = 0.5;
  transform->rotate_pivot[1] = 4.0;
  transform->scale_pivot_translate[2] = -1.0;
  transform->scale_pivot[0] = 3.0;
  transform->rotation[2] = 0.4;
  transform->rotate_axis[1] = -0.25;

  const double4x4 parent_effect = translation_matrix({10.0, 20.0, 30.0});
  const double3 rotate_center = BKE_object_clarity_rotate_pivot_world_get(object, parent_effect);
  EXPECT_NEAR(rotate_center.x, 12.5, 1.0e-12);
  EXPECT_NEAR(rotate_center.y, 21.0, 1.0e-12);
  EXPECT_NEAR(rotate_center.z, 30.0, 1.0e-12);

  const double3 scale_center = BKE_object_clarity_scale_pivot_world_get(object, parent_effect);
  EXPECT_TRUE(std::isfinite(scale_center.x));
  EXPECT_TRUE(std::isfinite(scale_center.y));
  EXPECT_TRUE(std::isfinite(scale_center.z));

  float local_axis[3][3];
  float parent_axis[3][3];
  float gimbal_axis[3][3];
  EXPECT_TRUE(BKE_object_clarity_local_axis_world_get(object, parent_effect, local_axis));
  EXPECT_TRUE(BKE_object_clarity_parent_axis_world_get(object, parent_effect, parent_axis));
  EXPECT_TRUE(BKE_object_clarity_gimbal_axis_world_get(object, parent_effect, gimbal_axis));
  const std::array<const float (*)[3], 3> axis_matrices = {local_axis, parent_axis, gimbal_axis};
  for (const float (*axis_matrix)[3] : axis_matrices) {
    for (int axis = 0; axis < 3; axis++) {
      EXPECT_NEAR(len_v3(axis_matrix[axis]), 1.0f, 1.0e-6f);
    }
    EXPECT_NEAR(determinant_m3_array(axis_matrix), 1.0f, 1.0e-5f);
  }

  MEM_SAFE_DELETE(object.clarity_transform);
}

TEST(object_transform_clarity_parenting, PivotWorldSettersPreserveMatrix)
{
  Object object;
  ClarityObjectTransform *transform = clarity_transform_create(object);
  transform->translation[0] = 2.0;
  transform->translation[1] = -3.0;
  transform->rotation[0] = 0.4;
  transform->rotation[1] = -0.25;
  transform->rotate_axis[2] = 0.2;
  transform->scale[0] = -2.0;
  transform->scale[1] = 0.75;
  transform->scale[2] = 1.5;
  transform->shear[0] = 0.3;
  transform->shear[2] = -0.2;

  double4x4 offset_parent_matrix = translation_matrix({1.0, -2.0, 0.5});
  offset_parent_matrix[1][0] = 0.25;
  std::copy_n(
      offset_parent_matrix.base_ptr(), 16, &transform->offset_parent_matrix[0][0]);
  double4x4 parent_effect = translation_matrix({10.0, 20.0, 30.0});
  parent_effect[0][0] = 0.5;
  parent_effect[1][1] = -1.25;
  parent_effect[2][2] = 2.0;

  const double4x4 matrix_before = BKE_clarity_transform_world_matrix(*transform, parent_effect);
  const double3 target_world = {9.25, -4.5, 6.75};
  ASSERT_TRUE(
      BKE_object_clarity_rotate_pivot_world_set(object, parent_effect, target_world, true));
  ASSERT_TRUE(
      BKE_object_clarity_scale_pivot_world_set(object, parent_effect, target_world, true));

  expect_matrix_near(BKE_clarity_transform_world_matrix(*transform, parent_effect), matrix_before);
  EXPECT_NEAR(BKE_object_clarity_rotate_pivot_world_get(object, parent_effect).x,
              target_world.x,
              1.0e-11);
  EXPECT_NEAR(BKE_object_clarity_rotate_pivot_world_get(object, parent_effect).y,
              target_world.y,
              1.0e-11);
  EXPECT_NEAR(BKE_object_clarity_rotate_pivot_world_get(object, parent_effect).z,
              target_world.z,
              1.0e-11);
  EXPECT_NEAR(BKE_object_clarity_scale_pivot_world_get(object, parent_effect).x,
              target_world.x,
              1.0e-11);
  EXPECT_NEAR(BKE_object_clarity_scale_pivot_world_get(object, parent_effect).y,
              target_world.y,
              1.0e-11);
  EXPECT_NEAR(BKE_object_clarity_scale_pivot_world_get(object, parent_effect).z,
              target_world.z,
              1.0e-11);

  MEM_SAFE_DELETE(object.clarity_transform);
}

TEST(object_transform_clarity_parenting, TransformModelConversionPreservesWorld)
{
  Object object;
  ObjectRuntime runtime;
  object.runtime = &runtime;
  object.loc[0] = 2.0f;
  object.loc[1] = -4.0f;
  object.loc[2] = 6.0f;
  object.rot[0] = 0.2f;
  object.rot[1] = -0.5f;
  object.rot[2] = 0.7f;
  object.scale[0] = -1.5f;
  object.scale[1] = 0.75f;
  object.scale[2] = 2.0f;
  BKE_object_where_is_calc_mat4(&object, object.runtime->object_to_world.ptr());
  const double4x4 world_before(object.object_to_world());

  ASSERT_TRUE(BKE_object_transform_model_set(object, OBJECT_TRANSFORM_CLARITY));
  ASSERT_TRUE(BKE_object_uses_clarity_transform(&object));
  float clarity_world[4][4];
  BKE_object_where_is_calc_mat4(&object, clarity_world);
  expect_matrix_near(double4x4(float4x4(clarity_world)), world_before, 1.0e-5);

  ASSERT_TRUE(BKE_object_transform_model_set(object, OBJECT_TRANSFORM_BLENDER));
  EXPECT_FALSE(BKE_object_uses_clarity_transform(&object));
  EXPECT_EQ(object.clarity_transform, nullptr);
  float blender_world[4][4];
  BKE_object_where_is_calc_mat4(&object, blender_world);
  expect_matrix_near(double4x4(float4x4(blender_world)), world_before, 1.0e-5);
}

TEST(object_transform_clarity_parenting, TransformModelConversionFailureIsAtomic)
{
  Object object;
  ObjectRuntime runtime;
  object.runtime = &runtime;
  ClarityObjectTransform *transform = clarity_transform_create(object);
  transform->translation[0] = 3.0;
  transform->rotation[1] = 0.4;
  transform->scale[2] = -2.0;
  transform->shear[0] = 0.75;
  BKE_object_where_is_calc_mat4(&object, object.runtime->object_to_world.ptr());

  const ClarityObjectTransform before = *transform;
  EXPECT_FALSE(BKE_object_transform_model_set(object, OBJECT_TRANSFORM_BLENDER));
  EXPECT_TRUE(BKE_object_uses_clarity_transform(&object));
  EXPECT_EQ(memcmp(object.clarity_transform, &before, sizeof(before)), 0);

  MEM_SAFE_DELETE(object.clarity_transform);
}

TEST(object_transform_clarity_parenting, BoneParentUsesBlenderParentEffect)
{
  Main *bmain = BKE_main_new();
  bArmature *armature = BKE_armature_add(bmain, "Clarity Parent Armature");
  Bone *bone = MEM_new<Bone>(__func__);
  STRNCPY(bone->name, "Clarity Parent Bone");
  bone->length = 2.0f;
  BLI_addtail(&armature->bonebase, bone);

  Object *parent = BKE_object_add_only_object(bmain, OB_ARMATURE, "Clarity Parent");
  parent->data = &armature->id;
  id_us_plus(&armature->id);
  BKE_pose_rebuild(bmain, parent, armature, true);
  bPoseChannel *pose_channel = BKE_pose_channel_find_name(parent->pose, bone->name);
  ASSERT_NE(pose_channel, nullptr);

  parent->runtime->object_to_world = float4x4(translation_matrix({5.0, -1.0, 3.0}));
  const float4x4 bone_matrix = float4x4(translation_matrix({0.0, 4.0, 0.0}));
  copy_m4_m4(pose_channel->pose_mat, bone_matrix.ptr());

  Object *child = BKE_object_add_only_object(bmain, OB_EMPTY, "Clarity Child");
  child->parent = parent;
  child->partype = PARBONE;
  child->parent_bone_head_tail_factor = 0.0f;
  STRNCPY(child->parsubstr, bone->name);
  ClarityObjectTransform *transform = clarity_transform_create(*child);
  transform->translation[0] = 1.0;

  float parent_effect[4][4];
  BKE_object_get_parent_matrix(child, parent, parent_effect);
  float world_matrix[4][4];
  BKE_object_where_is_calc_mat4(child, world_matrix);
  expect_matrix_near(double4x4(float4x4(world_matrix)),
                     double4x4(float4x4(parent_effect)) *
                         BKE_clarity_transform_dag_local_matrix(*transform),
                     1.0e-6);

  BKE_main_free(bmain);
}

}  // namespace blender::bke::tests
