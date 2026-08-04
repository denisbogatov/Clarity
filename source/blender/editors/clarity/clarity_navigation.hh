/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup editors
 */

#pragma once

#include <cstdint>
#include <memory>

#include "ED_view3d_navigation.hh"
#include "ED_clarity.hh"

#include "clarity_session.hh"

namespace blender::ed::clarity {

enum class ClarityNavigationMode : uint8_t {
  Orbit,
  Pan,
  Dolly,
};

enum class ClarityOrbitPivotPolicy : uint8_t {
  ViewCenter,
  Selection,
  LastFocused,
  Explicit,
};

struct ClarityNavigationSettings {
  ClarityOrbitPivotPolicy orbit_pivot = ClarityOrbitPivotPolicy::LastFocused;
  bool auto_pivot_from_selection = true;
  bool debug_logging = false;
  int frame_rate_limit = 120;
  double tool_activation_age_ms = -1.0;
  double tool_activation_duration_ms = 0.0;
};

struct ClarityNavigationDebugState;

class ClarityNavigationSession final : public ClarityInteractionSession {
 public:
  static std::unique_ptr<ClarityNavigationSession> begin(bContext *C,
                                                      ClarityNavigationMode mode,
                                                      const ClarityInputAction &action,
                                                      const ClarityNavigationSettings &settings);

  ClarityNavigationSession(
      ClaritySessionContext context,
      ClarityNavigationMode mode,
      ClarityPointerButton initiating_button,
      int2 initial_mouse,
      std::unique_ptr<blender::ed::view3d::NavigationSession> backend,
      const ClarityNavigationSettings &settings);
  ~ClarityNavigationSession() override;

  ClaritySessionKind kind() const override;
  ClaritySessionResult handle_event(bContext *C, const ClarityInputAction &action) override;
  void cancel(bContext *C) override;
  bool debug_enabled() const;
  void debug_stage_sample(ed::clarity::ClarityNavigationDebugStage stage,
                          double duration_ms,
                          double detail_a_ms,
                          double detail_b_ms,
                          int area_type,
                          int region_type);
  int frame_rate_limit() const;

  bool uses_undo() const override
  {
    return false;
  }

 private:
  ClarityNavigationMode mode_;
  ClarityPointerButton initiating_button_;
  int2 last_mouse_;
  std::unique_ptr<blender::ed::view3d::NavigationSession> backend_;
  std::unique_ptr<ClarityNavigationDebugState> debug_;
  int frame_rate_limit_;
};

}  // namespace blender::ed::clarity
