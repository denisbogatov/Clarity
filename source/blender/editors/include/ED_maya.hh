/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup editors
 */

#pragma once

#include <cstdint>
#include <memory>
#include <optional>

#include "BLI_math_matrix_types.hh"
#include "BLI_math_quaternion_types.hh"
#include "BLI_math_vector_types.hh"

#include "DNA_ID.h"

namespace blender {

struct bContext;
struct Main;
struct Object;
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

enum class MayaPivotTargetType : uint8_t {
  Object,
  Component,
};

/**
 * Which stored pivot a caller asks for. Rotate and scale pivots are authored independently, so the
 * requested usage decides which one may override the regular transform center.
 */
enum class MayaPivotUsage : uint8_t {
  /** Rotation around the custom rotate pivot (#TFM_ROTATION, #TFM_TRACKBALL). */
  Rotate,
  /** Scaling around the custom scale pivot (#TFM_RESIZE). */
  Scale,
  /** Gizmo drawing and snapping: follow the pivot of the active Maya tool. */
  Display,
};

enum eMayaPivotResetMode : uint8_t {
  MAYA_PIVOT_RESET_CENTER = 0,
  MAYA_PIVOT_RESET_ZERO = 1,
};

enum eMayaPivotBakeMode : uint8_t {
  MAYA_PIVOT_BAKE_POSITION = 0,
  MAYA_PIVOT_BAKE_ORIENTATION,
  MAYA_PIVOT_BAKE_BOTH,
};

struct MayaPivotFrame {
  double3 position_world = double3(0.0);
  math::QuaternionBase<double> orientation_world = math::QuaternionBase<double>::identity();
  bool position_valid = false;
  bool orientation_valid = false;
};

enum class MayaPivotSnapTargetType : uint8_t {
  None,
  Vertex,
  Edge,
  Face,
  Curve,
  Grid,
  ObjectPivot,
  ComponentPivot,
  ViewPlane,
};

struct MayaPivotSnapResult {
  std::optional<double3> position_world;
  std::optional<math::QuaternionBase<double>> orientation_world;
  MayaPivotSnapTargetType type = MayaPivotSnapTargetType::None;
  Object *object = nullptr;
  std::optional<float4x4> object_to_world;
  int component_index = -1;
};

struct MayaPivotToolSettings {
  bool pin_component_pivot = false;
  bool snap_position = true;
  bool snap_orientation = true;
  bool bake_orientation_automatically = false;
  bool preserve_children = true;
  bool show_orientation_handle = true;
  eMayaPivotResetMode reset_mode = MAYA_PIVOT_RESET_CENTER;
  int active_axis = 0;
};

struct MayaObjectRuntimeRef {
  uint32_t session_uid = 0;
  char id_name[MAX_ID_NAME] = {};
};

class MayaPivotEditTargetBackend {
 public:
  virtual ~MayaPivotEditTargetBackend() = default;

