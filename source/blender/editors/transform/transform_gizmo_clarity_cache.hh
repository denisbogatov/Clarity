/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup edtransform
 *
 * Maya visual profile and narrow state for avoiding redundant Clarity gizmo style writes.
 */

#pragma once

namespace blender::ed::transform {

struct ClarityGizmoRGB8 {
  int r;
  int g;
  int b;
};

/**
 * Screen-space measurements from `tests/pivot_reference/fixtures/maya_2025_pivot_visual.json`.
 *
 * Geometry is expressed in Blender gizmo units. At the reference/default size one unit is 75 px,
 * which keeps these values independent of display scale and the user's gizmo-size preference.
 */
struct ClarityGizmoVisualProfile {
  static constexpr float reference_size_px = 75.0f;

  static constexpr ClarityGizmoRGB8 axis_x = {255, 1, 0};
  static constexpr ClarityGizmoRGB8 axis_y = {0, 255, 15};
  static constexpr ClarityGizmoRGB8 axis_z = {0, 0, 255};
  static constexpr ClarityGizmoRGB8 view = {100, 220, 255};
  /* The ring that rotates in the plane of the screen, outside the sphere. */
  static constexpr ClarityGizmoRGB8 view_rotate = {255, 255, 0};
  static constexpr ClarityGizmoRGB8 selected = {253, 255, 136};

  static constexpr float translate_axis_start = 0.25f;
  static constexpr float translate_axis_end = 0.80f;
  static constexpr float scale_axis_start = 0.25f;
  static constexpr float scale_axis_end = 0.75f;

  /* The plane diamond itself extends another 0.1 units, so these put its centre at 0.6/0.8. */
  static constexpr float plane_length = 0.50f;
  static constexpr float maya_edit_pivot_plane_length = 0.70f;
  static constexpr float plane_fill_alpha = 0.25f;
  /**
   * Opacity of the trackball, which Clarity draws as the outline of the sphere.
   *
   * Blender fills the disc translucently and Maya does not; what Maya draws is the circle
   * where the sphere meets its own silhouette, and it is the shape the three axis rings end
   * on - each of them is a half circle of exactly this radius, so their ends sit on it. The
   * fill is dropped through #ED_GIZMO_DIAL_DRAW_FLAG_FILL_SELECT, which keeps the disc for
   * picking and leaves the drawing a line, so this is the opacity of that line.
   */
  static constexpr float trackball_alpha = 1.0f;

  static constexpr float translate_center_scale = 0.135f;
  static constexpr float scale_center_scale = 0.065f;
  static constexpr float rotate_axis_scale = 0.80f;
  static constexpr float rotate_view_scale = 0.92f;
  static constexpr float maya_edit_pivot_rotate_scale = 0.40f;
  static constexpr float line_width = 1.0f;

  /**
   * How much larger than Maya the pivot manipulator is drawn.
   *
   * Maya's own is an 80 px arrow with a 30 px ring around it, and matching that literally is what
   * the values above do. Edit Pivot is the one layout that puts three rings, three plane handles
   * and a centre square inside those same 80 px, so the free stretch of an arrow - the part with
   * nothing else drawn across it - came out around 20 px of one-pixel line. Maya's proportions are
   * kept and every Edit Pivot handle is scaled by this one factor, which is the same thing a Maya
   * user does with `+` when the manipulator is too small for the display.
   */
  static constexpr float edit_pivot_size_boost = 1.40f;
  static constexpr float edit_pivot_axis_start = translate_axis_start * edit_pivot_size_boost;
  static constexpr float edit_pivot_axis_end = translate_axis_end * edit_pivot_size_boost;
  static constexpr float edit_pivot_rotate_scale = maya_edit_pivot_rotate_scale *
                                                   edit_pivot_size_boost;
  static constexpr float edit_pivot_plane_length = maya_edit_pivot_plane_length *
                                                   edit_pivot_size_boost;
  /* The centre square is the one handle the boost leaves alone. Its size is not reach, it is what
   * it takes away from the arrows: it sits where they begin, and the cursor's pick range widens
   * every handle by the same eight pixels, so a square grown here is a square that answers where
   * the arrow is the thing being aimed at. Maya's measurement is small for the same reason. */
  static constexpr float edit_pivot_center_scale = translate_center_scale;

