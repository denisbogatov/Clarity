/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup editors
 */

#include "maya_runtime.hh"

#include <algorithm>
#include <array>
#include <cstdio>
#include <string>

#include "BLI_fileops.h"
#include "BLI_map.hh"
#include "BLI_path_utils.hh"
#include "BLI_time.h"
#include "BLI_utildefines.h"
#include "BLI_vector.hh"

#include "BKE_appdir.hh"
#include "BKE_context.hh"
#include "BKE_global.hh"

#include "DNA_windowmanager_types.h"

#include "ED_maya.hh"

#include "RNA_access.hh"

#include "maya_session.hh"

namespace blender::ed::maya {

struct MayaTransformDebugStageSample {
  MayaNavigationDebugStage stage;
  uint64_t frame_index;
  uint64_t event_index;
  double elapsed_ms;
  double duration_ms;
  double detail_a_ms;
  double detail_b_ms;
  int area_type;
  int region_type;
};

static const char *transform_debug_stage_name(const MayaNavigationDebugStage stage)
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

struct MayaTransformDebugState {
  std::string operator_id;
  int context_mode;
  int mesh_select_mode;
  double start_time = BLI_time_now_seconds();
  double last_event_time = start_time;
  uint64_t event_index = 0;
  uint64_t frame_index = 0;
  bool flushed = false;
  Vector<MayaTransformDebugStageSample> samples;
  std::array<double, size_t(MayaNavigationDebugStage::Count)> stage_max_ms = {};

  MayaTransformDebugState(const char *operator_id, const int context_mode, const int mesh_select_mode)
      : operator_id(operator_id ? operator_id : "-"),
        context_mode(context_mode),
        mesh_select_mode(mesh_select_mode)
  {
    samples.reserve(32768);
  }

  ~MayaTransformDebugState()
  {
    flush();
  }

  void record(const MayaNavigationDebugStage stage,
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
    if (stage == MayaNavigationDebugStage::TransformEvent) {
      event_index++;
      last_event_time = BLI_time_now_seconds();
    }

    const int stage_index = int(stage);
    stage_max_ms[stage_index] = std::max(stage_max_ms[stage_index], duration_ms);
    if (samples.size() < 65536) {
      samples.append({stage,
                      frame_index,
                      event_index,
                      (BLI_time_now_seconds() - start_time) * 1000.0,
                      duration_ms,
                      detail_a_ms,
                      detail_b_ms,
                      area_type,
                      region_type});
    }
  }

  void flush()
  {
    if (flushed) {
      return;
    }
    flushed = true;

    char filepath[FILE_MAX];
    BLI_path_join(filepath, sizeof(filepath), BKE_tempdir_base(), "maya_navigation_trace.log");
    FILE *file = BLI_fopen(filepath, "a");
    if (file == nullptr) {
      return;
    }

    std::fprintf(file,
                 "TRANSFORM_SESSION operator=%s context_mode=%d mesh_select_mode=%d "
                 "events=%llu frames=%llu duration_ms=%.3f samples=%d\n",
                 operator_id.c_str(),
                 context_mode,
                 mesh_select_mode,
                 static_cast<unsigned long long>(event_index),
                 static_cast<unsigned long long>(frame_index),
                 (last_event_time - start_time) * 1000.0,
                 int(samples.size()));
    std::fputs("  PERF_SUMMARY", file);
    for (int stage_index = 0; stage_index < int(MayaNavigationDebugStage::Count); stage_index++) {
      if (stage_max_ms[stage_index] > 0.0) {
        std::fprintf(file,
                     " max_%s_ms=%.3f",
                     transform_debug_stage_name(MayaNavigationDebugStage(stage_index)),
                     stage_max_ms[stage_index]);
      }
    }
    std::fputc('\n', file);

    for (const MayaTransformDebugStageSample &sample : samples) {
      const bool transform_stage = ELEM(sample.stage,
                                        MayaNavigationDebugStage::TransformEvent,
                                        MayaNavigationDebugStage::TransformApply,
                                        MayaNavigationDebugStage::GeometryUpdate,
                                        MayaNavigationDebugStage::TransformModalTotal,
                                        MayaNavigationDebugStage::DepsgraphUpdate,
                                        MayaNavigationDebugStage::GizmoRefresh);
      if (!transform_stage && sample.duration_ms < 2.0) {
        continue;
      }
      if (transform_stage && sample.duration_ms < 0.05) {
        continue;
      }
      std::fprintf(file,
                   "  PERF event=%llu frame=%llu t_ms=%.3f stage=%s duration_ms=%.3f "
                   "detail_a_ms=%.3f detail_b_ms=%.3f area=%d region=%d\n",
                   static_cast<unsigned long long>(sample.event_index),
                   static_cast<unsigned long long>(sample.frame_index),
                   sample.elapsed_ms,
                   transform_debug_stage_name(sample.stage),
                   sample.duration_ms,
                   sample.detail_a_ms,
                   sample.detail_b_ms,
                   sample.area_type,
                   sample.region_type);
    }
    std::fputc('\n', file);
    std::fclose(file);
  }
};

MayaWindowRuntime::MayaWindowRuntime() = default;
MayaWindowRuntime::~MayaWindowRuntime() = default;
MayaWindowRuntime::MayaWindowRuntime(MayaWindowRuntime &&other) = default;
MayaWindowRuntime &MayaWindowRuntime::operator=(MayaWindowRuntime &&other) = default;

bool MayaWindowRuntime::navigation_active() const
{
  return active_session && active_session->kind() == MayaSessionKind::Navigation;
}

static Map<const wmWindow *, MayaWindowRuntime> &runtimes()
{
  static Map<const wmWindow *, MayaWindowRuntime> runtime_by_window;
  return runtime_by_window;
}

MayaWindowRuntime *runtime_get(const bContext *C)
{
  const wmWindow *win = CTX_wm_window(C);
  if (win == nullptr) {
    return nullptr;
  }
  return runtimes().lookup_ptr(win);
}

MayaWindowRuntime *runtime_ensure(const bContext *C)
{
  const wmWindow *win = CTX_wm_window(C);
  if (win == nullptr) {
    return nullptr;
  }
  return &runtimes().lookup_or_add_default(win);
}

bool navigation_debug_logging_enabled(const bContext *C)
{
  wmWindowManager *wm = CTX_wm_manager(C);
  if (wm == nullptr) {
    return false;
  }

  PointerRNA wm_ptr = RNA_id_pointer_create(&wm->id);
  PropertyRNA *property = RNA_struct_find_property(&wm_ptr, "maya_navigation_debug");
  return property != nullptr && RNA_property_boolean_get(&wm_ptr, property);
}

int navigation_frame_rate_limit_setting(const bContext *C)
{
  wmWindowManager *wm = CTX_wm_manager(C);
  if (wm == nullptr) {
    return 120;
  }

  PointerRNA wm_ptr = RNA_id_pointer_create(&wm->id);
  PropertyRNA *property = RNA_struct_find_property(&wm_ptr, "maya_navigation_fps_limit");
  if (property == nullptr) {
    return 120;
  }

  switch (RNA_property_enum_get(&wm_ptr, property)) {
    case 0:
      return 60;
    case 2:
      return 144;
    case 3:
      return 240;
    default:
      return 120;
  }
}

static MayaNavigationSession *navigation_debug_session_get(const bContext *C)
{
  MayaWindowRuntime *runtime = runtime_get(C);
  if (runtime == nullptr || !runtime->navigation_active()) {
    return nullptr;
  }
  MayaNavigationSession *session = static_cast<MayaNavigationSession *>(
      runtime->active_session.get());
  return session->debug_enabled() ? session : nullptr;
}

}  // namespace blender::ed::maya

