/* SPDX-FileCopyrightText: 2017-2025 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

#include "infos/overlay_grid_infos.hh"

FRAGMENT_SHADER_CREATE_INFO(overlay_grid_next)

#include "draw_view_lib.glsl"
#include "gpu_shader_math_base_lib.glsl"
#include "gpu_shader_utildefines_lib.glsl"
#include "overlay_common_lib.glsl"
#include "overlay_grid_common_lib.glsl"

/* TODO(not_mark): De-duplicate in BSL port, `gpu_shader_math_vector_compare_lib`. */
bool is_equal(float2 a, float2 b, float epsilon)
{
  return all(lessThanEqual(abs(a - b), float2(epsilon)));
}

void main()
{
  /* Test if a vertex output position overlaps with an active axis line. */
  constexpr float axis_epsilon = 2e-7f;
  bool3 axis_mask = bool3(
      flag_test(grid_flag, AXIS_X) && is_equal(vertex_out.pos.yz, float2(0.0), axis_epsilon),
      flag_test(grid_flag, AXIS_Y) && is_equal(vertex_out.pos.xz, float2(0.0), axis_epsilon),
      flag_test(grid_flag, AXIS_Z) && is_equal(vertex_out.pos.xy, float2(0.0), axis_epsilon));

  /* If an axis line overlaps, the fragment can be discarded. */
  if (any(axis_mask) && flag_test(grid_flag, SHOW_GRID)) {
    gpu_discard_fragment();
  }

  /* Axis color is fixed by theme, while grid color is a mix of [grid, grid_emphasis]
   * dependent on the level. */
  if (flag_test(grid_flag, GRID_FINITE) && any(axis_mask)) {
    out_color = float4(0.0f, 0.0f, 0.0f, 1.0f);
  }
  else if (flag_test(grid_flag, GRID_FINITE)) {
    /* Linear-light equivalent of Clarity's sRGB #404040 grid color. */
    out_color = float4(float3(0.05126946f), 1.0f);
  }
  else if (axis_mask.x) {
    out_color = theme.colors.grid_axis_x;
  }
  else if (axis_mask.y) {
    out_color = theme.colors.grid_axis_y;
  }
  else if (axis_mask.z) {
    out_color = theme.colors.grid_axis_z;
  }
  else {
    out_color = mix(theme.colors.grid, theme.colors.grid_emphasis, vertex_out_flat.emphasis);
  }

  /* Fragment alpha. */
  out_color.a *= vertex_out_flat.alpha;
  /* Keep the 3D viewport grid crisp like Clarity: it has a finite, hard boundary and does not
   * disappear with distance or viewing angle. The image editor still needs its edge fade for
   * very small UV units. */
  if (flag_test(grid_flag, GRID_SIMA)) {
    float length_fade = 1.0f - min(1.0f, dot(vertex_out.coord, vertex_out.coord));
    out_color.a *= pow2f(length_fade);
  }

  /* Viewport anti-aliasing output.
   * #159243: do not output AA information on straight lines in e.g. orthographic views,
   * as these will periodically lie above/below a pixel, causing shimmering in motion. */
  if (out_color.a != 0.0 && !flag_test(grid_flag, GRID_SIMA | GRID_ALIGNED)) {
    line_output = pack_line_data(gl_FragCoord.xy, edge_start, edge_pos);
  }
  else {
    line_output = float4(0.0);
  }

  /* Alpha discard; discard by stipple pattern for low alpha, to account for overlays
   * incompatible with depth+blend, e.g. MeshEdit. */
  constexpr float dash_width = 4.0f; /* Width of dash pattern; increase to make lines longer. */
  constexpr float fade_start = 0.1f; /* Cutoff for dash fade; alpha above is fully drawn. */
  constexpr float fade_rcp = 1.0f / fade_start;
  float dist = distance(edge_start, edge_pos);
  if (out_color.a < fade_start && fade_rcp * out_color.a < fract(dist / dash_width)) {
    gpu_discard_fragment();
  }

  /* Grid iteration additive alpha in perspective view; lower iterations
   * are given stronger alpha to minimize pop-in of upper iterations. */
  if (drw_view_is_perspective() && !flag_test(grid_flag, GRID_FINITE)) {
    constexpr float additive_alpha[OVERLAY_GRID_ITER_LEN] = {1.0f, 0.50f, 0.25f, 0.125f};
    out_color.a *= additive_alpha[grid_iter];
  }
}
