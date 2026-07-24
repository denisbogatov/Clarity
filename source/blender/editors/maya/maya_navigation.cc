/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup editors
 */

#include "maya_navigation.hh"

#include <algorithm>
#include <array>
#include <cstdio>

#include "BLI_fileops.h"
#include "BLI_path_utils.hh"
#include "BLI_set.hh"
#include "BLI_time.h"
#include "BLI_vector.hh"

#include "DNA_screen_types.h"
#include "DNA_space_enums.h"
#include "DNA_userdef_types.h"

#include "BKE_appdir.hh"

namespace blender::ed::maya {

struct MayaNavigationDebugSample {
  uint64_t event_index;
  double elapsed_ms;
  double event_gap_ms;
  double update_ms;
  int2 mouse_delta;
};

struct MayaNavigationDebugStageSample {
  MayaNavigationDebugStage stage;
  uint64_t frame_index;
  double elapsed_ms;
  double duration_ms;
  double detail_a_ms;
  double detail_b_ms;
  int area_type;
  int region_type;
};

static const char *debug_stage_name(const MayaNavigationDebugStage stage)
{
  switch (stage) {
    case MayaNavigationDebugStage::FrameBegin:
      return "frame_begin";
    case MayaNavigationDebugStage::FrameRateLimit:
      return "frame_limit";
    case MayaNavigationDebugStage::MakeDrawable:
      return "make_drawable";
    case MayaNavigationDebugStage::SwapAcquire:
      return "swap_acquire";
    case MayaNavigationDebugStage::ScreenUpdate:
      return "screen_update";
    case MayaNavigationDebugStage::AreaLayout:
      return "area_layout";
    case MayaNavigationDebugStage::AreaRegionSizes:
      return "area_region_sizes";
    case MayaNavigationDebugStage::ToolSystemUpdate:
      return "tool_system_update";
    case MayaNavigationDebugStage::RegionBufferCreate:
      return "region_buffer_create";
    case MayaNavigationDebugStage::RegionBind:
      return "region_bind";
    case MayaNavigationDebugStage::RegionDraw:
      return "region_draw";
    case MayaNavigationDebugStage::Gizmo3D:
      return "gizmo_3d";
    case MayaNavigationDebugStage::Gizmo2D:
      return "gizmo_2d";
    case MayaNavigationDebugStage::RegionUnbind:
      return "region_unbind";
    case MayaNavigationDebugStage::AreaTotal:
      return "area_total";
    case MayaNavigationDebugStage::WindowOffscreen:
      return "window_offscreen";
    case MayaNavigationDebugStage::WindowOnscreen:
      return "window_onscreen";
    case MayaNavigationDebugStage::WindowDraw:
      return "window_draw";
    case MayaNavigationDebugStage::DrawFlagClear:
      return "draw_flag_clear";
    case MayaNavigationDebugStage::SwapRelease:
      return "swap_release";
    case MayaNavigationDebugStage::FrameTotal:
      return "frame_total";
    case MayaNavigationDebugStage::TransformEvent:
      return "transform_event";
    case MayaNavigationDebugStage::TransformApply:
      return "transform_apply";
    case MayaNavigationDebugStage::GeometryUpdate:
      return "geometry_update";
    case MayaNavigationDebugStage::TransformModalTotal:
      return "transform_modal_total";
    case MayaNavigationDebugStage::DepsgraphUpdate:
      return "depsgraph_update";
    case MayaNavigationDebugStage::GizmoRefresh:
      return "gizmo_refresh";
    case MayaNavigationDebugStage::GPUContextDrawLock:
      return "gpu_context_draw_lock";
    case MayaNavigationDebugStage::GPUContextSharedLock:
      return "gpu_context_shared_lock";
    case MayaNavigationDebugStage::GPUContextRenderBegin:
      return "gpu_context_render_begin";
    case MayaNavigationDebugStage::GPUContextSystemActivate:
      return "gpu_context_system_activate";
    case MayaNavigationDebugStage::GPUContextActivate:
      return "gpu_context_activate";
    case MayaNavigationDebugStage::GPUContextFrameBegin:
      return "gpu_context_frame_begin";
    case MayaNavigationDebugStage::Count:
      break;
  }
  return "unknown";
}

static const char *debug_area_name(const int area_type)
{
  switch (area_type) {
    case SPACE_VIEW3D:
      return "VIEW_3D";
    case SPACE_TOPBAR:
      return "TOPBAR";
    case SPACE_STATUSBAR:
      return "STATUSBAR";
    case SPACE_SHELF:
      return "SHELF";
    case SPACE_ITEM:
      return "ITEM";
    case SPACE_OUTLINER:
      return "OUTLINER";
    case SPACE_PROPERTIES:
      return "PROPERTIES";
    case SPACE_FILE:
      return "FILE_BROWSER";
  }
  return area_type < 0 ? "-" : "OTHER";
}

static const char *debug_region_name(const int region_type)
{
  switch (region_type) {
    case RGN_TYPE_WINDOW:
      return "WINDOW";
    case RGN_TYPE_HEADER:
      return "HEADER";
    case RGN_TYPE_CHANNELS:
      return "CHANNELS";
    case RGN_TYPE_TEMPORARY:
      return "TEMPORARY";
    case RGN_TYPE_UI:
      return "UI";
    case RGN_TYPE_TOOLS:
      return "TOOLS";
    case RGN_TYPE_TOOL_PROPS:
      return "TOOL_PROPS";
    case RGN_TYPE_PREVIEW:
      return "PREVIEW";
    case RGN_TYPE_HUD:
      return "HUD";
    case RGN_TYPE_NAV_BAR:
      return "NAV_BAR";
    case RGN_TYPE_EXECUTE:
      return "EXECUTE";
    case RGN_TYPE_FOOTER:
      return "FOOTER";
    case RGN_TYPE_TOOL_HEADER:
      return "TOOL_HEADER";
  }
  return region_type < 0 ? "-" : "OTHER";
}

struct MayaNavigationDebugState {
  MayaNavigationMode mode;
  double start_time;
  double last_event_time;
  double tool_activation_age_ms;
  double tool_activation_duration_ms;
  int viewport_fps_limit;
  int maya_fps_limit;
  bool viewport_vsync;
  double max_event_gap_ms = 0.0;
  double max_update_ms = 0.0;
  uint64_t event_count = 0;
  uint64_t frame_index = 0;
  Vector<MayaNavigationDebugSample> samples;
  Vector<MayaNavigationDebugStageSample> stage_samples;
  std::array<double, size_t(MayaNavigationDebugStage::Count)> stage_max_ms = {};

