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
struct UndoStep;
struct wmEvent;
struct wmOperator;
struct wmWindow;

namespace ed::maya {

enum class MayaDispatchResult : uint8_t {
  PassThrough,
  Handled,
  StartModal,
};

enum class MayaPivotEditTarget : uint8_t {
  None,
  ObjectOrigin,
  ComponentPivot,
};

enum class MayaSnapMode : uint8_t {
  None,
  Grid,
  Curve,
  Point,
  ViewPlane,
  MeshCenter,
  StepAbsolute,
  StepRelative,
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
  ViewportRedrawState,
  ViewportBufferReset,
  ViewportBufferMissing,
  ViewportComposite,
  Count,
};

}  // namespace ed::maya

bool ED_maya_interaction_enabled(const bContext *C);
void ED_operatortypes_maya();
ed::maya::MayaDispatchResult ED_maya_event_dispatch(bContext *C, const wmEvent *event);
int ED_maya_interaction_frame_rate_limit(const bContext *C);
bool ED_maya_navigation_debug_active(const bContext *C);
ed::maya::MayaPivotEditTarget ED_maya_pivot_edit_target_get(const bContext *C);
bool ED_maya_pivot_custom_matrix_get(const bContext *C, float r_matrix[4][4]);
bool ED_maya_pivot_edit_data_get(const bContext *C,
                                 float **r_location,
                                 float **r_rotation_quaternion);
bool ED_maya_snap_override_set(const bContext *C, ed::maya::MayaSnapMode mode, bool enabled);
ed::maya::MayaSnapMode ED_maya_snap_override_get(const bContext *C);
bool ED_maya_snap_mode_set(const bContext *C, ed::maya::MayaSnapMode mode);
ed::maya::MayaSnapMode ED_maya_snap_mode_get(const bContext *C);
void ED_maya_pivot_event_pre_modal(bContext *C, const wmEvent *event);
void ED_maya_transform_begin(
    const bContext *C,
    const char *operator_id,
    int context_mode,
    int mesh_select_mode,
    bool is_maya_pivot_transform);
void ED_maya_transform_update(const bContext *C, const float world_translation[3]);
void ED_maya_transform_end(bContext *C, bool cancelled);
void ED_maya_undo_step_store(const bContext *C);
void ED_maya_undo_step_clear(const bContext *C);
void ED_maya_undo_steps_restore(
    bContext *C, const UndoStep *step_from, const UndoStep *step_to, bool is_undo);
bool ED_maya_shift_transform_prepare(bContext *C, wmOperator *op, const wmEvent *event);
void ED_maya_navigation_debug_stage_sample(
    const bContext *C,
    ed::maya::MayaNavigationDebugStage stage,
    double duration_ms,
    double detail_a_ms = 0.0,
    double detail_b_ms = 0.0,
    int area_type = -1,
    int region_type = -1);
void ED_maya_viewport_debug_event(const bContext *C,
                                  ed::maya::MayaNavigationDebugStage stage,
                                  int code,
                                  int detail_a,
                                  int detail_b,
                                  int area_type,
                                  int region_type);
void ED_maya_runtime_free(bContext *C, const wmWindow *win);

}  // namespace blender
