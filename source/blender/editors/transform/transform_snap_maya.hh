/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup edtransform
 *
 * What the Maya snapping state asks of a transform.
 *
 * Deliberately not part of #transform_snap.hh: almost every translation unit of the module includes
 * that header, so the Maya rule set would drag them all into a rebuild on every edit. Only the
 * three files that decide, apply or test the rules include this one.
 */

#pragma once

#include "DNA_scene_types.h"

#include "ED_maya.hh"

namespace blender::ed::transform {

/**
 * Everything defaults to off: in the Maya interaction model nothing snaps unless a Maya mode asks
 * for it, so Blender's own magnet and its `Ctrl` invert never get a say. Leaving them in charge is
 * what quantized every transform to the increment grid with no key held, and what kept Maya's own
 * modes from snapping at all while the magnet was off.
 *
 * Pure data, so the rules are unit tested without a context.
 */
struct MayaSnapPlan {
  /** Snapping runs at all: #MOD_SNAP and #SCE_SNAP. */
  bool use_snap = false;
  eSnapMode snap_to = SCE_SNAP_TO_NONE;
  /** #SCE_SNAP_ABS_GRID: steps counted from the origin instead of from the transform start. */
  bool absolute_grid = false;
  bool curve_targets_only = false;
  bool include_object_pivots = false;
  /** Not a snap but a constraint: translation is projected onto the frozen view plane. */
  bool view_plane = false;
  bool mesh_center = false;
  /** Maya moves the pivot onto the target, never the closest part of the selection. */
  bool source_is_center = false;
  /**
   * Increment to force on the transform mode, zero keeps the one the mode computed itself. Carries
   * whatever unit that mode counts in: scene units while translating, radians while rotating.
   */
  float increment = 0.0f;
};

struct MayaSnapPlanInput {
  ed::maya::MayaSnapMode mode = ed::maya::MayaSnapMode::None;
  bool is_translation = false;
  /** A rotation counts its steps in radians, so it takes the angle instead of the distance. */
  bool is_rotation = false;
  bool orientation_is_global = true;
  bool space_is_view3d = true;
  /**
   * Maya's `snapComponentsRelative`, from the Move Tool marking menu. On, the pivot is what lands
   * on the target and the selection keeps its internal spacing; off, the snap aims at the selection
   * itself, so the part of it nearest the target is what reaches it.
   */
  bool keep_spacing = true;
  ed::maya::MayaStepSnapSettings step;
};

MayaSnapPlan transform_snap_maya_plan_get(const MayaSnapPlanInput &input);

/* -------------------------------------------------------------------- */
/** \name Pivot Snapping
 *
 * Where a drag of the Edit Pivot manipulator leaves the pivot. Maya magnets the pivot onto the
 * element under the pointer and leaves it following the pointer while there is none, so the two
 * positions the transform can offer have to be kept apart: the one it applied (which already
 * carries the snap) and the one the pointer alone asks for.
 * \{ */

struct MayaPivotSnapInput {
  /** What the transform applied, snap included. Also the one that honors numeric input. */
  double3 applied_position = double3(0.0);
  /** Where the pointer alone would put the pivot, with the snap left out. */
  double3 pointer_position = double3(0.0);
  /** The element under the pointer; only read when #has_target. */
  double3 target_position = double3(0.0);
  /**
   * The same target reached through the active constraint: the pivot slides along the axis or plane
   * of the handle being dragged instead of leaving it. Only read when #has_constraint.
   */
  double3 constrained_target_position = double3(0.0);
  /** A target was found inside the snap tolerance. */
  bool has_target = false;
  /** An axis or plane handle of the manipulator is driving the drag. */
  bool has_constraint = false;
  /** That target carries a surface normal, so it can aim the pivot as well as place it. */
  bool target_has_normal = false;
  /** Edit Pivot settings: either half of a snap can be turned off independently. */
  bool snap_position = true;
  bool snap_orientation = true;
};

struct MayaPivotSnapDecision {
  double3 position = double3(0.0);
  /** The position is the target itself, not a dragged one. */
  bool from_target = false;
  /** The target's normal re-aims the pivot. */
  bool aim_at_normal = false;
};

MayaPivotSnapDecision maya_pivot_snap_decision_get(const MayaPivotSnapInput &input);

/** \} */

}  // namespace blender::ed::transform