namespace blender {

int ED_maya_interaction_frame_rate_limit(const bContext *C)
{
  ed::maya::MayaWindowRuntime *runtime = ed::maya::runtime_get(C);
  if ((runtime != nullptr && runtime->transform_active) || G.moving != 0) {
    return ed::maya::navigation_frame_rate_limit_setting(C);
  }

  if (runtime == nullptr || !runtime->navigation_active()) {
    return 0;
  }
  const ed::maya::MayaNavigationSession *session =
      static_cast<const ed::maya::MayaNavigationSession *>(runtime->active_session.get());
  return session->frame_rate_limit();
}

bool ED_maya_navigation_debug_active(const bContext *C)
{
  const ed::maya::MayaWindowRuntime *runtime = ed::maya::runtime_get(C);
  return ed::maya::navigation_debug_session_get(C) != nullptr ||
         (runtime != nullptr && runtime->transform_debug != nullptr);
}

void ED_maya_transform_begin(const bContext *C,
                             const char *operator_id,
                             const int context_mode,
                             const int mesh_select_mode)
{
  ed::maya::MayaWindowRuntime *runtime = ed::maya::runtime_ensure(C);
  if (runtime == nullptr) {
    return;
  }
  runtime->transform_active = true;
  if (ED_maya_interaction_enabled(C) && ed::maya::navigation_debug_logging_enabled(C)) {
    runtime->transform_debug = std::make_unique<ed::maya::MayaTransformDebugState>(
        operator_id, context_mode, mesh_select_mode);
  }
}

void ED_maya_transform_end(const bContext *C)
{
  if (ed::maya::MayaWindowRuntime *runtime = ed::maya::runtime_get(C)) {
    runtime->transform_active = false;
    runtime->transform_debug.reset();
  }
}

void ED_maya_navigation_debug_stage_sample(
    const bContext *C,
    const ed::maya::MayaNavigationDebugStage stage,
    const double duration_ms,
    const double detail_a_ms,
    const double detail_b_ms,
    const int area_type,
    const int region_type)
{
  if (ed::maya::MayaNavigationSession *session =
          ed::maya::navigation_debug_session_get(C))
  {
    session->debug_stage_sample(
        stage, duration_ms, detail_a_ms, detail_b_ms, area_type, region_type);
  }
  if (ed::maya::MayaWindowRuntime *runtime = ed::maya::runtime_get(C)) {
    if (runtime->transform_debug) {
      runtime->transform_debug->record(
          stage, duration_ms, detail_a_ms, detail_b_ms, area_type, region_type);
    }
  }
}

void ED_maya_runtime_free(bContext *C, const wmWindow *win)
{
  if (ed::maya::MayaWindowRuntime *runtime = ed::maya::runtimes().lookup_ptr(win)) {
    if (C != nullptr && runtime->active_session) {
      runtime->active_session->cancel(C);
    }
  }
  ed::maya::runtimes().remove(win);
}

}  // namespace blender
