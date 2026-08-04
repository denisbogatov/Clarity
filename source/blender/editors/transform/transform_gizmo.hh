/* SPDX-FileCopyrightText: 2001-2002 NaN Holding BV. All rights reserved.
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup edtransform
 */

#pragma once

struct TransformBounds;
struct TransInfo;
namespace blender {

/* -------------------------------------------------------------------- */
/** \name Types/
 * \{ */

struct ARegion;
struct bContext;
struct bScreen;
struct RegionView3D;
struct Scene;
struct ScrArea;
struct wmGizmoGroup;
struct wmGizmoGroupType;
struct wmMsgBus;

namespace ed::transform {

/* Axes as index. */
enum {
  MAN_AXIS_TRANS_X = 0,
  MAN_AXIS_TRANS_Y,
  MAN_AXIS_TRANS_Z,
  MAN_AXIS_TRANS_C,

  MAN_AXIS_TRANS_XY,
  MAN_AXIS_TRANS_YZ,
  MAN_AXIS_TRANS_ZX,
#define MAN_AXIS_RANGE_TRANS_START MAN_AXIS_TRANS_X
#define MAN_AXIS_RANGE_TRANS_END (MAN_AXIS_TRANS_ZX + 1)

  MAN_AXIS_ROT_X,
  MAN_AXIS_ROT_Y,
  MAN_AXIS_ROT_Z,
  MAN_AXIS_ROT_C,
  MAN_AXIS_ROT_T, /* Trackball rotation. */
#define MAN_AXIS_RANGE_ROT_START MAN_AXIS_ROT_X
#define MAN_AXIS_RANGE_ROT_END (MAN_AXIS_ROT_T + 1)

  MAN_AXIS_SCALE_X,
  MAN_AXIS_SCALE_Y,
  MAN_AXIS_SCALE_Z,
  MAN_AXIS_SCALE_C,
  MAN_AXIS_SCALE_XY,
  MAN_AXIS_SCALE_YZ,
  MAN_AXIS_SCALE_ZX,
#define MAN_AXIS_RANGE_SCALE_START MAN_AXIS_SCALE_X
#define MAN_AXIS_RANGE_SCALE_END (MAN_AXIS_SCALE_ZX + 1)

  MAN_AXIS_LAST = MAN_AXIS_SCALE_ZX + 1,
};

/* Axis types. */
enum {
  MAN_AXES_ALL = 0,
  MAN_AXES_TRANSLATE,
  MAN_AXES_ROTATE,
  MAN_AXES_SCALE,
};

/** \} */

/* -------------------------------------------------------------------- */
/** \name Gizmo
 * \{ */

/* `transform_gizmo_3d.cc` */

#define GIZMO_AXIS_LINE_WIDTH 2.0f

/**
 * Whether \a axis_idx is still drawn while \a axis_idx_active is being dragged.
 *
 * Clarity keeps the whole manipulator on screen for the duration of the drag, so a handle that was
 * visible stays visible; Blender shows only the dragged handle, plus the translate arrows as a
 * visual reference. \a visible_before_drag keeps the handles that the view-alignment rules had
 * already hidden out of the way.
 */
bool gizmo_3d_axis_visible_during_drag(bool use_clarity_style,
                                       int axis_idx_active,
                                       int axis_idx,
                                       bool visible_before_drag);

/**
 * Draw style (`ED_GIZMO_PRIMITIVE_STYLE_*`) of the translate center handle. Clarity draws a square
 * that becomes a circle for the duration of the drag; Blender draws a circle either way.
 *
 * Edit Pivot is the exception: the square with a diamond and a circle is the indicator that the mode
 * is on, so it is drawn as long as the mode lasts, the drag included.
 */
int gizmo_3d_translate_center_style_get(bool use_clarity_style, bool is_dragging, bool is_edit_pivot);

/**
 * Manipulator layout of the mode, from the layout the active tool asks for.
 *
 * Edit Pivot adds the rotation rings on top of it, the way Clarity's pivot manipulator does, and a tool
 * with no manipulator of its own still gets the translate handles to drag the pivot by.
 */
int gizmo_3d_twtype_resolve(bool clarity_edit_pivot, int tool_twtype);

/**
 * Layout the translate handles are drawn with.
 *
 * Clarity's pivot manipulator puts the rotation rings *around* the Move handles without touching them.
 * Feeding the rings to the translate handles is what shortened the arrows, took their stems away and
 * hid the plane handles, which made turning the mode on look like the manipulator was rebuilt.
 */
int gizmo_3d_translate_layout_twtype_get(bool use_clarity_style, int twtype);

/**
 * Draw style (`ED_GIZMO_PRIMITIVE_STYLE_*`) of the scale center handle. Clarity draws a cube that the
 * drag keeps, Blender an annulus that the drag turns into a circle.
 */
int gizmo_3d_scale_center_style_get(bool use_clarity_style, bool is_dragging);

void gizmo_prepare_mat(const bContext *C, RegionView3D *rv3d, const TransformBounds *tbounds);
void gizmo_xform_message_subscribe(wmGizmoGroup *gzgroup,
                                   wmMsgBus *mbus,
                                   Scene *scene,
                                   bScreen *screen,
                                   ScrArea *area,
                                   ARegion *region,
                                   void (*type_fn)(wmGizmoGroupType *));

/**
 * Set the #T_NO_GIZMO flag.
 *
 * \note This maintains the conventional behavior of not displaying the gizmo if the operator has
 * been triggered by shortcuts.
 */
void transform_gizmo_3d_model_from_constraint_and_mode_init(TransInfo *t);

/**
 * Change the gizmo and its orientation to match the transform state.
 *
 * \note This used while the modal operator is running so changes to the constraint or mode show
 * the gizmo associated with that state, as if it had been the initial gizmo dragged.
 */
void transform_gizmo_3d_model_from_constraint_and_mode_set(TransInfo *t);

/**
 * Restores the non-modal state of the gizmo.
 */
void transform_gizmo_3d_model_from_constraint_and_mode_restore(TransInfo *t);

/** \} */

}  // namespace ed::transform
}  // namespace blender
