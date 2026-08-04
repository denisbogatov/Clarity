/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup editors
 */

#include "clarity_navigation.hh"

#include "clarity_runtime.hh"

#include <algorithm>
#include <array>
#include <cstdlib>
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

namespace blender::ed::clarity {

static constexpr int CLARITY_TUMBLE_SCALE_NUMERATOR = 4;
static constexpr int CLARITY_TUMBLE_SCALE_DENOMINATOR = 5;

static int clarity_tumble_delta_scale(const int delta)
{
  const int magnitude = std::abs(delta);
  const int scaled = (magnitude * CLARITY_TUMBLE_SCALE_NUMERATOR +
                      CLARITY_TUMBLE_SCALE_DENOMINATOR / 2) /
                     CLARITY_TUMBLE_SCALE_DENOMINATOR;
  return delta < 0 ? -scaled : scaled;
}

struct ClarityNavigationDebugSample {
  uint64_t event_index;
  double elapsed_ms;
  double event_gap_ms;
  double update_ms;
  int2 mouse_delta;
};

struct ClarityNavigationDebugStageSample {
  ClarityNavigationDebugStage stage;
  uint64_t frame_index;
  double elapsed_ms;
  double duration_ms;
  double detail_a_ms;
  double detail_b_ms;
  int area_type;
  int region_type;
};

static const char *debug_stage_name(const ClarityNavigationDebugStage stage)
{
  switch (stage) {
    case ClarityNavigationDebugStage::FrameBegin:
      return "frame_begin";
    case ClarityNavigationDebugStage::FrameRateLimit:
      return "frame_limit";
    case ClarityNavigationDebugStage::MakeDrawable:
      return "make_drawable";
    case ClarityNavigationDebugStage::SwapAcquire:
      return "swap_acquire";
    case ClarityNavigationDebugStage::ScreenUpdate:
      return "screen_update";
    case ClarityNavigationDebugStage::AreaLayout:
      return "area_layout";
    case ClarityNavigationDebugStage::AreaRegionSizes:
      return "area_region_sizes";
    case ClarityNavigationDebugStage::ToolSystemUpdate:
      return "tool_system_update";
    case ClarityNavigationDebugStage::RegionBufferCreate:
      return "region_buffer_create";
    case ClarityNavigationDebugStage::RegionBind:
      return "region_bind";
    case ClarityNavigationDebugStage::RegionDraw:
      return "region_draw";
    case ClarityNavigationDebugStage::Gizmo3D:
      return "gizmo_3d";
    case ClarityNavigationDebugStage::Gizmo2D:
      return "gizmo_2d";
    case ClarityNavigationDebugStage::RegionUnbind:
      return "region_unbind";
    case ClarityNavigationDebugStage::AreaTotal:
      return "area_total";
    case ClarityNavigationDebugStage::WindowOffscreen:
      return "window_offscreen";
    case ClarityNavigationDebugStage::WindowOnscreen:
      return "window_onscreen";
    case ClarityNavigationDebugStage::WindowDraw:
      return "window_draw";
    case ClarityNavigationDebugStage::DrawFlagClear:
      return "draw_flag_clear";
    case ClarityNavigationDebugStage::SwapRelease:
      return "swap_release";
    case ClarityNavigationDebugStage::FrameTotal:
      return "frame_total";
    case ClarityNavigationDebugStage::TransformEvent:
      return "transform_event";
    case ClarityNavigationDebugStage::TransformApply:
      return "transform_apply";
    case ClarityNavigationDebugStage::GeometryUpdate:
      return "geometry_update";
    case ClarityNavigationDebugStage::TransformModalTotal:
      return "transform_modal_total";
    case ClarityNavigationDebugStage::DepsgraphUpdate:
      return "depsgraph_update";
    case ClarityNavigationDebugStage::GizmoRefresh:
      return "gizmo_refresh";
    case ClarityNavigationDebugStage::GPUContextDrawLock:
      return "gpu_context_draw_lock";
    case ClarityNavigationDebugStage::GPUContextSharedLock:
      return "gpu_context_shared_lock";
    case ClarityNavigationDebugStage::GPUContextRenderBegin:
      return "gpu_context_render_begin";
    case ClarityNavigationDebugStage::GPUContextSystemActivate:
      return "gpu_context_system_activate";
    case ClarityNavigationDebugStage::GPUContextActivate:
      return "gpu_context_activate";
    case ClarityNavigationDebugStage::GPUContextFrameBegin:
      return "gpu_context_frame_begin";
    case ClarityNavigationDebugStage::ViewportRedrawState:
      return "viewport_redraw_state";
    case ClarityNavigationDebugStage::ViewportBufferReset:
      return "viewport_buffer_reset";
    case ClarityNavigationDebugStage::ViewportBufferMissing:
      return "viewport_buffer_missing";
    case ClarityNavigationDebugStage::ViewportComposite:
      return "viewport_composite";
    case ClarityNavigationDebugStage::Count:
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

struct ClarityNavigationDebugState {
  ClarityNavigationMode mode;
  double start_time;
  double last_event_time;
  double tool_activation_age_ms;
  double tool_activation_duration_ms;
  int viewport_fps_limit;
  int clarity_fps_limit;
  bool viewport_vsync;
  double max_event_gap_ms = 0.0;
  double max_update_ms = 0.0;
  uint64_t event_count = 0;
  uint64_t frame_index = 0;
  Vector<ClarityNavigationDebugSample> samples;
  Vector<ClarityNavigationDebugStageSample> stage_samples;
  std::array<double, size_t(ClarityNavigationDebugStage::Count)> stage_max_ms = {};

  ClarityNavigationDebugState(const ClarityNavigationMode mode,
                           const ClarityNavigationSettings &settings)
      : mode(mode),
        start_time(BLI_time_now_seconds()),
        last_event_time(start_time),
        tool_activation_age_ms(settings.tool_activation_age_ms),
        tool_activation_duration_ms(settings.tool_activation_duration_ms),
        viewport_fps_limit(U.viewport_fps_limit),
        clarity_fps_limit(settings.frame_rate_limit),
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

  void record_stage(const ClarityNavigationDebugStage stage,
                    const double duration_ms,
                    const double detail_a_ms,
                    const double detail_b_ms,
                    const int area_type,
                    const int region_type)
  {
    if (stage == ClarityNavigationDebugStage::FrameBegin) {
      frame_index++;
      return;
    }
    if (frame_index == 0) {
      return;
    }

    const bool viewport_event = ELEM(stage,
                                     ClarityNavigationDebugStage::ViewportRedrawState,
                                     ClarityNavigationDebugStage::ViewportBufferReset,
                                     ClarityNavigationDebugStage::ViewportBufferMissing);
    const int stage_index = int(stage);
    if (!viewport_event) {
      stage_max_ms[stage_index] = std::max(stage_max_ms[stage_index], duration_ms);
    }
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
    FILE *file = navigation_trace_file_open();
    if (file == nullptr) {
      return;
    }

    const char *mode_name = mode == ClarityNavigationMode::Orbit ?
                                "orbit" :
                                mode == ClarityNavigationMode::Pan ? "pan" : "dolly";
    std::fprintf(file,
                 "SESSION mode=%s events=%llu duration_ms=%.3f "
                 "tool_age_ms=%.3f tool_switch_ms=%.6f max_gap_ms=%.3f "
                 "max_update_ms=%.3f anomalies=%d fps_limit=%d clarity_fps_limit=%d "
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
                 clarity_fps_limit,
                 int(viewport_vsync));
    for (const ClarityNavigationDebugSample &sample : samples) {
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
    for (int stage_index = int(ClarityNavigationDebugStage::FrameRateLimit);
         stage_index < int(ClarityNavigationDebugStage::Count);
         stage_index++)
    {
      const ClarityNavigationDebugStage stage = ClarityNavigationDebugStage(stage_index);
      if (stage_max_ms[stage_index] > 0.0) {
        std::fprintf(
            file, " max_%s_ms=%.3f", debug_stage_name(stage), stage_max_ms[stage_index]);
      }
    }
    std::fputc('\n', file);
    std::fputs("  VIEWPORT_CODES redraw_code=region_do_draw_flags "
               "buffer_reset_bits=create:1,stereo:2,offscreen_size:4,format:8,"
               "viewport_size:16 detail_a=width_or_partial_pixels "
               "detail_b=height_or_buffer_present\n",
               file);

    Set<uint64_t> slow_frames;
    for (const ClarityNavigationDebugStageSample &sample : stage_samples) {
      if (sample.stage == ClarityNavigationDebugStage::FrameTotal &&
          sample.duration_ms >= 12.0)
      {
        slow_frames.add(sample.frame_index);
      }
    }
    for (const ClarityNavigationDebugStageSample &sample : stage_samples) {
      const bool viewport_event = ELEM(sample.stage,
                                       ClarityNavigationDebugStage::ViewportRedrawState,
                                       ClarityNavigationDebugStage::ViewportBufferReset,
                                       ClarityNavigationDebugStage::ViewportBufferMissing);
      if (viewport_event) {
        std::fprintf(file,
                     "  VIEWPORT_EVENT frame=%llu t_ms=%.3f stage=%s code=%.0f "
                     "detail_a=%.0f detail_b=%.0f area=%s(%d) region=%s(%d)\n",
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
        continue;
      }
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

static blender::ed::view3d::NavigationMode backend_mode_from_clarity_mode(
    const ClarityNavigationMode mode)
{
  switch (mode) {
    case ClarityNavigationMode::Orbit:
      return blender::ed::view3d::NavigationMode::Orbit;
    case ClarityNavigationMode::Pan:
      return blender::ed::view3d::NavigationMode::Pan;
    case ClarityNavigationMode::Dolly:
      return blender::ed::view3d::NavigationMode::Dolly;
  }
  return blender::ed::view3d::NavigationMode::Orbit;
}

static blender::ed::view3d::OrbitPivotPolicy backend_pivot_from_clarity_policy(
    const ClarityOrbitPivotPolicy policy)
{
  switch (policy) {
    case ClarityOrbitPivotPolicy::ViewCenter:
      return blender::ed::view3d::OrbitPivotPolicy::ViewCenter;
    case ClarityOrbitPivotPolicy::Selection:
      return blender::ed::view3d::OrbitPivotPolicy::Selection;
    case ClarityOrbitPivotPolicy::LastFocused:
      return blender::ed::view3d::OrbitPivotPolicy::LastFocused;
    case ClarityOrbitPivotPolicy::Explicit:
      return blender::ed::view3d::OrbitPivotPolicy::Explicit;
  }
  return blender::ed::view3d::OrbitPivotPolicy::LastFocused;
}

std::unique_ptr<ClarityNavigationSession> ClarityNavigationSession::begin(
    bContext *C,
    const ClarityNavigationMode mode,
    const ClarityInputAction &action,
    const ClarityNavigationSettings &settings)
{
  if (action.pointer_button == ClarityPointerButton::None) {
    return nullptr;
  }

  blender::ed::view3d::NavigationBeginParams params;
  params.mode = backend_mode_from_clarity_mode(mode);
  params.mouse_xy = action.mouse;
  params.mouse_region_xy = action.mouse_region;
  params.use_mouse_position = mode != ClarityNavigationMode::Dolly;
  params.invert_direction = mode == ClarityNavigationMode::Dolly;
  params.orbit_around_selection = settings.auto_pivot_from_selection;
  params.pivot_policy = backend_pivot_from_clarity_policy(settings.orbit_pivot);

  std::unique_ptr<blender::ed::view3d::NavigationSession> backend =
      blender::ed::view3d::navigation_session_begin(C, params);
  if (!backend) {
    return nullptr;
  }

  return std::make_unique<ClarityNavigationSession>(ED_clarity_session_context_from_context(C),
                                                 mode,
                                                 action.pointer_button,
                                                 action.mouse,
                                                 std::move(backend),
                                                 settings);
}

ClarityNavigationSession::ClarityNavigationSession(
    ClaritySessionContext context,
    const ClarityNavigationMode mode,
    const ClarityPointerButton initiating_button,
    const int2 initial_mouse,
    std::unique_ptr<blender::ed::view3d::NavigationSession> backend,
    const ClarityNavigationSettings &settings)
    : ClarityInteractionSession(context),
      mode_(mode),
      initiating_button_(initiating_button),
      last_mouse_(initial_mouse),
      backend_(std::move(backend)),
      debug_(settings.debug_logging ?
                 std::make_unique<ClarityNavigationDebugState>(mode, settings) :
                 nullptr),
      frame_rate_limit_(settings.frame_rate_limit)
{
}

ClarityNavigationSession::~ClarityNavigationSession()
{
  if (debug_) {
    debug_->flush();
  }
}

bool ClarityNavigationSession::debug_enabled() const
{
  return debug_ != nullptr;
}

int ClarityNavigationSession::frame_rate_limit() const
{
  return frame_rate_limit_;
}

void ClarityNavigationSession::debug_stage_sample(const ClarityNavigationDebugStage stage,
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

ClaritySessionKind ClarityNavigationSession::kind() const
{
  return ClaritySessionKind::Navigation;
}

ClaritySessionResult ClarityNavigationSession::handle_event(bContext *C,
                                                      const ClarityInputAction &action)
{
  if (action.id == ClarityActionID::EndNavigation) {
    backend_->confirm(C);
    return ClaritySessionResult::Finished;
  }

  if (action.id == ClarityActionID::PointerMove) {
    if (!action.alt) {
      backend_->confirm(C);
      return ClaritySessionResult::Finished;
    }
    if (action.mouse_delta.x == 0 && action.mouse_delta.y == 0) {
      return ClaritySessionResult::Running;
    }

    int2 navigation_mouse = action.mouse;
    if (mode_ == ClarityNavigationMode::Orbit) {
      const int2 tumble_delta = action.mouse - last_mouse_;
      navigation_mouse = last_mouse_ +
                         int2(clarity_tumble_delta_scale(tumble_delta.x),
                              clarity_tumble_delta_scale(tumble_delta.y));
    }
    else {
      last_mouse_ = action.mouse;
    }

    const double event_time = debug_ ? BLI_time_now_seconds() : 0.0;
    const blender::ed::view3d::NavigationResult navigation_result = backend_->update(
        C, navigation_mouse, action.mouse_region);
    if (debug_) {
      const double update_ms = (BLI_time_now_seconds() - event_time) * 1000.0;
      debug_->record(event_time, update_ms, action.mouse_delta);
    }

    switch (navigation_result) {
      case blender::ed::view3d::NavigationResult::Running:
        return ClaritySessionResult::Running;
      case blender::ed::view3d::NavigationResult::Finished:
        return ClaritySessionResult::Finished;
      case blender::ed::view3d::NavigationResult::Cancelled:
        return ClaritySessionResult::Cancelled;
      case blender::ed::view3d::NavigationResult::Failed:
        cancel(C);
        return ClaritySessionResult::Cancelled;
    }
  }

  if (action.id == ClarityActionID::Confirm &&
      action.pointer_button == initiating_button_)
  {
    backend_->confirm(C);
    return ClaritySessionResult::Finished;
  }

  if (action.id == ClarityActionID::Cancel) {
    cancel(C);
    return ClaritySessionResult::Cancelled;
  }

  return ClaritySessionResult::Running;
}

void ClarityNavigationSession::cancel(bContext *C)
{
  if (backend_) {
    backend_->cancel(C);
  }
}

}  // namespace blender::ed::clarity
