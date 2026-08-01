/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup edtransform
 *
 * Narrow state for avoiding redundant Maya gizmo style writes.
 */

#pragma once

namespace blender::ed::transform {

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
struct MayaGizmoStyleCache {
  bool valid;
  bool use_maya_style;
  bool use_edit_pivot_style;
  int twtype;

  bool update_needed(const bool next_maya_style,
                     const bool next_edit_pivot_style,
                     const int next_twtype) const
  {
    return !valid || use_maya_style != next_maya_style ||
           use_edit_pivot_style != next_edit_pivot_style || twtype != next_twtype;
  }

  void mark_applied(const bool next_maya_style,
                    const bool next_edit_pivot_style,
                    const int next_twtype)
  {
    valid = true;
    use_maya_style = next_maya_style;
    use_edit_pivot_style = next_edit_pivot_style;
    twtype = next_twtype;
  }

  void invalidate()
  {
    valid = false;
  }
};

}  // namespace blender::ed::transform
