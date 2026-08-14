/* SPDX-FileCopyrightText: 2023 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

#include "testing/testing.h"

/* Keep first since `BLI_utildefines.h` defines `AT` which conflicts with STL. */
#include "intern/abc_axis_conversion.h"

#include "BLI_math_base.h"
#include "BLI_math_matrix.h"
#include "BLI_math_rotation.h"

namespace blender::io::alembic {

TEST(abc_matrix, CreateRotationMatrixNativeYUp)
{
  const float euler[3] = {M_PI / 6.0f, M_PI / 4.0f, M_PI / 3.0f};
  float result_x[3][3];
  float result_y[3][3];
  float result_z[3][3];
  float expect_x[3][3];
  float expect_y[3][3];
  float expect_z[3][3];

  create_swapped_rotation_matrix(
      result_x, result_y, result_z, euler, ABC_YUP_FROM_ZUP);
  axis_angle_to_mat3_single(expect_x, 'X', euler[0]);
  axis_angle_to_mat3_single(expect_y, 'Y', euler[1]);
  axis_angle_to_mat3_single(expect_z, 'Z', euler[2]);

  EXPECT_M3_NEAR(expect_x, result_x, 1e-5f);
  EXPECT_M3_NEAR(expect_y, result_y, 1e-5f);
  EXPECT_M3_NEAR(expect_z, result_z, 1e-5f);
}

TEST(abc_matrix, CopyM44PreservesMatchingYUpBasis)
{
  float input[4][4] = {
      {3.25519061088f, 1.87938535213f, -1.36808049679f, 0.0f},
      {-2.20484805107f, 4.41282081604f, 0.81587958336f, 0.0f},
      {2.27113389968f, 0.10816989839f, 5.55249977112f, 0.0f},
      {1.0f, 2.0f, 3.0f, 1.0f},
  };
  float result[4][4];

  copy_m44_axis_swap(result, input, ABC_YUP_FROM_ZUP);
  EXPECT_M4_NEAR(input, result, 1e-5f);

  copy_m44_axis_swap(result, input, ABC_ZUP_FROM_YUP);
  EXPECT_M4_NEAR(input, result, 1e-5f);
}

}  // namespace blender::io::alembic
