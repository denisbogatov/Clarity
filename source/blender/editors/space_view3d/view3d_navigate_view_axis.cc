/* SPDX-FileCopyrightText: 2023 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup spview3d
 */

#include "BLI_math_base.h"
#include "BLI_math_rotation.h"
#include "BLI_math_vector.h"

#include "DNA_object_types.h"
#include "DNA_userdef_types.h"

#include "BLT_translation.hh"

#include "BKE_context.hh"

#include "ED_transform.hh"

#include "WM_api.hh"

#include "RNA_access.hh"
#include "RNA_define.hh"

#include "UI_resources.hh"

#include "view3d_intern.hh"

#include "view3d_navigate.hh" /* own include */

namespace blender {

static constexpr int VIEW3D_VIEW_DIAGONAL_BASE = 100;
static constexpr int VIEW3D_VIEW_DIAGONAL_COUNT = 12;
static constexpr int VIEW3D_VIEW_CORNER_BASE =
    VIEW3D_VIEW_DIAGONAL_BASE + VIEW3D_VIEW_DIAGONAL_COUNT;
static constexpr int VIEW3D_VIEW_CORNER_COUNT = 8;

static const eRegionView3D_View diagonal_view_pairs[VIEW3D_VIEW_DIAGONAL_COUNT][2] = {
    {RV3D_VIEW_LEFT, RV3D_VIEW_FRONT},
    {RV3D_VIEW_LEFT, RV3D_VIEW_BACK},
    {RV3D_VIEW_RIGHT, RV3D_VIEW_FRONT},
    {RV3D_VIEW_RIGHT, RV3D_VIEW_BACK},
    {RV3D_VIEW_LEFT, RV3D_VIEW_BOTTOM},
    {RV3D_VIEW_LEFT, RV3D_VIEW_TOP},
    {RV3D_VIEW_RIGHT, RV3D_VIEW_BOTTOM},
    {RV3D_VIEW_RIGHT, RV3D_VIEW_TOP},
    {RV3D_VIEW_FRONT, RV3D_VIEW_BOTTOM},
    {RV3D_VIEW_FRONT, RV3D_VIEW_TOP},
    {RV3D_VIEW_BACK, RV3D_VIEW_BOTTOM},
    {RV3D_VIEW_BACK, RV3D_VIEW_TOP},
};

static const eRegionView3D_View corner_view_triples[VIEW3D_VIEW_CORNER_COUNT][3] = {
    {RV3D_VIEW_LEFT, RV3D_VIEW_BOTTOM, RV3D_VIEW_BACK},
    {RV3D_VIEW_LEFT, RV3D_VIEW_BOTTOM, RV3D_VIEW_FRONT},
    {RV3D_VIEW_LEFT, RV3D_VIEW_TOP, RV3D_VIEW_BACK},
    {RV3D_VIEW_LEFT, RV3D_VIEW_TOP, RV3D_VIEW_FRONT},
    {RV3D_VIEW_RIGHT, RV3D_VIEW_BOTTOM, RV3D_VIEW_BACK},
    {RV3D_VIEW_RIGHT, RV3D_VIEW_BOTTOM, RV3D_VIEW_FRONT},
    {RV3D_VIEW_RIGHT, RV3D_VIEW_TOP, RV3D_VIEW_BACK},
    {RV3D_VIEW_RIGHT, RV3D_VIEW_TOP, RV3D_VIEW_FRONT},
};

static void axis_view_direction(const eRegionView3D_View view, float r_direction[3])
{
  float quat[4];
  ED_view3d_quat_from_axis_view(view, RV3D_VIEW_AXIS_ROLL_0, quat);
  invert_qt_normalized(quat);
  r_direction[0] = 0.0f;
  r_direction[1] = 0.0f;
  r_direction[2] = 1.0f;
  mul_qt_v3(quat, r_direction);
}

static void view_quat_from_direction_y_up(const float direction[3], float r_quat[4])
{
  const float world_up[3] = {0.0f, 1.0f, 0.0f};
  float camera_basis[3][3];

  /* Keep the camera level like Maya's "Preserve scene up" ViewCube option. */
  cross_v3_v3v3(camera_basis[0], world_up, direction);
  if (normalize_v3(camera_basis[0]) == 0.0f) {
    ED_view3d_quat_from_axis_view(direction[1] >= 0.0f ? RV3D_VIEW_TOP : RV3D_VIEW_BOTTOM,
                                 RV3D_VIEW_AXIS_ROLL_0,
                                 r_quat);
    return;
  }
  cross_v3_v3v3(camera_basis[1], direction, camera_basis[0]);
  normalize_v3(camera_basis[1]);
  copy_v3_v3(camera_basis[2], direction);

  /* The basis is camera-to-world; RegionView3D stores the inverse rotation. */
  mat3_normalized_to_quat(r_quat, camera_basis);
  invert_qt_normalized(r_quat);
}

/* -------------------------------------------------------------------- */
/** \name View Axis Operator
 * \{ */

static const EnumPropertyItem prop_view_items[] = {
    {RV3D_VIEW_LEFT, "LEFT", ICON_TRIA_LEFT, "Left", "View from the left"},
    {RV3D_VIEW_RIGHT, "RIGHT", ICON_TRIA_RIGHT, "Right", "View from the right"},
    {RV3D_VIEW_BOTTOM, "BOTTOM", ICON_TRIA_DOWN, "Bottom", "View from the bottom"},
    {RV3D_VIEW_TOP, "TOP", ICON_TRIA_UP, "Top", "View from the top"},
    {RV3D_VIEW_FRONT, "FRONT", 0, "Front", "View from the front"},
    {RV3D_VIEW_BACK, "BACK", 0, "Back", "View from the back"},
    {VIEW3D_VIEW_DIAGONAL_BASE + 0, "LEFT_FRONT", 0, "Left Front", "View from left front"},
    {VIEW3D_VIEW_DIAGONAL_BASE + 1, "LEFT_BACK", 0, "Left Back", "View from left back"},
    {VIEW3D_VIEW_DIAGONAL_BASE + 2, "RIGHT_FRONT", 0, "Right Front", "View from right front"},
    {VIEW3D_VIEW_DIAGONAL_BASE + 3, "RIGHT_BACK", 0, "Right Back", "View from right back"},
    {VIEW3D_VIEW_DIAGONAL_BASE + 4, "LEFT_BOTTOM", 0, "Left Bottom", "View from left bottom"},
    {VIEW3D_VIEW_DIAGONAL_BASE + 5, "LEFT_TOP", 0, "Left Top", "View from left top"},
    {VIEW3D_VIEW_DIAGONAL_BASE + 6, "RIGHT_BOTTOM", 0, "Right Bottom", "View from right bottom"},
    {VIEW3D_VIEW_DIAGONAL_BASE + 7, "RIGHT_TOP", 0, "Right Top", "View from right top"},
    {VIEW3D_VIEW_DIAGONAL_BASE + 8, "FRONT_BOTTOM", 0, "Front Bottom", "View from front bottom"},
    {VIEW3D_VIEW_DIAGONAL_BASE + 9, "FRONT_TOP", 0, "Front Top", "View from front top"},
    {VIEW3D_VIEW_DIAGONAL_BASE + 10, "BACK_BOTTOM", 0, "Back Bottom", "View from back bottom"},
    {VIEW3D_VIEW_DIAGONAL_BASE + 11, "BACK_TOP", 0, "Back Top", "View from back top"},
    {VIEW3D_VIEW_CORNER_BASE + 0,
     "LEFT_BOTTOM_BACK",
     0,
     "Left Bottom Back",
     "View from left bottom back"},
    {VIEW3D_VIEW_CORNER_BASE + 1,
     "LEFT_BOTTOM_FRONT",
     0,
     "Left Bottom Front",
     "View from left bottom front"},
    {VIEW3D_VIEW_CORNER_BASE + 2,
     "LEFT_TOP_BACK",
     0,
     "Left Top Back",
     "View from left top back"},
    {VIEW3D_VIEW_CORNER_BASE + 3,
     "LEFT_TOP_FRONT",
     0,
     "Left Top Front",
     "View from left top front"},
    {VIEW3D_VIEW_CORNER_BASE + 4,
     "RIGHT_BOTTOM_BACK",
     0,
     "Right Bottom Back",
     "View from right bottom back"},
    {VIEW3D_VIEW_CORNER_BASE + 5,
     "RIGHT_BOTTOM_FRONT",
     0,
     "Right Bottom Front",
     "View from right bottom front"},
    {VIEW3D_VIEW_CORNER_BASE + 6,
     "RIGHT_TOP_BACK",
     0,
     "Right Top Back",
     "View from right top back"},
    {VIEW3D_VIEW_CORNER_BASE + 7,
     "RIGHT_TOP_FRONT",
     0,
     "Right Top Front",
     "View from right top front"},
    {0, nullptr, 0, nullptr, nullptr},
};

static wmOperatorStatus view_axis_exec(bContext *C, wmOperator *op)
{
  View3D *v3d;
  ARegion *region;
  RegionView3D *rv3d;
  static eRegionView3D_Persp perspo = RV3D_PERSP;
  int viewnum;
  int view_axis_roll = RV3D_VIEW_AXIS_ROLL_0;
  const int smooth_viewtx = WM_operator_smooth_viewtx_get(op);

  /* no nullptr check is needed, poll checks */
  ED_view3d_context_user_region(C, &v3d, &region);
  rv3d = static_cast<RegionView3D *>(region->regiondata);

  ED_view3d_smooth_view_force_finish(C, v3d, region);

  viewnum = RNA_enum_get(op->ptr, "type");
  const bool is_diagonal_view = viewnum >= VIEW3D_VIEW_DIAGONAL_BASE &&
                                viewnum < VIEW3D_VIEW_DIAGONAL_BASE +
                                              VIEW3D_VIEW_DIAGONAL_COUNT;
  const bool is_corner_view = viewnum >= VIEW3D_VIEW_CORNER_BASE &&
                              viewnum < VIEW3D_VIEW_CORNER_BASE + VIEW3D_VIEW_CORNER_COUNT;
  const bool is_custom_axis_view = is_diagonal_view || is_corner_view;

  float align_quat_buf[4];
  float *align_quat = nullptr;

  if (RNA_boolean_get(op->ptr, "align_active")) {
    /* align to active object */
    Object *obact = CTX_data_active_object(C);
    if (obact != nullptr) {
      float twmat[3][3];
      const Main *bmain = CTX_data_main(C);
      const Scene *scene = CTX_data_scene(C);
      ViewLayer *view_layer = CTX_data_view_layer(C);
      Object *obedit = CTX_data_edit_object(C);
      /* same as transform gizmo when normal is set */
      ed::transform::ED_getTransformOrientationMatrix(
          *bmain, scene, view_layer, v3d, obact, obedit, V3D_AROUND_ACTIVE, twmat);
      align_quat = align_quat_buf;
      mat3_to_quat(align_quat, twmat);
      invert_qt_normalized(align_quat);
    }
  }

  if (RNA_boolean_get(op->ptr, "relative") && !is_custom_axis_view) {
    float quat_rotate[4];
    float quat_test[4];

    if (viewnum == RV3D_VIEW_LEFT) {
      axis_angle_to_quat(quat_rotate, rv3d->viewinv[1], -M_PI_2);
    }
    else if (viewnum == RV3D_VIEW_RIGHT) {
      axis_angle_to_quat(quat_rotate, rv3d->viewinv[1], M_PI_2);
    }
    else if (viewnum == RV3D_VIEW_TOP) {
      axis_angle_to_quat(quat_rotate, rv3d->viewinv[0], -M_PI_2);
    }
    else if (viewnum == RV3D_VIEW_BOTTOM) {
      axis_angle_to_quat(quat_rotate, rv3d->viewinv[0], M_PI_2);
    }
    else if (viewnum == RV3D_VIEW_FRONT) {
      unit_qt(quat_rotate);
    }
    else if (viewnum == RV3D_VIEW_BACK) {
      axis_angle_to_quat(quat_rotate, rv3d->viewinv[0], M_PI);
    }
    else {
      BLI_assert(0);
    }

    mul_qt_qtqt(quat_test, rv3d->viewquat, quat_rotate);

    float angle_best = FLT_MAX;
    int view_best = -1;
    int view_axis_roll_best = -1;
    for (int i = RV3D_VIEW_FRONT; i <= RV3D_VIEW_BOTTOM; i++) {
      for (int j = RV3D_VIEW_AXIS_ROLL_0; j <= RV3D_VIEW_AXIS_ROLL_270; j++) {
        float quat_axis[4];
        ED_view3d_quat_from_axis_view(
            eRegionView3D_View(i), eRegionView3D_ViewAxisRoll(j), quat_axis);
        if (align_quat) {
          mul_qt_qtqt(quat_axis, quat_axis, align_quat);
        }
        const float angle_test = fabsf(angle_signed_qtqt(quat_axis, quat_test));
        if (angle_best > angle_test) {
          angle_best = angle_test;
          view_best = i;
          view_axis_roll_best = j;
        }
      }
    }
    if (view_best == -1) {
      view_best = RV3D_VIEW_FRONT;
      view_axis_roll_best = RV3D_VIEW_AXIS_ROLL_0;
    }

    /* Disallow non-upright views in turn-table modes,
     * it's too difficult to navigate out of them. */
    if ((U.flag & USER_TRACKBALL) == 0) {
      if (!ELEM(view_best, RV3D_VIEW_TOP, RV3D_VIEW_BOTTOM)) {
        view_axis_roll_best = RV3D_VIEW_AXIS_ROLL_0;
      }
    }

    viewnum = view_best;
    view_axis_roll = view_axis_roll_best;
  }

  /* Maya's default ViewCube mode uses orthographic faces and perspective angled views. Never let
   * an orthographic face click leak into the following edge or corner click. */
  eRegionView3D_Persp nextperspo = RV3D_PERSP;
  if (!is_custom_axis_view) {
    nextperspo = (rv3d->persp == RV3D_CAMOB) ? rv3d->lpersp : perspo;
  }
  float quat[4];
  eRegionView3D_View viewnum_enum;
  const eRegionView3D_ViewAxisRoll view_axis_roll_enum = eRegionView3D_ViewAxisRoll(
      view_axis_roll);
  if (is_diagonal_view) {
    const int diagonal_index = viewnum - VIEW3D_VIEW_DIAGONAL_BASE;
    float direction_a[3];
    float direction_b[3];
    axis_view_direction(diagonal_view_pairs[diagonal_index][0], direction_a);
    axis_view_direction(diagonal_view_pairs[diagonal_index][1], direction_b);
    add_v3_v3(direction_a, direction_b);
    normalize_v3(direction_a);

    /* Aim exactly between the two neighboring face normals without introducing view roll. */
    view_quat_from_direction_y_up(direction_a, quat);
    viewnum_enum = RV3D_VIEW_USER;
  }
  else if (is_corner_view) {
    const int corner_index = viewnum - VIEW3D_VIEW_CORNER_BASE;
    float direction[3];
    float direction_next[3];
    axis_view_direction(corner_view_triples[corner_index][0], direction);
    axis_view_direction(corner_view_triples[corner_index][1], direction_next);
    add_v3_v3(direction, direction_next);
    axis_view_direction(corner_view_triples[corner_index][2], direction_next);
    add_v3_v3(direction, direction_next);
    normalize_v3(direction);

    /* Aim through the selected corner, equally between all three neighboring faces. */
    view_quat_from_direction_y_up(direction, quat);
    viewnum_enum = RV3D_VIEW_USER;
  }
  else {
    viewnum_enum = eRegionView3D_View(viewnum);
    ED_view3d_quat_from_axis_view(viewnum_enum, view_axis_roll_enum, quat);
  }
  axis_set_view(C,
                v3d,
                region,
                quat,
                viewnum_enum,
                view_axis_roll_enum,
                nextperspo,
                align_quat,
                smooth_viewtx);

  perspo = rv3d->persp;

  return OPERATOR_FINISHED;
}

void VIEW3D_OT_view_axis(wmOperatorType *ot)
{
  PropertyRNA *prop;

  /* identifiers */
  ot->name = "View Axis";
  ot->description = "Use a preset viewpoint";
  ot->idname = "VIEW3D_OT_view_axis";

  /* API callbacks. */
  ot->exec = view_axis_exec;
  ot->poll = ED_operator_rv3d_user_region_poll;

  /* flags */
  ot->flag = 0;

  ot->prop = RNA_def_enum(ot->srna, "type", prop_view_items, 0, "View", "Preset viewpoint to use");
  RNA_def_property_flag(ot->prop, PROP_SKIP_SAVE);
  RNA_def_property_translation_context(ot->prop, BLT_I18NCONTEXT_EDITOR_VIEW3D);

  prop = RNA_def_boolean(
      ot->srna, "align_active", false, "Align Active", "Align to the active object's axis");
  RNA_def_property_flag(prop, PROP_SKIP_SAVE);
  prop = RNA_def_boolean(
      ot->srna, "relative", false, "Relative", "Rotate relative to the current orientation");
  RNA_def_property_flag(prop, PROP_SKIP_SAVE);
}

/** \} */

}  // namespace blender
