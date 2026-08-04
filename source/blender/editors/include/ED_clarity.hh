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

namespace ed::clarity {

enum class ClarityDispatchResult : uint8_t {
  PassThrough,
  Handled,
  StartModal,
};

enum class ClarityPivotEditTarget : uint8_t {
  None,
  ObjectOrigin,
  ComponentPivot,
};

enum class ClarityPivotTargetType : uint8_t {
  Object,
  Component,
};

/**
 * Which stored pivot a caller asks for. Rotate and scale pivots are authored independently, so the
 * requested usage decides which one may override the regular transform center.
 */
enum class ClarityPivotUsage : uint8_t {
  /** Rotation around the custom rotate pivot (#TFM_ROTATION, #TFM_TRACKBALL). */
  Rotate,
  /** Scaling around the custom scale pivot (#TFM_RESIZE). */
  Scale,
  /** Gizmo drawing and snapping: follow the pivot of the active Clarity tool. */
  Display,
};

enum eClarityPivotResetMode : uint8_t {
  CLARITY_PIVOT_RESET_CENTER = 0,
  CLARITY_PIVOT_RESET_ZERO = 1,
};

enum eClarityPivotBakeMode : uint8_t {
  CLARITY_PIVOT_BAKE_POSITION = 0,
  CLARITY_PIVOT_BAKE_ORIENTATION,
  CLARITY_PIVOT_BAKE_BOTH,
};

struct ClarityPivotFrame {
  double3 position_world = double3(0.0);
  math::QuaternionBase<double> orientation_world = math::QuaternionBase<double>::identity();
  bool position_valid = false;
  bool orientation_valid = false;
};

enum class ClarityPivotSnapTargetType : uint8_t {
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

struct ClarityPivotSnapResult {
  std::optional<double3> position_world;
  std::optional<math::QuaternionBase<double>> orientation_world;
  ClarityPivotSnapTargetType type = ClarityPivotSnapTargetType::None;
  Object *object = nullptr;
  std::optional<float4x4> object_to_world;
  int component_index = -1;
};

struct ClarityPivotToolSettings {
  bool pin_component_pivot = false;
  bool snap_position = true;
  bool snap_orientation = true;
  bool bake_orientation_automatically = false;
  bool preserve_children = true;
  bool show_orientation_handle = true;
  eClarityPivotResetMode reset_mode = CLARITY_PIVOT_RESET_CENTER;
  int active_axis = 0;
};

struct ClarityObjectRuntimeRef {
  uint32_t session_uid = 0;
  char id_name[MAX_ID_NAME] = {};
};

class ClarityPivotEditTargetBackend {
 public:
  virtual ~ClarityPivotEditTargetBackend() = default;

