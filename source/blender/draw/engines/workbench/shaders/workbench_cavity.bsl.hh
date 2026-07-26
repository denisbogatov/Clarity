/* SPDX-FileCopyrightText: 2017-2023 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

#pragma once

#include "draw_view_lib.glsl"

#include "workbench_common.bsl.hh"

SHADER_LIBRARY_CREATE_INFO(draw_view)

/* From The Alchemy screen-space ambient obscurance algorithm
 * http://graphics.cs.williams.edu/papers/AlchemyHPG11/VV11AlchemyAO.pdf */

namespace workbench {

struct Cavity {
  [[sampler(7)]] sampler2D jitter_tx;
  [[uniform(5)]] const float4 (&cavity_samples)[512];
};

void cavity_compute([[resource_table]] const workbench::Cavity &cavity,
                    [[resource_table]] const workbench::World &world,
                    sampler2DDepth depth_tx,
                    sampler2D normal_tx,
                    float2 screenco,
                    float &cavities,
                    float &edges)
{
  cavities = edges = 0.0f;

  float depth = texture(depth_tx, screenco).x;

  /* Early out if background and in front. */
  if (depth == 1.0f || depth == 0.0f) {
    return;
  }

  const WorldData &world_data = world.world_data;

  float3 position = drw_point_screen_to_view(float3(screenco, depth));
  float3 normal = workbench::normal_decode(texture(normal_tx, screenco));

  float2 jitter_co = (screenco * world_data.viewport_size.xy) * world_data.cavity_jitter_scale;
  float2 noise = texture(cavity.jitter_tx, jitter_co).rg;

  /* Maya Viewport 2.0 defines the SSAO radius in screen-space pixels. */
  float2 offset = world_data.viewport_size_inv * world_data.cavity_distance;

  /* NOTE: Putting noise usage here to put some ALU after texture fetch. */
  float2 rotX = noise;
  float2 rotY = float2(-rotX.y, rotX.x);

  float sample_weight_sum = 0.0f;
  int sample_start = world_data.cavity_sample_start;
  int sample_end = world_data.cavity_sample_end;
  for (int i = sample_start; i < sample_end && i < 512; i++) {
    /* sample_coord.xy is sample direction (normalized).
     * sample_coord.z is sample distance from disk center. */
    float4 sample_coord = cavity.cavity_samples[i];
    /* Rotate with random direction to get jittered result. */
    float2 dir_jittered = float2(dot(sample_coord.xy, rotX), dot(sample_coord.xy, rotY));
    dir_jittered.xy *= sample_coord.z;

    float2 uvcoords = screenco + dir_jittered * offset;
    /* Out of screen case. */
    if (any(greaterThan(abs(uvcoords - 0.5f), float2(0.5f)))) {
      continue;
    }
    float sample_weight = sample_coord.w;
    sample_weight_sum += sample_weight;

    /* Sample depth. */
    float s_depth = texture(depth_tx, uvcoords).r;
    /* Background pixels do not participate in Maya's normal-depth SSAO pass. */
    if (s_depth == 1.0f || s_depth == 0.0f) {
      continue;
    }
    float3 s_pos = drw_point_screen_to_view(float3(uvcoords, s_depth));

    float3 dir = s_pos - position;
    float len = length(dir);
    float f_cavities = dot(dir, normal);
    float f_bias = 0.05f * len + 0.0001f;

    float attenuation = 1.0f / (len * (1.0f + len * len * world_data.cavity_attenuation));

    /* use minor bias here to avoid self shadowing */
    if (f_cavities > -f_bias) {
      cavities += f_cavities * attenuation * sample_weight;
    }
  }
  cavities /= max(sample_weight_sum, 1.0e-8f);

  /* don't let cavity wash out the surface appearance */
  cavities = clamp(cavities * world_data.cavity_valley_factor, 0.0f, 1.0f);
}

}  // namespace workbench
