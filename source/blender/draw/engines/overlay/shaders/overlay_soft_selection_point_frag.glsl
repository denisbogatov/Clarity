/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

#include "infos/overlay_extra_infos.hh"

FRAGMENT_SHADER_CREATE_INFO(overlay_soft_selection_point)

void main()
{
  /* Maya's component feedback is the ramp color itself, without Blender's vertex-theme mix. */
  const float distance_to_center = distance(gl_PointCoord, float2(0.5f));
  if (distance_to_center > 0.5f) {
    gpu_discard_fragment();
    return;
  }
  frag_color = final_color;
  line_output = float4(0.0f);
}
