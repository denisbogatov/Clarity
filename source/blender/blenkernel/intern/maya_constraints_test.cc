/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

#include "testing/testing.h"

#include "MEM_guardedalloc.h"

#include "BKE_maya_constraints.hh"
#include "BKE_object.hh"
#include "BKE_object_transform_maya.hh"
#include "BKE_object_types.hh"

namespace blender::bke::tests {

static void maya_object_initialize(Object &object,
                                   ObjectRuntime &runtime,
                                   const double3 &translation,
                                   const double3 &rotate_pivot)
{
  object.runtime = &runtime;
  object.transform_model = OBJECT_TRANSFORM_MAYA;
  object.maya_transform = MEM_new<MayaObjectTransform>(__func__);
  BKE_maya_transform_set_defaults(*object.maya_transform);
  for (int axis = 0; axis < 3; axis++) {
    object.maya_transform->translation[axis] = translation[axis];
    object.maya_transform->rotate_pivot[axis] = rotate_pivot[axis];
  }
  runtime.maya_transform.evaluated = *object.maya_transform;
  runtime.maya_transform.valid = true;
  runtime.object_to_world = float4x4(BKE_maya_transform_dag_local_matrix(
      runtime.maya_transform.evaluated));
}

TEST(maya_constraints, PointConstraintWeightedChannelsAndSkipAxes)
{
  Object constrained{};
  Object target_a{};
  Object target_b{};
  ObjectRuntime constrained_runtime;
  ObjectRuntime target_a_runtime;
  ObjectRuntime target_b_runtime;
  maya_object_initialize(
      constrained, constrained_runtime, double3(1.0, 2.0, 3.0), double3(0.5, 0.0, 0.0));
  maya_object_initialize(
      target_a, target_a_runtime, double3(3.0, 4.0, 5.0), double3(1.0, 0.0, 0.0));
  maya_object_initialize(
      target_b, target_b_runtime, double3(9.0, 1.0, -1.0), double3(-1.0, 1.0, 0.0));

  MayaConstraint *constraint = BKE_maya_constraint_add(
      constrained, MAYA_CONSTRAINT_POINT, "pointConstraint1");
  BKE_maya_constraint_target_add(*constraint, target_a, 1.0);
  BKE_maya_constraint_target_add(*constraint, target_b, 3.0);
  constraint->skip_translate[1] = true;

  const double4x4 parent_effect = double4x4::identity();
  const MayaConstraintEvalContext context{constrained, parent_effect};
  MayaConstraintChannelOutput output;
  ASSERT_TRUE(BKE_maya_point_constraint_evaluate(*constraint, context, output));
  ASSERT_TRUE(output.translation.has_value());

  /* Target rotate-pivot world positions are (4, 4, 5) and (8, 2, -1).
   * Their 1:3 weighted average is (7, 2.5, 0.5). The constrained rotate pivot is 0.5 X. */
  EXPECT_DOUBLE_EQ((*output.translation).x, 6.5);
  EXPECT_DOUBLE_EQ((*output.translation).y, 2.5);
  EXPECT_DOUBLE_EQ((*output.translation).z, 0.5);
  EXPECT_TRUE(output.translation_mask[0]);
  EXPECT_FALSE(output.translation_mask[1]);
  EXPECT_TRUE(output.translation_mask[2]);

  BKE_maya_constraint_output_apply(constrained, output);
  EXPECT_DOUBLE_EQ(constrained.runtime->maya_transform.evaluated.translation[0], 6.5);
  EXPECT_DOUBLE_EQ(constrained.runtime->maya_transform.evaluated.translation[1], 2.0);
  EXPECT_DOUBLE_EQ(constrained.runtime->maya_transform.evaluated.translation[2], 0.5);
  EXPECT_TRUE(constrained.runtime->maya_transform.translation_driven[0]);
  EXPECT_FALSE(constrained.runtime->maya_transform.translation_driven[1]);
  EXPECT_TRUE(constrained.runtime->maya_transform.translation_driven[2]);
  EXPECT_DOUBLE_EQ(constrained.maya_transform->translation[0], 1.0);
  EXPECT_DOUBLE_EQ(constrained.maya_transform->translation[1], 2.0);
  EXPECT_DOUBLE_EQ(constrained.maya_transform->translation[2], 3.0);

  BKE_maya_constraints_clear(constrained);
  MEM_SAFE_DELETE(constrained.maya_transform);
  MEM_SAFE_DELETE(target_a.maya_transform);
  MEM_SAFE_DELETE(target_b.maya_transform);
}

TEST(maya_constraints, TransformCapabilitiesAreExplicit)
{
  Object object{};
  object.type = OB_MESH;
  MayaTransformCapabilities capabilities = BKE_maya_transform_capabilities_get(object);
  EXPECT_TRUE(capabilities.bake_position);
  EXPECT_TRUE(capabilities.bake_orientation);
  EXPECT_TRUE(capabilities.geometry_compensation);

  object.type = OB_CURVES_LEGACY;
  capabilities = BKE_maya_transform_capabilities_get(object);
  EXPECT_TRUE(capabilities.edit_pivot_position);
  EXPECT_FALSE(capabilities.bake_position);

  object.type = OB_ARMATURE;
  capabilities = BKE_maya_transform_capabilities_get(object);
  EXPECT_FALSE(capabilities.bake_orientation);
  EXPECT_FALSE(capabilities.preserve_children);
}

}  // namespace blender::bke::tests
