/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup editors
 */

#pragma once

#include <cstdint>
#include <memory>

#include "maya_navigation.hh"
#include "maya_tool.hh"

namespace blender {

struct bContext;

namespace ed::maya {

class MayaInteractionSession;
struct MayaTransformDebugState;

enum class MayaComponentMode : uint8_t {
  Object,
  Vertex,
  Edge,
  Face,
};

enum class MayaPivotMode : uint8_t {
  Object,
  SelectionCenter,
  Component,
  Custom,
};

struct MayaTemporaryOverrides {
  bool grid_snap = false;
  bool point_snap = false;
  bool curve_snap = false;
  bool edit_pivot = false;
};

struct MayaWindowRuntime {
  MayaWindowRuntime();
  ~MayaWindowRuntime();
  MayaWindowRuntime(MayaWindowRuntime &&other);
  MayaWindowRuntime &operator=(MayaWindowRuntime &&other);
  MayaWindowRuntime(const MayaWindowRuntime &other) = delete;
  MayaWindowRuntime &operator=(const MayaWindowRuntime &other) = delete;

  MayaToolState tool;
  MayaComponentMode component_mode = MayaComponentMode::Object;
  MayaPivotMode pivot_mode = MayaPivotMode::Object;

  std::unique_ptr<MayaInteractionSession> active_session;
  std::unique_ptr<MayaTransformDebugState> transform_debug;
  bool transform_active = false;
  MayaTemporaryOverrides temporary;
  MayaNavigationSettings navigation_settings;
  double last_tool_activation_time = 0.0;
  double last_tool_activation_duration_ms = 0.0;

  bool navigation_active() const;
};

MayaWindowRuntime *runtime_get(const bContext *C);
MayaWindowRuntime *runtime_ensure(const bContext *C);
bool navigation_debug_logging_enabled(const bContext *C);
int navigation_frame_rate_limit_setting(const bContext *C);

}  // namespace ed::maya
}  // namespace blender
