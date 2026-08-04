/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup editors
 */

#include "clarity_runtime.hh"

#include "MEM_guardedalloc.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdio>
#include <limits>
#include <optional>
#include <string>
#include <utility>

#include "BLI_fileops.h"
#include "BLI_bounds_types.hh"
#include "BLI_index_range.hh"
#include "BLI_listbase_iterator.hh"
#include "BLI_map.hh"
#include "BLI_math_matrix.h"
#include "BLI_math_matrix.hh"
#include "BLI_math_matrix_types.hh"
#include "BLI_math_quaternion.hh"
#include "BLI_math_rotation.h"
#include "BLI_math_vector.h"
#include "BLI_math_vector.hh"
#include "BLI_path_utils.hh"
#include "BLI_string.h"
#include "BLI_time.h"
#include "BLI_utildefines.h"
#include "BLI_vector.hh"

#include "BKE_appdir.hh"
#include "BKE_blender_version.h"
#include "BKE_context.hh"
#include "BKE_editmesh.hh"
#include "BKE_global.hh"
#include "BKE_layer.hh"
#include "BKE_lib_id.hh"
#include "BKE_main.hh"
#include "BKE_clarity_constraints.hh"
#include "BKE_object.hh"
#include "BKE_object_custom_pivot.hh"
#include "BKE_object_transform_clarity.hh"
#include "BKE_undo_system.hh"
#include "BKE_wm_runtime.hh"

#include "DNA_object_types.h"
#include "DNA_scene_types.h"
#include "DNA_screen_types.h"
#include "DNA_view3d_types.h"
#include "DNA_windowmanager_types.h"

#include "ED_clarity.hh"
#include "ED_object.hh"
#include "ED_screen.hh"
#include "ED_transform_snap_object_context.hh"
#include "ED_undo.hh"
#include "ED_view3d.hh"

#include "DEG_depsgraph.hh"

#include "bmesh.hh"

#include "RNA_access.hh"

#include "clarity_session.hh"
#include "clarity_input.hh"
#include "clarity_tool_presentation.hh"
#include "clarity_tools.hh"

#include "WM_api.hh"
#include "WM_types.hh"
#include "wm_event_types.hh"

namespace blender::ed::clarity {

void ClaritySnapObjectContextDeleter::operator()(ed::transform::SnapObjectContext *context) const
{
  ed::transform::snap_object_context_destroy(context);
}

std::FILE *navigation_trace_file_open()
{
  char filepath[FILE_MAX];
  BLI_path_join(filepath, sizeof(filepath), BKE_tempdir_base(), "clarity_navigation_trace.log");

  /* The trace is reopened for appending many times per session, so without rotating it once per run
   * the file accumulates sessions from different builds. Any aggregate over it then silently mixes
   * them, which reads as a measurement rather than as stale data. One run, one file. */
  static bool run_header_written = false;
  if (!run_header_written) {
    run_header_written = true;
    char previous[FILE_MAX];
    BLI_path_join(
        previous, sizeof(previous), BKE_tempdir_base(), "clarity_navigation_trace.prev.log");
    if (BLI_exists(filepath)) {
      BLI_rename_overwrite(filepath, previous);
    }
    if (std::FILE *header = BLI_fopen(filepath, "w")) {
      /* The settings that decide how a frame is paced belong to the header: a comparison between two
       * runs is only meaningful once they are known to have been paced the same way. */
      std::fprintf(header,
                   "RUN blender=%s fps_limit=%d vsync=%d viewport_aa=%d\n",
                   BKE_blender_version_string(),
                   int(U.viewport_fps_limit),
                   int(U.viewport_vsync),
                   int(U.viewport_aa));
      std::fclose(header);
    }
  }
  return BLI_fopen(filepath, "a");
}

struct ClarityPivotUndoSnapshot {
  uint32_t scene_session_uid = 0;
  uint32_t object_session_uid = 0;
  ClarityObjectRuntimeRef manipulator_object;
  float location[3] = {};
  float rotation_quaternion[4] = {1.0f, 0.0f, 0.0f, 0.0f};
  double manipulator_position[3] = {};
  double manipulator_orientation[4] = {1.0, 0.0, 0.0, 0.0};
  int selection_mode = 0;
  int pivot_point = 0;
  int selected_counts[3] = {};
  int element_counts[3] = {};
  uint64_t selection_hash = 0;
  int active_element_index = -1;
  char active_element_type = 0;
  bool selection_signature_valid = false;
  bool position_valid = false;
  bool orientation_valid = false;
  bool pinned = false;
  bool has_custom = false;
  bool manipulator_position_valid = false;
  bool manipulator_orientation_valid = false;
};

struct ClarityPivotUndoState {
  std::optional<ClarityPivotUndoSnapshot> pending_before;
};

struct ClarityTransformTransaction::Impl {
  struct ObjectState {
    Object *object = nullptr;
    void *transform_backup = nullptr;
    std::optional<ClarityObjectTransform> clarity_transform;
    std::optional<ObjectCustomPivot> custom_pivot;
    bool had_custom_pivot = false;

    ~ObjectState()
    {
      if (transform_backup != nullptr) {
        BKE_object_tfm_free(transform_backup);
      }
    }
  };

  struct GeometryState {
    ID *data = nullptr;
    std::unique_ptr<ed::object::XFormObjectData> snapshot;
  };

  Depsgraph *depsgraph = nullptr;
  Scene *scene = nullptr;
  Vector<std::unique_ptr<ObjectState>> objects;
  Vector<std::unique_ptr<GeometryState>> geometry;
  ClarityManipulatorPivotState *runtime_state = nullptr;
  std::optional<ClarityManipulatorPivotState> runtime_snapshot;
  bool committed = false;
  bool rolled_back = false;
};

ClarityTransformTransaction::ClarityTransformTransaction(Depsgraph *depsgraph, Scene *scene)
    : impl_(std::make_unique<Impl>())
{
  impl_->depsgraph = depsgraph;
  impl_->scene = scene;
}

ClarityTransformTransaction::~ClarityTransformTransaction()
{
  if (impl_ && !impl_->committed && !impl_->rolled_back) {
    rollback();
  }
}

bool ClarityTransformTransaction::capture_object(Object &object)
{
  for (const std::unique_ptr<Impl::ObjectState> &state : impl_->objects) {
    if (state->object == &object) {
      return true;
    }
  }
  auto state = std::make_unique<Impl::ObjectState>();
  state->object = &object;
  state->transform_backup = BKE_object_tfm_backup(&object);
  if (state->transform_backup == nullptr) {
    return false;
  }
  if (BKE_object_uses_clarity_transform(&object)) {
    state->clarity_transform = *object.clarity_transform;
  }
  state->had_custom_pivot = object.custom_pivot != nullptr;
  if (state->had_custom_pivot) {
    state->custom_pivot = *object.custom_pivot;
  }
  impl_->objects.append(std::move(state));
  return true;
}

bool ClarityTransformTransaction::capture_geometry(ID &data)
{
  for (const std::unique_ptr<Impl::GeometryState> &state : impl_->geometry) {
    if (state->data == &data) {
      return true;
    }
  }
  auto state = std::make_unique<Impl::GeometryState>();
  state->data = &data;
  state->snapshot = ed::object::data_xform_create(&data);
  if (!state->snapshot) {
    return false;
  }
  impl_->geometry.append(std::move(state));
  return true;
}

bool ClarityTransformTransaction::capture_child(Object &child)
{
  return capture_object(child);
}

bool ClarityTransformTransaction::capture_runtime(ClarityManipulatorPivotState &state)
{
  if (impl_->runtime_state != nullptr && impl_->runtime_state != &state) {
    return false;
  }
  impl_->runtime_state = &state;
  impl_->runtime_snapshot = state;
  return true;
}

bool ClarityTransformTransaction::transform_geometry(ID &data, const float4x4 &matrix)
{
  for (const std::unique_ptr<Impl::GeometryState> &state : impl_->geometry) {
    if (state->data == &data) {
      ed::object::data_xform_by_mat4(*state->snapshot, matrix);
      ed::object::data_xform_tag_update(*state->snapshot);
      return true;
    }
  }
  return false;
}

void ClarityTransformTransaction::commit()
{
  impl_->committed = true;
}

void ClarityTransformTransaction::rollback()
{
  if (impl_->committed || impl_->rolled_back) {
    return;
  }
  for (const std::unique_ptr<Impl::GeometryState> &state : impl_->geometry) {
    ed::object::data_xform_restore(*state->snapshot);
    ed::object::data_xform_tag_update(*state->snapshot);
  }
  for (const std::unique_ptr<Impl::ObjectState> &state : impl_->objects) {
    if (state->clarity_transform.has_value()) {
      *state->object->clarity_transform = *state->clarity_transform;
      BKE_object_clarity_evaluated_channels_invalidate(*state->object);
    }
    if (state->had_custom_pivot) {
      *BKE_object_custom_pivot_ensure(*state->object) = *state->custom_pivot;
    }
    else {
      BKE_object_custom_pivot_reset(*state->object);
    }
    BKE_object_tfm_restore(state->object, state->transform_backup);
    DEG_id_tag_update(&state->object->id, ID_RECALC_TRANSFORM);
  }
  if (impl_->runtime_state != nullptr && impl_->runtime_snapshot.has_value()) {
    *impl_->runtime_state = *impl_->runtime_snapshot;
  }
  if (impl_->depsgraph != nullptr && impl_->scene != nullptr) {
    for (const std::unique_ptr<Impl::ObjectState> &state : impl_->objects) {
      BKE_object_where_is_calc(impl_->depsgraph, impl_->scene, state->object);
    }
  }
  impl_->rolled_back = true;
}

struct ClarityPivotUndoStepPayload {
  const wmWindow *owner_window = nullptr;
  uint64_t owner_runtime_id = 0;
  ClarityPivotUndoSnapshot before;
  ClarityPivotUndoSnapshot after;
};

struct ClarityTransformDebugStageSample {
  ClarityNavigationDebugStage stage;
  uint64_t frame_index;
  uint64_t event_index;
  double elapsed_ms;
  double duration_ms;
  double detail_a_ms;
  double detail_b_ms;
  int area_type;
  int region_type;
};

static const char *transform_debug_stage_name(const ClarityNavigationDebugStage stage)
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

struct ClarityTransformDebugState {
  std::string operator_id;
  int context_mode;
  int mesh_select_mode;
  bool clarity_pivot_transform;
  ClarityPivotEditTarget pivot_target;
  ClaritySnapMode snap_mode_at_begin;
  double start_time = BLI_time_now_seconds();
  double last_event_time = start_time;
  uint64_t event_index = 0;
  uint64_t frame_index = 0;
  bool flushed = false;
  Vector<ClarityTransformDebugStageSample> samples;
  std::array<double, size_t(ClarityNavigationDebugStage::Count)> stage_max_ms = {};

  ClarityTransformDebugState(const char *operator_id,
                          const int context_mode,
                          const int mesh_select_mode,
                          const bool clarity_pivot_transform,
                          const ClarityPivotEditTarget pivot_target,
                          const ClaritySnapMode snap_mode_at_begin)
      : operator_id(operator_id ? operator_id : "-"),
        context_mode(context_mode),
        mesh_select_mode(mesh_select_mode),
        clarity_pivot_transform(clarity_pivot_transform),
        pivot_target(pivot_target),
        snap_mode_at_begin(snap_mode_at_begin)
  {
    samples.reserve(32768);
  }

  ~ClarityTransformDebugState()
  {
    flush();
  }

