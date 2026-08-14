/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

#pragma once

#include <array>

#include "BLI_math_vector_types.hh"
#include "BLI_span.hh"

#include "DNA_scene_types.h"

struct BMesh;

namespace blender::bke {

struct SoftSelectionSpatialIndex;

/**
 * Build an immutable nearest-neighbor index for Maya Volume/Global falloff distances.
 *
 * The implementation is deliberately opaque so draw-engine headers do not expose BLI's KD-tree
 * templates (or become dependent on their include order). Returns nullptr for an empty input.
 */
SoftSelectionSpatialIndex *soft_selection_spatial_index_create(Span<float3> positions);

void soft_selection_spatial_index_free(SoftSelectionSpatialIndex *index);

/** Return false only when `index` is null or empty. */
bool soft_selection_spatial_index_nearest_distance(const SoftSelectionSpatialIndex *index,
                                                   const float3 &position,
                                                   float &r_distance);

/** A sorted, immutable Maya falloff snapshot, shared by transforms and viewport feedback. */
class SoftSelectionCurve {
 private:
  std::array<SoftSelectionCurvePoint, SOFT_SELECTION_CURVE_POINT_MAX> points_{};
  int points_num_ = 0;

 public:
  explicit SoftSelectionCurve(const SoftSelectionSettings &settings);

  /** Evaluate the Maya ramp at normalized falloff distance: 0 at selection, 1 at radius. */
  float evaluate(float normalized_distance) const;

  int size() const
  {
    return points_num_;
  }
};

/**
 * Convert a geometric distance to the exact transform weight used by Maya-style soft selection.
 * Explicit selection always has full weight, independent of the editable falloff curve.
 */
float soft_selection_weight(const SoftSelectionCurve &curve,
                            float distance,
                            float radius,
                            bool is_selected);

/**
 * Calculate Maya Surface-mode geodesic distances in the space described by `mtx`.
 *
 * Hidden geometry is a boundary. `index` optionally receives the selected source vertex index.
 */
void soft_selection_mesh_surface_distances(BMesh *bm,
                                           const float mtx[3][3],
                                           float *distances,
                                           int *index = nullptr);

}  // namespace blender::bke
