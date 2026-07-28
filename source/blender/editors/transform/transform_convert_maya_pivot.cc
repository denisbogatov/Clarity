/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup edtransform
 *
 * Transform conversion for Maya object and component pivots.
 */

#include <memory>

#include "MEM_guardedalloc.h"

#include "DNA_action_types.h"

#include "BLI_math_matrix.h"
#include "BLI_math_quaternion.hh"
#include "BLI_math_rotation.h"
#include "BLI_math_vector.h"

#include "ED_maya.hh"

#include "transform.hh"
#include "transform_convert.hh"
#include "transform_snap.hh"

namespace blender::ed::transform {

struct MayaPivotTransData {
  std::unique_ptr<maya::MayaPivotEditTargetBackend> target;
  maya::MayaPivotFrame initial_frame;
  float position_proxy[3] = {};
  float orientation_proxy[4] = {1.0f, 0.0f, 0.0f, 0.0f};
  float initial_position_proxy[3] = {};
  float initial_orientation_proxy[4] = {1.0f, 0.0f, 0.0f, 0.0f};
};

static void freeTransMayaPivot(TransInfo * /*t*/,
                               TransDataContainer * /*tc*/,
                               TransCustomData *custom_data)
{
  MEM_delete(static_cast<MayaPivotTransData *>(custom_data->data));
  custom_data->data = nullptr;
}

static math::QuaternionBase<double> quaternion_from_proxy(const float proxy[4])
{
  return math::normalize(math::QuaternionBase<double>(
      double(proxy[0]), double(proxy[1]), double(proxy[2]), double(proxy[3])));
}

static double3 maya_pivot_unsnapped_position_get(TransInfo *t,
                                                 const MayaPivotTransData &data)
{
  float translation[3];
  copy_v3_v3(translation, t->values);
  if (!is_zero_v3(t->values_modal_offset)) {
    float offset[3];
    mul_v3_m3v3(offset, t->spacemtx, t->values_modal_offset);
    add_v3_v3(translation, offset);
  }
  if (t->con.mode & CON_APPLY) {
    float input[3];
    copy_v3_v3(input, translation);
    t->con.applyVec(t, nullptr, nullptr, input, translation);
  }
  if (t->tsnap.maya_view_plane && (t->con.mode & CON_APPLY) == 0) {
    project_plane_normalized_v3_v3v3(
        translation, translation, t->tsnap.maya_view_plane_normal);
  }
  return data.initial_frame.position_world + double3(translation);
}

static void recalcDataMayaPivot(TransInfo *t)
{
  TransDataContainer *tc = TRANS_DATA_CONTAINER_FIRST_OK(t);
  if (tc == nullptr || tc->custom.type.data == nullptr) {
    return;
  }
  MayaPivotTransData &data = *static_cast<MayaPivotTransData *>(tc->custom.type.data);
  if (t->state == TRANS_CANCEL) {
    data.target->cancel();
    return;
  }

  maya::MayaPivotToolSettings settings;
  ED_maya_pivot_tool_settings_get(t->context, settings);
  const bool has_snap_target = validSnap(t);
  if (t->mode == TFM_TRANSLATION) {
    double3 position = data.initial_frame.position_world;
    for (int axis = 0; axis < 3; axis++) {
      position[axis] += double(data.position_proxy[axis] - data.initial_position_proxy[axis]);
    }
    if (has_snap_target && settings.snap_position) {
      /* Snapping puts the pivot exactly on the target, as Maya does. Deriving it from the proxy
       * delta instead would offset it by the distance between the pivot and the transform center,
       * which is what made the pivot jump away while a snap key was held. */
      position = double3(t->tsnap.snap_target);
    }
    else if (has_snap_target) {
      position = maya_pivot_unsnapped_position_get(t, data);
    }
    if (!data.target->position_set(position, true)) {
      return;
    }

    if (has_snap_target && settings.snap_orientation && !is_zero_v3(t->tsnap.snapNormal)) {
      maya::MayaPivotFrame snapped_frame = data.initial_frame;
      snapped_frame.position_world = position;
      const double3 surface_normal(t->tsnap.snapNormal);
      if (ED_maya_pivot_orientation_aim(
              snapped_frame, position + surface_normal, 2, double3(0.0, 1.0, 0.0)))
      {
        data.target->orientation_set(snapped_frame.orientation_world, false);
      }
    }
    return;
  }

  if (t->mode == TFM_ROTATION) {
    const math::QuaternionBase<double> proxy_initial = quaternion_from_proxy(
        data.initial_orientation_proxy);
    const math::QuaternionBase<double> proxy_result = quaternion_from_proxy(
        data.orientation_proxy);
    const math::QuaternionBase<double> proxy_delta = proxy_result * math::invert(proxy_initial);
    const math::QuaternionBase<double> orientation = math::normalize(
        proxy_delta * data.initial_frame.orientation_world);
    if (!data.target->orientation_set(orientation, false))
    {
      return;
    }
  }
}

static void specialAfterTransMayaPivot(bContext * /*C*/, TransInfo *t)
{
  TransDataContainer *tc = TRANS_DATA_CONTAINER_FIRST_OK(t);
  if (tc == nullptr || tc->custom.type.data == nullptr) {
    return;
  }
  MayaPivotTransData &data = *static_cast<MayaPivotTransData *>(tc->custom.type.data);
  if (t->state == TRANS_CANCEL) {
    data.target->cancel();
  }
  else {
    data.target->commit();
  }
}

static void createTransMayaPivot(bContext *C, TransInfo *t)
{
  std::unique_ptr<maya::MayaPivotEditTargetBackend> target =
      ED_maya_pivot_edit_target_create(C);
  if (!target) {
    return;
  }
  const maya::MayaPivotFrame frame = target->frame_get();

  BLI_assert(t->data_container_len == 1);
  TransDataContainer *tc = t->data_container;
  MayaPivotTransData *pivot_data = MEM_new<MayaPivotTransData>(__func__);
  pivot_data->target = std::move(target);
  pivot_data->initial_frame = frame;
  for (int axis = 0; axis < 3; axis++) {
    pivot_data->position_proxy[axis] = float(frame.position_world[axis]);
  }
  pivot_data->orientation_proxy[0] = float(frame.orientation_world.w);
  pivot_data->orientation_proxy[1] = float(frame.orientation_world.x);
  pivot_data->orientation_proxy[2] = float(frame.orientation_world.y);
  pivot_data->orientation_proxy[3] = float(frame.orientation_world.z);
  copy_v3_v3(pivot_data->initial_position_proxy, pivot_data->position_proxy);
  copy_qt_qt(pivot_data->initial_orientation_proxy, pivot_data->orientation_proxy);
  tc->custom.type.data = pivot_data;
  tc->custom.type.free_cb = freeTransMayaPivot;

  tc->data_len = 1;
  TransData *td = tc->data = MEM_new_zeroed<TransData>("TransData(MayaPivot)");
  TransDataExtension *td_ext = tc->data_ext = MEM_new_zeroed<TransDataExtension>(
      "TransDataExtension(MayaPivot)");

  td->flag = TD_SELECTED;
  copy_v3_v3(td->center, pivot_data->position_proxy);
  unit_m3(td->mtx);
  quat_to_mat3(td->axismtx, pivot_data->orientation_proxy);
  normalize_m3(td->axismtx);
  pseudoinverse_m3_m3(td->smtx, td->mtx, PSEUDOINVERSE_EPSILON);
  td->loc = pivot_data->position_proxy;
  copy_v3_v3(td->iloc, pivot_data->position_proxy);

  td_ext->quat = pivot_data->orientation_proxy;
  copy_qt_qt(td_ext->iquat, pivot_data->orientation_proxy);
  td_ext->rotOrder = ROT_MODE_QUAT;
}

TransConvertTypeInfo TransConvertType_MayaPivot = {
    /*flags*/ 0,
    /*create_trans_data*/ createTransMayaPivot,
    /*recalc_data*/ recalcDataMayaPivot,
    /*special_aftertrans_update*/ specialAfterTransMayaPivot,
};

}  // namespace blender::ed::transform
