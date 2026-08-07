/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup edtransform
 *
 * Transform conversion for Clarity object and component pivots.
 */

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <memory>

#include "MEM_guardedalloc.h"

#include "DNA_action_types.h"

#include "BLI_math_matrix.h"
#include "BLI_math_quaternion.hh"
#include "BLI_math_rotation.h"
#include "BLI_math_vector.h"

#include "ED_clarity.hh"

#include "transform.hh"
#include "transform_convert.hh"
#include "transform_snap.hh"
#include "transform_snap_clarity.hh"

namespace blender::ed::transform {

struct ClarityPivotTransData {
  std::unique_ptr<clarity::ClarityPivotEditTargetBackend> target;
  clarity::ClarityPivotFrame initial_frame;
  float position_proxy[3] = {};
  float orientation_proxy[4] = {1.0f, 0.0f, 0.0f, 0.0f};
  float initial_position_proxy[3] = {};
  float initial_orientation_proxy[4] = {1.0f, 0.0f, 0.0f, 0.0f};
  std::FILE *trace_file = nullptr;
  uint64_t trace_update_count = 0;
};

static void freeTransClarityPivot(TransInfo *t,
                               TransDataContainer * /*tc*/,
                               TransCustomData *custom_data)
{
  ClarityPivotTransData *data = static_cast<ClarityPivotTransData *>(custom_data->data);
  if (data->trace_file != nullptr) {
    std::fprintf(data->trace_file,
                 "pivot-drag-end state=%d updates=%llu\n",
                 int(t->state),
                 static_cast<unsigned long long>(data->trace_update_count));
    std::fclose(data->trace_file);
    data->trace_file = nullptr;
  }
  MEM_delete(data);
  custom_data->data = nullptr;
}

static math::QuaternionBase<double> quaternion_from_proxy(const float proxy[4])
{
  return math::normalize(math::QuaternionBase<double>(
      double(proxy[0]), double(proxy[1]), double(proxy[2]), double(proxy[3])));
}

static double3 clarity_pivot_unsnapped_position_get(TransInfo *t,
                                                 const ClarityPivotTransData &data)
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
  if (t->tsnap.clarity_view_plane && (t->con.mode & CON_APPLY) == 0) {
    project_plane_normalized_v3_v3v3(
        translation, translation, t->tsnap.clarity_view_plane_normal);
  }
  return data.initial_frame.position_world + double3(translation);
}

/**
 * One line per pivot update, so a snap that behaves unexpectedly can be read off a log instead of
 * guessed at: it shows what the snap search was allowed to look at, whether it found anything and
 * which of the three candidate positions won.
 *
 * Written to the file named by `BLENDER_CLARITY_SNAP_TRACE_FILE`, the same pattern as
 * #BLENDER_STARTUP_TRACE_FILE. Deliberately not `stderr`: that only reaches a log while the console
 * of the session happens to be redirected, which is why the manipulator trace kept coming back
 * empty. `go.bat --trace` sets the variable. Temporary, like the manipulator trace.
 */
static std::FILE *clarity_pivot_trace_open()
{
  const char *filepath = std::getenv("BLENDER_CLARITY_SNAP_TRACE_FILE");
  if (filepath == nullptr) {
    filepath = std::getenv("BLENDER_MAYA_SNAP_TRACE_FILE");
  }
  if (filepath == nullptr) {
    return nullptr;
  }
  return std::fopen(filepath, "a");
}

/**
 * One line as soon as a pivot drag starts, so an empty log is never ambiguous: with this line the
 * drag ran and found nothing to snap to, without it the drag never reached this conversion at all.
 */
static void clarity_pivot_drag_trace_begin(const TransInfo *t, ClarityPivotTransData &data)
{
  if (data.trace_file == nullptr) {
    return;
  }
  /* The snapping state is decided after the conversion, so only the mode is meaningful here. */
  std::fprintf(data.trace_file, "pivot-drag-begin mode=%d\n", int(t->mode));
  /* Keep the trace useful if Blender hangs mid-drag without flushing every modal update. */
  std::fflush(data.trace_file);
}

static void clarity_pivot_snap_trace(ClarityPivotTransData &data,
                                  const TransInfo *t,
                                  const ClarityPivotSnapInput &input,
                                  const ClarityPivotSnapDecision &decision)
{
  if (data.trace_file == nullptr) {
    return;
  }
  data.trace_update_count++;
  std::fprintf(data.trace_file,
               "pivot-snap snap_to=%d tol_px=%.1f mval=(%.0f %.0f) target=%d target_type=%d "
               "snap_pos=%d applied=(%.4f %.4f %.4f) "
               "pointer=(%.4f %.4f %.4f) target_co=(%.4f %.4f %.4f) result=(%.4f %.4f %.4f) "
               "from_target=%d\n",
               int(t->tsnap.mode),
               double(t->tsnap.clarity_snap_dist_px),
               double(t->mval[0]),
               double(t->mval[1]),
               int(input.has_target),
               int(t->tsnap.target_type),
               int(input.snap_position),
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
               int(decision.from_target));
}