  /**
   * Half-width of the invisible cylinder that answers for an axis stem, in gizmo units.
   *
   * The stem is one pixel of line by Maya's measurement and stays that way; what a hand aims at is
   * this cylinder. It does not scale with #edit_pivot_size_boost - it is a pointing tolerance in
   * pixels, not part of the drawing.
   */
  static constexpr float edit_pivot_axis_select_radius = 0.20f;
  /**
   * Width of the band that answers for a rotation ring, in logical pixels.
   *
   * Unlike the axis stem above, a ring may not carry its tolerance in its own geometry. The three
   * rings cross each other twice per pair, and a selection pass hands the contested pixels to
   * whichever ring is nearest the camera - so a band wide enough to be comfortable is a band that
   * answers with the near ring while the cursor sits exactly on the far one. This is Maya's
   * `manipOptions -linePick`: one drawn pixel with a pixel of slack around it. The comfort comes
   * from the cursor instead, whose pick range is granted in steps, the narrowest one first.
   */
  static constexpr float ring_select_width = 3.0f;
  /**
   * The part of the centre handle that answers a press, as a fraction of its drawn half width.
   *
   * The centre square starts free movement in every direction at once - the one handle whose drag
   * cannot be undone by aiming better, and the one sitting exactly where all six axis handles
   * begin. Maya draws it as a square with a small circle inside, and it is the circle that has to
   * be hit: the square says where the handle is, the circle says how precisely it has to be meant.
   * Anything larger takes presses that were aimed at an arrow.
   */
  static constexpr float center_select_radius = 0.5f;
  /**
   * Depth bias of a handle that crosses the translate stems, in gizmo units.
   *
   * Picking is depth-based: the handle nearest the camera inside the cursor rectangle wins. A ring
   * meets every axis at a shared point, and a plane handle sits on a diagonal that a single view
   * angle can lay right along one of them, so without a bias the winner follows the camera and the
   * same aim answers differently from one orbit to the next. Negative pushes those handles back,
   * which is the same value upstream uses where a scale layout puts rings over the axes.
   */
  static constexpr float across_axes_select_bias = -2.0f;
};

/**
 * Write the manipulator's orientation into a transform matrix, keeping the matrix affine.
 *
 * The Clarity pivot owns the location row of #RegionView3D::twmat and writes it separately, three
 * floats at a time, so nothing on that path ever sets the fourth element of that row. A zero there
 * is not "no translation": it is a matrix that discards the translation of whatever it multiplies.
 * Every handle copies this matrix into its own basis, so the whole manipulator inherits it - and
 * the result is invisible until something multiplies by a matrix that has a translation. Drawing
 * does not: it runs with a model-view that carries none. Picking does: it puts the view matrix
 * there, and each handle lands at the camera instead of at the pivot, outside the few pixels the
 * selection pass rasterizes. That is a manipulator drawn exactly where it belongs and unable to
 * answer a click anywhere.
 */
constexpr void clarity_gizmo_matrix_axes_set(float matrix[4][4], const float axes[3][3])
{
  for (int axis = 0; axis < 3; axis++) {
    matrix[axis][0] = axes[axis][0];
    matrix[axis][1] = axes[axis][1];
    matrix[axis][2] = axes[axis][2];
    matrix[axis][3] = 0.0f;
  }
  matrix[3][3] = 1.0f;
}

/**
 * #wmGizmo::select_bias of the rotation rings.
 *
 * Rings and axis handles share their screen space in two layouts: Edit Pivot, which draws the rings
 * around the translate handles, and a tool that shows scale and rotation at once. In both the axis
 * has to win the contested pixels, because it is the smaller target and the one being aimed at.
 *
 * The plane handles of Edit Pivot follow the same rule, see #clarity_gizmo_plane_select_bias_get.
 */
constexpr float clarity_gizmo_rotate_select_bias_get(const bool edit_pivot,
                                                     const bool scale_and_rotate)
{
  return (edit_pivot || scale_and_rotate) ?
             ClarityGizmoVisualProfile::across_axes_select_bias :
             0.0f;
}

/**
 * #wmGizmo::select_bias of the plane handles.
 *
 * Edit Pivot pushes its plane diamonds out to the ends of the arrows, where a diagonal and an axis
 * can share the same pixels from a whole range of view angles. The arrow is what the user is aiming
 * at along its length; the diamond is only ever aimed at where it is drawn, and it keeps every
 * pixel an arrow does not want.
 */
constexpr float clarity_gizmo_plane_select_bias_get(const bool edit_pivot)
{
  return edit_pivot ? ClarityGizmoVisualProfile::across_axes_select_bias : 0.0f;
}

/**
 * Gizmo properties are rebuilt when the layout changes and temporarily overridden during a drag.
 * Between those transitions, rewriting the same RNA properties on every draw is unnecessary work.
 *
 * Every input the style depends on is part of the key, including the manipulator layout: the
 * translate handles are laid out from #GizmoGroup::twtype, so a cache that only tracked the two
 * style flags would keep a stale layout whenever a `twtype` change did not also happen to
 * invalidate.
 *
 * Kept trivial because #GizmoGroup is allocated with #MEM_new_zeroed.
 */
struct ClarityGizmoStyleCache {
  bool valid;
  bool use_clarity_style;
  bool use_edit_pivot_style;
  int twtype;

  bool update_needed(const bool next_clarity_style,
                     const bool next_edit_pivot_style,
                     const int next_twtype) const
  {
    return !valid || use_clarity_style != next_clarity_style ||
           use_edit_pivot_style != next_edit_pivot_style || twtype != next_twtype;
  }

  void mark_applied(const bool next_clarity_style,
                    const bool next_edit_pivot_style,
                    const int next_twtype)
  {
    valid = true;
    use_clarity_style = next_clarity_style;
    use_edit_pivot_style = next_edit_pivot_style;
    twtype = next_twtype;
  }

  void invalidate()
  {
    valid = false;
  }
};

}  // namespace blender::ed::transform
