/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup edtransform
 *
 * Transform conversion for Maya object and component pivots.
 */

#include <cstdio>
#include <cstdlib>
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
#include "transform_snap_maya.hh"

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

/**
 * One line per pivot update, so a snap that behaves unexpectedly can be read off a log instead of
 * guessed at: it shows what the snap search was allowed to look at, whether it found anything and
 * which of the three candidate positions won.
 *
 * Written to the file named by `BLENDER_MAYA_SNAP_TRACE_FILE`, the same pattern as
 * #BLENDER_STARTUP_TRACE_FILE. Deliberately not `stderr`: that only reaches a log while the console
 * of the session happens to be redirected, which is why the manipulator trace kept coming back
 * empty. `go.bat --trace` sets the variable. Temporary, like the manipulator trace.
 */
static std::FILE *maya_pivot_trace_open()
{
  const char *filepath = std::getenv("BLENDER_MAYA_SNAP_TRACE_FILE");
  if (filepath == nullptr) {
    return nullptr;
  }
  return std::fopen(filepath, "a");
}

/**
 * One line as soon as a pivot drag starts, so an empty log is never ambiguous: with this line the
 * drag ran and found nothing to snap to, without it the drag never reached this conversion at all.
 */
static void maya_pivot_drag_trace_begin(const TransInfo *t)
{
  std::FILE *file = maya_pivot_trace_open();
  if (file == nullptr) {
    return;
  }
  /* The snapping state is decided after the conversion, so only the mode is meaningful here. */
  std::fprintf(file, "pivot-drag-begin mode=%d\n", int(t->mode));
  std::fclose(file);
}

static void maya_pivot_snap_trace(const TransInfo *t,
                                  const MayaPivotSnapInput &input,
                                  const MayaPivotSnapDecision &decision)
{
  std::FILE *file = maya_pivot_trace_open();
  if (file == nullptr) {
    return;
  }
  std::fprintf(file,
               "pivot-snap snap_to=%d tol_px=%.1f mval=(%.0f %.0f) target=%d normal=%d "
               "snap_pos=%d snap_orient=%d applied=(%.4f %.4f %.4f) pointer=(%.4f %.4f %.4f) "
               "target_co=(%.4f %.4f %.4f) result=(%.4f %.4f %.4f) from_target=%d aim=%d\n",
               int(t->tsnap.mode),
               double(t->tsnap.maya_snap_dist_px),
               double(t->mval[0]),
               double(t->mval[1]),
               int(input.has_target),
               int(input.target_has_normal),
               int(input.snap_position),
               int(input.snap_orientation),
               input.applied_position.x,
               input.applied_position.y,
               input.applied_position.z,
               input.pointer_position.x,
               input.pointer_position.y,
               input.pointer_position.z,
               input.target_position.x,
               input.target_position.y,
               input.target_position.z,
               decision.position.x,
               decision.position.y,
               decision.position.z,
               int(decision.from_target),
               int(decision.aim_at_normal));
  std::fclose(file);
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
  if (t->mode == TFM_TRANSLATION) {
    MayaPivotSnapInput snap_input;
    snap_input.applied_position = data.initial_frame.position_world;
    for (int axis = 0; axis < 3; axis++) {
      snap_input.applied_position[axis] += double(data.position_proxy[axis] -
                                                  data.initial_position_proxy[axis]);
    }
    snap_input.pointer_position = maya_pivot_unsnapped_position_get(t, data);
    snap_input.target_position = double3(t->tsnap.snap_target);
    snap_input.constrained_target_position = snap_input.target_position;
    snap_input.has_constraint = (t->con.mode & CON_APPLY) != 0;
    if (snap_input.has_constraint) {
      /* Reach the target through the constraint, so a dragged axis handle keeps the pivot on its
       * axis and only slides it to where the target projects onto it. */
      float offset[3];
      for (int axis = 0; axis < 3; axis++) {
        offset[axis] = float(snap_input.target_position[axis] -
                             data.initial_frame.position_world[axis]);
      }
      float constrained[3];
      t->con.applyVec(t, nullptr, nullptr, offset, constrained);
      snap_input.constrained_target_position = data.initial_frame.position_world +
                                               double3(constrained);
    }
    snap_input.has_target = validSnap(t);
    snap_input.target_has_normal = !is_zero_v3(t->tsnap.snapNormal);
    snap_input.snap_position = settings.snap_position;
    snap_input.snap_orientation = settings.snap_orientation;

    const MayaPivotSnapDecision decision = maya_pivot_snap_decision_get(snap_input);
    maya_pivot_snap_trace(t, snap_input, decision);
    if (!data.target->position_set(decision.position, true)) {
      return;
    }

    if (decision.aim_at_normal) {
      maya::MayaPivotFrame snapped_frame = data.initial_frame;
      snapped_frame.position_world = decision.position;
      const double3 surface_normal(t->tsnap.snapNormal);
      /* Same reference frame the click path uses: the view up decides the secondary axis, so a
       * dragged and a clicked snap onto the same face produce the same pivot. */
      if (ED_maya_pivot_orientation_aim(
              snapped_frame, decision.position + surface_normal, 2, double3(t->viewinv[1])))
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

  maya_pivot_drag_trace_begin(t);
}

TransConvertTypeInfo TransConvertType_MayaPivot = {
    /*flags*/ 0,
    /*create_trans_data*/ createTransMayaPivot,
    /*recalc_data*/ recalcDataMayaPivot,
    /*special_aftertrans_update*/ specialAfterTransMayaPivot,
};

}  // namespace blender::ed::transform