  virtual MayaPivotTargetType type() const = 0;
  virtual MayaPivotFrame frame_get() const = 0;
  virtual bool position_set(const double3 &position_world, bool preserve) = 0;
  virtual bool orientation_set(const math::QuaternionBase<double> &orientation_world,
                               bool bake) = 0;
  virtual void reset_position(eMayaPivotResetMode mode) = 0;
  virtual void reset_orientation() = 0;
  virtual void cancel() = 0;
  virtual void commit() = 0;
};

enum class MayaSnapMode : uint8_t {
  None,
  Grid,
  Curve,
  Point,
  ViewPlane,
  MeshCenter,
  /** Discrete steps. #MayaStepSnapSettings decides how big they are and what they are measured
   * from, exactly like Maya's Step Snap settings behind the same key. */
  Step,
};

/**
 * Maya's `manipMoveContext -xformConstraint`: what the moved components stay attached to. Lives
 * here rather than with the rest of the marking menu state because the transform module is what
 * has to honor it.
 */
enum class MayaTransformConstraint : uint8_t {
  Off = 0,
  Edge = 1,
  Surface = 2,
};

enum eMayaStepSnapMode : uint8_t {
  /** Steps counted from where the transform started. Maya's default. */
  MAYA_STEP_SNAP_RELATIVE = 0,
  /** Steps counted from the world origin, so the result lands on multiples of the step. */
  MAYA_STEP_SNAP_ABSOLUTE = 1,
};

struct MayaStepSnapSettings {
  eMayaStepSnapMode mode = MAYA_STEP_SNAP_RELATIVE;
  /** One step of a translation, in scene units. */
  float size = 1.0f;
  /**
   * One step of a rotation, in radians. Maya's own default is 15 degrees, spelled out here so this
   * widely included header does not have to pull in the math constants for it.
   */
  float angle = 0.261799388f;
};

/**
 * Maya's snapping tolerance: the region around the pointer a target has to be in to win.
 * With #limited off the region is the whole viewport, which is Maya's "snap to anything viewable".
 */
struct MayaSnapToleranceSettings {
  bool limited = true;
  int size_px = 10;
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

/**
 * Whether the temporary manipulator trace is on, set by the `BLENDER_MAYA_GIZMO_TRACE` environment
 * variable. Remove together with the trace once the manipulator lifecycle is settled.
 */
bool ED_maya_gizmo_trace_enabled();

bool ED_maya_interaction_enabled(const bContext *C);
/**
 * Whether the Maya interaction model owns this session at all, regardless of what the pointer
 * happens to be over. #ED_maya_interaction_enabled additionally requires a 3D View, so it answers
 * "may this event be interpreted here", not "is the Maya model active".
 */
bool ED_maya_interaction_preset_enabled(const bContext *C);
ed::maya::MayaObjectRuntimeRef ED_maya_object_runtime_ref_create(const Object &object);
Object *ED_maya_object_runtime_ref_resolve(
    Main &bmain, const ed::maya::MayaObjectRuntimeRef &reference);
void ED_operatortypes_maya();
ed::maya::MayaDispatchResult ED_maya_event_dispatch(bContext *C, const wmEvent *event);
int ED_maya_interaction_frame_rate_limit(const bContext *C);
bool ED_maya_navigation_debug_active(const bContext *C);
ed::maya::MayaPivotEditTarget ED_maya_pivot_edit_target_get(const bContext *C);
bool ED_maya_pivot_custom_matrix_get(const bContext *C,
                                     ed::maya::MayaPivotUsage usage,
                                     float r_matrix[4][4]);
bool ED_maya_pivot_custom_orientation_get(const bContext *C, float r_orientation[3][3]);
bool ED_maya_pivot_edit_data_get(const bContext *C,
                                 float **r_location,
                                 float **r_rotation_quaternion);
std::unique_ptr<ed::maya::MayaPivotEditTargetBackend> ED_maya_pivot_edit_target_create(
    bContext *C);
void ED_maya_pivot_reset_position(bContext *C, ed::maya::eMayaPivotResetMode mode);
void ED_maya_pivot_reset_orientation(bContext *C);
void ED_maya_pivot_reset_all(bContext *C, ed::maya::eMayaPivotResetMode mode);
void ED_maya_pivot_undo_begin(const bContext *C);
bool ED_maya_pivot_bake(bContext *C, ed::maya::eMayaPivotBakeMode mode);
/**
 * Read-only world-space frame of the runtime pivot manipulator of the context window. Returns
 * false when the window has no Maya runtime yet; the validity flags of \a r_frame tell whether the
 * position and the orientation carry a pivot the user actually authored.
 */
bool ED_maya_pivot_manipulator_state_get(const bContext *C, ed::maya::MayaPivotFrame &r_frame);
/**
 * Element the pivot would snap to if the user clicked now. Only filled while Edit Pivot is active
 * and a temporary snap key is held, so a false return means the overlay has nothing to draw.
 */
bool ED_maya_pivot_snap_preview_get(const bContext *C, ed::maya::MayaPivotSnapResult &r_result);
bool ED_maya_pivot_tool_settings_get(const bContext *C,
                                     ed::maya::MayaPivotToolSettings &r_settings);
bool ED_maya_pivot_tool_settings_set(const bContext *C,
                                     const ed::maya::MayaPivotToolSettings &settings);
void ED_maya_pivot_active_axis_set(const bContext *C, int active_axis);
bool ED_maya_pivot_orientation_aim(ed::maya::MayaPivotFrame &frame,
                                   const double3 &target_world,
                                   int active_axis,
                                   const double3 &view_up);
/**
 * Feed one physical key event to the momentary snap state. Returns whether the event belongs to a
 * snap key, in which case it must not reach any other binding.
 *
 * The idle dispatcher and a running transform both funnel their key events through here, so the two
 * can never disagree about which key holds which mode.
 */
bool ED_maya_snap_key_event_apply(const bContext *C,
                                  int key_type,
                                  short key_val,
                                  uint8_t modifier);
/**
 * Treat every momentary snap key as released. For the cases where the release itself can never
 * reach the dispatcher — the pointer left the 3D View, a popup swallowed the event — which is what
 * used to leave temporary snapping stuck on.
 */
bool ED_maya_snap_override_release_all(const bContext *C);
ed::maya::MayaSnapMode ED_maya_snap_override_get(const bContext *C);
bool ED_maya_snap_mode_set(const bContext *C, ed::maya::MayaSnapMode mode);
ed::maya::MayaSnapMode ED_maya_snap_mode_get(const bContext *C);
/** Step size and reference of #ed::maya::MayaSnapMode::Step, the defaults when there is no window. */
ed::maya::MayaStepSnapSettings ED_maya_snap_step_settings_get(const bContext *C);
ed::maya::MayaSnapToleranceSettings ED_maya_snap_tolerance_settings_get(const bContext *C);
/**
 * Maya's `snapComponentsRelative`, from the Move Tool marking menu. On, the whole selection travels
 * to the snap target as one and keeps its internal spacing; off, the snap aims at the selection
 * itself. Defaults to on when there is no window runtime.
 */
bool ED_maya_move_keep_spacing_get(const bContext *C);
/**
 * Maya's `manipMoveContext -xformConstraint`, from the Move Tool marking menu: what a moved
 * component stays attached to. Defaults to off when there is no window runtime.
 */
ed::maya::MayaTransformConstraint ED_maya_transform_constraint_get(const bContext *C);
/**
 * Radius in pixels a Maya snap target has to be inside of, derived from the tolerance settings.
 * \a region_size_px is what an unlimited tolerance resolves to, so the caller decides what
 * "anything viewable" means for its own query.
 */
float ED_maya_snap_tolerance_px_get(const bContext *C, int region_size_px);
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
/**
 * Hands a drag to Blender's own vertex or edge slide when the Edge transform constraint is on.
 * Returns true when the slide took the drag, which leaves the caller with nothing to transform.
 */
bool ED_maya_transform_slide_invoke(bContext *C, wmOperator *op, const wmEvent *event);
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
