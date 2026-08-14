/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

#include "BKE_soft_selection.hh"

#include <algorithm>
#include <cfloat>
#include <cmath>

#include "BLI_kdtree.hh"
#include "BLI_linklist_stack.h"
#include "BLI_math_geom.h"
#include "BLI_math_matrix.h"
#include "BLI_math_vector.h"
#include "BLI_utildefines.h"

#include "bmesh.hh"

namespace blender::bke {

struct SoftSelectionSpatialIndex {
  KDTree<float3> *tree = nullptr;
};

SoftSelectionSpatialIndex *soft_selection_spatial_index_create(const Span<float3> positions)
{
  if (positions.is_empty()) {
    return nullptr;
  }

  SoftSelectionSpatialIndex *index = MEM_new<SoftSelectionSpatialIndex>(__func__);
  index->tree = kdtree_new<float3>(positions.size());
  for (const int i : positions.index_range()) {
    kdtree_insert<float3>(index->tree, i, positions[i]);
  }
  kdtree_balance<float3>(index->tree);
  return index;
}

void soft_selection_spatial_index_free(SoftSelectionSpatialIndex *index)
{
  if (index == nullptr) {
    return;
  }
  kdtree_free<float3>(index->tree);
  MEM_delete(index);
}

bool soft_selection_spatial_index_nearest_distance(const SoftSelectionSpatialIndex *index,
                                                   const float3 &position,
                                                   float &r_distance)
{
  if (index == nullptr || index->tree == nullptr) {
    return false;
  }

  KDTreeNearest<float3> nearest;
  if (kdtree_find_nearest<float3>(index->tree, position, &nearest) == -1) {
    return false;
  }
  r_distance = nearest.dist;
  return true;
}

static float finite_unit_float(const float value, const float fallback)
{
  return std::isfinite(value) ? std::clamp(value, 0.0f, 1.0f) : fallback;
}

SoftSelectionCurve::SoftSelectionCurve(const SoftSelectionSettings &settings)
{
  points_num_ = std::clamp(settings.curve_point_count, 0, SOFT_SELECTION_CURVE_POINT_MAX);
  for (int i = 0; i < points_num_; i++) {
    points_[i] = settings.curve_points[i];
    points_[i].position = finite_unit_float(points_[i].position, 0.0f);
    points_[i].value = finite_unit_float(points_[i].value, 0.0f);
    const int interpolation = std::clamp(int(points_[i].interpolation),
                                         int(SOFT_SELECT_INTERP_NONE),
                                         int(SOFT_SELECT_INTERP_SPLINE));
    points_[i].interpolation = eTool_SoftSelectionInterpolation(interpolation);
  }

  /* Maya evaluates ramp entries in position order. Stable ordering gives duplicate entries a
   * deterministic meaning and preserves their MEL string order. */
  std::stable_sort(points_.begin(),
                   points_.begin() + points_num_,
                   [](const SoftSelectionCurvePoint &a, const SoftSelectionCurvePoint &b) {
                     return a.position < b.position;
                   });
}

static float interpolate_spline(const SoftSelectionCurvePoint &previous,
                                const SoftSelectionCurvePoint &left,
                                const SoftSelectionCurvePoint &right,
                                const SoftSelectionCurvePoint &next,
                                const float t)
{
  const float segment_width = right.position - left.position;
  const float left_span = right.position - previous.position;
  const float right_span = next.position - left.position;
  const float linear_slope = (right.value - left.value) / segment_width;
  const float left_slope = left_span > 0.0f ? (right.value - previous.value) / left_span :
                                              linear_slope;
  const float right_slope = right_span > 0.0f ? (next.value - left.value) / right_span :
                                                linear_slope;

  const float t2 = t * t;
  const float t3 = t2 * t;
  const float h00 = 2.0f * t3 - 3.0f * t2 + 1.0f;
  const float h10 = t3 - 2.0f * t2 + t;
  const float h01 = -2.0f * t3 + 3.0f * t2;
  const float h11 = t3 - t2;
  return h00 * left.value + h10 * segment_width * left_slope + h01 * right.value +
         h11 * segment_width * right_slope;
}

float SoftSelectionCurve::evaluate(const float normalized_distance) const
{
  const float position = finite_unit_float(normalized_distance, 1.0f);
  if (points_num_ == 0) {
    /* A malformed/old file remains usable and fails closed outside the explicit selection. */
    return position == 0.0f ? 1.0f : 0.0f;
  }
  if (points_num_ == 1 || position < points_[0].position) {
    return points_[0].value;
  }

  /* Use the last entry at a duplicate position. This also makes an exact ramp-key query return
   * that key's value, while the interpolation belongs to its outgoing segment as in Maya. */
  int left_index = 0;
  while (left_index + 1 < points_num_ && points_[left_index + 1].position <= position) {
    left_index++;
  }
  if (left_index + 1 == points_num_) {
    return points_[left_index].value;
  }

  const SoftSelectionCurvePoint &left = points_[left_index];
  const SoftSelectionCurvePoint &right = points_[left_index + 1];
  const float width = right.position - left.position;
  if (width <= 0.0f) {
    return right.value;
  }
  float t = (position - left.position) / width;

  float value;
  switch (left.interpolation) {
    case SOFT_SELECT_INTERP_NONE:
      value = left.value;
      break;
    case SOFT_SELECT_INTERP_LINEAR:
      value = left.value + t * (right.value - left.value);
      break;
    case SOFT_SELECT_INTERP_SMOOTH:
      t = t * t * (3.0f - 2.0f * t);
      value = left.value + t * (right.value - left.value);
      break;
    case SOFT_SELECT_INTERP_SPLINE: {
      const SoftSelectionCurvePoint &previous = points_[std::max(left_index - 1, 0)];
      const SoftSelectionCurvePoint &next = points_[std::min(left_index + 2, points_num_ - 1)];
      value = interpolate_spline(previous, left, right, next, t);
      break;
    }
    default:
      value = 0.0f;
      break;
  }
  return finite_unit_float(value, 0.0f);
}

float soft_selection_weight(const SoftSelectionCurve &curve,
                            const float distance,
                            const float radius,
                            const bool is_selected)
{
  if (is_selected) {
    return 1.0f;
  }
  if (!std::isfinite(distance) || !std::isfinite(radius) || radius <= 0.0f || distance > radius) {
    return 0.0f;
  }
  return curve.evaluate(distance / radius);
}

/* Propagate distance from v1 and v2 to v0. */
static bool bmesh_test_dist_add(
    BMVert *v0, BMVert *v1, BMVert *v2, float *distances, int *index, const float mtx[3][3])
{
  if ((BM_elem_flag_test(v0, BM_ELEM_SELECT) == 0) && (BM_elem_flag_test(v0, BM_ELEM_HIDDEN) == 0))
  {
    const int i0 = BM_elem_index_get(v0);
    const int i1 = BM_elem_index_get(v1);

    BLI_assert(distances[i1] != FLT_MAX);
    if (distances[i0] <= distances[i1]) {
      return false;
    }

    float distance;
    if (v2 != nullptr) {
      const int i2 = BM_elem_index_get(v2);
      BLI_assert(distances[i2] != FLT_MAX);
      if (distances[i0] <= distances[i2]) {
        return false;
      }

      float vm0[3], vm1[3], vm2[3];
      mul_v3_m3v3(vm0, mtx, v0->co);
      mul_v3_m3v3(vm1, mtx, v1->co);
      mul_v3_m3v3(vm2, mtx, v2->co);
      distance = geodesic_distance_propagate_across_triangle(
          vm0, vm1, vm2, distances[i1], distances[i2]);
    }
    else {
      float vector[3];
      sub_v3_v3v3(vector, v1->co, v0->co);
      mul_m3_v3(mtx, vector);
      distance = distances[i1] + len_v3(vector);
    }

    if (distance < distances[i0]) {
      distances[i0] = distance;
      if (index != nullptr) {
        index[i0] = index[i1];
      }
      return true;
    }
  }
  return false;
}

static bool bmesh_test_loose_edge(BMEdge *edge)
{
  if (edge->l == nullptr) {
    return true;
  }

  BMIter iter;
  BMFace *face;
  BM_ITER_ELEM (face, &iter, edge, BM_FACES_OF_EDGE) {
    if (BM_elem_flag_test(face, BM_ELEM_HIDDEN) == 0) {
      return false;
    }
  }
  return true;
}

void soft_selection_mesh_surface_distances(BMesh *bm,
                                           const float mtx[3][3],
                                           float *distances,
                                           int *index)
{
  BLI_LINKSTACK_DECLARE(queue, BMEdge *);
  BLI_LINKSTACK_DECLARE(queue_next, BMEdge *);

  /* Any BM_ELEM_TAG'd edge is in `queue_next`, so it is never added twice. */
  const int tag_queued = BM_ELEM_TAG;
  const int tag_loose = BM_ELEM_TAG_ALT;

  BLI_LINKSTACK_INIT(queue);
  BLI_LINKSTACK_INIT(queue_next);

  BMIter viter;
  BMVert *vert;
  int vert_index;
  BM_ITER_MESH_INDEX (vert, &viter, bm, BM_VERTS_OF_MESH, vert_index) {
    BM_elem_index_set(vert, vert_index);
    const bool selected = BM_elem_flag_test(vert, BM_ELEM_SELECT) &&
                          !BM_elem_flag_test(vert, BM_ELEM_HIDDEN);
    distances[vert_index] = selected ? 0.0f : FLT_MAX;
    if (index != nullptr) {
      index[vert_index] = vert_index;
    }
  }
  bm->elem_index_dirty &= ~BM_VERT;

  BMIter eiter;
  BMEdge *edge;
  BM_ITER_MESH (edge, &eiter, bm, BM_EDGES_OF_MESH) {
    BM_elem_flag_disable(edge, tag_queued);
    if (BM_elem_flag_test(edge, BM_ELEM_HIDDEN)) {
      continue;
    }

    const int index_1 = BM_elem_index_get(edge->v1);
    const int index_2 = BM_elem_index_get(edge->v2);
    if (distances[index_1] != FLT_MAX || distances[index_2] != FLT_MAX) {
      BLI_LINKSTACK_PUSH(queue, edge);
    }
    BM_elem_flag_set(edge, tag_loose, bmesh_test_loose_edge(edge));
  }

  do {
    while ((edge = BLI_LINKSTACK_POP(queue))) {
      BMVert *vert_1 = edge->v1;
      BMVert *vert_2 = edge->v2;
      int index_1 = BM_elem_index_get(vert_1);
      int index_2 = BM_elem_index_get(vert_2);

      if (BM_elem_flag_test(edge, tag_loose) ||
          (distances[index_1] == FLT_MAX || distances[index_2] == FLT_MAX))
      {
        if (distances[index_1] > distances[index_2]) {
          std::swap(index_1, index_2);
          std::swap(vert_1, vert_2);
        }

        if (bmesh_test_dist_add(vert_2, vert_1, nullptr, distances, index, mtx)) {
          const bool need_direct_distance = BM_elem_flag_test(edge, tag_loose) ||
                                            BM_elem_flag_test(vert_1, BM_ELEM_SELECT) ||
                                            BM_elem_flag_test(vert_2, BM_ELEM_SELECT);
          BMEdge *other_edge;
          BMIter other_eiter;
          BM_ITER_ELEM (other_edge, &other_eiter, vert_2, BM_EDGES_OF_VERT) {
            if (other_edge != edge && !BM_elem_flag_test(other_edge, tag_queued) &&
                !BM_elem_flag_test(other_edge, BM_ELEM_HIDDEN) &&
                (need_direct_distance || BM_elem_flag_test(other_edge, tag_loose) ||
                 distances[BM_elem_index_get(BM_edge_other_vert(other_edge, vert_2))] != FLT_MAX))
            {
              BM_elem_flag_enable(other_edge, tag_queued);
              BLI_LINKSTACK_PUSH(queue_next, other_edge);
            }
          }
        }
      }

      if (!BM_elem_flag_test(edge, tag_loose)) {
        BMLoop *loop;
        BMIter liter;
        BM_ITER_ELEM (loop, &liter, edge, BM_LOOPS_OF_EDGE) {
          if (BM_elem_flag_test(loop->f, BM_ELEM_HIDDEN)) {
            continue;
          }
          for (BMLoop *other_loop = loop->next->next; other_loop != loop;
               other_loop = other_loop->next)
          {
            BMVert *other_vert = other_loop->v;
            BLI_assert(!ELEM(other_vert, vert_1, vert_2));
            if (bmesh_test_dist_add(other_vert, vert_1, vert_2, distances, index, mtx)) {
              BMEdge *other_edge;
              BMIter other_eiter;
              BM_ITER_ELEM (other_edge, &other_eiter, other_vert, BM_EDGES_OF_VERT) {
                if (other_edge != edge && !BM_elem_flag_test(other_edge, tag_queued) &&
                    !BM_elem_flag_test(other_edge, BM_ELEM_HIDDEN) &&
                    (BM_elem_flag_test(other_edge, tag_loose) ||
                     distances[BM_elem_index_get(BM_edge_other_vert(other_edge, other_vert))] !=
                         FLT_MAX))
                {
                  BM_elem_flag_enable(other_edge, tag_queued);
                  BLI_LINKSTACK_PUSH(queue_next, other_edge);
                }
              }
            }
          }
        }
      }
    }

    for (LinkNode *link = queue_next; link != nullptr; link = link->next) {
      BM_elem_flag_disable(static_cast<BMEdge *>(link->link), tag_queued);
    }
    BLI_LINKSTACK_SWAP(queue, queue_next);
    BLI_assert(BM_iter_mesh_count_flag(BM_EDGES_OF_MESH, bm, tag_queued, true) == 0);
  } while (BLI_LINKSTACK_SIZE(queue));

  BLI_LINKSTACK_FREE(queue);
  BLI_LINKSTACK_FREE(queue_next);
}

}  // namespace blender::bke
