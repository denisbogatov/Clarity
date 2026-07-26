/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup edtransform
 *
 * Transform conversion for the standalone Maya component pivot.
 */

#include "MEM_guardedalloc.h"

#include "DNA_action_types.h"

#include "BLI_math_matrix.h"
#include "BLI_math_rotation.h"
#include "BLI_math_vector.h"

#include "ED_maya.hh"

#include "transform.hh"
#include "transform_convert.hh"

namespace blender::ed::transform {

static void createTransMayaPivot(bContext *C, TransInfo *t)
{
  float *location;
  float *rotation_quaternion;
  if (!ED_maya_pivot_edit_data_get(C, &location, &rotation_quaternion)) {
    return;
  }

  BLI_assert(t->data_container_len == 1);
  TransDataContainer *tc = t->data_container;
  tc->data_len = 1;
  TransData *td = tc->data = MEM_new_zeroed<TransData>("TransData(MayaPivot)");
  TransDataExtension *td_ext = tc->data_ext = MEM_new_zeroed<TransDataExtension>(
      "TransDataExtension(MayaPivot)");

  td->flag = TD_SELECTED;
  copy_v3_v3(td->center, location);
  unit_m3(td->mtx);
  quat_to_mat3(td->axismtx, rotation_quaternion);
  normalize_m3(td->axismtx);
  pseudoinverse_m3_m3(td->smtx, td->mtx, PSEUDOINVERSE_EPSILON);
  td->loc = location;
  copy_v3_v3(td->iloc, location);

  td_ext->quat = rotation_quaternion;
  copy_qt_qt(td_ext->iquat, rotation_quaternion);
  td_ext->rotOrder = ROT_MODE_QUAT;
}

TransConvertTypeInfo TransConvertType_MayaPivot = {
    /*flags*/ 0,
    /*create_trans_data*/ createTransMayaPivot,
    /*recalc_data*/ nullptr,
    /*special_aftertrans_update*/ nullptr,
};

}  // namespace blender::ed::transform
