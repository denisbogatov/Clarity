/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

#include "testing/testing.h"

#include "BLI_math_vector.h"

#include "transform.hh"
#include "transform_snap.hh"

namespace blender::ed::transform::tests {

static TransSnap maya_snap_state(const bool maya_mode_active,
                                 const bool pivot_valid,
                                 const float pivot[3])
{
  TransSnap tsnap = {};
  tsnap.maya_mode_active = maya_mode_active;
  tsnap.maya_pivot_source_valid = pivot_valid;
  copy_v3_v3(tsnap.maya_pivot_source, pivot);
  return tsnap;
}

/** Plain Blender snapping keeps moving the center of the selection onto the target. */
TEST(transform_snap, SourceCenterIgnoresPivotWithoutMayaSnapping)
{
  const float pivot[3] = {5.0f, 6.0f, 7.0f};
  const float center[3] = {1.0f, 2.0f, 3.0f};
  const TransSnap tsnap = maya_snap_state(false, true, pivot);

  float source[3];
  transform_snap_source_center_calc(tsnap, center, source);
  EXPECT_EQ_ARRAY(center, source, 3);
}

/** Maya puts the pivot the user sees onto the target, whatever the selection center is. */
TEST(transform_snap, SourceCenterUsesCapturedPivotWithMayaSnapping)
{
  const float pivot[3] = {5.0f, 6.0f, 7.0f};
  const float center[3] = {1.0f, 2.0f, 3.0f};
  const TransSnap tsnap = maya_snap_state(true, true, pivot);

  float source[3];
  transform_snap_source_center_calc(tsnap, center, source);
  EXPECT_EQ_ARRAY(pivot, source, 3);
}

/** No pivot was captured (no custom pivot, or the pivot itself is being edited). */
TEST(transform_snap, SourceCenterFallsBackToCenterWithoutCapturedPivot)
{
  const float pivot[3] = {5.0f, 6.0f, 7.0f};
  const float center[3] = {1.0f, 2.0f, 3.0f};
  const TransSnap tsnap = maya_snap_state(true, false, pivot);

  float source[3];
  transform_snap_source_center_calc(tsnap, center, source);
  EXPECT_EQ_ARRAY(center, source, 3);
}

/**
 * The pivot the source sits on is excluded from the pivot targets in every mode. Returning null
 * here is what created the dead zone in which the selection snapped onto its own pivot.
 */
TEST(transform_snap, ExcludedPivotFollowsTheSnapSource)
{
  const float pivot[3] = {5.0f, 6.0f, 7.0f};
  const float center[3] = {1.0f, 2.0f, 3.0f};

  const TransSnap captured = maya_snap_state(true, true, pivot);
  const float *excluded = transform_snap_excluded_pivot_get(captured, center);
  ASSERT_NE(excluded, nullptr);
  EXPECT_EQ_ARRAY(pivot, excluded, 3);

  /* Editing the pivot captures nothing, there the transform center already is the pivot. */
  const TransSnap pivot_edit = maya_snap_state(true, false, pivot);
  excluded = transform_snap_excluded_pivot_get(pivot_edit, center);
  ASSERT_NE(excluded, nullptr);
  EXPECT_EQ_ARRAY(center, excluded, 3);
}

}  // namespace blender::ed::transform::tests
