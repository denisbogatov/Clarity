/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup editors
 */

#pragma once

#include <cstdint>

namespace blender {

struct bContext;
struct wmEvent;
struct wmWindow;

namespace ed::maya {

enum class MayaDispatchResult : uint8_t {
  PassThrough,
  Handled,
  StartModal,
};

enum class MayaNavigationDebugStage : uint8_t {
  FrameBegin,
  FrameRateLimit,
  MakeDrawable,
  SwapAcquire,
  ScreenUpdate,
  AreaLayout,
  AreaRegionSizes,
  ToolSystemUpdate,
  RegionBufferCreate,
  RegionBind,
  RegionDraw,
  Gizmo3D,
  Gizmo2D,
  RegionUnbind,
  AreaTotal,
  WindowOffscreen,
  WindowOnscreen,
  WindowDraw,
  DrawFlagClear,
  SwapRelease,
  FrameTotal,
  TransformEvent,
  TransformApply,
  GeometryUpdate,
  TransformModalTotal,
  DepsgraphUpdate,
  GizmoRefresh,
  GPUContextDrawLock,
  GPUContextSharedLock,
  GPUContextRenderBegin,
  GPUContextSystemActivate,
  GPUContextActivate,
  GPUContextFrameBegin,
  Count,
};

}  // namespace ed::maya

bool ED_maya_interaction_enabled(const bContext *C);
ed::maya::MayaDispatchResult ED_maya_event_dispatch(bContext *C, const wmEvent *event);
int ED_maya_interaction_frame_rate_limit(const bContext *C);
bool ED_maya_navigation_debug_active(const bContext *C);
void ED_maya_transform_begin(
    const bContext *C, const char *operator_id, int context_mode, int mesh_select_mode);
void ED_maya_transform_end(const bContext *C);
void ED_maya_transform_panel_cache_tick(const bContext *C);
uint64_t ED_maya_transform_panel_cache_serial(const bContext *C);
void ED_maya_navigation_debug_stage_sample(
    const bContext *C,
    ed::maya::MayaNavigationDebugStage stage,
    double duration_ms,
    double detail_a_ms = 0.0,
    double detail_b_ms = 0.0,
    int area_type = -1,
    int region_type = -1);
void ED_maya_runtime_free(bContext *C, const wmWindow *win);

}  // namespace blender
