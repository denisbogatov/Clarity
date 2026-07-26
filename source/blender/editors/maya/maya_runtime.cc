/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup editors
 */

#include "maya_runtime.hh"

#include "MEM_guardedalloc.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdio>
#include <optional>
#include <string>

#include "BLI_fileops.h"
#include "BLI_map.hh"
#include "BLI_math_matrix.h"
#include "BLI_math_matrix_types.hh"
#include "BLI_math_rotation.h"
#include "BLI_math_vector.h"
#include "BLI_path_utils.hh"
#include "BLI_time.h"
#include "BLI_utildefines.h"
#include "BLI_vector.hh"

#include "BKE_appdir.hh"
#include "BKE_context.hh"
#include "BKE_editmesh.hh"
#include "BKE_global.hh"
#include "BKE_layer.hh"
#include "BKE_lib_id.hh"
#include "BKE_undo_system.hh"
#include "BKE_wm_runtime.hh"

#include "DNA_object_types.h"
#include "DNA_scene_types.h"
#include "DNA_screen_types.h"
#include "DNA_view3d_types.h"
#include "DNA_windowmanager_types.h"

#include "ED_maya.hh"
#include "ED_screen.hh"

#include "bmesh.hh"

#include "RNA_access.hh"

#include "maya_session.hh"
#include "maya_tool_presentation.hh"
#include "maya_tools.hh"

#include "WM_api.hh"
#include "WM_types.hh"
#include "wm_event_types.hh"

namespace blender::ed::maya {

struct MayaPivotUndoSnapshot {
  uint32_t scene_session_uid = 0;
  uint32_t object_session_uid = 0;
  float location[3] = {};
  float rotation_quaternion[4] = {1.0f, 0.0f, 0.0f, 0.0f};
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
};

struct MayaPivotUndoState {
  std::optional<MayaPivotUndoSnapshot> pending_before;
};

struct MayaPivotUndoStepPayload {
  const wmWindow *owner_window = nullptr;
  uint64_t owner_runtime_id = 0;
  MayaPivotUndoSnapshot before;
  MayaPivotUndoSnapshot after;
};

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
    case MayaNavigationDebugStage::ViewportRedrawState:
      return "viewport_redraw_state";
    case MayaNavigationDebugStage::ViewportBufferReset:
      return "viewport_buffer_reset";
    case MayaNavigationDebugStage::ViewportBufferMissing:
      return "viewport_buffer_missing";
    case MayaNavigationDebugStage::ViewportComposite:
      return "viewport_composite";
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

    const bool viewport_event = ELEM(stage,
                                     MayaNavigationDebugStage::ViewportRedrawState,
                                     MayaNavigationDebugStage::ViewportBufferReset,
                                     MayaNavigationDebugStage::ViewportBufferMissing);
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
    std::fputs("  VIEWPORT_CODES redraw_code=region_do_draw_flags "
               "buffer_reset_bits=create:1,stereo:2,offscreen_size:4,format:8,"
               "viewport_size:16 detail_a=width_or_partial_pixels "
               "detail_b=height_or_buffer_present\n",
               file);