  MayaNavigationDebugState(const MayaNavigationMode mode,
                           const MayaNavigationSettings &settings)
      : mode(mode),
        start_time(BLI_time_now_seconds()),
        last_event_time(start_time),
        tool_activation_age_ms(settings.tool_activation_age_ms),
        tool_activation_duration_ms(settings.tool_activation_duration_ms),
        viewport_fps_limit(U.viewport_fps_limit),
        maya_fps_limit(settings.frame_rate_limit),
        viewport_vsync(U.viewport_vsync)
  {
    samples.reserve(64);
    stage_samples.reserve(32768);
  }

  void record(const double event_time, const double update_ms, const int2 mouse_delta)
  {
    const double event_gap_ms = (event_time - last_event_time) * 1000.0;
    last_event_time = event_time;
    event_count++;
    max_event_gap_ms = std::max(max_event_gap_ms, event_gap_ms);
    max_update_ms = std::max(max_update_ms, update_ms);

    if (event_gap_ms >= 12.0 || update_ms >= 1.0) {
      samples.append({event_count,
                      (event_time - start_time) * 1000.0,
                      event_gap_ms,
                      update_ms,
                      mouse_delta});
    }
  }

  void record_stage(const MayaNavigationDebugStage stage,
                    const double duration_ms,
                    const double detail_a_ms,
                    const double detail_b_ms,
                    const int area_type,
                    const int region_type)
  {
    if (stage == MayaNavigationDebugStage::FrameBegin) {
      frame_index++;
      return;
    }
    if (frame_index == 0) {
      return;
    }

    const int stage_index = int(stage);
    stage_max_ms[stage_index] = std::max(stage_max_ms[stage_index], duration_ms);
    stage_samples.append({stage,
                          frame_index,
                          (BLI_time_now_seconds() - start_time) * 1000.0,
                          duration_ms,
                          detail_a_ms,
                          detail_b_ms,
                          area_type,
                          region_type});
  }

