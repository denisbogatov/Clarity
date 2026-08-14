/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

#pragma once

/** \file
 * \ingroup bli
 *
 * Clarity's native world-space basis follows Maya's right-handed Y-up convention:
 * X points right, Y points up, and positive Z points forward.
 *
 * These constants describe semantic world axes. Generic vector, matrix, camera-local, and
 * object-local math remains coordinate-independent and must not be remapped at its call sites.
 */

#include "BLI_math_basis_types.hh"
#include "BLI_math_vector_types.hh"

namespace blender::math::world {

inline constexpr Axis right_axis = Axis::X;
inline constexpr Axis up_axis = Axis::Y;
inline constexpr Axis forward_axis = Axis::Z;

inline constexpr float3 right = {1.0f, 0.0f, 0.0f};
inline constexpr float3 up = {0.0f, 1.0f, 0.0f};
inline constexpr float3 forward = {0.0f, 0.0f, 1.0f};
inline constexpr float3 gravity = {0.0f, -9.81f, 0.0f};

}  // namespace blender::math::world
