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
#include "ED_maya.hh"

#include "maya_session.hh"

namespace blender::ed::maya {

enum class MayaNavigationMode : uint8_t {
  Orbit,
  Pan,
  Dolly,
};

enum class MayaOrbitPivotPolicy : uint8_t {
  ViewCenter,
  Selection,
  LastFocused,
  Explicit,
};

struct MayaNavigationSettings {
  MayaOrbitPivotPolicy orbit_pivot = MayaOrbitPivotPolicy::LastFocused;
  bool auto_pivot_from_selection = true;
  bool debug_logging = false;
  int frame_rate_limit = 120;
  double tool_activation_age_ms = -1.0;
  double tool_activation_duration_ms = 0.0;
};

struct MayaNavigationDebugState;

class MayaNavigationSession final : public MayaInteractionSession {
 public:
  static std::unique_ptr<MayaNavigationSession> begin(bContext *C,
                                                      MayaNavigationMode mode,
                                                      const MayaInputAction &action,
                                                      const MayaNavigationSettings &settings);

  MayaNavigationSession(
      MayaSessionContext context,
      MayaNavigationMode mode,
      MayaPointerButton initiating_button,
      int2 initial_mouse,
      std::unique_ptr<blender::ed::view3d::NavigationSession> backend,
      const MayaNavigationSettings &settings);
  ~MayaNavigationSession() override;

  MayaSessionKind kind() const override;
  MayaSessionResult handle_event(bContext *C, const MayaInputAction &action) override;
  void cancel(bContext *C) override;
  bool debug_enabled() const;
  void debug_stage_sample(ed::maya::MayaNavigationDebugStage stage,
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
  MayaNavigationMode mode_;
  MayaPointerButton initiating_button_;
  int2 last_mouse_;
  std::unique_ptr<blender::ed::view3d::NavigationSession> backend_;
  std::unique_ptr<MayaNavigationDebugState> debug_;
  int frame_rate_limit_;
};

}  // namespace blender::ed::maya