  void flush() const
  {
    char filepath[FILE_MAX];
    BLI_path_join(filepath, sizeof(filepath), BKE_tempdir_base(), "maya_navigation_trace.log");
    FILE *file = BLI_fopen(filepath, "a");
    if (file == nullptr) {
      return;
    }

    const char *mode_name = mode == MayaNavigationMode::Orbit ?
                                "orbit" :
                                mode == MayaNavigationMode::Pan ? "pan" : "dolly";
    std::fprintf(file,
                 "SESSION mode=%s events=%llu duration_ms=%.3f "
                 "tool_age_ms=%.3f tool_switch_ms=%.6f max_gap_ms=%.3f "
                 "max_update_ms=%.3f anomalies=%d fps_limit=%d maya_fps_limit=%d "
                 "vsync=%d\n",
                 mode_name,
                 static_cast<unsigned long long>(event_count),
                 (last_event_time - start_time) * 1000.0,
                 tool_activation_age_ms,
                 tool_activation_duration_ms,
                 max_event_gap_ms,
                 max_update_ms,
                 int(samples.size()),
                 viewport_fps_limit,
                 maya_fps_limit,
                 int(viewport_vsync));
    for (const MayaNavigationDebugSample &sample : samples) {
      std::fprintf(file,
                   "  SLOW event=%llu t_ms=%.3f gap_ms=%.3f update_ms=%.3f "
                   "delta=(%d,%d)\n",
                   static_cast<unsigned long long>(sample.event_index),
                   sample.elapsed_ms,
                   sample.event_gap_ms,
                   sample.update_ms,
                   sample.mouse_delta.x,
                   sample.mouse_delta.y);
    }

    std::fprintf(file, "  FRAME_SUMMARY frames=%llu", static_cast<unsigned long long>(frame_index));
    for (int stage_index = int(MayaNavigationDebugStage::FrameRateLimit);
         stage_index < int(MayaNavigationDebugStage::Count);
         stage_index++)
    {
      const MayaNavigationDebugStage stage = MayaNavigationDebugStage(stage_index);
      if (stage_max_ms[stage_index] > 0.0) {
        std::fprintf(
            file, " max_%s_ms=%.3f", debug_stage_name(stage), stage_max_ms[stage_index]);
      }
    }
    std::fputc('\n', file);

    Set<uint64_t> slow_frames;
    for (const MayaNavigationDebugStageSample &sample : stage_samples) {
      if (sample.stage == MayaNavigationDebugStage::FrameTotal &&
          sample.duration_ms >= 12.0)
      {
        slow_frames.add(sample.frame_index);
      }
    }
    for (const MayaNavigationDebugStageSample &sample : stage_samples) {
      if (!slow_frames.contains(sample.frame_index) && sample.duration_ms < 4.0) {
        continue;
      }
      std::fprintf(file,
                   "  FRAME frame=%llu t_ms=%.3f stage=%s duration_ms=%.3f "
                   "detail_a_ms=%.3f detail_b_ms=%.3f area=%s(%d) region=%s(%d)\n",
                   static_cast<unsigned long long>(sample.frame_index),
                   sample.elapsed_ms,
                   debug_stage_name(sample.stage),
                   sample.duration_ms,
                   sample.detail_a_ms,
                   sample.detail_b_ms,
                   debug_area_name(sample.area_type),
                   sample.area_type,
                   debug_region_name(sample.region_type),
                   sample.region_type);
    }
    std::fputc('\n', file);
    std::fclose(file);
  }
};

static blender::ed::view3d::NavigationMode backend_mode_from_maya_mode(
    const MayaNavigationMode mode)
{
  switch (mode) {
    case MayaNavigationMode::Orbit:
      return blender::ed::view3d::NavigationMode::Orbit;
    case MayaNavigationMode::Pan:
      return blender::ed::view3d::NavigationMode::Pan;
    case MayaNavigationMode::Dolly:
      return blender::ed::view3d::NavigationMode::Dolly;
  }
  return blender::ed::view3d::NavigationMode::Orbit;
}

static blender::ed::view3d::OrbitPivotPolicy backend_pivot_from_maya_policy(
    const MayaOrbitPivotPolicy policy)
{
  switch (policy) {
    case MayaOrbitPivotPolicy::ViewCenter:
      return blender::ed::view3d::OrbitPivotPolicy::ViewCenter;
    case MayaOrbitPivotPolicy::Selection:
      return blender::ed::view3d::OrbitPivotPolicy::Selection;
    case MayaOrbitPivotPolicy::LastFocused:
      return blender::ed::view3d::OrbitPivotPolicy::LastFocused;
    case MayaOrbitPivotPolicy::Explicit:
      return blender::ed::view3d::OrbitPivotPolicy::Explicit;
  }
  return blender::ed::view3d::OrbitPivotPolicy::LastFocused;
}

std::unique_ptr<MayaNavigationSession> MayaNavigationSession::begin(
    bContext *C,
    const MayaNavigationMode mode,
    const MayaInputAction &action,
    const MayaNavigationSettings &settings)
{
  if (action.pointer_button == MayaPointerButton::None) {
    return nullptr;
  }

  blender::ed::view3d::NavigationBeginParams params;
  params.mode = backend_mode_from_maya_mode(mode);
  params.mouse_xy = action.mouse;
  params.mouse_region_xy = action.mouse_region;
  params.use_mouse_position = true;
  params.invert_direction = mode == MayaNavigationMode::Dolly;
  params.orbit_around_selection = settings.auto_pivot_from_selection;
  params.pivot_policy = backend_pivot_from_maya_policy(settings.orbit_pivot);

  std::unique_ptr<blender::ed::view3d::NavigationSession> backend =
      blender::ed::view3d::navigation_session_begin(C, params);
  if (!backend) {
    return nullptr;
  }

  return std::make_unique<MayaNavigationSession>(ED_maya_session_context_from_context(C),
                                                 mode,
                                                 action.pointer_button,
                                                 action.mouse,
                                                 std::move(backend),
                                                 settings);
}

MayaNavigationSession::MayaNavigationSession(
    MayaSessionContext context,
    const MayaNavigationMode mode,
    const MayaPointerButton initiating_button,
    const int2 initial_mouse,
    std::unique_ptr<blender::ed::view3d::NavigationSession> backend,
    const MayaNavigationSettings &settings)
    : MayaInteractionSession(context),
      mode_(mode),
      initiating_button_(initiating_button),
      last_mouse_(initial_mouse),
      backend_(std::move(backend)),
      debug_(settings.debug_logging ?
                 std::make_unique<MayaNavigationDebugState>(mode, settings) :
                 nullptr),
      frame_rate_limit_(settings.frame_rate_limit)
{
}

MayaNavigationSession::~MayaNavigationSession()
{
  if (debug_) {
    debug_->flush();
  }
}

bool MayaNavigationSession::debug_enabled() const
{
  return debug_ != nullptr;
}

int MayaNavigationSession::frame_rate_limit() const
{
  return frame_rate_limit_;
}

void MayaNavigationSession::debug_stage_sample(const MayaNavigationDebugStage stage,
                                               const double duration_ms,
                                               const double detail_a_ms,
                                               const double detail_b_ms,
                                               const int area_type,
                                               const int region_type)
{
  if (debug_) {
    debug_->record_stage(
        stage, duration_ms, detail_a_ms, detail_b_ms, area_type, region_type);
  }
}

MayaSessionKind MayaNavigationSession::kind() const
{
  return MayaSessionKind::Navigation;
}

MayaSessionResult MayaNavigationSession::handle_event(bContext *C,
                                                      const MayaInputAction &action)
{
  if (action.id == MayaActionID::EndNavigation) {
    backend_->confirm(C);
    return MayaSessionResult::Finished;
  }

  if (action.id == MayaActionID::PointerMove) {
    if (!action.alt) {
      backend_->confirm(C);
      return MayaSessionResult::Finished;
    }
    if (action.mouse.x == last_mouse_.x && action.mouse.y == last_mouse_.y) {
      return MayaSessionResult::Running;
    }
    last_mouse_ = action.mouse;

    const double event_time = debug_ ? BLI_time_now_seconds() : 0.0;
    const blender::ed::view3d::NavigationResult navigation_result = backend_->update(
        C, action.mouse, action.mouse_region);
    if (debug_) {
      const double update_ms = (BLI_time_now_seconds() - event_time) * 1000.0;
      debug_->record(event_time, update_ms, action.mouse_delta);
    }

    switch (navigation_result) {
      case blender::ed::view3d::NavigationResult::Running:
        return MayaSessionResult::Running;
      case blender::ed::view3d::NavigationResult::Finished:
        return MayaSessionResult::Finished;
      case blender::ed::view3d::NavigationResult::Cancelled:
        return MayaSessionResult::Cancelled;
      case blender::ed::view3d::NavigationResult::Failed:
        cancel(C);
        return MayaSessionResult::Cancelled;
    }
  }

  if (action.id == MayaActionID::Confirm &&
      action.pointer_button == initiating_button_)
  {
    backend_->confirm(C);
    return MayaSessionResult::Finished;
  }

  if (action.id == MayaActionID::Cancel) {
    cancel(C);
    return MayaSessionResult::Cancelled;
  }

  return MayaSessionResult::Running;
}

void MayaNavigationSession::cancel(bContext *C)
{
  if (backend_) {
    backend_->cancel(C);
  }
}

}  // namespace blender::ed::maya
