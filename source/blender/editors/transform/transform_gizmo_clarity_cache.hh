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
  static constexpr ClarityGizmoRGB8 selected = {253, 255, 136};

  static constexpr float translate_axis_start = 0.25f;
  static constexpr float translate_axis_end = 0.80f;
  static constexpr float scale_axis_start = 0.25f;
  static constexpr float scale_axis_end = 0.75f;

  /* The plane diamond itself extends another 0.1 units, so these put its centre at 0.6/0.8. */
  static constexpr float plane_length = 0.50f;
  static constexpr float edit_pivot_plane_length = 0.70f;
  static constexpr float plane_fill_alpha = 0.25f;
  static constexpr float trackball_alpha = 0.0f;

  static constexpr float translate_center_scale = 0.135f;
  static constexpr float scale_center_scale = 0.065f;
  static constexpr float rotate_axis_scale = 0.80f;
  static constexpr float rotate_view_scale = 0.92f;
  static constexpr float maya_edit_pivot_rotate_scale = 0.40f;
  /* The literal Maya radius reads too small in Blender's UI; keep its measured value above. */
  static constexpr float edit_pivot_rotate_scale = 0.50f;
  static constexpr float line_width = 1.0f;
  static constexpr float edit_pivot_axis_select_radius = 0.12f;
  static constexpr float edit_pivot_ring_select_width = 14.0f;
};

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