static void recalcDataClarityPivot(TransInfo *t)
{
  TransDataContainer *tc = TRANS_DATA_CONTAINER_FIRST_OK(t);
  if (tc == nullptr || tc->custom.type.data == nullptr) {
    return;
  }
  ClarityPivotTransData &data = *static_cast<ClarityPivotTransData *>(tc->custom.type.data);
  if (t->state == TRANS_CANCEL) {
    data.target->cancel();
    return;
  }

  clarity::ClarityPivotToolSettings settings;
  ED_clarity_pivot_tool_settings_get(t->context, settings);
  if (t->mode == TFM_TRANSLATION) {
    ClarityPivotSnapInput snap_input;
    snap_input.applied_position = data.initial_frame.position_world;
    for (int axis = 0; axis < 3; axis++) {
      snap_input.applied_position[axis] += double(data.position_proxy[axis] -
                                                  data.initial_position_proxy[axis]);
    }
    snap_input.pointer_position = clarity_pivot_unsnapped_position_get(t, data);
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
    snap_input.snap_position = settings.snap_position;

    const ClarityPivotSnapDecision decision = clarity_pivot_snap_decision_get(snap_input);
    clarity_pivot_snap_trace(data, t, snap_input, decision);
    if (!data.target->position_set(decision.position, true)) {
      /* The write is all-or-nothing, so the pivot simply stays where the last accepted update left
       * it. Worth a trace line: to the user this looks like the pivot ignoring the mouse. */
      if (data.trace_file != nullptr) {
        std::fprintf(data.trace_file,
                     "pivot-position-rejected target=(%.4f %.4f %.4f)\n",
                     decision.position.x,
                     decision.position.y,
                     decision.position.z);
        std::fflush(data.trace_file);
      }
      return;
    }

    /* The orientation is deliberately left alone: a drag moves the pivot, and a click on a
     * component is what aligns it - `TRANSFORM_OT_clarity_pivot_click`, mirroring Clarity's own split
     * between "middle-drag to snap the pivot to edges or vertices" and "click a component to snap
     * and align the pivot to it". Turning the pivot on every snapped update handed it a new frame
     * whenever the element under the pointer changed, and the drag that caused it could not put it
     * back. */
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

static void specialAfterTransClarityPivot(bContext * /*C*/, TransInfo *t)
{
  TransDataContainer *tc = TRANS_DATA_CONTAINER_FIRST_OK(t);
  if (tc == nullptr || tc->custom.type.data == nullptr) {
    return;
  }
  ClarityPivotTransData &data = *static_cast<ClarityPivotTransData *>(tc->custom.type.data);
  if (t->state == TRANS_CANCEL) {
    data.target->cancel();
  }
  else {
    data.target->commit();
  }
}

static void createTransClarityPivot(bContext *C, TransInfo *t)
{
  std::unique_ptr<clarity::ClarityPivotEditTargetBackend> target =
      ED_clarity_pivot_edit_target_create(C);
  if (!target) {
    return;
  }
  const clarity::ClarityPivotFrame frame = target->frame_get();

  BLI_assert(t->data_container_len == 1);
  TransDataContainer *tc = t->data_container;
  ClarityPivotTransData *pivot_data = MEM_new<ClarityPivotTransData>(__func__);
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
  pivot_data->trace_file = clarity_pivot_trace_open();
  tc->custom.type.data = pivot_data;
  tc->custom.type.free_cb = freeTransClarityPivot;

  tc->data_len = 1;
  TransData *td = tc->data = MEM_new_zeroed<TransData>("TransData(ClarityPivot)");
  TransDataExtension *td_ext = tc->data_ext = MEM_new_zeroed<TransDataExtension>(
      "TransDataExtension(ClarityPivot)");

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

  clarity_pivot_drag_trace_begin(t, *pivot_data);
}

TransConvertTypeInfo TransConvertType_ClarityPivot = {
    /*flags*/ 0,
    /*create_trans_data*/ createTransClarityPivot,
    /*recalc_data*/ recalcDataClarityPivot,
    /*special_aftertrans_update*/ specialAfterTransClarityPivot,
};

}  // namespace blender::ed::transform
