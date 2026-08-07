/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup edtransform
 *
 * What the Clarity snapping state asks of a transform.
 *
 * Deliberately not part of #transform_snap.hh: almost every translation unit of the module includes
 * that header, so the Clarity rule set would drag them all into a rebuild on every edit. Only the
 * three files that decide, apply or test the rules include this one.
 */

#pragma once

#include "DNA_scene_types.h"

#include "ED_clarity.hh"

namespace blender::ed::transform {

/**
 * Everything defaults to off: in the Clarity interaction model nothing snaps unless a Clarity mode asks
 * for it, so Blender's own magnet and its `Ctrl` invert never get a say. Leaving them in charge is
 * what quantized every transform to the increment grid with no key held, and what kept Clarity's own
 * modes from snapping at all while the magnet was off.
 *
 * Pure data, so the rules are unit tested without a context.
 */
struct ClaritySnapPlan {
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
  /** Clarity moves the pivot onto the target, never the closest part of the selection. */
  bool source_is_center = false;
  /**
   * Increment to force on the transform mode, zero keeps the one the mode computed itself. Carries
   * whatever unit that mode counts in: scene units while translating, radians while rotating.
   */
  float increment = 0.0f;
};

struct ClaritySnapPlanInput {
  ed::clarity::ClaritySnapMode mode = ed::clarity::ClaritySnapMode::None;
  bool is_translation = false;
  /** A rotation counts its steps in radians, so it takes the angle instead of the distance. */
  bool is_rotation = false;
  bool orientation_is_global = true;
  bool space_is_view3d = true;
  /**
   * Clarity's `snapComponentsRelative`, from the Move Tool marking menu. On, the pivot is what lands
   * on the target and the selection keeps its internal spacing; off, the snap aims at the selection
   * itself, so the part of it nearest the target is what reaches it.
   */
  bool keep_spacing = true;
  /**
   * Clarity's `manipMoveContext -xformConstraint`. Unlike a snap mode it is not held down: it stays on
   * until it is turned off, and it only governs components, so it is read separately.
   */
  ed::clarity::ClarityTransformConstraint transform_constraint =
      ed::clarity::ClarityTransformConstraint::Off;
  /** Components are what a transform constraint applies to; whole objects are never constrained. */
  bool is_component_edit = false;
  ed::clarity::ClarityStepSnapSettings step;
};

ClaritySnapPlan transform_snap_clarity_plan_get(const ClaritySnapPlanInput &input);

/* -------------------------------------------------------------------- */
/** \name Pivot Snapping
 *
 * Where a drag of the Edit Pivot manipulator leaves the pivot. Clarity magnets the pivot onto the
 * element under the pointer and leaves it following the pointer while there is none, so the two
 * positions the transform can offer have to be kept apart: the one it applied (which already
 * carries the snap) and the one the pointer alone asks for.
 *
 * A drag moves the pivot and nothing else. Clarity splits the two halves across two interactions:
 * "hold C or V and middle-drag ... to snap the pivot to that object's edges or vertices" is
 * positional, while "click a component to snap and align the pivot to the selected component" is
 * what turns it, with `Ctrl + click` for the orientation alone. Turning the pivot mid-drag put it in
 * a new frame every time the element under the pointer changed, which is not a thing Clarity does and
 * not a thing a drag can undo.
 * \{ */

/**
 * What the vector a snap returns alongside its position actually is, for the click that aligns the
 * pivot with a component.
 *
 * A click always puts the component's *normal* on the pivot's X axis - a capture of Clarity 2025
 * shows a clicked face leaving X on the face normal, a clicked corner on the vertex normal, and a
 * clicked edge on the bisector of the two faces beside it, never along the edge. The snap backend
 * however keeps one field for all element types and fills it with `v1 - v0` for an edge, so an edge
 * hit is the one case whose normal has to be rebuilt from the mesh before it can be used.
 */
enum class ClarityPivotSnapVector : uint8_t {
  /** The target says nothing about direction, so the pivot keeps the orientation it had. */
  None = 0,
  /** Usable as it stands: a face normal, or the vertex normal of a point or an edge endpoint. */
  SurfaceNormal,
  /** A direction along the edge. The caller replaces it with the mean normal of its faces. */
  EdgeDirection,
};

struct ClarityPivotSnapInput {
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
  /** Edit Pivot's `snapPos`: with it off the pointer keeps the pivot and the target only shows. */
  bool snap_position = true;
};

struct ClarityPivotSnapDecision {
  double3 position = double3(0.0);
  /** The position is the target itself, not a dragged one. */
  bool from_target = false;
};

ClarityPivotSnapDecision clarity_pivot_snap_decision_get(const ClarityPivotSnapInput &input);

/** Which vector a clicked element carries, from the element type that won the search. */
ClarityPivotSnapVector clarity_pivot_snap_vector_get(eSnapMode target_type);
/** The pivot axis that vector is turned onto, -1 when it defines no direction. */
int clarity_pivot_snap_aim_axis_get(ClarityPivotSnapVector target_vector);
/** \} */

}  // namespace blender::ed::transform
