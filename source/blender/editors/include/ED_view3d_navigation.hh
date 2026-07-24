/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup spview3d
 */

#pragma once

#include <cstdint>
#include <memory>
#include <optional>

#include "BLI_math_vector_types.hh"

namespace blender {

struct bContext;

namespace ed::view3d {

enum class NavigationMode : uint8_t {
  Orbit,
  Pan,
  Dolly,
};

enum class NavigationResult : uint8_t {
  Running,
  Finished,
  Cancelled,
  Failed,
};

enum class OrbitPivotPolicy : uint8_t {
  ViewCenter,
  Selection,
  LastFocused,
  Explicit,
};

struct NavigationBeginParams {
  NavigationMode mode = NavigationMode::Orbit;

  int2 mouse_xy;
  int2 mouse_region_xy;

  bool use_mouse_position = true;
  bool invert_direction = false;
  bool orbit_around_selection = true;
  OrbitPivotPolicy pivot_policy = OrbitPivotPolicy::LastFocused;
  std::optional<float3> explicit_pivot;
};

class NavigationSession {
 public:
  virtual ~NavigationSession() = default;

  virtual NavigationResult update(bContext *C,
                                  const int2 &mouse_xy,
                                  const int2 &mouse_region_xy) = 0;
  virtual void confirm(bContext *C) = 0;
  virtual void cancel(bContext *C) = 0;
};

std::unique_ptr<NavigationSession> navigation_session_begin(
    bContext *C, const NavigationBeginParams &params);

bool navigation_frame_selected(bContext *C, bool use_all_regions, int smooth_viewtx);

}  // namespace ed::view3d
}  // namespace blender
