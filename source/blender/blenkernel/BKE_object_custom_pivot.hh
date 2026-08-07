/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

#pragma once

#include "BLI_math_quaternion_types.hh"
#include "BLI_math_vector_types.hh"

struct Object;
struct ObjectCustomPivot;

namespace blender {

ObjectCustomPivot *BKE_object_custom_pivot_ensure(Object &object);
void BKE_object_custom_pivot_reset(Object &object);

/**
 * True when the requested pivot position was authored and should override the regular transform
 * center. Rotate and scale pivots have independent validity.
 */
bool BKE_object_custom_pivot_position_valid(const Object &object, bool use_scale_pivot);
bool BKE_object_custom_pivot_orientation_valid(const Object &object);

/**
 * Clear the selected pivot positions and their validity. The custom pivot is freed once nothing
 * is left valid.
 */
void BKE_object_custom_pivot_position_clear(Object &object,
                                            bool clear_rotate_pivot,
                                            bool clear_scale_pivot);
void BKE_object_custom_pivot_orientation_clear(Object &object);

bool BKE_object_custom_pivot_position_world_get(const Object &object,
                                                bool use_scale_pivot,
                                                double3 &r_position);
bool BKE_object_custom_pivot_position_world_set(Object &object,
                                                bool use_scale_pivot,
                                                const double3 &position);
bool BKE_object_custom_pivot_orientation_world_get(
    const Object &object, math::QuaternionBase<double> &r_orientation);
bool BKE_object_custom_pivot_orientation_world_set(
    Object &object, const math::QuaternionBase<double> &orientation);

/* -------------------------------------------------------------------- */
/** \name Object Pivot Resolver
 *
 * Clarity keeps exactly one rotate and one scale pivot per transform node, but stores it in one of
 * two places. An object using the Clarity transform model stores it in its DAG channels, where it
 * takes part in the matrix composition and therefore in every later rotation. #ObjectCustomPivot is
 * the shim for objects still using the Blender transform model, which has no such channel: there
 * the pivot is tool state until it is baked.
 *
 * Everything that reads or draws an authored pivot goes through here, so an object can never end up
 * with two competing pivots, and the manipulator, the transform and the origin overlay cannot
 * disagree about where the pivot is.
 * \{ */

/** True when the pivot is authored away from the object origin. */
bool BKE_object_pivot_valid(const Object &object, bool use_scale_pivot);

/**
 * World-space position of the authored pivot, false when the object has none.
 *
 * The pivot of a DAG transform is the sum of its pivot and its pivot translate channel - the
 * compensation the preserving setter writes is part of where the pivot ends up.
 */
bool BKE_object_pivot_world_get(const Object &object, bool use_scale_pivot, double3 &r_position);

/**
 * Where an object's origin marker belongs: the authored pivot when there is one, and the object
 * origin otherwise. Rotate and scale pivots are authored together by the pivot tools, so the rotate
 * pivot is asked for first and the scale pivot only stands in for data that carries just that one.
 */
double3 BKE_object_origin_display_position_get(const Object &object);

/** \} */

}  // namespace blender
