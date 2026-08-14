/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

#include "transform_soft_selection.hh"

#include "transform.hh"

namespace blender::ed::transform {

bool soft_selection_mode_uses_surface_distance(const eTool_SoftSelectionFalloffMode mode)
{
  return mode == SOFT_SELECT_FALLOFF_SURFACE;
}

bool soft_selection_mode_affects_unselected_containers(const eTool_SoftSelectionFalloffMode mode)
{
  return mode == SOFT_SELECT_FALLOFF_GLOBAL;
}

bool transform_should_draw_proportional_circle(const int transform_flags)
{
  return (transform_flags & T_PROP_EDIT) != 0 && (transform_flags & T_SOFT_SELECTION) == 0;
}

}  // namespace blender::ed::transform
