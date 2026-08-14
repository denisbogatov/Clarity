/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

#include "infos/overlay_extra_infos.hh"

VERTEX_SHADER_CREATE_INFO(overlay_soft_selection_point)

#include "draw_view_clipping_lib.glsl"
#include "draw_view_lib.glsl"

void main()
{
  float3 world_pos = data_buf[gl_VertexID].pos_.xyz;
  gl_Position = drw_point_world_to_homogenous(world_pos);
  gl_Position.z -= ndc_offset_factor * ndc_offset;
  gl_PointSize = theme.sizes.vert * 2.0f;

  final_color = data_buf[gl_VertexID].color_;
  final_color.a = 1.0f;
  view_clipping_distances(world_pos);
}
