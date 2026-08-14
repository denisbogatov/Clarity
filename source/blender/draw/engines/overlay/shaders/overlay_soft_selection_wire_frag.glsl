/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

#include "infos/overlay_extra_infos.hh"

FRAGMENT_SHADER_CREATE_INFO(overlay_soft_selection_wire)

#include "overlay_common_lib.glsl"

void main()
{
  line_output = pack_line_data(gl_FragCoord.xy, edge_start, edge_pos);
  frag_color = final_color;
}
