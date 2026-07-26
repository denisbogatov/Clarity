/* SPDX-FileCopyrightText: 2023 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup edtransform
 */

#include "DNA_curve_types.h"

#include <cfloat>
#include <cmath>

#include "BLI_listbase.h"
#include "BLI_math_geom.h"
#include "BLI_math_matrix.h"
#include "BLI_math_vector.h"
#include "BLI_vector.hh"

#include "BKE_curve.hh"
#include "BKE_object.hh"

#include "ED_transform_snap_object_context.hh"

#include "transform_snap_object.hh"

namespace blender::ed::transform {

static bool project_to_screen(const SnapObjectContext &sctx,
                              const SnapData &nearest2d,
                              const float3 &point,
                              float2 &r_screen)
{
  float clip[4];
  mul_v4_m4v3(clip, nearest2d.pmat_local.ptr(), point);
  if (fabsf(clip[3]) < 1e-8f) {
    return false;
  }
  r_screen.x = (clip[0] / clip[3] * 0.5f + 0.5f) * sctx.runtime.win_size.x;
  r_screen.y = (clip[1] / clip[3] * 0.5f + 0.5f) * sctx.runtime.win_size.y;
  return true;
}

static bool snap_bezier_segment_adaptive(const SnapObjectContext &sctx,
                                         SnapData &nearest2d,
                                         const float3 &p0,
                                         const float3 &p1,
                                         const float3 &p2,
                                         const float3 &p3,
                                         const int depth)
{
  float2 screen[4];
  const bool projected = project_to_screen(sctx, nearest2d, p0, screen[0]) &&
                         project_to_screen(sctx, nearest2d, p1, screen[1]) &&
                         project_to_screen(sctx, nearest2d, p2, screen[2]) &&
                         project_to_screen(sctx, nearest2d, p3, screen[3]);
  const bool flat_enough = projected &&
                           max_ff(dist_squared_to_line_segment_v2(
                                      screen[1], screen[0], screen[3]),
                                  dist_squared_to_line_segment_v2(
                                      screen[2], screen[0], screen[3])) <= 0.25f;
  if (flat_enough || depth >= (projected ? 12 : 6)) {
    return nearest2d.snap_edge(p0, p3);
  }

  const float3 p01 = (p0 + p1) * 0.5f;
  const float3 p12 = (p1 + p2) * 0.5f;
  const float3 p23 = (p2 + p3) * 0.5f;
  const float3 p012 = (p01 + p12) * 0.5f;
  const float3 p123 = (p12 + p23) * 0.5f;
  const float3 p0123 = (p012 + p123) * 0.5f;
  return snap_bezier_segment_adaptive(
             sctx, nearest2d, p0, p01, p012, p0123, depth + 1) |
         snap_bezier_segment_adaptive(
             sctx, nearest2d, p0123, p123, p23, p3, depth + 1);
}

static bool snap_bezier_shape(const SnapObjectContext &sctx,
                              SnapData &nearest2d,
                              const Nurb &nu)
{
  if (nu.pntsu < 2) {
    return false;
  }

  bool has_snap = false;
  const bool is_cyclic = (nu.flagu & CU_NURB_CYCLIC) != 0;
  const int segment_count = nu.pntsu - (is_cyclic ? 0 : 1);
  for (const int segment : IndexRange(segment_count)) {
    const BezTriple &a = nu.bezt[segment];
    const BezTriple &b = nu.bezt[(segment + 1) % nu.pntsu];
    if (a.h2 == HD_VECT && b.h1 == HD_VECT) {
      has_snap |= nearest2d.snap_edge(a.vec[1], b.vec[1]);
    }
    else {
      has_snap |= snap_bezier_segment_adaptive(
          sctx, nearest2d, a.vec[1], a.vec[2], b.vec[0], b.vec[1], 0);
    }
  }
  return has_snap;
}

static bool snap_nurbs_shape(const SnapObjectContext &sctx,
                             SnapData &nearest2d,
                             const Nurb &nu)
{
  if (nu.pntsv != 1 || !BKE_nurb_check_valid_u(&nu)) {
    return false;
  }

  float2 screen_min(FLT_MAX);
  float2 screen_max(-FLT_MAX);
  bool has_projected_point = false;
  for (const int point : IndexRange(nu.pntsu)) {
    float2 screen;
    if (project_to_screen(sctx, nearest2d, float3(nu.bp[point].vec), screen)) {
      minmax_v2v2_v2(screen_min, screen_max, screen);
      has_projected_point = true;
    }
  }
  const int segment_count = max_ii(SEGMENTSU(&nu), 1);
  const float screen_extent = has_projected_point ? len_v2v2(screen_min, screen_max) : 0.0f;
  const int adaptive_resolution = clamp_i(
      int(ceilf(screen_extent / (8.0f * segment_count))), 8, 64);
  const int resolution = max_ii(nu.resolu, adaptive_resolution);
  const int points_num = resolution * SEGMENTSU(&nu);
  if (points_num < 2) {
    return false;
  }

  Vector<float3> points(points_num, float3(0.0f));
  BKE_nurb_makeCurve(&nu,
                     reinterpret_cast<float *>(points.data()),
                     nullptr,
                     nullptr,
                     nullptr,
                     resolution,
                     sizeof(float3));

  bool has_snap = false;
  for (const int point : IndexRange(1, points_num - 1)) {
    has_snap |= nearest2d.snap_edge(points[point - 1], points[point]);
  }
  if (nu.flagu & CU_NURB_CYCLIC) {
    has_snap |= nearest2d.snap_edge(points.last(), points.first());
  }
  return has_snap;
}

static bool snap_poly_shape(SnapData &nearest2d, const Nurb &nu)
{
  if (nu.pntsu < 2) {
    return false;
  }

  bool has_snap = false;
  for (const int point : IndexRange(1, nu.pntsu - 1)) {
    has_snap |= nearest2d.snap_edge(float3(nu.bp[point - 1].vec), float3(nu.bp[point].vec));
  }
  if (nu.flagu & CU_NURB_CYCLIC) {
    has_snap |= nearest2d.snap_edge(float3(nu.bp[nu.pntsu - 1].vec), float3(nu.bp[0].vec));
  }
  return has_snap;
}

eSnapMode snapCurve(SnapObjectContext *sctx, const Object *ob_eval, const float4x4 &obmat)
{
  bool has_snap = false;

  const bool snap_to_shape = (sctx->runtime.snap_to_flag & SCE_SNAP_TO_EDGE) != 0;
  const bool snap_to_points = (sctx->runtime.snap_to_flag & SCE_SNAP_TO_POINT) != 0;
  if (!snap_to_shape && !snap_to_points) {
    return SCE_SNAP_TO_NONE;
  }

  Curve *cu = id_cast<Curve *>(ob_eval->data);

  SnapData nearest2d(sctx, obmat);

  const bool use_obedit = BKE_object_is_in_editmode(ob_eval);

  if (use_obedit == false) {
    /* Test BoundBox. */
    std::optional<Bounds<float3>> bounds = BKE_curve_minmax(cu, true);
    if (bounds && !nearest2d.snap_boundbox(bounds->min, bounds->max)) {
      return SCE_SNAP_TO_NONE;
    }
  }

  nearest2d.clip_planes_enable(sctx, ob_eval, !snap_to_shape);

  bool skip_selected = (sctx->runtime.params.snap_target_select & SCE_SNAP_TARGET_NOT_SELECTED) !=
                       0;

  for (Nurb &nu : use_obedit ? cu->editnurb->nurbs : cu->nurb) {
    if (use_obedit && nu.hide) {
      continue;
    }

    if (snap_to_shape) {
      if (use_obedit && skip_selected) {
        bool has_selected_control_point = false;
        if (nu.bezt) {
          for (const int point : IndexRange(nu.pntsu)) {
            if (nu.bezt[point].f2 & SELECT) {
              has_selected_control_point = true;
              break;
            }
          }
        }
        else if (nu.bp) {
          for (const int point : IndexRange(nu.pntsu * nu.pntsv)) {
            if (nu.bp[point].f1 & SELECT) {
              has_selected_control_point = true;
              break;
            }
          }
        }
        if (has_selected_control_point) {
          continue;
        }
      }

      if (nu.type == CU_BEZIER) {
        has_snap |= snap_bezier_shape(*sctx, nearest2d, nu);
      }
      else if (nu.type == CU_NURBS) {
        has_snap |= snap_nurbs_shape(*sctx, nearest2d, nu);
      }
      else if (nu.type == CU_POLY) {
        has_snap |= snap_poly_shape(nearest2d, nu);
      }
      continue;
    }

    if (nu.bezt) {
      for (int u : IndexRange(nu.pntsu)) {
        if (use_obedit) {
          if (nu.bezt[u].hide) {
            /* Skip hidden. */
            continue;
          }

          bool is_selected = (nu.bezt[u].f2 & SELECT) != 0;
          if (is_selected && skip_selected) {
            continue;
          }

          /* Don't snap if handle is selected (moving),
           * or if it is aligning to a moving handle. */
          bool is_selected_h1 = (nu.bezt[u].f1 & SELECT) != 0;
          bool is_selected_h2 = (nu.bezt[u].f3 & SELECT) != 0;
          bool is_autoalign_h1 = (nu.bezt[u].h1 & HD_ALIGN) != 0;
          bool is_autoalign_h2 = (nu.bezt[u].h2 & HD_ALIGN) != 0;
          if (!skip_selected || !(is_selected_h1 || (is_autoalign_h1 && is_selected_h2))) {
            has_snap |= nearest2d.snap_point(nu.bezt[u].vec[0]);
          }

          if (!skip_selected || !(is_selected_h2 || (is_autoalign_h2 && is_selected_h1))) {
            has_snap |= nearest2d.snap_point(nu.bezt[u].vec[2]);
          }
        }
        has_snap |= nearest2d.snap_point(nu.bezt[u].vec[1]);
      }
    }
    else if (nu.bp) {
      for (int u : IndexRange(nu.pntsu * nu.pntsv)) {
        if (use_obedit) {
          if (nu.bp[u].hide) {
            /* Skip hidden. */
            continue;
          }

          bool is_selected = (nu.bp[u].f1 & SELECT) != 0;
          if (is_selected && skip_selected) {
            continue;
          }
        }
        has_snap |= nearest2d.snap_point(nu.bp[u].vec);
      }
    }
  }
  if (has_snap) {
    nearest2d.register_result(sctx, ob_eval, &cu->id);
    return snap_to_shape ? SCE_SNAP_TO_EDGE : SCE_SNAP_TO_POINT;
  }
  return SCE_SNAP_TO_NONE;
}

}  // namespace blender::ed::transform