  virtual ClarityPivotTargetType type() const = 0;
  virtual ClarityPivotFrame frame_get() const = 0;
  virtual bool position_set(const double3 &position_world, bool preserve) = 0;
  virtual bool orientation_set(const math::QuaternionBase<double> &orientation_world,
                               bool bake) = 0;
  virtual void reset_position(eClarityPivotResetMode mode) = 0;
  virtual void reset_orientation() = 0;
  virtual void cancel() = 0;
  virtual void commit() = 0;
};

enum class ClaritySnapMode : uint8_t {
  None,
  Grid,
  Curve,
  Point,
  ViewPlane,
  MeshCenter,
  /** Discrete steps. #ClarityStepSnapSettings decides how big they are and what they are measured
   * from, exactly like Clarity's Step Snap settings behind the same key. */
  Step,
};

/**
 * Clarity's `manipMoveContext -xformConstraint`: what the moved components stay attached to. Lives
 * here rather than with the rest of the marking menu state because the transform module is what
 * has to honor it.
 */
enum class ClarityTransformConstraint : uint8_t {
  Off = 0,
  Edge = 1,
  Surface = 2,
};

enum eClarityStepSnapMode : uint8_t {
  /** Steps counted from where the transform started. Clarity's default. */
  CLARITY_STEP_SNAP_RELATIVE = 0,
  /** Steps counted from the world origin, so the result lands on multiples of the step. */
  CLARITY_STEP_SNAP_ABSOLUTE = 1,
};

struct ClarityStepSnapSettings {
  eClarityStepSnapMode mode = CLARITY_STEP_SNAP_RELATIVE;
  /** One step of a translation, in scene units. */
  float size = 1.0f;
  /**
   * One step of a rotation, in radians. Clarity's own default is 15 degrees, spelled out here so this
   * widely included header does not have to pull in the math constants for it.
   */
  float angle = 0.261799388f;
};

/**
 * Clarity's snapping tolerance: the region around the pointer a target has to be in to win.
 * With #limited off the region is the whole viewport, which is Clarity's "snap to anything viewable".
 */
struct ClaritySnapToleranceSettings {
  bool limited = true;
  int size_px = 10;
};

enum class ClarityNavigationDebugStage : uint8_t {
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

}  // namespace ed::clarity

/**
 * Whether the temporary manipulator trace is on, set by the `BLENDER_CLARITY_GIZMO_TRACE` environment
 * variable. Remove together with the trace once the manipulator lifecycle is settled.
 */
bool ED_clarity_gizmo_trace_enabled();

bool ED_clarity_interaction_enabled(const bContext *C);
/**
 * Whether the Clarity interaction model owns this session at all, regardless of what the pointer
 * happens to be over. #ED_clarity_interaction_enabled additionally requires a 3D View, so it answers
 * "may this event be interpreted here", not "is the Clarity model active".
 */
bool ED_clarity_interaction_preset_enabled(const bContext *C);
ed::clarity::ClarityObjectRuntimeRef ED_clarity_object_runtime_ref_create(const Object &object);
Object *ED_clarity_object_runtime_ref_resolve(
    Main &bmain, const ed::clarity::ClarityObjectRuntimeRef &reference);
void ED_operatortypes_clarity();
ed::clarity::ClarityDispatchResult ED_clarity_event_dispatch(bContext *C, const wmEvent *event);
int ED_clarity_interaction_frame_rate_limit(const bContext *C);
bool ED_clarity_navigation_debug_active(const bContext *C);
ed::clarity::ClarityPivotEditTarget ED_clarity_pivot_edit_target_get(const bContext *C);
bool ED_clarity_pivot_custom_matrix_get(const bContext *C,
                                     ed::clarity::ClarityPivotUsage usage,
                                     float r_matrix[4][4]);
bool ED_clarity_pivot_custom_orientation_get(const bContext *C, float r_orientation[3][3]);
bool ED_clarity_pivot_edit_data_get(const bContext *C,
                                 float **r_location,
                                 float **r_rotation_quaternion);
std::unique_ptr<ed::clarity::ClarityPivotEditTargetBackend> ED_clarity_pivot_edit_target_create(
    bContext *C);
void ED_clarity_pivot_reset_position(bContext *C, ed::clarity::eClarityPivotResetMode mode);
void ED_clarity_pivot_reset_orientation(bContext *C);
void ED_clarity_pivot_reset_all(bContext *C, ed::clarity::eClarityPivotResetMode mode);
void ED_clarity_pivot_undo_begin(const bContext *C);
bool ED_clarity_pivot_bake(bContext *C, ed::clarity::eClarityPivotBakeMode mode);
/**
 * Read-only world-space frame of the runtime pivot manipulator of the context window. Returns
 * false when the window has no Clarity runtime yet; the validity flags of \a r_frame tell whether the
 * position and the orientation carry a pivot the user actually authored.
 */
bool ED_clarity_pivot_manipulator_state_get(const bContext *C, ed::clarity::ClarityPivotFrame &r_frame);
/**
 * Element the pivot would snap to if the user clicked now. Only filled while Edit Pivot is active
 * and a temporary snap key is held, so a false return means the overlay has nothing to draw.
 */
bool ED_clarity_pivot_snap_preview_get(const bContext *C, ed::clarity::ClarityPivotSnapResult &r_result);
bool ED_clarity_pivot_tool_settings_get(const bContext *C,
                                     ed::clarity::ClarityPivotToolSettings &r_settings);
bool ED_clarity_pivot_tool_settings_set(const bContext *C,
                                     const ed::clarity::ClarityPivotToolSettings &settings);
void ED_clarity_pivot_active_axis_set(const bContext *C, int active_axis);
bool ED_clarity_pivot_orientation_aim(ed::clarity::ClarityPivotFrame &frame,
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
bool ED_clarity_snap_key_event_apply(const bContext *C,
                                  int key_type,
                                  short key_val,
                                  uint8_t modifier);
/**
 * Treat every momentary snap key as released. For the cases where the release itself can never
 * reach the dispatcher — the pointer left the 3D View, a popup swallowed the event — which is what
 * used to leave temporary snapping stuck on.
 */
bool ED_clarity_snap_override_release_all(const bContext *C);
ed::clarity::ClaritySnapMode ED_clarity_snap_override_get(const bContext *C);
bool ED_clarity_snap_mode_set(const bContext *C, ed::clarity::ClaritySnapMode mode);
ed::clarity::ClaritySnapMode ED_clarity_snap_mode_get(const bContext *C);
/** Step size and reference of #ed::clarity::ClaritySnapMode::Step, the defaults when there is no window. */
ed::clarity::ClarityStepSnapSettings ED_clarity_snap_step_settings_get(const bContext *C);
ed::clarity::ClaritySnapToleranceSettings ED_clarity_snap_tolerance_settings_get(const bContext *C);
/**
 * Clarity's `snapComponentsRelative`, from the Move Tool marking menu. On, the whole selection travels
 * to the snap target as one and keeps its internal spacing; off, the snap aims at the selection
 * itself. Defaults to on when there is no window runtime.
 */
bool ED_clarity_move_keep_spacing_get(const bContext *C);
/**
 * Clarity's `manipMoveContext -xformConstraint`, from the Move Tool marking menu: what a moved
 * component stays attached to. Defaults to off when there is no window runtime.
 */
ed::clarity::ClarityTransformConstraint ED_clarity_transform_constraint_get(const bContext *C);
/**
 * Radius in pixels a Clarity snap target has to be inside of, derived from the tolerance settings.
 * \a region_size_px is what an unlimited tolerance resolves to, so the caller decides what
 * "anything viewable" means for its own query.
 */
float ED_clarity_snap_tolerance_px_get(const bContext *C, int region_size_px);
void ED_clarity_pivot_event_pre_modal(bContext *C, const wmEvent *event);
void ED_clarity_transform_begin(
    const bContext *C,
    const char *operator_id,
    int context_mode,
    int mesh_select_mode,
    bool is_clarity_pivot_transform);
void ED_clarity_transform_update(const bContext *C, const float world_translation[3]);
void ED_clarity_transform_end(bContext *C, bool cancelled);
void ED_clarity_undo_step_store(const bContext *C);
void ED_clarity_undo_step_clear(const bContext *C);
void ED_clarity_undo_steps_restore(
    bContext *C, const UndoStep *step_from, const UndoStep *step_to, bool is_undo);
bool ED_clarity_shift_transform_prepare(bContext *C, wmOperator *op, const wmEvent *event);
/**
 * Hands a drag to Blender's own vertex or edge slide when the Edge transform constraint is on.
 * Returns true when the slide took the drag, which leaves the caller with nothing to transform.
 */
bool ED_clarity_transform_slide_invoke(bContext *C, wmOperator *op, const wmEvent *event);
void ED_clarity_navigation_debug_stage_sample(
    const bContext *C,
    ed::clarity::ClarityNavigationDebugStage stage,
    double duration_ms,
    double detail_a_ms = 0.0,
    double detail_b_ms = 0.0,
    int area_type = -1,
    int region_type = -1);
void ED_clarity_viewport_debug_event(const bContext *C,
                                  ed::clarity::ClarityNavigationDebugStage stage,
                                  int code,
                                  int detail_a,
                                  int detail_b,
                                  int area_type,
                                  int region_type);
void ED_clarity_runtime_free(bContext *C, const wmWindow *win);

}  // namespace blender
