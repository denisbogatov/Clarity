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

}  // namespace blender
