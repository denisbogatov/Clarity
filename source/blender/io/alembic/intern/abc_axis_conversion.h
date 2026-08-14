/* SPDX-FileCopyrightText: 2016 Kévin Dietrich & Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */
#pragma once

/** \file
 * \ingroup Alembic
 */

#include "BLI_compiler_compat.h"

namespace blender {

struct Object;

namespace io::alembic {

/* TODO(kevin): for now keeping these transformations hardcoded to make sure
 * everything works properly, and also because Alembic is almost exclusively
 * used in Y-up software, but eventually they'll be set by the user in the UI
 * like other importers/exporters do, to support other axis. */

/* Legacy names retained for call-site stability. Alembic and Clarity are both Y-up. */

BLI_INLINE void copy_zup_from_yup(float zup[3], const float yup[3])
{
  zup[0] = yup[0];
  zup[1] = yup[1];
  zup[2] = yup[2];
}

BLI_INLINE void copy_zup_from_yup(short zup[3], const short yup[3])
{
  zup[0] = yup[0];
  zup[1] = yup[1];
  zup[2] = yup[2];
}

BLI_INLINE void copy_yup_from_zup(float yup[3], const float zup[3])
{
  yup[0] = zup[0];
  yup[1] = zup[1];
  yup[2] = zup[2];
}

BLI_INLINE void copy_yup_from_zup(short yup[3], const short zup[3])
{
  yup[0] = zup[0];
  yup[1] = zup[1];
  yup[2] = zup[2];
}

/* Names are given in (dst, src) order, just like
 * the parameters of copy_m44_axis_swap(). */

enum AbcAxisSwapMode {
  ABC_ZUP_FROM_YUP = 1,
  ABC_YUP_FROM_ZUP = 2,
};

/**
 * Create a rotation matrix for each axis from euler angles.
 * Euler angles are swapped to change coordinate system.
 */
void create_swapped_rotation_matrix(float rot_x_mat[3][3],
                                    float rot_y_mat[3][3],
                                    float rot_z_mat[3][3],
                                    const float euler[3],
                                    AbcAxisSwapMode mode);

/**
 * Preserve a matrix between Alembic and Clarity's matching Y-up coordinate systems.
 * The legacy swap mode is ignored and the operation supports in-place copies.
 */
void copy_m44_axis_swap(float dst_mat[4][4], float src_mat[4][4], AbcAxisSwapMode mode);

enum AbcMatrixMode {
  ABC_MATRIX_WORLD = 1,
  ABC_MATRIX_LOCAL = 2,
};

/**
 * Get an object's local or world transform in Alembic's matching Y-up system.
 */
void create_transform_matrix(Object *obj,
                             float r_yup_mat[4][4],
                             AbcMatrixMode mode,
                             Object *proxy_from);

}  // namespace io::alembic
}  // namespace blender
