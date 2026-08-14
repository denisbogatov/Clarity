/* SPDX-FileCopyrightText: 2023 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup Alembic
 */

#include "abc_axis_conversion.h"

#include "BLI_assert.h"
#include "BLI_math_matrix.h"
#include "BLI_math_rotation.h"
#include "BLI_math_vector.h"

#include "BKE_object_types.hh"

#include "DNA_object_types.h"

namespace blender::io::alembic {

void create_swapped_rotation_matrix(float rot_x_mat[3][3],
                                    float rot_y_mat[3][3],
                                    float rot_z_mat[3][3],
                                    const float euler[3],
                                    AbcAxisSwapMode mode)
{
  BLI_assert(mode == ABC_ZUP_FROM_YUP || mode == ABC_YUP_FROM_ZUP);
  const float rx = euler[0];
  const float ry = euler[1];
  const float rz = euler[2];

  unit_m3(rot_x_mat);
  unit_m3(rot_y_mat);
  unit_m3(rot_z_mat);

  rot_x_mat[1][1] = cos(rx);
  rot_x_mat[2][1] = -sin(rx);
  rot_x_mat[1][2] = sin(rx);
  rot_x_mat[2][2] = cos(rx);

  rot_y_mat[2][2] = cos(ry);
  rot_y_mat[0][2] = -sin(ry);
  rot_y_mat[2][0] = sin(ry);
  rot_y_mat[0][0] = cos(ry);

  rot_z_mat[0][0] = cos(rz);
  rot_z_mat[1][0] = -sin(rz);
  rot_z_mat[0][1] = sin(rz);
  rot_z_mat[1][1] = cos(rz);
}

void copy_m44_axis_swap(float dst_mat[4][4], float src_mat[4][4], AbcAxisSwapMode mode)
{
  BLI_assert(mode == ABC_ZUP_FROM_YUP || mode == ABC_YUP_FROM_ZUP);
  copy_m4_m4(dst_mat, src_mat);
}

void create_transform_matrix(Object *obj,
                             float r_yup_mat[4][4],
                             AbcMatrixMode mode,
                             Object *proxy_from)
{
  float internal_mat[4][4];

  /* get local or world matrix. */
  if (mode == ABC_MATRIX_LOCAL && obj->parent) {
    /* Note that this produces another matrix than the local matrix, due to
     * constraints and modifiers as well as the obj->parentinv matrix. */
    invert_m4_m4(obj->parent->runtime->world_to_object.ptr(),
                 obj->parent->object_to_world().ptr());
    mul_m4_m4m4(
        internal_mat, obj->parent->world_to_object().ptr(), obj->object_to_world().ptr());
  }
  else {
    copy_m4_m4(internal_mat, obj->object_to_world().ptr());
  }

  if (proxy_from) {
    mul_m4_m4m4(internal_mat, proxy_from->object_to_world().ptr(), internal_mat);
  }

  copy_m4_m4(r_yup_mat, internal_mat);
}

}  // namespace blender::io::alembic