    for (const MayaTransformDebugStageSample &sample : samples) {
      const bool viewport_event = ELEM(sample.stage,
                                       MayaNavigationDebugStage::ViewportRedrawState,
                                       MayaNavigationDebugStage::ViewportBufferReset,
                                       MayaNavigationDebugStage::ViewportBufferMissing);
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

static uint64_t maya_runtime_instance_id_next = 1;

MayaWindowRuntime::MayaWindowRuntime() : instance_id(maya_runtime_instance_id_next++) {}
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

static UndoStep *pivot_undo_active_step_get(const bContext *C)
{
  wmWindowManager *wm = CTX_wm_manager(C);
  if (wm == nullptr || wm->runtime == nullptr || wm->runtime->undo_stack == nullptr) {
    return nullptr;
  }
  return wm->runtime->undo_stack->step_active;
}

static std::optional<MayaPivotUndoSnapshot> pivot_undo_snapshot_create(
    const bContext *C, const MayaWindowRuntime &runtime)
{
  const MayaCustomPivotData *custom = runtime.pivot_edit.custom.get();
  if (custom == nullptr || custom->scene == nullptr || custom->object == nullptr ||
      CTX_data_mode_enum(C) != CTX_MODE_EDIT_MESH ||
      custom->scene != CTX_data_scene(C))
  {
    return std::nullopt;
  }

  BKE_lib_libblock_session_uid_ensure(&custom->scene->id);
  BKE_lib_libblock_session_uid_ensure(&custom->object->id);
  MayaPivotUndoSnapshot snapshot;
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
  return snapshot;
}

static void pivot_undo_step_begin(const bContext *C, MayaWindowRuntime &runtime)
{
  if (runtime.pivot_undo) {
    runtime.pivot_undo->pending_before.reset();
  }
  const std::optional<MayaPivotUndoSnapshot> snapshot = pivot_undo_snapshot_create(C, runtime);
  if (!snapshot) {
    return;
  }
  if (!runtime.pivot_undo) {
    runtime.pivot_undo = std::make_unique<MayaPivotUndoState>();
  }
  runtime.pivot_undo->pending_before = *snapshot;
}

static void pivot_undo_pending_clear(MayaWindowRuntime &runtime)
{
  if (runtime.pivot_undo) {
    runtime.pivot_undo->pending_before.reset();
  }
}

static void pivot_undo_step_payload_free(void *user_data)
{
  MEM_delete(static_cast<MayaPivotUndoStepPayload *>(user_data));
}

static const MayaPivotUndoStepPayload *pivot_undo_step_payload_get(const UndoStep *step)
{
  if (step == nullptr || step->user_data_free != pivot_undo_step_payload_free) {
    return nullptr;
  }
  return static_cast<const MayaPivotUndoStepPayload *>(step->user_data);
}

static bool pivot_undo_snapshot_restore(bContext *C,
                                        const MayaPivotUndoStepPayload &payload,
                                        const MayaPivotUndoSnapshot &snapshot)
{
  MayaWindowRuntime *runtime = runtimes().lookup_ptr(payload.owner_window);
  if (runtime == nullptr || runtime->instance_id != payload.owner_runtime_id) {
    return false;
  }

  Main *bmain = CTX_data_main(C);
  Scene *scene = id_cast<Scene *>(
      BKE_libblock_find_session_uid(bmain, ID_SCE, snapshot.scene_session_uid));
  Object *object = id_cast<Object *>(
      BKE_libblock_find_session_uid(bmain, ID_OB, snapshot.object_session_uid));
  if (scene == nullptr || object == nullptr) {
    return false;
  }

  auto custom = std::make_unique<MayaCustomPivotData>();
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
  runtime->pivot_mode = MayaPivotMode::Custom;
  if (runtime->pivot_edit.target == MayaPivotEditTarget::ComponentPivot) {
    runtime->pivot_edit.scene = scene;
    runtime->pivot_edit.object = object;
  }

  if (payload.owner_window == CTX_wm_window(C)) {
    ED_maya_tool_presentation_refresh(C, *runtime);
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
  PropertyRNA *property = RNA_struct_find_property(&wm_ptr, "maya_navigation_debug");
  return property != nullptr && RNA_property_boolean_get(&wm_ptr, property);
}

int navigation_frame_rate_limit_setting(const bContext * /*C*/)
{
  return U.viewport_fps_limit;
}

static MayaPivotEditTarget pivot_edit_target_from_context(const bContext *C,
                                                          const MayaWindowRuntime &runtime)
{
  const ARegion *region = CTX_wm_region(C);
  if (region == nullptr || region->regiontype != RGN_TYPE_WINDOW ||
      CTX_data_active_object(C) == nullptr ||
      !ELEM(runtime.tool.active, MayaToolID::Move, MayaToolID::Rotate, MayaToolID::Scale))
  {
    return MayaPivotEditTarget::None;
  }

  switch (CTX_data_mode_enum(C)) {
    case CTX_MODE_OBJECT:
      return MayaPivotEditTarget::ObjectOrigin;
    case CTX_MODE_EDIT_MESH:
      return MayaPivotEditTarget::ComponentPivot;
    default:
      return MayaPivotEditTarget::None;
  }
}

static void pivot_edit_status_set(bContext *C,
                                  const MayaPivotEditTarget target,
                                  const bool persistent)
{
  ED_workspace_status_text(
      C,
      target == MayaPivotEditTarget::ObjectOrigin ?
          (persistent ?
               "Edit Pivot (Object): drag the move or rotate handles; Insert exits" :
               "Edit Pivot (Object): release D to exit") :
          (persistent ?
               "Edit Pivot (Components): drag the move or rotate handles; Insert exits" :
               "Edit Pivot (Components): release D to exit"));
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

    auto hash_selected_element = [&](const BMElem *element, const uint64_t type) {
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

static bool pivot_component_selection_changed(const MayaCustomPivotData &custom,
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
                                           MayaWindowRuntime &runtime,
                                           const bool force)
{
  MayaCustomPivotData *custom = runtime.pivot_edit.custom.get();
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

void pivot_edit_end(bContext *C, MayaWindowRuntime &runtime)
{
  MayaPivotEditState &state = runtime.pivot_edit;
  const MayaPivotEditTarget ended_target = state.target;
  if (state.target == MayaPivotEditTarget::ObjectOrigin && state.scene != nullptr &&
      !state.data_origin_was_enabled)
  {
    state.scene->toolsettings->transform_flag &= ~SCE_XFORM_DATA_ORIGIN;
  }

  state.phase = MayaPivotEditPhase::Normal;
  state.target = MayaPivotEditTarget::None;
  state.scene = nullptr;
  state.object = nullptr;
  state.workspace = nullptr;
  state.area = nullptr;
  state.region = nullptr;
  state.tool = MayaToolID::None;
  state.tool_revision = 0;
  state.persistent = false;
  state.exit_after_drag = false;
  state.restart_after_drag = false;
  state.restart_after_cancel = false;
  state.restart_persistent = false;
  runtime.temporary.edit_pivot = false;

  if (C != nullptr && ended_target != MayaPivotEditTarget::None) {
    ED_workspace_status_text(C, nullptr);
    if (ended_target == MayaPivotEditTarget::ObjectOrigin) {
      WM_event_add_notifier(C, NC_SCENE | ND_TOOLSETTINGS, nullptr);
    }
    ED_maya_tool_presentation_refresh(C, runtime);
  }
}

static bool pivot_edit_begin(bContext *C,
                             MayaWindowRuntime &runtime,
                             const bool persistent)
{
  const MayaPivotEditTarget target = pivot_edit_target_from_context(C, runtime);
  Scene *scene = CTX_data_scene(C);
  Object *object = CTX_data_active_object(C);
  if (target == MayaPivotEditTarget::None || scene == nullptr || object == nullptr) {
    return false;
  }

  MayaPivotEditState &state = runtime.pivot_edit;
  if (target == MayaPivotEditTarget::ObjectOrigin) {
    state.data_origin_was_enabled = (scene->toolsettings->transform_flag &
                                     SCE_XFORM_DATA_ORIGIN) != 0;
    scene->toolsettings->transform_flag |= SCE_XFORM_DATA_ORIGIN;
    runtime.pivot_mode = MayaPivotMode::Object;
  }
  else {
    const bool create_custom = !state.custom || state.custom->scene != scene ||
                               (state.custom->object != object && !state.custom->pinned);
    if (create_custom) {
      auto custom = std::make_unique<MayaCustomPivotData>();
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
    runtime.pivot_mode = MayaPivotMode::Custom;
  }

  state.target = target;
  state.scene = scene;
  state.object = object;
  state.workspace = CTX_wm_workspace(C);
  state.area = CTX_wm_area(C);
  state.region = CTX_wm_region(C);
  state.tool = runtime.tool.active;
  state.tool_revision = runtime.tool.revision;
  state.persistent = persistent;
  state.exit_after_drag = false;
  state.restart_after_drag = false;
  state.restart_after_cancel = false;
  state.restart_persistent = false;
  state.phase = persistent ? MayaPivotEditPhase::PersistentPivot :
                             MayaPivotEditPhase::PivotArmed;
  runtime.temporary.edit_pivot = true;

  pivot_edit_status_set(C, target, persistent);
  if (target == MayaPivotEditTarget::ObjectOrigin) {
    WM_event_add_notifier(C, NC_SCENE | ND_TOOLSETTINGS, nullptr);
  }
  ED_maya_tool_presentation_refresh(C, runtime);
  return true;
}

bool pivot_edit_resume_persistent(bContext *C, MayaWindowRuntime &runtime)
{
  if (pivot_edit_begin(C, runtime, true)) {
    return true;
  }

  /* Insert is a persistent request, even while the current area, mode, or tool cannot host a
   * pivot manipulator. Validation retries the request when a supported context becomes active. */
  runtime.pivot_edit.persistent = true;
  runtime.pivot_edit.phase = MayaPivotEditPhase::PersistentPivot;
  return true;
}

bool pivot_edit_key_press(bContext *C, MayaWindowRuntime &runtime)
{
  MayaPivotEditState &state = runtime.pivot_edit;
  if (runtime.physical_input.edit_pivot) {
    return state.target != MayaPivotEditTarget::None || pivot_edit_begin(C, runtime, false);
  }
  runtime.physical_input.edit_pivot = true;
  if (state.persistent) {
    return true;
  }
  if (state.target != MayaPivotEditTarget::None) {
    return true;
  }
  return pivot_edit_begin(C, runtime, false);
}

bool pivot_edit_key_release(bContext *C, MayaWindowRuntime &runtime)
{
  MayaPivotEditState &state = runtime.pivot_edit;
  if (!runtime.physical_input.edit_pivot) {
    return false;
  }

  runtime.physical_input.edit_pivot = false;
  if (state.persistent) {
    return true;
  }
  if (runtime.transform_active && state.target != MayaPivotEditTarget::None) {
    state.exit_after_drag = true;
    state.phase = MayaPivotEditPhase::PivotCommitPending;
    return true;
  }
  if (state.target != MayaPivotEditTarget::None) {
    pivot_edit_end(C, runtime);
    return true;
  }
  return false;
}

bool pivot_edit_toggle_persistent(bContext *C, MayaWindowRuntime &runtime)
{
  MayaPivotEditState &state = runtime.pivot_edit;
  if (!state.persistent && runtime.transform_active &&
      state.target != MayaPivotEditTarget::None)
  {
    state.persistent = true;
    state.exit_after_drag = false;
    if (state.restart_after_drag) {
      state.restart_persistent = true;
    }
    return true;
  }
  if (state.persistent) {
    if (runtime.transform_active && state.target != MayaPivotEditTarget::None) {
      state.persistent = false;
      state.exit_after_drag = !runtime.physical_input.edit_pivot;
      state.restart_persistent = false;
      state.phase = MayaPivotEditPhase::PivotCommitPending;
    }
    else {
      pivot_edit_end(C, runtime);
    }
    return true;
  }
  return pivot_edit_resume_persistent(C, runtime);
}

bool pivot_edit_pin_toggle(bContext *C, MayaWindowRuntime &runtime)
{
  Scene *scene = CTX_data_scene(C);
  Object *object = CTX_data_active_object(C);
  if (scene == nullptr || object == nullptr || CTX_data_mode_enum(C) != CTX_MODE_EDIT_MESH) {
    return false;
  }

  MayaPivotEditState &state = runtime.pivot_edit;
  const bool create_custom = !state.custom || state.custom->scene != scene ||
                             (state.custom->object != object && !state.custom->pinned);
  if (create_custom) {
    auto custom = std::make_unique<MayaCustomPivotData>();
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
  ED_maya_tool_presentation_refresh(C, runtime);
  return true;
}

void pivot_edit_focus_lost(bContext *C, MayaWindowRuntime &runtime)
{
  runtime.temporary.snap_stack.clear();
  if (wmWindowManager *wm = CTX_wm_manager(C)) {
    wm->runtime->maya_snap_temporary_mode = uint8_t(MayaSnapMode::None);
  }

  MayaPivotEditState &state = runtime.pivot_edit;
  runtime.physical_input.edit_pivot = false;
  if (state.persistent) {
    if (runtime.transform_active && state.target != MayaPivotEditTarget::None) {
      state.restart_after_drag = true;
      state.restart_after_cancel = true;
      state.restart_persistent = true;
      state.phase = MayaPivotEditPhase::PivotCommitPending;
    }
    return;
  }
  if (state.target == MayaPivotEditTarget::None) {
    return;
  }
  if (runtime.transform_active) {
    state.exit_after_drag = true;
    state.phase = MayaPivotEditPhase::PivotCommitPending;
  }
  else {
    pivot_edit_end(C, runtime);
  }
}

void pivot_edit_validate(bContext *C, MayaWindowRuntime &runtime)
{
  MayaPivotEditState &state = runtime.pivot_edit;
  if (state.target == MayaPivotEditTarget::None) {
    if (state.persistent) {
      pivot_edit_resume_persistent(C, runtime);
    }
    else if (runtime.physical_input.edit_pivot) {
      pivot_edit_begin(C, runtime, false);
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
      state.restart_after_cancel = false;
      state.restart_persistent = state.persistent;
      state.phase = MayaPivotEditPhase::PivotCommitPending;
      return;
    }

    const bool resume_persistent = state.persistent;
    const bool resume_temporary = runtime.physical_input.edit_pivot && !state.persistent;
    pivot_edit_end(C, runtime);
    if (resume_persistent) {
      pivot_edit_resume_persistent(C, runtime);
    }
    else if (resume_temporary) {
      pivot_edit_begin(C, runtime, false);
    }
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

ed::maya::MayaPivotEditTarget ED_maya_pivot_edit_target_get(const bContext *C)
{
  const ed::maya::MayaWindowRuntime *runtime = ed::maya::runtime_get(C);
  return runtime != nullptr ? runtime->pivot_edit.target :
                              ed::maya::MayaPivotEditTarget::None;
}

bool ED_maya_pivot_custom_matrix_get(const bContext *C, float r_matrix[4][4])
{
  ed::maya::MayaWindowRuntime *runtime = ed::maya::runtime_get(C);
  if (runtime == nullptr || !ed::maya::pivot_custom_sync_to_selection(C, *runtime, false)) {
    return false;
  }
  const ed::maya::MayaCustomPivotData *custom =
      runtime->pivot_edit.custom ? runtime->pivot_edit.custom.get() : nullptr;

  quat_to_mat4(r_matrix, custom->rotation_quaternion);
  copy_v3_v3(r_matrix[3], custom->location);
  return true;
}

bool ED_maya_pivot_edit_data_get(const bContext *C,
                                 float **r_location,
                                 float **r_rotation_quaternion)
{
  ed::maya::MayaWindowRuntime *runtime = ed::maya::runtime_get(C);
  if (runtime == nullptr || !ed::maya::pivot_custom_sync_to_selection(C, *runtime, false)) {
    return false;
  }
  ed::maya::MayaCustomPivotData *custom =
      runtime->pivot_edit.custom ? runtime->pivot_edit.custom.get() : nullptr;
  if (custom == nullptr ||
      runtime->pivot_edit.target != ed::maya::MayaPivotEditTarget::ComponentPivot ||
      custom->scene != CTX_data_scene(C) || custom->object != CTX_data_active_object(C))
  {
    return false;
  }

  *r_location = custom->location;
  *r_rotation_quaternion = custom->rotation_quaternion;
  return true;
}

bool ED_maya_snap_override_set(const bContext *C,
                               const ed::maya::MayaSnapMode mode,
                               const bool enabled)
{
  if (!ED_maya_interaction_enabled(C) || mode == ed::maya::MayaSnapMode::None) {
    return false;
  }
  ed::maya::MayaWindowRuntime *runtime = ed::maya::runtime_ensure(C);
  if (runtime == nullptr) {
    return false;
  }

  Vector<ed::maya::MayaSnapMode, 5> &stack = runtime->temporary.snap_stack;
  wmWindowManager *wm = CTX_wm_manager(C);
  if (wm != nullptr &&
      runtime->interaction_revision_seen != wm->runtime->maya_interaction_revision)
  {
    runtime->interaction_revision_seen = wm->runtime->maya_interaction_revision;
    stack.clear();
    wm->runtime->maya_snap_temporary_mode = uint8_t(ed::maya::MayaSnapMode::None);
  }
  const auto remove_mode = [&](const ed::maya::MayaSnapMode mode_to_remove) {
    int64_t index;
    while ((index = stack.as_span().first_index_try(mode_to_remove)) != -1) {
      stack.remove(index);
    }
  };
  const bool is_step_mode = ELEM(mode,
                                 ed::maya::MayaSnapMode::StepAbsolute,
                                 ed::maya::MayaSnapMode::StepRelative);
  if (!enabled && is_step_mode)
  {
    remove_mode(ed::maya::MayaSnapMode::StepAbsolute);
    remove_mode(ed::maya::MayaSnapMode::StepRelative);
  }
  else if (!enabled) {
    remove_mode(mode);
  }
  else if (stack.as_span().contains(mode) ||
           (is_step_mode &&
            (stack.as_span().contains(ed::maya::MayaSnapMode::StepAbsolute) ||
             stack.as_span().contains(ed::maya::MayaSnapMode::StepRelative))))
  {
    return true;
  }
  else {
    stack.append(mode);
  }

  if (wm != nullptr) {
    wm->runtime->maya_snap_temporary_mode = uint8_t(
        stack.is_empty() ? ed::maya::MayaSnapMode::None : stack.last());
  }
  WM_event_add_notifier(C, NC_SPACE | ND_SPACE_VIEW3D, nullptr);
  return true;
}

ed::maya::MayaSnapMode ED_maya_snap_override_get(const bContext *C)
{
  ed::maya::MayaWindowRuntime *runtime = ed::maya::runtime_get(C);
  if (runtime == nullptr) {
    return ed::maya::MayaSnapMode::None;
  }
  const wmWindowManager *wm = CTX_wm_manager(C);
  const bool interaction_enabled = ED_maya_interaction_enabled(C);
  if (wm != nullptr &&
      runtime->interaction_revision_seen != wm->runtime->maya_interaction_revision)
  {
    runtime->interaction_revision_seen = wm->runtime->maya_interaction_revision;
    runtime->temporary.snap_stack.clear();
    wm->runtime->maya_snap_temporary_mode = uint8_t(ed::maya::MayaSnapMode::None);
  }
  return interaction_enabled && !runtime->temporary.snap_stack.is_empty() ?
             runtime->temporary.snap_stack.last() :
             ed::maya::MayaSnapMode::None;
}

bool ED_maya_snap_mode_set(const bContext *C, const ed::maya::MayaSnapMode mode)
{
  wmWindowManager *wm = CTX_wm_manager(C);
  if (wm == nullptr || wm->runtime == nullptr) {
    return false;
  }
  wm->runtime->maya_snap_mode = uint8_t(mode);
  WM_event_add_notifier(C, NC_SPACE | ND_SPACE_VIEW3D, nullptr);
  return true;
}

ed::maya::MayaSnapMode ED_maya_snap_mode_get(const bContext *C)
{
  const wmWindowManager *wm = CTX_wm_manager(C);
  if (!ED_maya_interaction_enabled(C) || wm == nullptr || wm->runtime == nullptr) {
    return ed::maya::MayaSnapMode::None;
  }
  return ed::maya::MayaSnapMode(wm->runtime->maya_snap_mode);
}

void ED_maya_pivot_event_pre_modal(bContext *C, const wmEvent *event)
{
  if (event == nullptr) {
    return;
  }
  ed::maya::MayaWindowRuntime *runtime = ed::maya::runtime_get(C);
  if (runtime == nullptr) {
    return;
  }

  if (event->type == EVT_DKEY && event->val == KM_RELEASE) {
    ed::maya::pivot_edit_key_release(C, *runtime);
  }
  else if (event->type == EVT_INSERTKEY && event->val == KM_PRESS &&
           (event->flag & WM_EVENT_IS_REPEAT) == 0)
  {
    ed::maya::pivot_edit_toggle_persistent(C, *runtime);
  }
  else if (event->type == WINDEACTIVATE) {
    ed::maya::pivot_edit_focus_lost(C, *runtime);
  }
}

void ED_maya_transform_begin(const bContext *C,
                             const char *operator_id,
                             const int context_mode,
                             const int mesh_select_mode,
                             const bool is_maya_pivot_transform)
{
  ed::maya::MayaWindowRuntime *runtime = ed::maya::runtime_ensure(C);
  if (runtime == nullptr) {
    return;
  }
  ed::maya::pivot_undo_step_begin(C, *runtime);
  runtime->transform_active = true;
  ed::maya::MayaPivotEditState &pivot = runtime->pivot_edit;
  if (pivot.target != ed::maya::MayaPivotEditTarget::None &&
      (pivot.target == ed::maya::MayaPivotEditTarget::ObjectOrigin ||
       is_maya_pivot_transform))
  {
    pivot.phase = ed::maya::MayaPivotEditPhase::PivotDragging;
  }
  pivot.follow_transform = false;
  zero_v3(pivot.follow_translation_previous);
  /* A custom component pivot follows translation in world space. Rotation and scale use it as
   * their fixed center and deliberately keep its world-space orientation unchanged. */
  if (ED_maya_interaction_enabled(C) && STREQ(operator_id, "TRANSFORM_OT_translate") &&
      context_mode == CTX_MODE_EDIT_MESH &&
      !is_maya_pivot_transform && pivot.custom &&
      pivot.custom->scene == CTX_data_scene(C) &&
      pivot.custom->object == CTX_data_active_object(C))
  {
    pivot.follow_transform = true;
    copy_v3_v3(pivot.follow_location_initial, pivot.custom->location);
  }
  if (ED_maya_interaction_enabled(C) && ed::maya::navigation_debug_logging_enabled(C)) {
    runtime->transform_debug = std::make_unique<ed::maya::MayaTransformDebugState>(
        operator_id, context_mode, mesh_select_mode);
  }
}

void ED_maya_transform_update(const bContext *C, const float world_translation[3])
{
  ed::maya::MayaWindowRuntime *runtime = ed::maya::runtime_get(C);
  if (runtime == nullptr || !runtime->pivot_edit.follow_transform) {
    return;
  }

  ed::maya::MayaPivotEditState &pivot = runtime->pivot_edit;
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

void ED_maya_transform_end(bContext *C, const bool cancelled)
{
  if (ed::maya::MayaWindowRuntime *runtime = ed::maya::runtime_get(C)) {
    ed::maya::shift_transform_end(C, *runtime, cancelled);
    ed::maya::MayaPivotEditState &pivot = runtime->pivot_edit;
    const bool was_pivot_drag = ELEM(pivot.phase,
                                     ed::maya::MayaPivotEditPhase::PivotDragging,
                                     ed::maya::MayaPivotEditPhase::PivotCommitPending);
    const bool exit_after_drag = pivot.exit_after_drag;
    const bool restart_after_drag = pivot.restart_after_drag;
    const bool restart_after_cancel = pivot.restart_after_cancel;
    const bool restart_persistent = pivot.restart_persistent;
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
      ed::maya::pivot_undo_pending_clear(*runtime);
    }

    if (was_pivot_drag) {
      if (cancelled || exit_after_drag || restart_after_drag ||
          (!pivot.persistent && !runtime->physical_input.edit_pivot))
      {
        ed::maya::pivot_edit_end(C, *runtime);
        if (restart_after_drag && (!cancelled || restart_after_cancel)) {
          if (restart_persistent) {
            ed::maya::pivot_edit_resume_persistent(C, *runtime);
          }
          else if (runtime->physical_input.edit_pivot) {
            ed::maya::pivot_edit_begin(C, *runtime, false);
          }
        }
      }
      else {
        pivot.phase = pivot.persistent ?
                          ed::maya::MayaPivotEditPhase::PersistentPivot :
                          ed::maya::MayaPivotEditPhase::PivotArmed;
      }
    }
  }
}

void ED_maya_undo_step_store(const bContext *C)
{
  ed::maya::MayaWindowRuntime *runtime = ed::maya::runtime_get(C);
  UndoStep *step = ed::maya::pivot_undo_active_step_get(C);
  if (runtime == nullptr || step == nullptr || !runtime->pivot_undo ||
      !runtime->pivot_undo->pending_before)
  {
    return;
  }

  const std::optional<ed::maya::MayaPivotUndoSnapshot> after =
      ed::maya::pivot_undo_snapshot_create(C, *runtime);
  if (!after || step->user_data != nullptr) {
    ed::maya::pivot_undo_pending_clear(*runtime);
    return;
  }

  auto *payload = MEM_new<ed::maya::MayaPivotUndoStepPayload>(__func__);
  payload->owner_window = CTX_wm_window(C);
  payload->owner_runtime_id = runtime->instance_id;
  payload->before = *runtime->pivot_undo->pending_before;
  payload->after = *after;
  step->user_data = payload;
  step->user_data_free = ed::maya::pivot_undo_step_payload_free;
  step->data_size += sizeof(*payload);
  ed::maya::pivot_undo_pending_clear(*runtime);
}

void ED_maya_undo_step_clear(const bContext *C)
{
  if (ed::maya::MayaWindowRuntime *runtime = ed::maya::runtime_get(C)) {
    ed::maya::pivot_undo_pending_clear(*runtime);
  }
}

void ED_maya_undo_steps_restore(bContext *C,
                                const UndoStep *step_from,
                                const UndoStep *step_to,
                                const bool is_undo)
{
  if (step_from == step_to) {
    return;
  }

  if (is_undo) {
    for (const UndoStep *step = step_from; step != step_to; step = step->prev) {
      if (step == nullptr) {
        break;
      }
      if (const ed::maya::MayaPivotUndoStepPayload *payload =
              ed::maya::pivot_undo_step_payload_get(step))
      {
        ed::maya::pivot_undo_snapshot_restore(C, *payload, payload->before);
      }
    }
    return;
  }

  for (const UndoStep *step = step_from != nullptr ? step_from->next : nullptr; step != nullptr;
       step = step->next)
  {
    if (const ed::maya::MayaPivotUndoStepPayload *payload =
            ed::maya::pivot_undo_step_payload_get(step))
    {
      ed::maya::pivot_undo_snapshot_restore(C, *payload, payload->after);
    }
    if (step == step_to) {
      break;
    }
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

void ED_maya_viewport_debug_event(const bContext *C,
                                  const ed::maya::MayaNavigationDebugStage stage,
                                  const int code,
                                  const int detail_a,
                                  const int detail_b,
                                  const int area_type,
                                  const int region_type)
{
  if (!ed::maya::navigation_debug_logging_enabled(C)) {
    return;
  }
  if (ED_maya_navigation_debug_active(C)) {
    ED_maya_navigation_debug_stage_sample(
        C, stage, double(code), double(detail_a), double(detail_b), area_type, region_type);
    return;
  }

  char filepath[FILE_MAX];
  BLI_path_join(filepath, sizeof(filepath), BKE_tempdir_base(), "maya_navigation_trace.log");
  FILE *file = BLI_fopen(filepath, "a");
  if (file == nullptr) {
    return;
  }
  std::fprintf(file,
               "VIEWPORT_EVENT t_ms=%.3f stage=%s code=%d detail_a=%d detail_b=%d "
               "area=%d region=%d\n",
               BLI_time_now_seconds() * 1000.0,
               ed::maya::transform_debug_stage_name(stage),
               code,
               detail_a,
               detail_b,
               area_type,
               region_type);
  std::fclose(file);
}

void ED_maya_runtime_free(bContext *C, const wmWindow *win)
{
  if (ed::maya::MayaWindowRuntime *runtime = ed::maya::runtimes().lookup_ptr(win)) {
    if (C != nullptr) {
      ed::maya::pivot_edit_end(C, *runtime);
      if (wmWindowManager *wm = CTX_wm_manager(C)) {
        wm->runtime->maya_snap_temporary_mode = uint8_t(ed::maya::MayaSnapMode::None);
      }
    }
    if (C != nullptr && runtime->active_session) {
      runtime->active_session->cancel(C);
    }
  }
  ed::maya::runtimes().remove(win);
}

}  // namespace blender
