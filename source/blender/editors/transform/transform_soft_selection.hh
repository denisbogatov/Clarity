/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

#pragma once

#include "BKE_soft_selection.hh"

namespace blender::ed::transform {

using bke::SoftSelectionCurve;

bool soft_selection_mode_uses_surface_distance(eTool_SoftSelectionFalloffMode mode);
bool soft_selection_mode_affects_unselected_containers(eTool_SoftSelectionFalloffMode mode);

/** Standard Blender radius feedback is hidden when proportional editing backs Soft Selection. */
bool transform_should_draw_proportional_circle(int transform_flags);

}  // namespace blender::ed::transform