  void record(const ClarityNavigationDebugStage stage,
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
    if (stage == ClarityNavigationDebugStage::TransformEvent) {
      event_index++;
      last_event_time = BLI_time_now_seconds();
    }

    const bool viewport_event = ELEM(stage,
                                     ClarityNavigationDebugStage::ViewportRedrawState,
                                     ClarityNavigationDebugStage::ViewportBufferReset,
                                     ClarityNavigationDebugStage::ViewportBufferMissing);
    const int stage_index = int(stage);
    if (!viewport_event) {
      stage_max_ms[stage_index] = std::max(stage_max_ms[stage_index], duration_ms);
    }
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

    FILE *file = navigation_trace_file_open();
    if (file == nullptr) {
      return;
    }

    std::fprintf(file,
                  "TRANSFORM_SESSION operator=%s context_mode=%d mesh_select_mode=%d "
                  "clarity_pivot=%d pivot_target=%d snap_mode_at_begin=%d "
                  "events=%llu frames=%llu duration_ms=%.3f samples=%d\n",
                  operator_id.c_str(),
                  context_mode,
                  mesh_select_mode,
                  int(clarity_pivot_transform),
                  int(pivot_target),
                  int(snap_mode_at_begin),
                  static_cast<unsigned long long>(event_index),
                  static_cast<unsigned long long>(frame_index),
                  (last_event_time - start_time) * 1000.0,
                  int(samples.size()));
    std::fputs("  PERF_SUMMARY", file);
    for (int stage_index = 0; stage_index < int(ClarityNavigationDebugStage::Count); stage_index++) {
      if (stage_max_ms[stage_index] > 0.0) {
        std::fprintf(file,
                     " max_%s_ms=%.3f",
                     transform_debug_stage_name(ClarityNavigationDebugStage(stage_index)),
                     stage_max_ms[stage_index]);
      }
    }
    std::fputc('\n', file);
    std::fputs("  VIEWPORT_CODES redraw_code=region_do_draw_flags "
               "buffer_reset_bits=create:1,stereo:2,offscreen_size:4,format:8,"
               "viewport_size:16 detail_a=width_or_partial_pixels "
               "detail_b=height_or_buffer_present\n",
               file);

    for (const ClarityTransformDebugStageSample &sample : samples) {
      const bool viewport_event = ELEM(sample.stage,
                                       ClarityNavigationDebugStage::ViewportRedrawState,
                                       ClarityNavigationDebugStage::ViewportBufferReset,
                                       ClarityNavigationDebugStage::ViewportBufferMissing);
      if (viewport_event) {
        std::fprintf(file,
                     "  VIEWPORT_EVENT event=%llu frame=%llu t_ms=%.3f stage=%s code=%.0f "
                     "detail_a=%.0f detail_b=%.0f area=%d region=%d\n",
                     static_cast<unsigned long long>(sample.event_index),
                     static_cast<unsigned long long>(sample.frame_index),
                     sample.elapsed_ms,
                     transform_debug_stage_name(sample.stage),
                     sample.duration_ms,
                     sample.detail_a_ms,
                     sample.detail_b_ms,
                     sample.area_type,
                     sample.region_type);
        continue;
      }
      const bool transform_stage = ELEM(sample.stage,
                                        ClarityNavigationDebugStage::TransformEvent,
                                        ClarityNavigationDebugStage::TransformApply,
                                        ClarityNavigationDebugStage::GeometryUpdate,
                                        ClarityNavigationDebugStage::TransformModalTotal,
                                        ClarityNavigationDebugStage::DepsgraphUpdate,
                                        ClarityNavigationDebugStage::GizmoRefresh);
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

static uint64_t clarity_runtime_instance_id_next = 1;

ClarityWindowRuntime::ClarityWindowRuntime() : instance_id(clarity_runtime_instance_id_next++) {}
ClarityWindowRuntime::~ClarityWindowRuntime() = default;
ClarityWindowRuntime::ClarityWindowRuntime(ClarityWindowRuntime &&other) = default;
ClarityWindowRuntime &ClarityWindowRuntime::operator=(ClarityWindowRuntime &&other) = default;

bool ClarityWindowRuntime::navigation_active() const
{
  return active_session && active_session->kind() == ClaritySessionKind::Navigation;
}

static Map<const wmWindow *, ClarityWindowRuntime> &runtimes()
{
  static Map<const wmWindow *, ClarityWindowRuntime> runtime_by_window;
  return runtime_by_window;
}

static bool object_runtime_ref_is_empty(const ClarityObjectRuntimeRef &reference)
{
  return reference.session_uid == 0;
}

static void object_runtime_ref_clear(ClarityObjectRuntimeRef &reference)
{
  reference = {};
}

ClarityWindowRuntime *runtime_get(const bContext *C)
{
  const wmWindow *win = CTX_wm_window(C);
  if (win == nullptr) {
    return nullptr;
  }
  return runtimes().lookup_ptr(win);
}

ClarityWindowRuntime *runtime_ensure(const bContext *C)
{
  const wmWindow *win = CTX_wm_window(C);
  if (win == nullptr) {
    return nullptr;
  }
  return &runtimes().lookup_or_add_default(win);
}

static Object *manipulator_pivot_last_object_resolve(const bContext *C,
                                                     ClarityWindowRuntime &runtime)
{
  ClarityManipulatorPivotState &pivot = runtime.tool.manipulator_pivot;
  if (object_runtime_ref_is_empty(pivot.last_object)) {
    return nullptr;
  }
  Main *bmain = CTX_data_main(C);
  Object *object = bmain != nullptr ?
                       ED_clarity_object_runtime_ref_resolve(*bmain, pivot.last_object) :
                       nullptr;
  if (object != nullptr) {
    return object;
  }
  pivot.position_valid = false;
  pivot.orientation_valid = false;
  object_runtime_ref_clear(pivot.last_object);
  runtime.pivot_edit.custom.reset();
  runtime.pivot_edit.object = nullptr;
  runtime.pivot_edit.target = ClarityPivotEditTarget::None;
  runtime.pivot_edit.phase = ClarityPivotEditPhase::Normal;
  return nullptr;
}

static UndoStep *pivot_undo_active_step_get(const bContext *C)
{
  wmWindowManager *wm = CTX_wm_manager(C);
  if (wm == nullptr || wm->runtime == nullptr || wm->runtime->undo_stack == nullptr) {
    return nullptr;
  }
  return wm->runtime->undo_stack->step_active;
}

static std::optional<ClarityPivotUndoSnapshot> pivot_undo_snapshot_create(
    const bContext *C, const ClarityWindowRuntime &runtime)
{
  const ClarityCustomPivotData *custom = runtime.pivot_edit.custom.get();
  const bool has_custom = custom != nullptr && custom->scene != nullptr &&
                          custom->object != nullptr && custom->scene == CTX_data_scene(C);
  if (!has_custom && runtime.pivot_edit.target == ClarityPivotEditTarget::None &&
      object_runtime_ref_is_empty(runtime.tool.manipulator_pivot.last_object))
  {
    return std::nullopt;
  }

  ClarityPivotUndoSnapshot snapshot;
  snapshot.has_custom = has_custom;
  if (has_custom) {
    BKE_lib_libblock_session_uid_ensure(&custom->scene->id);
    BKE_lib_libblock_session_uid_ensure(&custom->object->id);
    snapshot.scene_session_uid = custom->scene->id.session_uid;
    snapshot.object_session_uid = custom->object->id.session_uid;
    copy_v3_v3(snapshot.location, custom->location);
    copy_qt_qt(snapshot.rotation_quaternion, custom->rotation_quaternion);
    snapshot.selection_mode = custom->selection_mode;
    snapshot.pivot_point = custom->pivot_point;
    std::copy(custom->selected_counts, custom->selected_counts + 3, snapshot.selected_counts);
    std::copy(custom->element_counts, custom->element_counts + 3, snapshot.element_counts);
    snapshot.selection_hash = custom->selection_hash;
    snapshot.active_element_index = custom->active_element_index;
    snapshot.active_element_type = custom->active_element_type;
    snapshot.selection_signature_valid = custom->selection_signature_valid;
    snapshot.position_valid = custom->position_valid;
    snapshot.orientation_valid = custom->orientation_valid;
    snapshot.pinned = custom->pinned;
  }

  const ClarityManipulatorPivotState &pivot = runtime.tool.manipulator_pivot;
  std::copy_n(
      static_cast<const double *>(pivot.position_world), 3, snapshot.manipulator_position);
  snapshot.manipulator_orientation[0] = pivot.orientation_world.w;
  snapshot.manipulator_orientation[1] = pivot.orientation_world.x;
  snapshot.manipulator_orientation[2] = pivot.orientation_world.y;
  snapshot.manipulator_orientation[3] = pivot.orientation_world.z;
  snapshot.manipulator_position_valid = pivot.position_valid;
  snapshot.manipulator_orientation_valid = pivot.orientation_valid;
  snapshot.manipulator_object = pivot.last_object;
  return snapshot;
}

static void pivot_undo_step_begin(const bContext *C, ClarityWindowRuntime &runtime)
{
  manipulator_pivot_last_object_resolve(C, runtime);
  if (runtime.pivot_undo) {
    runtime.pivot_undo->pending_before.reset();
  }
  const std::optional<ClarityPivotUndoSnapshot> snapshot = pivot_undo_snapshot_create(C, runtime);
  if (!snapshot) {
    return;
  }
  if (!runtime.pivot_undo) {
    runtime.pivot_undo = std::make_unique<ClarityPivotUndoState>();
  }
  runtime.pivot_undo->pending_before = *snapshot;
}

static void pivot_undo_pending_clear(ClarityWindowRuntime &runtime)
{
  if (runtime.pivot_undo) {
    runtime.pivot_undo->pending_before.reset();
  }
}

static void pivot_undo_step_payload_free(void *user_data)
{
  MEM_delete(static_cast<ClarityPivotUndoStepPayload *>(user_data));
}

static const ClarityPivotUndoStepPayload *pivot_undo_step_payload_get(const UndoStack *undo_stack,
                                                                   const UndoStep *step)
{
  if (undo_stack == nullptr || step == nullptr) {
    return nullptr;
  }
  return static_cast<const ClarityPivotUndoStepPayload *>(BKE_undosys_step_user_data_get(
      undo_stack, step, pivot_undo_step_payload_free));
}

static bool pivot_undo_snapshot_restore(bContext *C,
                                        const ClarityPivotUndoStepPayload &payload,
                                        const ClarityPivotUndoSnapshot &snapshot)
{
  ClarityWindowRuntime *runtime = runtimes().lookup_ptr(payload.owner_window);
  if (runtime == nullptr || runtime->instance_id != payload.owner_runtime_id) {
    return false;
  }

  Main *bmain = CTX_data_main(C);
  ClarityManipulatorPivotState &pivot = runtime->tool.manipulator_pivot;
  pivot.position_world = double3(snapshot.manipulator_position);
  pivot.orientation_world = math::QuaternionBase<double>(
      snapshot.manipulator_orientation[0],
      snapshot.manipulator_orientation[1],
      snapshot.manipulator_orientation[2],
      snapshot.manipulator_orientation[3]);
  pivot.position_valid = snapshot.manipulator_position_valid;
  pivot.orientation_valid = snapshot.manipulator_orientation_valid;
  pivot.pin_component_pivot = snapshot.pinned;
  pivot.last_object = snapshot.manipulator_object;
  manipulator_pivot_last_object_resolve(C, *runtime);

  if (!snapshot.has_custom) {
    runtime->pivot_edit.custom.reset();
    WM_main_add_notifier(NC_SPACE | ND_SPACE_VIEW3D, nullptr);
    return true;
  }

  Scene *scene = id_cast<Scene *>(
      BKE_libblock_find_session_uid(bmain, ID_SCE, snapshot.scene_session_uid));
  Object *object = id_cast<Object *>(
      BKE_libblock_find_session_uid(bmain, ID_OB, snapshot.object_session_uid));
  if (scene == nullptr || object == nullptr) {
    return false;
  }
  auto custom = std::make_unique<ClarityCustomPivotData>();
  custom->scene = scene;
  custom->object = object;
  copy_v3_v3(custom->location, snapshot.location);
  copy_qt_qt(custom->rotation_quaternion, snapshot.rotation_quaternion);
  custom->selection_mode = snapshot.selection_mode;
  custom->pivot_point = snapshot.pivot_point;
  std::copy(snapshot.selected_counts, snapshot.selected_counts + 3, custom->selected_counts);
  std::copy(snapshot.element_counts, snapshot.element_counts + 3, custom->element_counts);
  custom->selection_hash = snapshot.selection_hash;
  custom->active_element_index = snapshot.active_element_index;
  custom->active_element_type = snapshot.active_element_type;
  custom->selection_signature_valid = snapshot.selection_signature_valid;
  custom->position_valid = snapshot.position_valid;
  custom->orientation_valid = snapshot.orientation_valid;
  custom->pinned = snapshot.pinned;

  BMEditMesh *em = BKE_editmesh_from_object(object);
  if (em != nullptr) {
    /* Edit-mesh undo recreates the BMesh. Rebind the signature without recalculating the
     * explicitly restored pivot position or orientation. */
    custom->bmesh_identity = em->bm;
  }
  else {
    custom->selection_signature_valid = false;
  }
  runtime->pivot_edit.custom = std::move(custom);
  runtime->pivot_mode = ClarityPivotMode::Custom;
  if (runtime->pivot_edit.target == ClarityPivotEditTarget::ComponentPivot) {
    runtime->pivot_edit.scene = scene;
    runtime->pivot_edit.object = object;
  }

  if (payload.owner_window == CTX_wm_window(C)) {
    ED_clarity_tool_presentation_refresh(C, *runtime);
  }
  WM_main_add_notifier(NC_SPACE | ND_SPACE_VIEW3D, nullptr);
  return true;
}

bool navigation_debug_logging_enabled(const bContext *C)
{
  wmWindowManager *wm = CTX_wm_manager(C);
  if (wm == nullptr) {
    return false;
  }

  PointerRNA wm_ptr = RNA_id_pointer_create(&wm->id);
  PropertyRNA *property = RNA_struct_find_property(&wm_ptr, "clarity_navigation_debug");
  return property != nullptr && RNA_property_boolean_get(&wm_ptr, property);
}

int navigation_frame_rate_limit_setting(const bContext * /*C*/)
{
  return U.viewport_fps_limit;
}

static ClarityPivotEditTarget pivot_edit_target_from_context(const bContext *C,
                                                          const ClarityWindowRuntime &runtime)
{
  /* Editing the pivot does not depend on the active tool: Clarity presents the pivot manipulator for
   * any tool, including Select, where no transform manipulator is shown. */
  UNUSED_VARS(runtime);
  const ARegion *region = CTX_wm_region(C);
  if (region == nullptr || region->regiontype != RGN_TYPE_WINDOW ||
      CTX_data_active_object(C) == nullptr)
  {
    return ClarityPivotEditTarget::None;
  }

  switch (CTX_data_mode_enum(C)) {
    case CTX_MODE_OBJECT:
      return ClarityPivotEditTarget::ObjectOrigin;
    case CTX_MODE_EDIT_MESH:
      return ClarityPivotEditTarget::ComponentPivot;
    default:
      return ClarityPivotEditTarget::None;
  }
}

static void pivot_edit_status_set(bContext *C, const ClarityPivotEditTarget target)
{
  ED_workspace_status_text(
      C,
      target == ClarityPivotEditTarget::ObjectOrigin ?
          "Edit Pivot (Object): drag the move or rotate handles; D, Insert or Esc exits" :
          "Edit Pivot (Components): drag the move or rotate handles; D, Insert or Esc exits");
}

static Vector<Object *> pivot_edit_mesh_objects_get(const bContext *C)
{
  return BKE_view_layer_array_from_objects_in_edit_mode_unique_data(
      *CTX_data_main(C), CTX_data_scene(C), CTX_data_view_layer(C), CTX_wm_view3d(C));
}

static bool pivot_component_selection_signature_get(const Scene *scene,
                                                    const Span<Object *> objects,
                                                    Object *active_object,
                                                    int &r_selection_mode,
                                                    int r_selected_counts[3],
                                                    int r_element_counts[3],
                                                    uint64_t &r_selection_hash,
                                                    const void *&r_bmesh_identity,
                                                    const void *&r_active_element,
                                                    int &r_active_element_index,
                                                    char &r_active_element_type)
{
  r_selection_mode = scene->toolsettings->selectmode;
  std::fill_n(r_selected_counts, 3, 0);
  std::fill_n(r_element_counts, 3, 0);
  r_bmesh_identity = nullptr;
  r_active_element = nullptr;
  r_active_element_index = -1;
  r_active_element_type = 0;
  r_selection_hash = 1469598103934665603ULL;
  auto hash_value = [&](const uint64_t value) {
    r_selection_hash ^= value;
    r_selection_hash *= 1099511628211ULL;
  };

  for (Object *object : objects) {
    BMEditMesh *em = BKE_editmesh_from_object(object);
    if (em == nullptr || em->bm == nullptr) {
      continue;
    }
    BMesh *bm = em->bm;
    BM_mesh_elem_index_ensure(bm, BM_VERT | BM_EDGE | BM_FACE);
    hash_value(object->id.session_uid);
    hash_value(uint64_t(bm->totvert));
    hash_value(uint64_t(bm->totedge));
    hash_value(uint64_t(bm->totface));

    r_selected_counts[0] += bm->totvertsel;
    r_selected_counts[1] += bm->totedgesel;
    r_selected_counts[2] += bm->totfacesel;
    r_element_counts[0] += bm->totvert;
    r_element_counts[1] += bm->totedge;
    r_element_counts[2] += bm->totface;

    auto hash_selected_element = [&](const auto *element, const uint64_t type) {
      hash_value((uint64_t(BM_elem_index_get(element)) << 8) ^ type);
    };
    BMVert *vert;
    BMEdge *edge;
    BMFace *face;
    BMIter iter;
    BM_ITER_MESH (vert, &iter, bm, BM_VERTS_OF_MESH) {
      if (BM_elem_flag_test(vert, BM_ELEM_SELECT)) {
        hash_selected_element(vert, BM_VERT);
      }
    }
    BM_ITER_MESH (edge, &iter, bm, BM_EDGES_OF_MESH) {
      if (BM_elem_flag_test(edge, BM_ELEM_SELECT)) {
        hash_selected_element(edge, BM_EDGE);
      }
    }
    BM_ITER_MESH (face, &iter, bm, BM_FACES_OF_MESH) {
      if (BM_elem_flag_test(face, BM_ELEM_SELECT)) {
        hash_selected_element(face, BM_FACE);
      }
    }

    if (object == active_object) {
      r_bmesh_identity = bm;
      BMEditSelection active_selection;
      if (BM_select_history_active_get(bm, &active_selection)) {
        r_active_element = active_selection.ele;
        r_active_element_index = BM_elem_index_get(active_selection.ele);
        r_active_element_type = active_selection.htype;
      }
    }
  }
  return r_selected_counts[0] != 0 || r_selected_counts[1] != 0 ||
         r_selected_counts[2] != 0;
}

static bool pivot_component_selection_changed(const ClarityCustomPivotData &custom,
                                              const int selection_mode,
                                              const int pivot_point,
                                              const int selected_counts[3],
                                              const int element_counts[3],
                                              const uint64_t selection_hash,
                                              const void *bmesh_identity,
                                              const int active_element_index,
                                              const char active_element_type)
{
  return !custom.selection_signature_valid || custom.selection_mode != selection_mode ||
         custom.pivot_point != pivot_point ||
         !std::equal(selected_counts, selected_counts + 3, custom.selected_counts) ||
         !std::equal(element_counts, element_counts + 3, custom.element_counts) ||
         custom.selection_hash != selection_hash ||
         custom.bmesh_identity != bmesh_identity ||
         custom.active_element_index != active_element_index ||
         custom.active_element_type != active_element_type;
}

static bool pivot_component_matrix_get(const Scene *scene,
                                       const Span<Object *> objects,
                                       Object *active_object,
                                       const void *active_element,
                                       const char active_element_type,
                                       const float fallback_rotation_quaternion[4],
                                       const bool fallback_orientation_valid,
                                       float r_center[3],
                                       float r_rotation_quaternion[4])
{
  zero_v3(r_center);
  float normal[3] = {};
  float tangent[3] = {};
  float bounds_min[3];
  float bounds_max[3];
  INIT_MINMAX(bounds_min, bounds_max);
  int selected_count = 0;

  for (Object *object : objects) {
    BMEditMesh *em = BKE_editmesh_from_object(object);
    if (em == nullptr || em->bm == nullptr) {
      continue;
    }
    float object_matrix[3][3];
    float normal_matrix[3][3];
    copy_m3_m4(object_matrix, object->object_to_world().ptr());
    if (invert_m3_m3(normal_matrix, object_matrix)) {
      transpose_m3(normal_matrix);
    }
    else {
      normalize_m3_m3(normal_matrix, object_matrix);
    }

    BMVert *vert;
    BMIter iter;
    BM_ITER_MESH (vert, &iter, em->bm, BM_VERTS_OF_MESH) {
      if (!BM_elem_flag_test(vert, BM_ELEM_SELECT)) {
        continue;
      }
      float world_position[3];
      copy_v3_v3(world_position, vert->co);
      mul_m4_v3(object->object_to_world().ptr(), world_position);
      add_v3_v3(r_center, world_position);
      minmax_v3v3_v3(bounds_min, bounds_max, world_position);
      selected_count++;

      if (active_element == nullptr) {
        float world_normal[3];
        copy_v3_v3(world_normal, vert->no);
        mul_m3_v3(normal_matrix, world_normal);
        if (normalize_v3(world_normal) != 0.0f) {
          add_v3_v3(normal, world_normal);
        }
      }
    }
  }
  if (selected_count == 0) {
    return false;
  }

  if (scene->toolsettings->transform_pivot_point == V3D_AROUND_CURSOR) {
    copy_v3_v3(r_center, scene->cursor.location);
  }
  else {
    if (scene->toolsettings->transform_pivot_point == V3D_AROUND_ACTIVE &&
      active_element != nullptr)
    {
      BMEditSelection active_selection{};
      active_selection.ele = static_cast<BMElem *>(const_cast<void *>(active_element));
      active_selection.htype = active_element_type;
      BM_editselection_center(&active_selection, r_center);
      mul_m4_v3(active_object->object_to_world().ptr(), r_center);
    }
    else if (scene->toolsettings->transform_pivot_point == V3D_AROUND_CENTER_BOUNDS) {
      mid_v3_v3v3(r_center, bounds_min, bounds_max);
    }
    else {
      mul_v3_fl(r_center, 1.0f / float(selected_count));
    }
  }

  if (active_element != nullptr) {
    BMEditSelection active_selection{};
    active_selection.ele = static_cast<BMElem *>(const_cast<void *>(active_element));
    active_selection.htype = active_element_type;
    BM_editselection_normal(&active_selection, normal);
    BM_editselection_plane(&active_selection, tangent);
    float active_object_matrix[3][3];
    float active_normal_matrix[3][3];
    copy_m3_m4(active_object_matrix, active_object->object_to_world().ptr());
    if (invert_m3_m3(active_normal_matrix, active_object_matrix)) {
      transpose_m3(active_normal_matrix);
    }
    else {
      normalize_m3_m3(active_normal_matrix, active_object_matrix);
    }
    mul_m3_v3(active_normal_matrix, normal);
    mul_m3_v3(active_object_matrix, tangent);
  }

  if (normalize_v3(normal) == 0.0f) {
    if (fallback_orientation_valid) {
      copy_qt_qt(r_rotation_quaternion, fallback_rotation_quaternion);
      return true;
    }

    float object_matrix[3][3];
    copy_m3_m4(object_matrix, active_object->object_to_world().ptr());
    normalize_m3(object_matrix);
    if (determinant_m3_array(object_matrix) < 0.0f) {
      negate_v3(object_matrix[0]);
    }
    if (is_zero_v3(object_matrix[0]) || is_zero_v3(object_matrix[1]) ||
        is_zero_v3(object_matrix[2]))
    {
      unit_m3(object_matrix);
    }
    mat3_to_quat(r_rotation_quaternion, object_matrix);
    return true;
  }

  if (normalize_v3(tangent) == 0.0f) {
    if (fallback_orientation_valid) {
      float fallback_orientation[3][3];
      quat_to_mat3(fallback_orientation, fallback_rotation_quaternion);
      project_plane_normalized_v3_v3v3(tangent, fallback_orientation[1], normal);
      normalize_v3(tangent);
    }
  }
  if (is_zero_v3(tangent)) {
    ortho_v3_v3(tangent, normal);
    normalize_v3(tangent);
  }

  float orientation[3][3];
  copy_v3_v3(orientation[2], normal);
  negate_v3_v3(orientation[1], tangent);
  cross_v3_v3v3(orientation[0], orientation[2], orientation[1]);
  if (normalize_v3(orientation[0]) == 0.0f) {
    ortho_basis_v3v3_v3(orientation[0], orientation[1], orientation[2]);
  }
  else {
    cross_v3_v3v3(orientation[1], orientation[2], orientation[0]);
    normalize_v3(orientation[1]);
  }
  mat3_to_quat(r_rotation_quaternion, orientation);
  return true;
}

static bool pivot_custom_sync_to_selection(const bContext *C,
                                           ClarityWindowRuntime &runtime,
                                           const bool force)
{
  ClarityCustomPivotData *custom = runtime.pivot_edit.custom.get();
  Scene *scene = CTX_data_scene(C);
  Object *object = CTX_data_active_object(C);
  if (custom == nullptr || custom->scene != scene || CTX_data_mode_enum(C) != CTX_MODE_EDIT_MESH)
  {
    return false;
  }
  if (custom->object != object) {
    if (!custom->pinned || !custom->position_valid) {
      return false;
    }
    custom->object = object;
    custom->selection_signature_valid = false;
  }

  const Vector<Object *> objects = pivot_edit_mesh_objects_get(C);
  if (objects.is_empty()) {
    return false;
  }

  int selection_mode;
  int selected_counts[3];
  int element_counts[3];
  uint64_t selection_hash;
  const void *bmesh_identity;
  const void *active_element;
  int active_element_index;
  char active_element_type;
  if (!pivot_component_selection_signature_get(scene,
                                               objects,
                                               object,
                                               selection_mode,
                                               selected_counts,
                                               element_counts,
                                               selection_hash,
                                               bmesh_identity,
                                               active_element,
                                               active_element_index,
                                               active_element_type))
  {
    return false;
  }
  if (!force && !pivot_component_selection_changed(*custom,
                                                   selection_mode,
                                                   scene->toolsettings->transform_pivot_point,
                                                   selected_counts,
                                                   element_counts,
                                                   selection_hash,
                                                   bmesh_identity,
                                                   active_element_index,
                                                   active_element_type))
  {
    return true;
  }

  if (!force && custom->pinned && custom->position_valid) {
    custom->selection_mode = selection_mode;
    custom->pivot_point = scene->toolsettings->transform_pivot_point;
    std::copy(selected_counts, selected_counts + 3, custom->selected_counts);
    std::copy(element_counts, element_counts + 3, custom->element_counts);
    custom->selection_hash = selection_hash;
    custom->bmesh_identity = bmesh_identity;
    custom->active_element_index = active_element_index;
    custom->active_element_type = active_element_type;
    custom->selection_signature_valid = true;
    return true;
  }

  if (!pivot_component_matrix_get(scene,
                                  objects,
                                  object,
                                  active_element,
                                  active_element_type,
                                  custom->rotation_quaternion,
                                  custom->orientation_valid,
                                  custom->location,
                                  custom->rotation_quaternion))
  {
    return false;
  }

  custom->selection_mode = selection_mode;
  custom->pivot_point = scene->toolsettings->transform_pivot_point;
  std::copy(selected_counts, selected_counts + 3, custom->selected_counts);
  std::copy(element_counts, element_counts + 3, custom->element_counts);
  custom->selection_hash = selection_hash;
  custom->bmesh_identity = bmesh_identity;
  custom->active_element_index = active_element_index;
  custom->active_element_type = active_element_type;
  custom->selection_signature_valid = true;
  custom->position_valid = true;
  custom->orientation_valid = true;
  return true;
}

static double4x4 clarity_parent_effect_matrix_get(const Object &object)
{
  if (object.parent == nullptr) {
    return double4x4::identity();
  }
  float parent_effect[4][4];
  BKE_object_get_parent_matrix(&object, object.parent, parent_effect);
  return double4x4(float4x4(parent_effect));
}

/* -------------------------------------------------------------------- */
/** \name Object Pivot Resolver
 *
 * Clarity keeps exactly one rotate and one scale pivot per transform node. An object using the Clarity
 * transform model stores them in its DAG channels, where they take part in the matrix composition
 * and therefore in every later rotation, and where moving the pivot is compensated by
 * `rotatePivotTranslate` / `scalePivotTranslate` so the object does not move.
 *
 * #ObjectCustomPivot is the shim for objects still using the Blender transform model, which has no
 * such channel: there the pivot is tool state until it is baked.
 *
 * Everything in the pivot tool layer goes through this resolver, so an object never ends up with
 * two competing pivots.
 * \{ */

static bool object_pivot_uses_dag_channels(const Object &object)
{
  return BKE_object_uses_clarity_transform(&object);
}

/** True when the pivot is authored away from the object origin. */
static bool object_pivot_valid(const Object &object, const bool use_scale_pivot)
{
  if (object_pivot_uses_dag_channels(object)) {
    const ClarityObjectTransform &transform = *object.clarity_transform;
    const double3 pivot(use_scale_pivot ? transform.scale_pivot : transform.rotate_pivot);
    return pivot != double3(0.0);
  }
  return BKE_object_custom_pivot_position_valid(object, use_scale_pivot);
}

static bool object_pivot_world_get(const Object &object,
                                   const bool use_scale_pivot,
                                   double3 &r_position)
{
  if (object_pivot_uses_dag_channels(object)) {
    if (!object_pivot_valid(object, use_scale_pivot)) {
      return false;
    }
    const double4x4 parent_effect = clarity_parent_effect_matrix_get(object);
    r_position = use_scale_pivot ?
                     BKE_object_clarity_scale_pivot_world_get(object, parent_effect) :
                     BKE_object_clarity_rotate_pivot_world_get(object, parent_effect);
    return true;
  }
  return BKE_object_custom_pivot_position_world_get(object, use_scale_pivot, r_position);
}

/**
 * Move the pivot to \a position. Clarity never moves the object while editing the pivot, so the DAG
 * path always compensates in the pivot translate channels.
 */
static bool object_pivot_world_set(Object &object,
                                   const bool use_scale_pivot,
                                   const double3 &position)
{
  if (object_pivot_uses_dag_channels(object)) {
    const double4x4 parent_effect = clarity_parent_effect_matrix_get(object);
    return use_scale_pivot ? BKE_object_clarity_scale_pivot_world_set(
                                 object, parent_effect, position, true) :
                             BKE_object_clarity_rotate_pivot_world_set(
                                 object, parent_effect, position, true);
  }
  return BKE_object_custom_pivot_position_world_set(object, use_scale_pivot, position);
}

/** Send both pivots back to the object origin, keeping the object in place. */
static void object_pivot_clear(Object &object)
{
  if (object_pivot_uses_dag_channels(object)) {
    ClarityObjectTransform &transform = *object.clarity_transform;
    BKE_clarity_transform_set_rotate_pivot(transform, double3(0.0), true);
    BKE_clarity_transform_set_scale_pivot(transform, double3(0.0), true);
    BKE_object_clarity_evaluated_channels_invalidate(object);
    return;
  }
  BKE_object_custom_pivot_position_clear(object, true, true);
}

/**
 * Drop the pivot channels without compensating, for baking the pivot into the transform. The
 * caller solves the target world matrix afterwards, so the pivot translates have to go as well:
 * they take part in the matrix composition.
 */
static void object_pivot_clear_baked(Object &object)
{
  if (object_pivot_uses_dag_channels(object)) {
    ClarityObjectTransform &transform = *object.clarity_transform;
    BKE_clarity_transform_set_rotate_pivot(transform, double3(0.0), false);
    BKE_clarity_transform_set_scale_pivot(transform, double3(0.0), false);
    std::fill_n(transform.rotate_pivot_translate, 3, 0.0);
    std::fill_n(transform.scale_pivot_translate, 3, 0.0);
    BKE_object_clarity_evaluated_channels_invalidate(object);
    return;
  }
  BKE_object_custom_pivot_position_clear(object, true, true);
}

/** \} */

static void manipulator_pivot_sync_from_component(ClarityWindowRuntime &runtime,
                                                  const ClarityCustomPivotData &custom)
{
  ClarityManipulatorPivotState &pivot = runtime.tool.manipulator_pivot;
  pivot.position_world = double3(custom.location);
  pivot.orientation_world = math::QuaternionBase<double>(
      double(custom.rotation_quaternion[0]),
      double(custom.rotation_quaternion[1]),
      double(custom.rotation_quaternion[2]),
      double(custom.rotation_quaternion[3]));
  pivot.position_valid = custom.position_valid;
  pivot.orientation_valid = custom.orientation_valid;
  pivot.pin_component_pivot = custom.pinned;
  pivot.last_object = custom.object != nullptr ?
                          ED_clarity_object_runtime_ref_create(*custom.object) :
                          ClarityObjectRuntimeRef{};
}

/**
 * Pick the orthonormalized solution closest to  previous. Rotating a basis by a half turn about
 * one of its own axes yields another valid basis for the same mirrored matrix, so the raw result can
 * differ by 180 degrees between two entries into the mode. Sign is normalized as well, since q and
 * -q describe the same rotation but not the same interpolation.
 */
static math::QuaternionBase<double> orientation_nearest_to_previous(
    const math::QuaternionBase<double> &orientation,
    const math::QuaternionBase<double> &previous)
{
  const math::QuaternionBase<double> half_turns[4] = {
      math::QuaternionBase<double>::identity(),
      math::QuaternionBase<double>(0.0, 1.0, 0.0, 0.0),
      math::QuaternionBase<double>(0.0, 0.0, 1.0, 0.0),
      math::QuaternionBase<double>(0.0, 0.0, 0.0, 1.0),
  };
  math::QuaternionBase<double> best = orientation;
  double best_dot = -1.0;
  for (const math::QuaternionBase<double> &half_turn : half_turns) {
    const math::QuaternionBase<double> candidate = math::normalize(orientation * half_turn);
    const double candidate_dot = std::abs(math::dot(candidate, previous));
    if (candidate_dot > best_dot) {
      best_dot = candidate_dot;
      best = candidate;
    }
  }
  /* Keep the hemisphere of the previous orientation. */
  if (math::dot(best, previous) < 0.0) {
    best = math::QuaternionBase<double>(-best.w, -best.x, -best.y, -best.z);
  }
  return best;
}

static bool manipulator_pivot_sync_from_object(ClarityWindowRuntime &runtime, Object &object)
{
  const ClarityTransformCapabilities capabilities = BKE_clarity_transform_capabilities_get(object);
  if (!capabilities.edit_pivot_position || !capabilities.edit_pivot_orientation) {
    return false;
  }

  ClarityManipulatorPivotState &pivot = runtime.tool.manipulator_pivot;
  /* The manipulator anchors on the rotate pivot, falling back to a scale-only pivot and finally to
   * the object origin. */
  double3 position_world;
  if (!object_pivot_world_get(object, false, position_world) &&
      !object_pivot_world_get(object, true, position_world))
  {
    position_world = double3(object.object_to_world().location());
  }
  pivot.position_world = position_world;
  math::QuaternionBase<double> orientation_world;
  if (!BKE_object_custom_pivot_orientation_world_get(object, orientation_world)) {
    return false;
  }
  if (pivot.previous_world_orientation_valid) {
    orientation_world = orientation_nearest_to_previous(orientation_world,
                                                        pivot.previous_world_orientation);
  }
  pivot.orientation_world = orientation_world;
  pivot.previous_world_orientation = orientation_world;
  pivot.previous_world_orientation_valid = true;
  pivot.position_valid = true;
  pivot.orientation_valid = true;
  pivot.last_object = ED_clarity_object_runtime_ref_create(object);
  return true;
}

static bool object_is_descendant_of(const Object &object, const Object &ancestor)
{
  for (const Object *parent = object.parent; parent != nullptr; parent = parent->parent) {
    if (parent == &ancestor) {
      return true;
    }
  }
  return false;
}

static std::optional<double3> object_hierarchy_bounds_center_world_get(const bContext *C,
                                                                       const Object &root)
{
  const Main *bmain = CTX_data_main(C);
  if (bmain == nullptr) {
    return std::nullopt;
  }

  double3 minimum(std::numeric_limits<double>::max());
  double3 maximum(std::numeric_limits<double>::lowest());
  bool has_bounds = false;
  for (const Object &object : bmain->objects) {
    if (&object != &root && !object_is_descendant_of(object, root)) {
      continue;
    }
    const std::optional<Bounds<float3>> bounds = BKE_object_boundbox_get(&object);
    if (!bounds) {
      continue;
    }
    for (const int x : IndexRange(2)) {
      for (const int y : IndexRange(2)) {
        for (const int z : IndexRange(2)) {
          const double3 corner = {
              x == 0 ? bounds->min.x : bounds->max.x,
              y == 0 ? bounds->min.y : bounds->max.y,
              z == 0 ? bounds->min.z : bounds->max.z,
          };
          const double3 world_corner = math::transform_point(
              double4x4(object.object_to_world()), corner);
          minimum = math::min(minimum, world_corner);
          maximum = math::max(maximum, world_corner);
          has_bounds = true;
        }
      }
    }
  }
  return has_bounds ? std::optional<double3>((minimum + maximum) * 0.5) : std::nullopt;
}

class ClarityObjectPivotEditTarget final : public ClarityPivotEditTargetBackend {
 private:
  bContext *context_;
  ClarityWindowRuntime &runtime_;
  Object &object_;
  std::optional<ObjectCustomPivot> initial_custom_pivot_;
  /** Editing the pivot of a Clarity transform writes its DAG channels, so they need a snapshot too. */
  std::optional<ClarityObjectTransform> initial_clarity_transform_;
  bool initially_had_custom_pivot_;
  ClarityManipulatorPivotState initial_pivot_;
  bool orientation_changed_ = false;

  void notify_changed()
  {
    WM_event_add_notifier(context_, NC_OBJECT | ND_TRANSFORM, &object_);
  }

 public:
  ClarityObjectPivotEditTarget(bContext *context, ClarityWindowRuntime &runtime, Object &object)
      : context_(context),
        runtime_(runtime),
        object_(object),
        initially_had_custom_pivot_(object.custom_pivot != nullptr),
        initial_pivot_(runtime.tool.manipulator_pivot)
  {
    if (object.custom_pivot != nullptr) {
      initial_custom_pivot_ = *object.custom_pivot;
    }
    if (object.clarity_transform != nullptr) {
      initial_clarity_transform_ = *object.clarity_transform;
    }
  }

  ClarityPivotTargetType type() const override
  {
    return ClarityPivotTargetType::Object;
  }

  ClarityPivotFrame frame_get() const override
  {
    const ClarityManipulatorPivotState &pivot = runtime_.tool.manipulator_pivot;
    return {pivot.position_world,
            pivot.orientation_world,
            pivot.position_valid,
            pivot.orientation_valid};
  }

  bool position_set(const double3 &position_world, const bool preserve) override
  {
    /* Editing the pivot never moves the object, so both pivots follow the manipulator. */
    UNUSED_VARS(preserve);
    if (!object_pivot_world_set(object_, false, position_world) ||
        !object_pivot_world_set(object_, true, position_world))
    {
      return false;
    }
    runtime_.tool.manipulator_pivot.position_world = position_world;
    runtime_.tool.manipulator_pivot.position_valid = true;
    runtime_.tool.manipulator_pivot.last_object = ED_clarity_object_runtime_ref_create(object_);
    /* A drag calls this once per modal update, and the transform system already publishes a redraw
     * notifier for each one, so a duplicate here would refresh the viewport, gizmos and sidebar a
     * second time per event. The one-shot paths - clicks, resets, and the restore #cancel runs from
     * `special_aftertrans_update` while the drag still counts as active - keep their notifier: it is
     * the only one carrying this object as its reference. */
    if (!runtime_.transform_active) {
      notify_changed();
    }
    return true;
  }

  bool orientation_set(const math::QuaternionBase<double> &orientation_world,
                       const bool bake) override
  {
    if (!BKE_object_custom_pivot_orientation_world_set(object_, orientation_world)) {
      return false;
    }
    runtime_.tool.manipulator_pivot.orientation_world = math::normalize(orientation_world);
    runtime_.tool.manipulator_pivot.orientation_valid = true;
    runtime_.tool.manipulator_pivot.last_object = ED_clarity_object_runtime_ref_create(object_);
    orientation_changed_ = true;
    if (bake) {
      return ED_clarity_pivot_bake(context_, CLARITY_PIVOT_BAKE_ORIENTATION);
    }
    return true;
  }

  void reset_position(const eClarityPivotResetMode mode) override
  {
    if (mode == CLARITY_PIVOT_RESET_CENTER) {
      if (const std::optional<double3> center_world =
              object_hierarchy_bounds_center_world_get(context_, object_))
      {
        position_set(*center_world, true);
      }
      return;
    }

    /* Reset Position clears both pivots, matching Edit Pivot Move which validates both. */
    object_pivot_clear(object_);
    runtime_.tool.manipulator_pivot.position_world = double3(
        object_.object_to_world().location());
    runtime_.tool.manipulator_pivot.position_valid = true;
    notify_changed();
  }

  void reset_orientation() override
  {
    BKE_object_custom_pivot_orientation_clear(object_);
    if (!BKE_object_custom_pivot_orientation_world_get(
            object_, runtime_.tool.manipulator_pivot.orientation_world))
    {
      return;
    }
    runtime_.tool.manipulator_pivot.orientation_valid = false;
    runtime_.tool.manipulator_pivot.last_object = ED_clarity_object_runtime_ref_create(object_);
    notify_changed();
  }

  void cancel() override
  {
    if (initially_had_custom_pivot_) {
      *BKE_object_custom_pivot_ensure(object_) = *initial_custom_pivot_;
    }
    else {
      BKE_object_custom_pivot_reset(object_);
    }
    if (initial_clarity_transform_ && object_.clarity_transform != nullptr) {
      *object_.clarity_transform = *initial_clarity_transform_;
      BKE_object_clarity_evaluated_channels_invalidate(object_);
    }
    runtime_.tool.manipulator_pivot = initial_pivot_;
    notify_changed();
  }

  void commit() override
  {
    if (orientation_changed_ && runtime_.tool.manipulator_pivot.bake_orientation_automatically) {
      ED_clarity_pivot_bake(context_, CLARITY_PIVOT_BAKE_ORIENTATION);
    }
  }
};

class ClarityComponentPivotEditTarget final : public ClarityPivotEditTargetBackend {
 private:
  bContext *context_;
  ClarityWindowRuntime &runtime_;
  ClarityCustomPivotData &custom_;
  ClarityCustomPivotData initial_custom_;
  ClarityManipulatorPivotState initial_pivot_;

 public:
  ClarityComponentPivotEditTarget(bContext *context,
                               ClarityWindowRuntime &runtime,
                               ClarityCustomPivotData &custom)
      : context_(context),
        runtime_(runtime),
        custom_(custom),
        initial_custom_(custom),
        initial_pivot_(runtime.tool.manipulator_pivot)
  {
  }

  ClarityPivotTargetType type() const override
  {
    return ClarityPivotTargetType::Component;
  }

  ClarityPivotFrame frame_get() const override
  {
    const ClarityManipulatorPivotState &pivot = runtime_.tool.manipulator_pivot;
    return {pivot.position_world,
            pivot.orientation_world,
            pivot.position_valid,
            pivot.orientation_valid};
  }

  bool position_set(const double3 &position_world, const bool /*preserve*/) override
  {
    runtime_.tool.manipulator_pivot.position_world = position_world;
    runtime_.tool.manipulator_pivot.position_valid = true;
    copy_v3fl_v3db(custom_.location, static_cast<const double *>(position_world));
    custom_.position_valid = true;
    return true;
  }

  bool orientation_set(const math::QuaternionBase<double> &orientation_world,
                       const bool /*bake*/) override
  {
    const math::QuaternionBase<double> normalized = math::normalize(orientation_world);
    runtime_.tool.manipulator_pivot.orientation_world = normalized;
    runtime_.tool.manipulator_pivot.orientation_valid = true;
    custom_.rotation_quaternion[0] = float(normalized.w);
    custom_.rotation_quaternion[1] = float(normalized.x);
    custom_.rotation_quaternion[2] = float(normalized.y);
    custom_.rotation_quaternion[3] = float(normalized.z);
    custom_.orientation_valid = true;
    return true;
  }

  void reset_position(const eClarityPivotResetMode mode) override
  {
    if (mode == CLARITY_PIVOT_RESET_ZERO && custom_.object != nullptr) {
      position_set(double3(custom_.object->object_to_world().location()), true);
      return;
    }
    if (pivot_custom_sync_to_selection(context_, runtime_, true)) {
      manipulator_pivot_sync_from_component(runtime_, custom_);
    }
  }

  void reset_orientation() override
  {
    const float3 position(custom_.location);
    const bool position_valid = custom_.position_valid;
    custom_.orientation_valid = false;
    if (!pivot_custom_sync_to_selection(context_, runtime_, true)) {
      return;
    }
    copy_v3_v3(custom_.location, position);
    custom_.position_valid = position_valid;
    manipulator_pivot_sync_from_component(runtime_, custom_);
  }

  void cancel() override
  {
    custom_ = initial_custom_;
    runtime_.tool.manipulator_pivot = initial_pivot_;
  }

  void commit() override {}
};

/**
 * Region-space pointer of the context window. #wmEvent::mval is only meaningful while an event is
 * being handled, so callers outside the dispatcher have to derive it from the window event state.
 */
static int2 pointer_region_position_get(const bContext *C)
{
  const wmWindow *win = CTX_wm_window(C);
  const ARegion *region = CTX_wm_region(C);
  if (win == nullptr || win->runtime == nullptr || win->runtime->eventstate == nullptr ||
      region == nullptr)
  {
    return int2(0);
  }
  return int2(win->runtime->eventstate->xy[0] - region->winrct.xmin,
              win->runtime->eventstate->xy[1] - region->winrct.ymin);
}

/**
 * Snap query behind the pivot snap preview. #clarity_pivot_click_exec runs the same query when the
 * user clicks and keeps its own copy for now, so both have to be updated together.
 *
 * \a r_result is reset first, so a miss leaves #ClarityPivotSnapTargetType::None behind.
 */
static void pivot_snap_target_query(const bContext *C,
                                    ed::transform::SnapObjectContext *snap_context,
                                    const ARegion &region,
                                    const View3D &view,
                                    const int2 &mouse_region,
                                    const double3 &previous_position,
                                    ClarityPivotSnapResult &r_result)
{
  r_result = {};
  if (snap_context == nullptr) {
    return;
  }
  ed::transform::SnapObjectParams snap_params{};
  snap_params.snap_target_select = SCE_SNAP_TARGET_ALL;
  snap_params.edit_mode_type = CTX_data_mode_enum(C) == CTX_MODE_EDIT_MESH ?
                                   ed::transform::SNAP_GEOM_EDIT :
                                   ed::transform::SNAP_GEOM_FINAL;
  snap_params.occlusion_test = ed::transform::SNAP_OCCLUSION_AS_SEEM;
  snap_params.ignore_editmode_filtering = true;

  float hit_position[3] = {};
  float hit_normal[3] = {};
  float hit_face_normal[3] = {};
  float hit_object_matrix[4][4] = {};
  int hit_index = -1;
  const Object *hit_object = nullptr;
  const float mouse_float[2] = {float(mouse_region.x), float(mouse_region.y)};
  const float previous[3] = {float(previous_position.x),
                             float(previous_position.y),
                             float(previous_position.z)};
  /* Same tolerance a drag would snap with, so the preview never promises a target the drag would
   * not take. */
  float snap_distance = ED_clarity_snap_tolerance_px_get(C, max_ii(region.winx, region.winy));
  const eSnapMode hit_type = ed::transform::snap_object_project_view3d_ex(
      snap_context,
      CTX_data_ensure_evaluated_depsgraph(C),
      &region,
      &view,
      eSnapMode(SCE_SNAP_TO_VERTEX | SCE_SNAP_TO_EDGE | SCE_SNAP_TO_FACE),
      &snap_params,
      nullptr,
      mouse_float,
      previous,
      &snap_distance,
      hit_position,
      hit_normal,
      &hit_index,
      &hit_object,
      hit_object_matrix,
      hit_face_normal);
  if (hit_type == SCE_SNAP_TO_NONE) {
    return;
  }

  r_result.position_world = double3(hit_position);
  r_result.type = hit_type & SCE_SNAP_TO_VERTEX ?
                      ClarityPivotSnapTargetType::Vertex :
                      (hit_type & SCE_SNAP_TO_EDGE ? ClarityPivotSnapTargetType::Edge :
                                                     ClarityPivotSnapTargetType::Face);
  r_result.object = const_cast<Object *>(hit_object);
  r_result.object_to_world = float4x4(hit_object_matrix);
  r_result.component_index = hit_index;
  /* The orientation a click would apply depends on its modifier keys, so the preview deliberately
   * reports only which element is under the mouse. */
}

void pivot_edit_snap_preview_clear(ClarityWindowRuntime &runtime)
{
  ClarityPivotEditState &state = runtime.pivot_edit;
  state.snap_preview = {};
  state.snap_preview_context.reset();
  state.snap_preview_mouse = int2(0);
  state.snap_preview_queried = false;
}

void pivot_edit_snap_preview_update(const bContext *C,
                                    ClarityWindowRuntime &runtime,
                                    const int2 &mouse_region)
{
  ClarityPivotEditState &state = runtime.pivot_edit;
  /* The preview exists only as feedback for the snap key the user is holding right now. A running
   * drag has no hover target either, and its snapping must not pull an extra depsgraph evaluation
   * into the modal loop. */
  if (state.target == ClarityPivotEditTarget::None || runtime.transform_active ||
      runtime.temporary.snap.is_empty())
  {
    pivot_edit_snap_preview_clear(runtime);
    return;
  }
  if (state.snap_preview_queried && state.snap_preview_mouse == mouse_region) {
    return;
  }

  ARegion *region = CTX_wm_region(C);
  const View3D *view = CTX_wm_view3d(C);
  if (region == nullptr || region->regiontype != RGN_TYPE_WINDOW || view == nullptr) {
    pivot_edit_snap_preview_clear(runtime);
    return;
  }

  const bool had_preview = state.snap_preview.type != ClarityPivotSnapTargetType::None;
  state.snap_preview_mouse = mouse_region;
  state.snap_preview_queried = true;

  std::unique_ptr<ed::transform::SnapObjectContext, ClaritySnapObjectContextDeleter>
      one_shot_context;
  ed::transform::SnapObjectContext *snap_context = nullptr;
  if (CTX_data_mode_enum(C) == CTX_MODE_EDIT_MESH) {
    /* Repeated queries with ignore_editmode_filtering are not supported by SnapObjectContext. */
    one_shot_context.reset(ed::transform::snap_object_context_create());
    snap_context = one_shot_context.get();
  }
  else {
    if (!state.snap_preview_context) {
      state.snap_preview_context.reset(ed::transform::snap_object_context_create());
    }
    snap_context = state.snap_preview_context.get();
  }
  pivot_snap_target_query(C,
                          snap_context,
                          *region,
                          *view,
                          mouse_region,
                          runtime.tool.manipulator_pivot.position_world,
                          state.snap_preview);

  /* Edge and face snap positions can move within the same component, so every valid hover update
   * needs a redraw. A miss after a hit also redraws once to remove the previous preview. */
  if (had_preview || state.snap_preview.type != ClarityPivotSnapTargetType::None) {
    ED_region_tag_redraw(region);
  }
}

void pivot_edit_end(bContext *C, ClarityWindowRuntime &runtime)
{
  manipulator_pivot_last_object_resolve(C, runtime);
  ClarityPivotEditState &state = runtime.pivot_edit;
  const ClarityPivotEditTarget ended_target = state.target;

  state.phase = ClarityPivotEditPhase::Normal;
  state.target = ClarityPivotEditTarget::None;
  state.scene = nullptr;
  state.object = nullptr;
  state.workspace = nullptr;
  state.area = nullptr;
  state.region = nullptr;
  state.tool = ClarityToolID::None;
  state.tool_revision = 0;
  state.persistent = false;
  state.exit_after_drag = false;
  state.restart_after_drag = false;
  runtime.temporary.edit_pivot = false;
  pivot_edit_snap_preview_clear(runtime);

  if (C != nullptr && ended_target != ClarityPivotEditTarget::None) {
    ED_workspace_status_text(C, nullptr);
    if (ended_target == ClarityPivotEditTarget::ObjectOrigin) {
      WM_event_add_notifier(C, NC_SCENE | ND_TOOLSETTINGS, nullptr);
    }
    ED_clarity_tool_presentation_refresh(C, runtime);
  }
}

/** Build the mode for the current context. The toggle itself is owned by the caller. */
static bool pivot_edit_begin(bContext *C, ClarityWindowRuntime &runtime)
{
  const ClarityPivotEditTarget target = pivot_edit_target_from_context(C, runtime);
  Scene *scene = CTX_data_scene(C);
  Main *bmain = CTX_data_main(C);
  Object *object = CTX_data_active_object(C);
  if (target == ClarityPivotEditTarget::None || scene == nullptr || bmain == nullptr ||
      object == nullptr)
  {
    return false;
  }

  ClarityPivotEditState &state = runtime.pivot_edit;
  if (target == ClarityPivotEditTarget::ObjectOrigin) {
    if (!BKE_id_is_editable(bmain, &object->id)) {
      return false;
    }
    /* Re-entering the mode on the same object keeps the pivot the user already edited. */
    const bool preserve_custom_manipulator =
        manipulator_pivot_last_object_resolve(C, runtime) == object &&
        (runtime.tool.manipulator_pivot.position_valid ||
         runtime.tool.manipulator_pivot.orientation_valid);
    if (preserve_custom_manipulator) {
      runtime.tool.manipulator_pivot.last_object = ED_clarity_object_runtime_ref_create(*object);
    }
    else {
      if (!manipulator_pivot_sync_from_object(runtime, *object)) {
        return false;
      }
    }
    state.data_origin_was_enabled = false;
    runtime.pivot_mode = ClarityPivotMode::Object;
  }
  else {
    const bool create_custom = !state.custom || state.custom->scene != scene ||
                               (state.custom->object != object && !state.custom->pinned);
    if (create_custom) {
      auto custom = std::make_unique<ClarityCustomPivotData>();
      custom->scene = scene;
      custom->object = object;
      state.custom = std::move(custom);
    }
    if (!pivot_custom_sync_to_selection(C, runtime, create_custom)) {
      if (create_custom) {
        state.custom.reset();
      }
      return false;
    }
    manipulator_pivot_sync_from_component(runtime, *state.custom);
    runtime.pivot_mode = ClarityPivotMode::Custom;
  }

  state.target = target;
  state.scene = scene;
  state.object = object;
  state.workspace = CTX_wm_workspace(C);
  state.area = CTX_wm_area(C);
  state.region = CTX_wm_region(C);
  state.tool = runtime.tool.active;
  state.tool_revision = runtime.tool.revision;
  state.persistent = true;
  state.exit_after_drag = false;
  state.restart_after_drag = false;
  state.phase = ClarityPivotEditPhase::PersistentPivot;
  runtime.temporary.edit_pivot = true;

  pivot_edit_status_set(C, target);
  if (target == ClarityPivotEditTarget::ObjectOrigin) {
    WM_event_add_notifier(C, NC_SCENE | ND_TOOLSETTINGS, nullptr);
  }
  ED_clarity_tool_presentation_refresh(C, runtime);
  return true;
}

bool pivot_edit_resume_persistent(bContext *C, ClarityWindowRuntime &runtime)
{
  if (pivot_edit_begin(C, runtime)) {
    return true;
  }

  /* The toggle stays on even while the current area, mode, or object cannot host a pivot
   * manipulator. Validation retries the request when a supported context becomes active. */
  runtime.pivot_edit.persistent = true;
  runtime.pivot_edit.phase = ClarityPivotEditPhase::PersistentPivot;
  return true;
}

bool pivot_edit_toggle_persistent(bContext *C, ClarityWindowRuntime &runtime)
{
  ClarityPivotEditState &state = runtime.pivot_edit;
  if (!state.persistent) {
    return pivot_edit_resume_persistent(C, runtime);
  }

  /* Turning the toggle off. A pivot drag in progress keeps its manipulator until it finishes. */
  state.persistent = false;
  if (runtime.transform_active && state.target != ClarityPivotEditTarget::None) {
    state.exit_after_drag = true;
    state.phase = ClarityPivotEditPhase::PivotCommitPending;
    return true;
  }
  pivot_edit_end(C, runtime);
  return true;
}

void pivot_edit_tool_changed(bContext *C, ClarityWindowRuntime &runtime)
{
  ClarityPivotEditState &state = runtime.pivot_edit;
  state.tool = runtime.tool.active;
  state.tool_revision = runtime.tool.revision;
  if (C != nullptr && state.target != ClarityPivotEditTarget::None) {
    /* The target and authored frame do not depend on the active tool. Reusing them avoids the
     * end/begin pair (and its two full presentation refreshes) while the gizmo changes layout. */
    ED_clarity_tool_presentation_refresh(C, runtime);
  }
}

bool pivot_edit_pin_toggle(bContext *C, ClarityWindowRuntime &runtime)
{
  Scene *scene = CTX_data_scene(C);
  Object *object = CTX_data_active_object(C);
  if (scene == nullptr || object == nullptr || CTX_data_mode_enum(C) != CTX_MODE_EDIT_MESH) {
    return false;
  }

  ClarityPivotEditState &state = runtime.pivot_edit;
  const bool create_custom = !state.custom || state.custom->scene != scene ||
                             (state.custom->object != object && !state.custom->pinned);
  if (create_custom) {
    auto custom = std::make_unique<ClarityCustomPivotData>();
    custom->scene = scene;
    custom->object = object;
    state.custom = std::move(custom);
  }
  if (!pivot_custom_sync_to_selection(C, runtime, create_custom)) {
    if (create_custom) {
      state.custom.reset();
    }
    return false;
  }

  pivot_undo_step_begin(C, runtime);
  state.custom->pinned = !state.custom->pinned;
  runtime.tool.manipulator_pivot.pin_component_pivot = state.custom->pinned;
  if (!state.custom->pinned) {
    state.custom->position_valid = false;
    state.custom->orientation_valid = false;
    state.custom->selection_signature_valid = false;
    if (!pivot_custom_sync_to_selection(C, runtime, true)) {
      state.custom.reset();
      runtime.tool.manipulator_pivot.position_valid = false;
      runtime.tool.manipulator_pivot.orientation_valid = false;
    }
  }
  if (state.custom) {
    manipulator_pivot_sync_from_component(runtime, *state.custom);
  }
  ED_clarity_tool_presentation_refresh(C, runtime);
  return true;
}

ClarityDispatchResult pivot_edit_click_handle_action(bContext *C,
                                                   ClarityWindowRuntime &runtime,
                                                   const ClarityInputAction &action)
{
  if (runtime.pivot_edit.target == ClarityPivotEditTarget::None ||
      !ELEM(action.id,
            ClarityActionID::SelectPrimary,
            ClarityActionID::SelectAdd,
            ClarityActionID::SelectRemove,
            ClarityActionID::SelectToggle))
  {
    return ClarityDispatchResult::PassThrough;
  }

  wmOperatorType *operator_type = WM_operatortype_find("TRANSFORM_OT_clarity_pivot_click", true);
  if (operator_type == nullptr) {
    return ClarityDispatchResult::PassThrough;
  }
  PointerRNA properties = WM_operator_properties_create_ptr(operator_type);
  const int mouse[2] = {action.mouse_region.x, action.mouse_region.y};
  RNA_int_set_array(&properties, "mouse", mouse);
  RNA_boolean_set(&properties, "shift", action.shift);
  RNA_boolean_set(&properties, "ctrl", action.ctrl);
  WM_operator_name_call_ptr(
      C, operator_type, wm::OpCallContext::ExecDefault, &properties, action.source_event);
  WM_operator_properties_free(&properties);
  return ClarityDispatchResult::Handled;
}

void pivot_edit_selection_changed(bContext *C, ClarityWindowRuntime &runtime)
{
  ClarityCustomPivotData *custom = runtime.pivot_edit.custom.get();
  if (custom == nullptr || custom->scene != CTX_data_scene(C)) {
    return;
  }
  if (pivot_custom_sync_to_selection(C, runtime, false)) {
    manipulator_pivot_sync_from_component(runtime, *custom);
  }
  else if (!custom->pinned) {
    custom->position_valid = false;
    custom->orientation_valid = false;
    runtime.tool.manipulator_pivot.position_valid = false;
    runtime.tool.manipulator_pivot.orientation_valid = false;
  }
}

/**
 * Mirror the UI reads. Written from one place only, so it can never disagree with the held keys.
 */
void tool_mirror_sync(const bContext *C, const ClarityToolID tool)
{
  const wmWindowManager *wm = CTX_wm_manager(C);
  if (wm != nullptr && wm->runtime != nullptr) {
    wm->runtime->clarity_tool = uint8_t(tool);
  }
}

void snap_override_mirror_sync(const bContext *C, const ClarityWindowRuntime &runtime)
{
  const wmWindowManager *wm = CTX_wm_manager(C);
  if (wm != nullptr && wm->runtime != nullptr) {
    wm->runtime->clarity_snap_temporary_mode = uint8_t(runtime.temporary.snap.active());
  }
}

/**
 * Leaving or re-entering the Clarity preset bumps the interaction revision. A key held across that
 * boundary will never deliver its release to us, so the override starts from empty.
 */
void snap_override_revision_reconcile(const bContext *C, ClarityWindowRuntime &runtime)
{
  const wmWindowManager *wm = CTX_wm_manager(C);
  if (wm == nullptr || wm->runtime == nullptr ||
      runtime.interaction_revision_seen == wm->runtime->clarity_interaction_revision)
  {
    return;
  }
  runtime.interaction_revision_seen = wm->runtime->clarity_interaction_revision;
  runtime.temporary.snap.clear();
  snap_override_mirror_sync(C, runtime);
}

float snap_tolerance_radius_px(const ClaritySnapToleranceSettings &settings,
                               const int region_size_px,
                               const float pixel_size)
{
  if (!settings.limited) {
    /* Clarity's unlimited region: everything the view shows is a candidate. */
    return float(max_ii(region_size_px, 1));
  }
  return float(max_ii(settings.size_px, 1)) * (pixel_size > 0.0f ? pixel_size : 1.0f);
}

/**
 * The one non-modifier key the window reports as held, #EVENT_NONE when none is. Updated while the
 * event is queued, so it is truthful no matter which handler ends up consuming the event.
 */
static wmEventType window_tracked_key_get(const bContext *C)
{
  const wmWindow *win = CTX_wm_window(C);
  const wmEvent *event_state = win != nullptr && win->runtime != nullptr ?
                                   win->runtime->eventstate :
                                   nullptr;
  return event_state != nullptr ? event_state->keymodifier : EVENT_NONE;
}

/**
 * Drop the held keys the window no longer tracks as down.
 *
 * A release only reaches the dispatcher when nothing else consumed the event first, so a modal
 * operator, a popup or a menu can swallow the one release a momentary mode depends on and leave it
 * on for good — snapping every later transform to the step grid. The window tracks whether any
 * non-modifier key is currently down, and no snap key can be held while that says none is.
 */
void snap_override_key_state_reconcile(const bContext *C, ClarityWindowRuntime &runtime)
{
  if (runtime.temporary.snap.is_empty() ||
      window_tracked_key_get(C) != EVENT_NONE ||
      !runtime.temporary.snap.release_window_tracked_keys())
  {
    return;
  }
  snap_override_mirror_sync(C, runtime);
  if (runtime.temporary.snap.is_empty()) {
    pivot_edit_snap_preview_clear(runtime);
  }
  WM_event_add_notifier(C, NC_SPACE | ND_SPACE_VIEW3D, nullptr);
}

void pivot_edit_input_reset(bContext *C, ClarityWindowRuntime &runtime)
{
  runtime.temporary.snap.clear();
  snap_override_mirror_sync(C, runtime);
  /* The snap keys are considered released, so the hovered target they previewed is gone too. */
  pivot_edit_snap_preview_clear(runtime);

  /* Losing focus must not turn the toggle off: like in Clarity, Edit Pivot survives leaving and
   * re-entering the window. Only the transient input overlays are dropped, and a drag that was
   * interrupted rebuilds its manipulator once the transform finishes. */
  ClarityPivotEditState &state = runtime.pivot_edit;
  if (state.persistent && runtime.transform_active &&
      state.target != ClarityPivotEditTarget::None)
  {
    state.restart_after_drag = true;
    state.phase = ClarityPivotEditPhase::PivotCommitPending;
  }
}

void pivot_edit_validate(bContext *C, ClarityWindowRuntime &runtime)
{
  ClarityPivotEditState &state = runtime.pivot_edit;
  if (state.target == ClarityPivotEditTarget::None) {
    if (state.persistent) {
      pivot_edit_resume_persistent(C, runtime);
    }
    return;
  }

  manipulator_pivot_last_object_resolve(C, runtime);
  if (state.target == ClarityPivotEditTarget::None) {
    if (state.persistent) {
      pivot_edit_resume_persistent(C, runtime);
    }
    return;
  }
  const bool context_changed =
      state.scene != CTX_data_scene(C) ||
      state.target != pivot_edit_target_from_context(C, runtime) ||
      state.object != CTX_data_active_object(C) ||
      state.workspace != CTX_wm_workspace(C) || state.area != CTX_wm_area(C) ||
      state.region != CTX_wm_region(C) ||
      state.tool_revision != runtime.tool.revision;
  if (context_changed) {
    if (runtime.transform_active) {
      state.restart_after_drag = true;
      state.phase = ClarityPivotEditPhase::PivotCommitPending;
      return;
    }

    const bool resume = state.persistent;
    pivot_edit_end(C, runtime);
    if (resume) {
      pivot_edit_resume_persistent(C, runtime);
    }
  }
}

static ClarityNavigationSession *navigation_debug_session_get(const bContext *C)
{
  ClarityWindowRuntime *runtime = runtime_get(C);
  if (runtime == nullptr || !runtime->navigation_active()) {
    return nullptr;
  }
  ClarityNavigationSession *session = static_cast<ClarityNavigationSession *>(
      runtime->active_session.get());
  return session->debug_enabled() ? session : nullptr;
}

}  // namespace blender::ed::clarity

namespace blender {

ed::clarity::ClarityObjectRuntimeRef ED_clarity_object_runtime_ref_create(const Object &object)
{
  ID &id = const_cast<ID &>(object.id);
  BKE_lib_libblock_session_uid_ensure(&id);
  ed::clarity::ClarityObjectRuntimeRef reference;
  reference.session_uid = id.session_uid;
  STRNCPY(reference.id_name, id.name);
  return reference;
}

Object *ED_clarity_object_runtime_ref_resolve(
    Main &bmain, const ed::clarity::ClarityObjectRuntimeRef &reference)
{
  if (reference.session_uid == 0) {
    return nullptr;
  }
  ID *id = BKE_libblock_find_session_uid(&bmain, ID_OB, reference.session_uid);
  return id != nullptr ? id_cast<Object *>(id) : nullptr;
}

int ED_clarity_interaction_frame_rate_limit(const bContext *C)
{
  ed::clarity::ClarityWindowRuntime *runtime = ed::clarity::runtime_get(C);
  if ((runtime != nullptr && runtime->transform_active) || G.moving != 0) {
    return ed::clarity::navigation_frame_rate_limit_setting(C);
  }

  if (runtime == nullptr || !runtime->navigation_active()) {
    return 0;
  }
  const ed::clarity::ClarityNavigationSession *session =
      static_cast<const ed::clarity::ClarityNavigationSession *>(runtime->active_session.get());
  return session->frame_rate_limit();
}

bool ED_clarity_navigation_debug_active(const bContext *C)
{
  const ed::clarity::ClarityWindowRuntime *runtime = ed::clarity::runtime_get(C);
  return ed::clarity::navigation_debug_session_get(C) != nullptr ||
         (runtime != nullptr && runtime->transform_debug != nullptr);
}

ed::clarity::ClarityPivotEditTarget ED_clarity_pivot_edit_target_get(const bContext *C)
{
  const ed::clarity::ClarityWindowRuntime *runtime = ed::clarity::runtime_get(C);
  return runtime != nullptr ? runtime->pivot_edit.target :
                              ed::clarity::ClarityPivotEditTarget::None;
}

namespace ed::clarity {

/**
 * The custom pivot must not silently take over every Blender pivot mode. Individual Custom Pivots
 * are not implemented, so a selection asking for per-element centers keeps the standard Blender
 * behavior.
 */
static bool pivot_custom_override_allowed(const bContext *C)
{
  if (!ED_clarity_interaction_enabled(C)) {
    return false;
  }
  const Scene *scene = CTX_data_scene(C);
  if (scene != nullptr && scene->toolsettings != nullptr &&
      scene->toolsettings->transform_pivot_point == V3D_AROUND_LOCAL_ORIGINS)
  {
    return false;
  }
  return true;
}

/** Resolve which of the two independent pivots the caller asks for. */
static bool pivot_usage_is_scale(const ClarityWindowRuntime *runtime, const ClarityPivotUsage usage)
{
  switch (usage) {
    case ClarityPivotUsage::Rotate:
      return false;
    case ClarityPivotUsage::Scale:
      return true;
    case ClarityPivotUsage::Display:
      return runtime != nullptr && runtime->tool.active == ClarityToolID::Scale;
  }
  return false;
}

/** The object whose custom pivot may override the transform center, or null. */
static Object *pivot_custom_object_get(const bContext *C,
                                       const ClarityWindowRuntime *runtime,
                                       bool &r_object_pivot_edit)
{
  r_object_pivot_edit = runtime != nullptr &&
                        runtime->pivot_edit.target == ClarityPivotEditTarget::ObjectOrigin;
  return r_object_pivot_edit ? runtime->pivot_edit.object : CTX_data_active_object(C);
}

/**
 * Selection cannot change while a modal transform owns the region. Its component pivot was synced
 * during transform initialization, so rescanning and hashing every mesh element from every gizmo
 * refresh only repeats work and can dominate a dense edit-mesh drag.
 */
static bool pivot_custom_prepare_for_read(const bContext *C, ClarityWindowRuntime &runtime)
{
  if (runtime.transform_active) {
    const ClarityCustomPivotData *custom = runtime.pivot_edit.custom.get();
    if (custom != nullptr && custom->selection_signature_valid &&
        CTX_data_mode_enum(C) == CTX_MODE_EDIT_MESH && custom->scene == CTX_data_scene(C) &&
        custom->object == CTX_data_active_object(C))
    {
      return true;
    }
  }
  return pivot_custom_sync_to_selection(C, runtime, false);
}

}  // namespace ed::clarity

bool ED_clarity_pivot_custom_matrix_get(const bContext *C,
                                     const ed::clarity::ClarityPivotUsage usage,
                                     float r_matrix[4][4])
{
  ed::clarity::ClarityWindowRuntime *runtime = ed::clarity::runtime_get(C);
  if (!ed::clarity::pivot_custom_override_allowed(C)) {
    return false;
  }
  bool object_pivot_edit;
  Object *object = ed::clarity::pivot_custom_object_get(C, runtime, object_pivot_edit);
  const bool use_scale_pivot = ed::clarity::pivot_usage_is_scale(runtime, usage);
  if (CTX_data_mode_enum(C) == CTX_MODE_OBJECT && object != nullptr &&
      (object_pivot_edit || ed::clarity::object_pivot_valid(*object, use_scale_pivot)))
  {
    double3 position_world;
    if (!ed::clarity::object_pivot_world_get(*object, use_scale_pivot, position_world)) {
      /* Edit Pivot always edits the custom pivot, starting from the object origin. */
      if (!object_pivot_edit) {
        return false;
      }
      position_world = double3(object->object_to_world().location());
    }
    math::QuaternionBase<double> orientation_world;
    if (!BKE_object_custom_pivot_orientation_world_get(*object, orientation_world)) {
      return false;
    }
    const float orientation[4] = {float(orientation_world.w),
                                  float(orientation_world.x),
                                  float(orientation_world.y),
                                  float(orientation_world.z)};
    quat_to_mat4(r_matrix, orientation);
    copy_v3fl_v3db(r_matrix[3], static_cast<const double *>(position_world));
    return true;
  }
  if (runtime == nullptr) {
    return false;
  }
  if (!ed::clarity::pivot_custom_prepare_for_read(C, *runtime)) {
    return false;
  }
  const ed::clarity::ClarityCustomPivotData *custom =
      runtime->pivot_edit.custom ? runtime->pivot_edit.custom.get() : nullptr;
  if (custom == nullptr || !custom->position_valid) {
    return false;
  }
  quat_to_mat4(r_matrix, custom->rotation_quaternion);
  copy_v3_v3(r_matrix[3], custom->location);
  return true;
}

bool ED_clarity_pivot_custom_orientation_get(const bContext *C, float r_orientation[3][3])
{
  ed::clarity::ClarityWindowRuntime *runtime = ed::clarity::runtime_get(C);
  if (!ed::clarity::pivot_custom_override_allowed(C)) {
    return false;
  }
  bool object_pivot_edit;
  Object *object = ed::clarity::pivot_custom_object_get(C, runtime, object_pivot_edit);
  if (CTX_data_mode_enum(C) == CTX_MODE_OBJECT && object != nullptr &&
      (object_pivot_edit || BKE_object_custom_pivot_orientation_valid(*object)))
  {
    math::QuaternionBase<double> orientation_world;
    if (!BKE_object_custom_pivot_orientation_world_get(*object, orientation_world)) {
      return false;
    }
    const float orientation[4] = {float(orientation_world.w),
                                  float(orientation_world.x),
                                  float(orientation_world.y),
                                  float(orientation_world.z)};
    quat_to_mat3(r_orientation, orientation);
    return true;
  }
  if (runtime == nullptr || !ed::clarity::pivot_custom_prepare_for_read(C, *runtime)) {
    return false;
  }
  const ed::clarity::ClarityCustomPivotData *custom =
      runtime->pivot_edit.custom ? runtime->pivot_edit.custom.get() : nullptr;
  if (custom == nullptr || !custom->orientation_valid) {
    return false;
  }
  quat_to_mat3(r_orientation, custom->rotation_quaternion);
  return true;
}

bool ED_clarity_pivot_edit_data_get(const bContext *C,
                                 float **r_location,
                                 float **r_rotation_quaternion)
{
  ed::clarity::ClarityWindowRuntime *runtime = ed::clarity::runtime_get(C);
  if (runtime == nullptr || !ed::clarity::pivot_custom_prepare_for_read(C, *runtime)) {
    return false;
  }
  ed::clarity::ClarityCustomPivotData *custom =
      runtime->pivot_edit.custom ? runtime->pivot_edit.custom.get() : nullptr;
  if (custom == nullptr ||
      runtime->pivot_edit.target != ed::clarity::ClarityPivotEditTarget::ComponentPivot ||
      custom->scene != CTX_data_scene(C) || custom->object != CTX_data_active_object(C))
  {
    return false;
  }

  *r_location = custom->location;
  *r_rotation_quaternion = custom->rotation_quaternion;
  return true;
}

std::unique_ptr<ed::clarity::ClarityPivotEditTargetBackend> ED_clarity_pivot_edit_target_create(
    bContext *C)
{
  ed::clarity::ClarityWindowRuntime *runtime = ed::clarity::runtime_get(C);
  if (runtime == nullptr) {
    return nullptr;
  }

  const bool use_active_object = runtime->pivot_edit.target == ed::clarity::ClarityPivotEditTarget::None &&
                                 CTX_data_mode_enum(C) == CTX_MODE_OBJECT;
  if (runtime->pivot_edit.target == ed::clarity::ClarityPivotEditTarget::ObjectOrigin ||
      use_active_object)
  {
    Object *object = use_active_object ? CTX_data_active_object(C) :
                                        runtime->pivot_edit.object;
    Main *bmain = CTX_data_main(C);
    const ClarityTransformCapabilities capabilities = object != nullptr ?
                                                       BKE_clarity_transform_capabilities_get(*object) :
                                                       ClarityTransformCapabilities{};
    if (object == nullptr || bmain == nullptr || !BKE_id_is_editable(bmain, &object->id) ||
        !capabilities.edit_pivot_position || !capabilities.edit_pivot_orientation)
    {
      return nullptr;
    }
    if (use_active_object ||
        ed::clarity::manipulator_pivot_last_object_resolve(C, *runtime) != object)
    {
      if (!ed::clarity::manipulator_pivot_sync_from_object(*runtime, *object)) {
        return nullptr;
      }
    }
    return std::make_unique<ed::clarity::ClarityObjectPivotEditTarget>(C, *runtime, *object);
  }

  if (runtime->pivot_edit.target == ed::clarity::ClarityPivotEditTarget::ComponentPivot &&
      ed::clarity::pivot_custom_sync_to_selection(C, *runtime, false) &&
      runtime->pivot_edit.custom)
  {
    ed::clarity::manipulator_pivot_sync_from_component(*runtime, *runtime->pivot_edit.custom);
    return std::make_unique<ed::clarity::ClarityComponentPivotEditTarget>(
        C, *runtime, *runtime->pivot_edit.custom);
  }
  return nullptr;
}

void ED_clarity_pivot_reset_position(bContext *C, const ed::clarity::eClarityPivotResetMode mode)
{
  if (std::unique_ptr<ed::clarity::ClarityPivotEditTargetBackend> target =
          ED_clarity_pivot_edit_target_create(C))
  {
    target->reset_position(mode);
    target->commit();
  }
}

void ED_clarity_pivot_reset_orientation(bContext *C)
{
  if (std::unique_ptr<ed::clarity::ClarityPivotEditTargetBackend> target =
          ED_clarity_pivot_edit_target_create(C))
  {
    target->reset_orientation();
    target->commit();
  }
}

void ED_clarity_pivot_reset_all(bContext *C, const ed::clarity::eClarityPivotResetMode mode)
{
  if (std::unique_ptr<ed::clarity::ClarityPivotEditTargetBackend> target =
          ED_clarity_pivot_edit_target_create(C))
  {
    target->reset_position(mode);
    target->reset_orientation();
    target->commit();
  }
}

void ED_clarity_pivot_undo_begin(const bContext *C)
{
  if (ed::clarity::ClarityWindowRuntime *runtime = ed::clarity::runtime_ensure(C)) {
    ed::clarity::pivot_undo_step_begin(C, *runtime);
  }
}

bool ED_clarity_pivot_manipulator_state_get(const bContext *C, ed::clarity::ClarityPivotFrame &r_frame)
{
  const ed::clarity::ClarityWindowRuntime *runtime = ed::clarity::runtime_get(C);
  if (runtime == nullptr) {
    return false;
  }
  const ed::clarity::ClarityManipulatorPivotState &pivot = runtime->tool.manipulator_pivot;
  r_frame.position_world = pivot.position_world;
  r_frame.orientation_world = pivot.orientation_world;
  r_frame.position_valid = pivot.position_valid;
  r_frame.orientation_valid = pivot.orientation_valid;
  return true;
}

bool ED_clarity_pivot_snap_preview_get(const bContext *C,
                                    ed::clarity::ClarityPivotSnapResult &r_result)
{
  const ed::clarity::ClarityWindowRuntime *runtime = ed::clarity::runtime_get(C);
  if (runtime == nullptr ||
      runtime->pivot_edit.snap_preview.type == ed::clarity::ClarityPivotSnapTargetType::None)
  {
    return false;
  }
  r_result = runtime->pivot_edit.snap_preview;
  return true;
}

bool ED_clarity_pivot_tool_settings_get(const bContext *C,
                                     ed::clarity::ClarityPivotToolSettings &r_settings)
{
  const ed::clarity::ClarityWindowRuntime *runtime = ed::clarity::runtime_get(C);
  if (runtime == nullptr) {
    return false;
  }
  const ed::clarity::ClarityManipulatorPivotState &pivot = runtime->tool.manipulator_pivot;
  r_settings.pin_component_pivot = pivot.pin_component_pivot;
  r_settings.snap_position = pivot.snap_position;
  r_settings.snap_orientation = pivot.snap_orientation;
  r_settings.bake_orientation_automatically = pivot.bake_orientation_automatically;
  r_settings.preserve_children = pivot.preserve_children;
  r_settings.show_orientation_handle = pivot.show_orientation_handle;
  r_settings.reset_mode = pivot.reset_mode;
  r_settings.active_axis = pivot.active_axis;
  return true;
}

bool ED_clarity_pivot_tool_settings_set(const bContext *C,
                                     const ed::clarity::ClarityPivotToolSettings &settings)
{
  ed::clarity::ClarityWindowRuntime *runtime = ed::clarity::runtime_ensure(C);
  if (runtime == nullptr) {
    return false;
  }
  ed::clarity::ClarityManipulatorPivotState &pivot = runtime->tool.manipulator_pivot;
  pivot.snap_position = settings.snap_position;
  pivot.snap_orientation = settings.snap_orientation;
  pivot.bake_orientation_automatically = settings.bake_orientation_automatically;
  pivot.preserve_children = settings.preserve_children;
  pivot.show_orientation_handle = settings.show_orientation_handle;
  pivot.reset_mode = settings.reset_mode;
  WM_event_add_notifier(C, NC_SPACE | ND_SPACE_VIEW3D, nullptr);
  return true;
}

void ED_clarity_pivot_active_axis_set(const bContext *C, const int active_axis)
{
  if (ed::clarity::ClarityWindowRuntime *runtime = ed::clarity::runtime_get(C)) {
    runtime->tool.manipulator_pivot.active_axis = clamp_i(active_axis, 0, 2);
  }
}

static bool clarity_pivot_bake_children_supported(const Main &bmain, const Object &parent)
{
  for (const Object &object : bmain.objects) {
    if (object.parent == &parent &&
        (object.constraints.first != nullptr || object.clarity_constraints.first != nullptr))
    {
      return false;
    }
  }
  return true;
}

struct ClarityPivotChildBakeState {
  Object *object;
  double4x4 world_matrix;
};

static bool clarity_pivot_preserve_direct_children(Depsgraph *depsgraph,
                                                Scene *scene,
                                                Object &parent,
                                                const Vector<ClarityPivotChildBakeState>
                                                    &child_states)
{
  BKE_object_where_is_calc(depsgraph, scene, &parent);
  ClarityTransformSetOptions options;
  for (const ClarityPivotChildBakeState &child_state : child_states) {
    if (BKE_object_uses_clarity_transform(child_state.object)) {
      Object &child = *child_state.object;
      if (!BKE_object_clarity_set_world_matrix(child,
                                            ed::clarity::clarity_parent_effect_matrix_get(child),
                                            child_state.world_matrix,
                                            options))
      {
        return false;
      }
      BKE_object_where_is_calc(depsgraph, scene, &child);
      DEG_id_tag_update(&child.id, ID_RECALC_TRANSFORM);
    }
  }
  for (const ClarityPivotChildBakeState &child_state : child_states) {
    if (!BKE_object_uses_clarity_transform(child_state.object)) {
      Object &child = *child_state.object;
      BKE_object_apply_mat4(&child, float4x4(child_state.world_matrix).ptr(), true, true);
      BKE_object_where_is_calc(depsgraph, scene, &child);
      DEG_id_tag_update(&child.id, ID_RECALC_TRANSFORM);
    }
  }
  return true;
}

bool ED_clarity_pivot_bake(bContext *C, const ed::clarity::eClarityPivotBakeMode mode)
{
  ed::clarity::ClarityWindowRuntime *runtime = ed::clarity::runtime_get(C);
  Object *object = CTX_data_active_object(C);
  Main *bmain = CTX_data_main(C);
  Scene *scene = CTX_data_scene(C);
  if (runtime == nullptr || object == nullptr || bmain == nullptr || scene == nullptr ||
      !BKE_id_is_editable(bmain, &object->id) ||
      CTX_data_mode_enum(C) != CTX_MODE_OBJECT ||
      object->constraints.first != nullptr || object->clarity_constraints.first != nullptr)
  {
    return false;
  }

  const bool bake_position = ELEM(
      mode, ed::clarity::CLARITY_PIVOT_BAKE_POSITION, ed::clarity::CLARITY_PIVOT_BAKE_BOTH);
  const bool bake_orientation = ELEM(
      mode, ed::clarity::CLARITY_PIVOT_BAKE_ORIENTATION, ed::clarity::CLARITY_PIVOT_BAKE_BOTH);
  const ClarityTransformCapabilities capabilities = BKE_clarity_transform_capabilities_get(*object);
  if ((bake_position && !capabilities.bake_position) ||
      (bake_orientation && !capabilities.bake_orientation) ||
      (runtime->tool.manipulator_pivot.preserve_children &&
       !capabilities.preserve_children))
  {
    return false;
  }
  if (capabilities.geometry_compensation && object->data != nullptr &&
      ID_REAL_USERS(static_cast<ID *>(object->data)) > 1)
  {
    return false;
  }
  if (runtime->tool.manipulator_pivot.preserve_children &&
      !clarity_pivot_bake_children_supported(*bmain, *object))
  {
    return false;
  }
  ed::clarity::ClarityManipulatorPivotState pivot_before = runtime->tool.manipulator_pivot;
  /* Baking the position moves the object origin onto the rotate pivot. */
  pivot_before.position_valid = ed::clarity::object_pivot_valid(*object, false);
  pivot_before.orientation_valid = BKE_object_custom_pivot_orientation_valid(*object);
  if ((bake_position &&
       (!pivot_before.position_valid ||
        !ed::clarity::object_pivot_world_get(*object, false, pivot_before.position_world))) ||
      (bake_orientation &&
       (!pivot_before.orientation_valid ||
        !BKE_object_custom_pivot_orientation_world_get(
            *object, pivot_before.orientation_world))))
  {
    return false;
  }

  Depsgraph *depsgraph = CTX_data_ensure_evaluated_depsgraph(C);
  ed::clarity::ClarityTransformTransaction transaction(depsgraph, scene);
  if (!transaction.capture_object(*object) ||
      !transaction.capture_runtime(runtime->tool.manipulator_pivot))
  {
    return false;
  }
  if (capabilities.geometry_compensation && object->data != nullptr &&
      !transaction.capture_geometry(*static_cast<ID *>(object->data)))
  {
    return false;
  }

  const double4x4 world_before(object->object_to_world());
  double4x4 target_world = world_before;
  if (bake_position) {
    target_world.location() = pivot_before.position_world;
  }
  if (bake_orientation) {
    float current_rotation_float[3][3];
    if (!BKE_clarity_matrix_orthonormalize(double3x3(world_before), current_rotation_float)) {
      return false;
    }
    const double3x3 current_rotation{float3x3(current_rotation_float)};
    const double3x3 residual = math::transpose(current_rotation) * double3x3(world_before);
    const double3x3 desired_rotation = math::from_rotation<double3x3>(
        pivot_before.orientation_world);
    const double3x3 target_linear = desired_rotation * residual;
    for (const int column : IndexRange(3)) {
      for (const int row : IndexRange(3)) {
        target_world[column][row] = target_linear[column][row];
      }
    }
  }

  Vector<ClarityPivotChildBakeState> child_states;
  if (runtime->tool.manipulator_pivot.preserve_children) {
    for (Object &child : bmain->objects) {
      if (child.parent == object) {
        if (!transaction.capture_child(child)) {
          return false;
        }
        child_states.append({&child, double4x4(child.object_to_world())});
      }
    }
  }

  /* Drop the pivot channels before solving the target matrix. They take part in the composition of
   * a Clarity transform, so clearing them afterwards would displace the object. */
  if (bake_position) {
    ed::clarity::object_pivot_clear_baked(*object);
  }

  if (BKE_object_uses_clarity_transform(object)) {
    ClarityTransformSetOptions options;
    if (!BKE_object_clarity_set_world_matrix(
            *object, ed::clarity::clarity_parent_effect_matrix_get(*object), target_world, options))
    {
      return false;
    }
  }
  else {
    BKE_object_apply_mat4(object, float4x4(target_world).ptr(), true, true);
  }
  BKE_object_where_is_calc(depsgraph, scene, object);

  const double4x4 world_after(object->object_to_world());
  bool inverse_success;
  const double4x4 world_after_inverse = math::invert(world_after, inverse_success);
  if (!inverse_success) {
    return false;
  }
  if (capabilities.geometry_compensation && object->data != nullptr &&
      !transaction.transform_geometry(*static_cast<ID *>(object->data),
                                      float4x4(world_after_inverse * world_before)))
  {
    return false;
  }

  if (!child_states.is_empty() &&
      !clarity_pivot_preserve_direct_children(depsgraph, scene, *object, child_states))
  {
    return false;
  }

  DEG_id_tag_update(&object->id, ID_RECALC_TRANSFORM | ID_RECALC_GEOMETRY);
  if (bake_orientation) {
    BKE_object_custom_pivot_orientation_clear(*object);
  }
  if (bake_position) {
    runtime->tool.manipulator_pivot.position_world = double3(
        object->object_to_world().location());
    runtime->tool.manipulator_pivot.position_valid = false;
  }
  if (bake_orientation) {
    BKE_object_custom_pivot_orientation_world_get(
        *object, runtime->tool.manipulator_pivot.orientation_world);
    runtime->tool.manipulator_pivot.orientation_valid = false;
  }
  runtime->tool.manipulator_pivot.last_object = ED_clarity_object_runtime_ref_create(*object);
  transaction.commit();
  WM_event_add_notifier(C, NC_OBJECT | ND_TRANSFORM, object);
  WM_event_add_notifier(C, NC_GEOM | ND_DATA, object->data);
  return true;
}

bool ED_clarity_pivot_orientation_aim(ed::clarity::ClarityPivotFrame &frame,
                                   const double3 &target_world,
                                   const int active_axis,
                                   const double3 &view_up)
{
  if (!frame.position_valid || active_axis < 0 || active_axis > 2) {
    return false;
  }
  double3 aim = target_world - frame.position_world;
  double aim_length;
  aim = math::normalize_and_get_length(aim, aim_length);
  if (aim_length <= 1.0e-12) {
    return false;
  }

  double3x3 previous = math::from_rotation<double3x3>(frame.orientation_world);
  double3 secondary = previous[(active_axis + 1) % 3];
  secondary -= aim * math::dot(secondary, aim);
  double secondary_length;
  secondary = math::normalize_and_get_length(secondary, secondary_length);
  if (secondary_length <= 1.0e-8) {
    secondary = view_up - aim * math::dot(view_up, aim);
    secondary = math::normalize_and_get_length(secondary, secondary_length);
    if (secondary_length <= 1.0e-8) {
      secondary = previous[(active_axis + 2) % 3];
      secondary -= aim * math::dot(secondary, aim);
      secondary = math::normalize_and_get_length(secondary, secondary_length);
      if (secondary_length <= 1.0e-8) {
        return false;
      }
    }
  }

  double3x3 orientation = double3x3::identity();
  orientation[active_axis] = aim;
  orientation[(active_axis + 1) % 3] = secondary;
  orientation[(active_axis + 2) % 3] = math::cross(aim, secondary);
  if (active_axis == 1) {
    orientation[0] = math::cross(orientation[1], orientation[2]);
  }
  else if (active_axis == 2) {
    orientation[1] = math::cross(orientation[2], orientation[0]);
  }
  if (math::determinant(orientation) < 0.0) {
    orientation[(active_axis + 1) % 3] = -orientation[(active_axis + 1) % 3];
  }
  frame.orientation_world = math::normalize(math::to_quaternion(orientation));
  frame.orientation_valid = true;
  return true;
}

bool ED_clarity_snap_key_event_apply(const bContext *C,
                                  const int key_type,
                                  const short key_val,
                                  const uint8_t modifier)
{
  const ed::clarity::ClaritySnapMode mode = ed::clarity::snap_key_event_mode_get(
      key_type, key_val, modifier);
  if (mode == ed::clarity::ClaritySnapMode::None) {
    return false;
  }
  if (!ED_clarity_interaction_enabled(C)) {
    return false;
  }
  ed::clarity::ClarityWindowRuntime *runtime = ed::clarity::runtime_ensure(C);
  if (runtime == nullptr) {
    return false;
  }

  ed::clarity::snap_override_revision_reconcile(C, *runtime);
  ed::clarity::ClaritySnapOverride &snap = runtime->temporary.snap;
  const bool changed = key_val == KM_PRESS ?
                           snap.press(key_type,
                                      mode,
                                      ed::clarity::window_tracked_key_get(C) == key_type) :
                           snap.release(key_type);
  ed::clarity::snap_override_mirror_sync(C, *runtime);
  if (!changed) {
    /* A key repeat or a release of a key that is not held: consumed, nothing to redraw. */
    return true;
  }

  /* The snap preview lives and dies with the held keys, so it follows the same state. */
  if (snap.is_empty()) {
    ed::clarity::pivot_edit_snap_preview_clear(*runtime);
  }
  else {
    ed::clarity::pivot_edit_snap_preview_update(
        C, *runtime, ed::clarity::pointer_region_position_get(C));
  }
  WM_event_add_notifier(C, NC_SPACE | ND_SPACE_VIEW3D, nullptr);
  return true;
}

bool ED_clarity_snap_override_release_all(const bContext *C)
{
  ed::clarity::ClarityWindowRuntime *runtime = ed::clarity::runtime_get(C);
  if (runtime == nullptr) {
    return false;
  }
  ed::clarity::snap_override_revision_reconcile(C, *runtime);
  if (!runtime->temporary.snap.clear()) {
    return false;
  }
  ed::clarity::snap_override_mirror_sync(C, *runtime);
  ed::clarity::pivot_edit_snap_preview_clear(*runtime);
  WM_event_add_notifier(C, NC_SPACE | ND_SPACE_VIEW3D, nullptr);
  return true;
}

ed::clarity::ClaritySnapMode ED_clarity_snap_override_get(const bContext *C)
{
  ed::clarity::ClarityWindowRuntime *runtime = ed::clarity::runtime_get(C);
  if (runtime == nullptr) {
    return ed::clarity::ClaritySnapMode::None;
  }
  ed::clarity::snap_override_revision_reconcile(C, *runtime);
  return ED_clarity_interaction_enabled(C) ? runtime->temporary.snap.active() :
                                          ed::clarity::ClaritySnapMode::None;
}

bool ED_clarity_snap_mode_set(const bContext *C, const ed::clarity::ClaritySnapMode mode)
{
  wmWindowManager *wm = CTX_wm_manager(C);
  if (wm == nullptr || wm->runtime == nullptr) {
    return false;
  }
  wm->runtime->clarity_snap_mode = uint8_t(mode);
  WM_event_add_notifier(C, NC_SPACE | ND_SPACE_VIEW3D, nullptr);
  return true;
}

ed::clarity::ClaritySnapMode ED_clarity_snap_mode_get(const bContext *C)
{
  const wmWindowManager *wm = CTX_wm_manager(C);
  if (!ED_clarity_interaction_enabled(C) || wm == nullptr || wm->runtime == nullptr) {
    return ed::clarity::ClaritySnapMode::None;
  }
  return ed::clarity::ClaritySnapMode(wm->runtime->clarity_snap_mode);
}

ed::clarity::ClarityStepSnapSettings ED_clarity_snap_step_settings_get(const bContext *C)
{
  ed::clarity::ClarityStepSnapSettings settings;
  const wmWindowManager *wm = CTX_wm_manager(C);
  if (wm == nullptr || wm->runtime == nullptr) {
    return settings;
  }
  settings.mode = ed::clarity::eClarityStepSnapMode(wm->runtime->clarity_snap_step_mode);
  if (wm->runtime->clarity_snap_step_size > 0.0f) {
    settings.size = wm->runtime->clarity_snap_step_size;
  }
  if (wm->runtime->clarity_snap_step_angle > 0.0f) {
    settings.angle = wm->runtime->clarity_snap_step_angle;
  }
  return settings;
}

ed::clarity::ClaritySnapToleranceSettings ED_clarity_snap_tolerance_settings_get(const bContext *C)
{
  ed::clarity::ClaritySnapToleranceSettings settings;
  const wmWindowManager *wm = CTX_wm_manager(C);
  if (wm == nullptr || wm->runtime == nullptr) {
    return settings;
  }
  settings.limited = wm->runtime->clarity_snap_use_tolerance;
  if (wm->runtime->clarity_snap_tolerance > 0) {
    settings.size_px = wm->runtime->clarity_snap_tolerance;
  }
  return settings;
}

float ED_clarity_snap_tolerance_px_get(const bContext *C, const int region_size_px)
{
  return ed::clarity::snap_tolerance_radius_px(
      ED_clarity_snap_tolerance_settings_get(C), region_size_px, U.pixelsize);
}

void ED_clarity_pivot_event_pre_modal(bContext *C, const wmEvent *event)
{
  if (event == nullptr) {
    return;
  }
  ed::clarity::ClarityWindowRuntime *runtime = ed::clarity::runtime_get(C);
  if (runtime == nullptr) {
    return;
  }

  /* Both pivot keys toggle, so a running transform sees the same model as the idle dispatcher. */
  if (ELEM(event->type, EVT_DKEY, EVT_INSERTKEY) && event->val == KM_PRESS &&
      (event->flag & WM_EVENT_IS_REPEAT) == 0)
  {
    ed::clarity::pivot_edit_toggle_persistent(C, *runtime);
  }
  else if (event->type == WINDEACTIVATE) {
    ed::clarity::pivot_edit_input_reset(C, *runtime);
  }
}

void ED_clarity_transform_begin(const bContext *C,
                             const char *operator_id,
                             const int context_mode,
                             const int mesh_select_mode,
                             const bool is_clarity_pivot_transform)
{
  ed::clarity::ClarityWindowRuntime *runtime = ed::clarity::runtime_ensure(C);
  if (runtime == nullptr) {
    return;
  }
  ed::clarity::pivot_undo_step_begin(C, *runtime);
  runtime->transform_active = true;
  ed::clarity::ClarityPivotEditState &pivot = runtime->pivot_edit;
  ed::clarity::pivot_edit_snap_preview_clear(*runtime);
  if (pivot.target != ed::clarity::ClarityPivotEditTarget::None &&
      (pivot.target == ed::clarity::ClarityPivotEditTarget::ObjectOrigin ||
       is_clarity_pivot_transform))
  {
    pivot.phase = ed::clarity::ClarityPivotEditPhase::PivotDragging;
  }
  pivot.follow_transform = false;
  zero_v3(pivot.follow_translation_previous);
  /* A custom component pivot follows translation in world space. Rotation and scale use it as
   * their fixed center and deliberately keep its world-space orientation unchanged. */
  if (ED_clarity_interaction_enabled(C) && STREQ(operator_id, "TRANSFORM_OT_translate") &&
      context_mode == CTX_MODE_EDIT_MESH &&
      !is_clarity_pivot_transform && pivot.custom &&
      pivot.custom->scene == CTX_data_scene(C) &&
      pivot.custom->object == CTX_data_active_object(C))
  {
    pivot.follow_transform = true;
    copy_v3_v3(pivot.follow_location_initial, pivot.custom->location);
  }
  if (ED_clarity_interaction_enabled(C) && ed::clarity::navigation_debug_logging_enabled(C)) {
    const ed::clarity::ClaritySnapMode temporary_snap_mode = runtime->temporary.snap.active();
    const ed::clarity::ClaritySnapMode effective_snap_mode =
        temporary_snap_mode != ed::clarity::ClaritySnapMode::None ? temporary_snap_mode :
                                                              ED_clarity_snap_mode_get(C);
    runtime->transform_debug = std::make_unique<ed::clarity::ClarityTransformDebugState>(
        operator_id,
        context_mode,
        mesh_select_mode,
        is_clarity_pivot_transform,
        pivot.target,
        effective_snap_mode);
  }
}

void ED_clarity_transform_update(const bContext *C, const float world_translation[3])
{
  ed::clarity::ClarityWindowRuntime *runtime = ed::clarity::runtime_get(C);
  if (runtime == nullptr || !runtime->pivot_edit.follow_transform) {
    return;
  }

  ed::clarity::ClarityPivotEditState &pivot = runtime->pivot_edit;
  if (!pivot.custom || pivot.custom->scene != CTX_data_scene(C) ||
      pivot.custom->object != CTX_data_active_object(C))
  {
    pivot.follow_transform = false;
    return;
  }

  float delta[3];
  sub_v3_v3v3(delta, world_translation, pivot.follow_translation_previous);
  add_v3_v3(pivot.custom->location, delta);
  copy_v3_v3(pivot.follow_translation_previous, world_translation);
}

void ED_clarity_transform_end(bContext *C, const bool cancelled)
{
  if (ed::clarity::ClarityWindowRuntime *runtime = ed::clarity::runtime_get(C)) {
    ed::clarity::shift_transform_end(C, *runtime, cancelled);
    ed::clarity::ClarityPivotEditState &pivot = runtime->pivot_edit;
    const bool was_pivot_drag = ELEM(pivot.phase,
                                     ed::clarity::ClarityPivotEditPhase::PivotDragging,
                                     ed::clarity::ClarityPivotEditPhase::PivotCommitPending);
    const bool exit_after_drag = pivot.exit_after_drag;
    const bool restart_after_drag = pivot.restart_after_drag;
    if (cancelled && pivot.follow_transform && pivot.custom &&
        pivot.custom->scene == CTX_data_scene(C))
    {
      copy_v3_v3(pivot.custom->location, pivot.follow_location_initial);
    }
    pivot.follow_transform = false;
    zero_v3(pivot.follow_translation_previous);
    runtime->transform_active = false;
    runtime->transform_debug.reset();
    if (cancelled) {
      ed::clarity::pivot_undo_pending_clear(*runtime);
    }

    /* Cancelling the drag only restores the pivot, it never leaves the mode: the toggle decides
     * that, and the backend already rolled the pivot back. */
    if (was_pivot_drag) {
      if (exit_after_drag) {
        ed::clarity::pivot_edit_end(C, *runtime);
      }
      else if (restart_after_drag) {
        ed::clarity::pivot_edit_end(C, *runtime);
        ed::clarity::pivot_edit_resume_persistent(C, *runtime);
      }
      else {
        pivot.phase = ed::clarity::ClarityPivotEditPhase::PersistentPivot;
      }
    }
  }
}

void ED_clarity_undo_step_store(const bContext *C)
{
  ed::clarity::ClarityWindowRuntime *runtime = ed::clarity::runtime_get(C);
  UndoStack *undo_stack = ED_undo_stack_get();
  UndoStep *step = ed::clarity::pivot_undo_active_step_get(C);
  if (runtime == nullptr || undo_stack == nullptr || step == nullptr || !runtime->pivot_undo ||
      !runtime->pivot_undo->pending_before)
  {
    return;
  }
  ed::clarity::manipulator_pivot_last_object_resolve(C, *runtime);

  const std::optional<ed::clarity::ClarityPivotUndoSnapshot> after =
      ed::clarity::pivot_undo_snapshot_create(C, *runtime);
  if (!after || ed::clarity::pivot_undo_step_payload_get(undo_stack, step) != nullptr) {
    ed::clarity::pivot_undo_pending_clear(*runtime);
    return;
  }

  auto *payload = MEM_new<ed::clarity::ClarityPivotUndoStepPayload>(__func__);
  payload->owner_window = CTX_wm_window(C);
  payload->owner_runtime_id = runtime->instance_id;
  payload->before = *runtime->pivot_undo->pending_before;
  payload->after = *after;
  BKE_undosys_step_user_data_set(
      undo_stack, step, payload, ed::clarity::pivot_undo_step_payload_free);
  step->data_size += sizeof(*payload);
  ed::clarity::pivot_undo_pending_clear(*runtime);
}

void ED_clarity_undo_step_clear(const bContext *C)
{
  if (ed::clarity::ClarityWindowRuntime *runtime = ed::clarity::runtime_get(C)) {
    ed::clarity::pivot_undo_pending_clear(*runtime);
  }
}

void ED_clarity_undo_steps_restore(bContext *C,
                                const UndoStep *step_from,
                                const UndoStep *step_to,
                                const bool is_undo)
{
  if (step_from == step_to) {
    return;
  }

  const UndoStack *undo_stack = ED_undo_stack_get();
  if (is_undo) {
    for (const UndoStep *step = step_from; step != step_to; step = step->prev) {
      if (step == nullptr) {
        break;
      }
      if (const ed::clarity::ClarityPivotUndoStepPayload *payload =
              ed::clarity::pivot_undo_step_payload_get(undo_stack, step))
      {
        ed::clarity::pivot_undo_snapshot_restore(C, *payload, payload->before);
      }
    }
    return;
  }

  for (const UndoStep *step = step_from != nullptr ? step_from->next : nullptr; step != nullptr;
       step = step->next)
  {
    if (const ed::clarity::ClarityPivotUndoStepPayload *payload =
            ed::clarity::pivot_undo_step_payload_get(undo_stack, step))
    {
      ed::clarity::pivot_undo_snapshot_restore(C, *payload, payload->after);
    }
    if (step == step_to) {
      break;
    }
  }
}

void ED_clarity_navigation_debug_stage_sample(
    const bContext *C,
    const ed::clarity::ClarityNavigationDebugStage stage,
    const double duration_ms,
    const double detail_a_ms,
    const double detail_b_ms,
    const int area_type,
    const int region_type)
{
  if (ed::clarity::ClarityNavigationSession *session =
          ed::clarity::navigation_debug_session_get(C))
  {
    session->debug_stage_sample(
        stage, duration_ms, detail_a_ms, detail_b_ms, area_type, region_type);
  }
  if (ed::clarity::ClarityWindowRuntime *runtime = ed::clarity::runtime_get(C)) {
    if (runtime->transform_debug) {
      runtime->transform_debug->record(
          stage, duration_ms, detail_a_ms, detail_b_ms, area_type, region_type);
    }
  }
}

void ED_clarity_viewport_debug_event(const bContext *C,
                                  const ed::clarity::ClarityNavigationDebugStage stage,
                                  const int code,
                                  const int detail_a,
                                  const int detail_b,
                                  const int area_type,
                                  const int region_type)
{
  if (!ed::clarity::navigation_debug_logging_enabled(C)) {
    return;
  }
  if (ED_clarity_navigation_debug_active(C)) {
    ED_clarity_navigation_debug_stage_sample(
        C, stage, double(code), double(detail_a), double(detail_b), area_type, region_type);
    return;
  }

  FILE *file = ed::clarity::navigation_trace_file_open();
  if (file == nullptr) {
    return;
  }
  std::fprintf(file,
               "VIEWPORT_EVENT t_ms=%.3f stage=%s code=%d detail_a=%d detail_b=%d "
               "area=%d region=%d\n",
               BLI_time_now_seconds() * 1000.0,
               ed::clarity::transform_debug_stage_name(stage),
               code,
               detail_a,
               detail_b,
               area_type,
               region_type);
  std::fclose(file);
}

void ED_clarity_runtime_free(bContext *C, const wmWindow *win)
{
  if (ed::clarity::ClarityWindowRuntime *runtime = ed::clarity::runtimes().lookup_ptr(win)) {
    if (runtime->selection_cursor != nullptr && G_MAIN->wm.first != nullptr) {
      WM_paint_cursor_end(runtime->selection_cursor);
      runtime->selection_cursor = nullptr;
    }
    if (C != nullptr) {
      ed::clarity::pivot_edit_end(C, *runtime);
      if (wmWindowManager *wm = CTX_wm_manager(C)) {
        wm->runtime->clarity_snap_temporary_mode = uint8_t(ed::clarity::ClaritySnapMode::None);
      }
    }
    if (C != nullptr && runtime->active_session) {
      runtime->active_session->cancel(C);
    }
  }
  ed::clarity::runtimes().remove(win);
}

}  // namespace blender
