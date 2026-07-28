/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

#include <algorithm>
#include <array>
#include <cmath>
#include <cstring>
#include <random>

#include "DNA_object_types.h"

#include "BLI_math_constants.h"
#include "BLI_math_rotation.h"

#include "BKE_object.hh"
#include "BKE_object_transform_maya.hh"

#include "MEM_guardedalloc.h"

#include "testing/testing.h"

namespace blender::bke::tests {

using RowMatrix = std::array<double, 16>;

static RowMatrix row_identity()
{
  return {1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0};
}

static RowMatrix row_multiply(const RowMatrix &a, const RowMatrix &b)
{
  RowMatrix result = {};
  for (int row = 0; row < 4; row++) {
    for (int column = 0; column < 4; column++) {
      for (int index = 0; index < 4; index++) {
        result[row * 4 + column] += a[row * 4 + index] * b[index * 4 + column];
      }
    }
  }
  return result;
}

static RowMatrix row_translation(const double translation[3], const double sign = 1.0)
{
  RowMatrix matrix = row_identity();
  matrix[12] = sign * translation[0];
  matrix[13] = sign * translation[1];
  matrix[14] = sign * translation[2];
  return matrix;
}

static RowMatrix row_scale(const double scale[3])
{
  RowMatrix matrix = row_identity();
  matrix[0] = scale[0];
  matrix[5] = scale[1];
  matrix[10] = scale[2];
  return matrix;
}

static RowMatrix row_shear(const double shear[3])
{
  RowMatrix matrix = row_identity();
  matrix[4] = shear[0];
  matrix[8] = shear[1];
  matrix[9] = shear[2];
  return matrix;
}

static RowMatrix row_axis_rotation(const int axis, const double angle)
{
  const double cosine = std::cos(angle);
  const double sine = std::sin(angle);
  RowMatrix matrix = row_identity();
  switch (axis) {
    case 0:
      matrix[5] = cosine;
      matrix[6] = sine;
      matrix[9] = -sine;
      matrix[10] = cosine;
      break;
    case 1:
      matrix[0] = cosine;
      matrix[2] = -sine;
      matrix[8] = sine;
      matrix[10] = cosine;
      break;
    case 2:
      matrix[0] = cosine;
      matrix[1] = sine;
      matrix[4] = -sine;
      matrix[5] = cosine;
      break;
  }
  return matrix;
}

static std::array<int, 3> rotation_axes(const eMayaRotationOrder rotation_order)
{
  switch (rotation_order) {
    case MAYA_ROT_ORDER_YZX:
      return {1, 2, 0};
    case MAYA_ROT_ORDER_ZXY:
      return {2, 0, 1};
    case MAYA_ROT_ORDER_XZY:
      return {0, 2, 1};
    case MAYA_ROT_ORDER_YXZ:
      return {1, 0, 2};
    case MAYA_ROT_ORDER_ZYX:
      return {2, 1, 0};
    case MAYA_ROT_ORDER_XYZ:
    default:
      return {0, 1, 2};
  }
}

static RowMatrix row_euler_rotation(const double rotation[3],
                                    const eMayaRotationOrder rotation_order)
{
  RowMatrix matrix = row_identity();
  for (const int axis : rotation_axes(rotation_order)) {
    matrix = row_multiply(matrix, row_axis_rotation(axis, rotation[axis]));
  }
  return matrix;
}

/**
 * Independent implementation of the row-vector formula published in Maya's xform
 * documentation. Blender's column-major storage has the same flat element order as the
 * transposed Maya row-vector matrix.
 */
static RowMatrix maya_row_reference_matrix(const MayaObjectTransform &transform)
{
  RowMatrix matrix = row_translation(transform.scale_pivot, -1.0);
  matrix = row_multiply(matrix, row_scale(transform.scale));
  matrix = row_multiply(matrix, row_shear(transform.shear));
  matrix = row_multiply(matrix, row_translation(transform.scale_pivot));
  matrix = row_multiply(matrix, row_translation(transform.scale_pivot_translate));
  matrix = row_multiply(matrix, row_translation(transform.rotate_pivot, -1.0));
  matrix = row_multiply(matrix, row_euler_rotation(transform.rotate_axis, MAYA_ROT_ORDER_XYZ));
  matrix = row_multiply(matrix, row_euler_rotation(transform.rotation, transform.rotation_order));
  matrix = row_multiply(matrix, row_translation(transform.rotate_pivot));
  matrix = row_multiply(matrix, row_translation(transform.rotate_pivot_translate));
  matrix = row_multiply(matrix, row_translation(transform.translation));

  RowMatrix offset_parent_matrix;
  std::copy(&transform.offset_parent_matrix[0][0],
            &transform.offset_parent_matrix[0][0] + 16,
            offset_parent_matrix.begin());
  return row_multiply(matrix, offset_parent_matrix);
}

static MayaObjectTransform full_reference_transform()
{
  MayaObjectTransform transform;
  const double degrees_to_radians = M_PI / 180.0;

  const double translation[3] = {1.25, -2.5, 3.75};
  const double rotation[3] = {
      20.0 * degrees_to_radians, -35.0 * degrees_to_radians, 70.0 * degrees_to_radians};
  const double rotate_axis[3] = {
      11.0 * degrees_to_radians, -7.0 * degrees_to_radians, 5.0 * degrees_to_radians};
  const double scale[3] = {2.0, -0.5, 1.25};
  const double shear[3] = {0.2, -0.3, 0.4};
  const double rotate_pivot[3] = {0.75, -1.5, 2.25};
  const double rotate_pivot_translate[3] = {-0.125, 0.25, 0.5};
  const double scale_pivot[3] = {-0.5, 1.0, -1.25};
  const double scale_pivot_translate[3] = {0.375, -0.625, 0.875};

  std::copy_n(translation, 3, transform.translation);
  std::copy_n(rotation, 3, transform.rotation);
  std::copy_n(rotate_axis, 3, transform.rotate_axis);
  std::copy_n(scale, 3, transform.scale);
  std::copy_n(shear, 3, transform.shear);
  std::copy_n(rotate_pivot, 3, transform.rotate_pivot);
  std::copy_n(rotate_pivot_translate, 3, transform.rotate_pivot_translate);
  std::copy_n(scale_pivot, 3, transform.scale_pivot);
  std::copy_n(scale_pivot_translate, 3, transform.scale_pivot_translate);
  return transform;
}

TEST(object_transform_maya, Maya2025ReferenceAllRotationOrders)
{
  /* Captured from Maya 2025's transform.matrix attribute in Blender Euler-order sequence. */
  static constexpr std::array<std::array<double, 16>, 6> expected = {{
      {0.4230623939113318,
       1.3939627841034778,
       1.3703597948686668,
       0.0,
       0.4446924343015535,
       -0.03568828990191478,
       -0.24693113379814094,
       0.0,
       -0.17603598645314067,
       -1.1876977583789183,
       0.7151995289533979,
       0.0,
       -1.2853977546826654,
       -3.365476406134347,
       6.728796744857546,
       1.0},
      {0.3277521389326403,
       1.8853713051278778,
       0.5813377479791603,
       0.0,
       0.4736066060394154,
       -0.18892848174319715,
       0.0016767534214695116,
       0.0,
       -0.6926884401513247,
       -0.6023170010529961,
       1.0538130551114129,
       0.0,
       -0.9848554739006041,
       -3.119870800737566,
       5.230163721916232,
       1.0},
      {0.7821673966271256,
       1.290405869377882,
       1.312656411986266,
       0.0,
       0.41064411765009645,
       -0.12303041927453284,
       -0.27610672677880643,
       0.0,
       -0.35291753424902295,
       -1.1271863668947866,
       0.7470107819209318,
       0.0,
       -1.1258092154376609,
       -2.7540238771333354,
       6.937602476825599,
       1.0},
      {0.3436463744613969,
       0.9063374835726462,
       1.7494169129143402,
       0.0,
       0.47513055110341507,
       -0.09898903604222123,
       -0.1563717690364756,
       0.0,
       -0.5960559377817802,
       -1.2224386331064392,
       0.3216925664729344,
       0.0,
       -1.0873461540141764,
       -2.5981802703487493,
       6.206509136967544,
       1.0},
      {-0.08666348808437974,
       1.718451882447744,
       1.0195158495800125,
       0.0,
       0.46890523856480154,
       -0.16235308648214827,
       0.11734288455720976,
       0.0,
       -0.907284717339724,
       -0.856061318531094,
       0.6301733575743917,
       0.0,
       -0.5117525237374932,
       -2.9821135985226346,
       4.524630875669347,
       1.0},
      {0.2810609195807241,
       1.6327374335200393,
       1.1203451399755486,
       0.0,
       0.43107728146860985,
       -0.25751920205336254,
       0.08863542167458935,
       0.0,
       -1.039365196587534,
       -0.7028101685625762,
       0.6155508549970508,
       0.0,
       -0.3697307095490506,
       -2.4070247968144014,
       4.670813853721821,
       1.0},
  }};

  static constexpr std::array<int, 6> expected_index = {0, 3, 4, 1, 2, 5};
  for (int rotation_order = MAYA_ROT_ORDER_XYZ; rotation_order <= MAYA_ROT_ORDER_ZYX;
       rotation_order++)
  {
    SCOPED_TRACE(rotation_order);
    MayaObjectTransform transform = full_reference_transform();
    transform.rotation_order = eMayaRotationOrder(rotation_order);
    const double4x4 result = BKE_maya_transform_dag_local_matrix(transform);
    for (int index = 0; index < 16; index++) {
      EXPECT_NEAR(
          result.base_ptr()[index], expected[expected_index[rotation_order]][index], 1.0e-12);
    }
  }
}

TEST(object_transform_maya, Maya2025ReferenceOffsetParentMatrix)
{
  MayaObjectTransform transform = full_reference_transform();
  transform.rotation_order = MAYA_ROT_ORDER_YXZ;
  const double offset_parent_matrix[16] = {0.8660254037844386,
                                           0.0,
                                           -0.5,
                                           0.0,
                                           0.0,
                                           1.0,
                                           0.0,
                                           0.0,
                                           0.5,
                                           0.0,
                                           0.8660254037844386,
                                           0.0,
                                           4.0,
                                           -1.0,
                                           2.0,
                                           1.0};
  std::copy_n(offset_parent_matrix, 16, &transform.offset_parent_matrix[0][0]);

  const double expected[16] = {1.3337050414841627,
                               1.290405869377882,
                               0.7457101009070757,
                               0.0,
                               0.21757487441022605,
                               -0.12303041927453284,
                               -0.44443749837126373,
                               0.0,
                               0.06786984085984737,
                               -1.1271863668947866,
                               0.8233890811689156,
                               0.0,
                               6.493821858029158,
                               -3.7540238771333354,
                               8.571044594007642,
                               1.0};
  const double4x4 result = BKE_maya_transform_dag_local_matrix(transform);
  for (int index = 0; index < 16; index++) {
    EXPECT_NEAR(result.base_ptr()[index], expected[index], 1.0e-12);
  }
}

TEST(object_transform_maya, RandomizedAgainstMayaRowFormula)
{
  std::mt19937 random(0x4d415941);
  std::uniform_real_distribution<double> value_distribution(-2.0, 2.0);
  std::uniform_real_distribution<double> angle_distribution(-M_PI, M_PI);

  for (int iteration = 0; iteration < 256; iteration++) {
    MayaObjectTransform transform;
    transform.rotation_order = eMayaRotationOrder(iteration % 6);
    for (int axis = 0; axis < 3; axis++) {
      transform.translation[axis] = value_distribution(random);
      transform.rotation[axis] = angle_distribution(random);
      transform.scale[axis] = value_distribution(random);
      if (std::abs(transform.scale[axis]) < 0.2) {
        transform.scale[axis] = std::copysign(0.2, transform.scale[axis]);
      }
      transform.shear[axis] = value_distribution(random);
      transform.rotate_pivot[axis] = value_distribution(random);
      transform.rotate_pivot_translate[axis] = value_distribution(random);
      transform.scale_pivot[axis] = value_distribution(random);
      transform.scale_pivot_translate[axis] = value_distribution(random);
    }
    for (double &value : transform.rotate_axis) {
      value = angle_distribution(random);
    }

    const double offset_translation[3] = {
        value_distribution(random), value_distribution(random), value_distribution(random)};
    const double offset_rotation[3] = {
        angle_distribution(random), angle_distribution(random), angle_distribution(random)};
    const double offset_scale[3] = {
        value_distribution(random), value_distribution(random), value_distribution(random)};
    RowMatrix offset = row_scale(offset_scale);
    offset = row_multiply(offset, row_euler_rotation(offset_rotation, transform.rotation_order));
    offset = row_multiply(offset, row_translation(offset_translation));
    std::copy(offset.begin(), offset.end(), &transform.offset_parent_matrix[0][0]);

    const RowMatrix expected = maya_row_reference_matrix(transform);
    const double4x4 result = BKE_maya_transform_dag_local_matrix(transform);
    SCOPED_TRACE(iteration);
    for (int index = 0; index < 16; index++) {
      EXPECT_NEAR(result.base_ptr()[index], expected[index], 1.0e-11);
    }
  }
}

TEST(object_transform_maya, RotationOrderConversionIsExplicit)
{
  EXPECT_EQ(BKE_maya_rotation_order_to_blender(MAYA_ROT_ORDER_XYZ), EULER_ORDER_XYZ);
  EXPECT_EQ(BKE_maya_rotation_order_to_blender(MAYA_ROT_ORDER_YZX), EULER_ORDER_YZX);
  EXPECT_EQ(BKE_maya_rotation_order_to_blender(MAYA_ROT_ORDER_ZXY), EULER_ORDER_ZXY);
  EXPECT_EQ(BKE_maya_rotation_order_to_blender(MAYA_ROT_ORDER_XZY), EULER_ORDER_XZY);
  EXPECT_EQ(BKE_maya_rotation_order_to_blender(MAYA_ROT_ORDER_YXZ), EULER_ORDER_YXZ);
  EXPECT_EQ(BKE_maya_rotation_order_to_blender(MAYA_ROT_ORDER_ZYX), EULER_ORDER_ZYX);

  for (int order = EULER_ORDER_XYZ; order <= EULER_ORDER_ZYX; order++) {
    const eEulerRotationOrders blender_order = eEulerRotationOrders(order);
    EXPECT_EQ(
        BKE_maya_rotation_order_to_blender(BKE_maya_rotation_order_from_blender(blender_order)),
        blender_order);
  }
}

TEST(object_transform_maya, RandomizedPreserveOperations)
{
  std::mt19937 random(0x50564f54);
  std::uniform_real_distribution<double> value_distribution(-3.0, 3.0);
  std::uniform_real_distribution<double> angle_distribution(-M_PI, M_PI);

  for (int iteration = 0; iteration < 256; iteration++) {
    MayaObjectTransform transform;
    transform.rotation_order = eMayaRotationOrder(iteration % 6);
    for (int axis = 0; axis < 3; axis++) {
      transform.translation[axis] = value_distribution(random);
      transform.rotation[axis] = angle_distribution(random);
      transform.rotate_axis[axis] = angle_distribution(random);
      transform.scale[axis] = value_distribution(random);
      if (iteration % 17 == 0) {
        transform.scale[axis] = std::copysign(1.0e-8, transform.scale[axis]);
      }
      transform.shear[axis] = value_distribution(random);
      transform.rotate_pivot[axis] = value_distribution(random);
      transform.rotate_pivot_translate[axis] = value_distribution(random);
      transform.scale_pivot[axis] = value_distribution(random);
      transform.scale_pivot_translate[axis] = value_distribution(random);
    }

    const double3 new_rotate_pivot = {
        value_distribution(random), value_distribution(random), value_distribution(random)};
    const double3 new_scale_pivot = {
        value_distribution(random), value_distribution(random), value_distribution(random)};
    const double4x4 matrix_before = BKE_maya_transform_channel_matrix(transform);

    BKE_maya_transform_set_rotate_pivot(transform, new_rotate_pivot, true);
    BKE_maya_transform_set_scale_pivot(transform, new_scale_pivot, true);

    const double4x4 matrix_after_pivots = BKE_maya_transform_channel_matrix(transform);
    SCOPED_TRACE(iteration);
    for (int index = 0; index < 16; index++) {
      EXPECT_NEAR(matrix_before.base_ptr()[index], matrix_after_pivots.base_ptr()[index], 1.0e-10);
    }

    const eMayaRotationOrder new_order = eMayaRotationOrder((iteration + 1) % 6);
    ASSERT_TRUE(BKE_maya_transform_set_rotation_order(transform, new_order, true));
    const double4x4 matrix_after_order = BKE_maya_transform_channel_matrix(transform);
    for (int index = 0; index < 16; index++) {
      EXPECT_NEAR(matrix_before.base_ptr()[index], matrix_after_order.base_ptr()[index], 1.0e-10);
    }

    const double3 new_rotate_axis = {
        angle_distribution(random), angle_distribution(random), angle_distribution(random)};
    ASSERT_TRUE(BKE_maya_transform_set_rotate_axis(transform, new_rotate_axis, true));
    const double4x4 matrix_after_axis = BKE_maya_transform_channel_matrix(transform);
    for (int index = 0; index < 16; index++) {
      EXPECT_NEAR(matrix_before.base_ptr()[index], matrix_after_axis.base_ptr()[index], 1.0e-10);
    }
  }
}

TEST(object_transform_maya, RandomizedChannelMatrixRoundTrip)
{
  std::mt19937 random(0x534f4c56);
  std::uniform_real_distribution<double> value_distribution(-3.0, 3.0);
  std::uniform_real_distribution<double> angle_distribution(-M_PI, M_PI);

  for (int iteration = 0; iteration < 256; iteration++) {
    MayaObjectTransform transform;
    transform.rotation_order = eMayaRotationOrder(iteration % 6);
    for (int axis = 0; axis < 3; axis++) {
      transform.translation[axis] = value_distribution(random);
      transform.rotation[axis] = angle_distribution(random);
      transform.rotate_axis[axis] = angle_distribution(random);
      transform.scale[axis] = value_distribution(random);
      if (std::abs(transform.scale[axis]) < 0.25) {
        transform.scale[axis] = std::copysign(0.25, transform.scale[axis]);
      }
      transform.shear[axis] = value_distribution(random);
      transform.rotate_pivot[axis] = value_distribution(random);
      transform.rotate_pivot_translate[axis] = value_distribution(random);
      transform.scale_pivot[axis] = value_distribution(random);
      transform.scale_pivot_translate[axis] = value_distribution(random);
    }

    const double4x4 matrix_before = BKE_maya_transform_channel_matrix(transform);
    MayaObjectTransform round_trip = transform;
    MayaTransformSetOptions options;
    ASSERT_TRUE(BKE_maya_transform_set_channel_matrix(round_trip, matrix_before, options));
    const double4x4 matrix_after = BKE_maya_transform_channel_matrix(round_trip);

    SCOPED_TRACE(iteration);
    for (int index = 0; index < 16; index++) {
      EXPECT_NEAR(matrix_before.base_ptr()[index], matrix_after.base_ptr()[index], 1.0e-10);
    }
    for (int axis = 0; axis < 3; axis++) {
      EXPECT_EQ(std::signbit(round_trip.scale[axis]), std::signbit(transform.scale[axis]));
    }
  }
}

TEST(object_transform_maya, CompatibleEulerAcrossPi)
{
  MayaObjectTransform transform;
  transform.rotation_order = MAYA_ROT_ORDER_XYZ;
  transform.rotation[0] = 179.0 * M_PI / 180.0;

  MayaTransformSetOptions options;
  for (const double angle_degrees : {181.0, 183.0}) {
    MayaObjectTransform target = transform;
    target.rotation[0] = angle_degrees * M_PI / 180.0;
    const double4x4 target_matrix = BKE_maya_transform_channel_matrix(target);
    ASSERT_TRUE(BKE_maya_transform_set_channel_matrix(transform, target_matrix, options));
    EXPECT_NEAR(transform.rotation[0], angle_degrees * M_PI / 180.0, 1.0e-10);
  }
}

TEST(object_transform_maya, MatrixSetterSingularCasesAreAtomic)
{
  MayaObjectTransform transform = full_reference_transform();
  MayaTransformSetOptions options;
  for (const int zero_axes : {1, 2, 3}) {
    const MayaObjectTransform initial = transform;
    double4x4 singular = double4x4::identity();
    for (int axis = 0; axis < zero_axes; axis++) {
      singular[axis] = double4(0.0);
    }
    EXPECT_FALSE(BKE_maya_transform_set_channel_matrix(transform, singular, options));
    EXPECT_EQ(memcmp(&transform, &initial, sizeof(transform)), 0);
  }

  double4x4 singular = double4x4::zero();
  options.policy = MAYA_TRANSFORM_SET_TRANSLATION_ONLY;
  singular.location() = {8.0, -4.0, 2.0};
  EXPECT_TRUE(BKE_maya_transform_set_channel_matrix(transform, singular, options));
  EXPECT_NEAR(BKE_maya_transform_channel_matrix(transform).location().x, 8.0, 1.0e-12);
  EXPECT_NEAR(BKE_maya_transform_channel_matrix(transform).location().y, -4.0, 1.0e-12);
  EXPECT_NEAR(BKE_maya_transform_channel_matrix(transform).location().z, 2.0, 1.0e-12);
}

TEST(object_transform_maya, DagAndWorldMatrixSetters)
{
  Object object;
  object.transform_model = OBJECT_TRANSFORM_MAYA;
  MayaObjectTransform *transform = BKE_object_maya_transform_ensure(&object);
  *transform = full_reference_transform();
  double4x4 offset_parent_matrix = double4x4::identity();
  offset_parent_matrix.location() = {1.0, -2.0, 0.5};
  offset_parent_matrix[1][0] = 0.25;
  offset_parent_matrix[2][1] = -0.4;
  std::copy_n(offset_parent_matrix.base_ptr(), 16, &transform->offset_parent_matrix[0][0]);
  const std::array<double, 16> initial_offset_parent_matrix = [&]() {
    std::array<double, 16> values;
    std::copy_n(&transform->offset_parent_matrix[0][0], 16, values.begin());
    return values;
  }();

  MayaObjectTransform target_transform = *transform;
  target_transform.translation[0] += 2.0;
  target_transform.rotation[1] -= 0.25;
  target_transform.scale[2] *= -1.5;
  const double4x4 target_dag = BKE_maya_transform_dag_local_matrix(target_transform);

  MayaTransformSetOptions options;
  ASSERT_TRUE(BKE_object_maya_set_dag_local_matrix(object, target_dag, options));
  const double4x4 dag_result = BKE_maya_transform_dag_local_matrix(*object.maya_transform);
  for (int index = 0; index < 16; index++) {
    EXPECT_NEAR(dag_result.base_ptr()[index], target_dag.base_ptr()[index], 1.0e-10);
    EXPECT_DOUBLE_EQ((&object.maya_transform->offset_parent_matrix[0][0])[index],
                     initial_offset_parent_matrix[index]);
  }

  double4x4 parent_effect = double4x4::identity();
  parent_effect.location() = {-5.0, 3.0, 7.0};
  parent_effect[0][0] = -2.0;
  const double4x4 target_world = parent_effect * target_dag;
  ASSERT_TRUE(BKE_object_maya_set_world_matrix(object, parent_effect, target_world, options));
  const double4x4 world_result = BKE_maya_transform_world_matrix(*object.maya_transform,
                                                                 parent_effect);
  for (int index = 0; index < 16; index++) {
    EXPECT_NEAR(world_result.base_ptr()[index], target_world.base_ptr()[index], 1.0e-10);
  }

  object.maya_transform->inherits_transform = false;
  const double4x4 unparented_target_world = target_dag;
  ASSERT_TRUE(
      BKE_object_maya_set_world_matrix(object, parent_effect, unparented_target_world, options));
  const double4x4 unparented_world_result = BKE_maya_transform_world_matrix(*object.maya_transform,
                                                                            parent_effect);
  for (int index = 0; index < 16; index++) {
    EXPECT_NEAR(unparented_world_result.base_ptr()[index],
                unparented_target_world.base_ptr()[index],
                1.0e-10);
  }

  object.maya_transform->inherits_transform = true;
  const MayaObjectTransform before_singular = *object.maya_transform;
  for (int column = 0; column < 4; column++) {
    for (int row = 0; row < 4; row++) {
      object.maya_transform->offset_parent_matrix[column][row] = 0.0;
    }
  }
  EXPECT_FALSE(BKE_object_maya_set_dag_local_matrix(object, target_dag, options));
  *object.maya_transform = before_singular;

  double4x4 singular_parent = double4x4::identity();
  singular_parent[1] = double4(0.0);
  EXPECT_FALSE(BKE_object_maya_set_world_matrix(object, singular_parent, target_world, options));
  EXPECT_EQ(memcmp(object.maya_transform, &before_singular, sizeof(before_singular)), 0);

  MEM_SAFE_DELETE(object.maya_transform);
}

}  // namespace blender::bke::tests
