/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup editors
 */

#pragma once

#include <cstdint>
#include <cstdio>
#include <memory>

#include "BLI_math_matrix_types.hh"
#include "BLI_math_quaternion_types.hh"
#include "BLI_math_vector_types.hh"
#include "BLI_vector.hh"

#include "clarity_marking_menu.hh"
#include "clarity_navigation.hh"
#include "clarity_tool.hh"

namespace blender {

struct bContext;
struct ARegion;
struct Depsgraph;
struct ID;
struct Object;
struct ScrArea;
struct Scene;
struct WorkSpace;
struct wmPaintCursor;

namespace ed::transform {
struct SnapObjectContext;
}

namespace ed::clarity {

class ClarityInteractionSession;
struct ClarityInputAction;
struct ClarityPivotUndoState;
struct ClaritySelectionMemory;
struct ClarityShiftTransformState;
struct ClarityTransformDebugState;

enum class ClarityComponentMode : uint8_t {
  Object,
  Vertex,
  Edge,
  Face,
  UV,
  VertexFace,
  Multi,
};

enum class ClarityPivotMode : uint8_t {
  Object,
  SelectionCenter,
  Component,
  Custom,
};

/**
 * Edit Pivot is a toggle, so the mode has three states: off, on, and dragging the pivot.
 * #PivotCommitPending is the tail of a drag whose outcome (exit or restart) was decided while the
 * transform was still running.
 */
enum class ClarityPivotEditPhase : uint8_t {
  Normal,
  PivotDragging,
  PivotCommitPending,
  PersistentPivot,
};

enum class ClarityCameraBasedSelection : uint8_t {
  Off,
  On,
  Auto,
};

struct ClarityCustomPivotData {
  Scene *scene = nullptr;
  Object *object = nullptr;
  float location[3] = {};
  float rotation_quaternion[4] = {1.0f, 0.0f, 0.0f, 0.0f};
  int selection_mode = 0;
  int pivot_point = 0;
  int selected_counts[3] = {};
  int element_counts[3] = {};
  uint64_t selection_hash = 0;
  const void *bmesh_identity = nullptr;
  int active_element_index = -1;
  char active_element_type = 0;
  bool selection_signature_valid = false;
  bool position_valid = false;
  bool orientation_valid = false;
  bool pinned = false;
};

struct ClaritySnapObjectContextDeleter {
  void operator()(ed::transform::SnapObjectContext *context) const;
};

struct ClarityPivotEditState {
  ClarityPivotEditPhase phase = ClarityPivotEditPhase::Normal;
  ClarityPivotEditTarget target = ClarityPivotEditTarget::None;
  Scene *scene = nullptr;
  Object *object = nullptr;
  WorkSpace *workspace = nullptr;
  ScrArea *area = nullptr;
  ARegion *region = nullptr;
  ClarityToolID tool = ClarityToolID::None;
  uint64_t tool_revision = 0;
  /**
   * The user's toggle. Stays set even while the current context cannot host a pivot manipulator,
   * so validation can bring the mode back as soon as a supported context becomes active.
   */
  bool persistent = false;
  /** Leave the mode once the running pivot drag finishes. */
  bool exit_after_drag = false;
  /** Rebuild the mode for the new context once the running pivot drag finishes. */
  bool restart_after_drag = false;
  bool data_origin_was_enabled = false;
  std::unique_ptr<ClarityCustomPivotData> custom;
  bool follow_transform = false;
  float follow_location_initial[3] = {};
  float follow_translation_previous[3] = {};
  /**
   * Element under the mouse while a snap key is held, so the overlay can preview where a click
   * would put the pivot. #ClarityPivotSnapTargetType::None means there is nothing to draw.
   */
  ClarityPivotSnapResult snap_preview;
  /**
   * Reuse the object-mode query context and its temporary storage while the preview follows the
   * pointer. Edit mode deliberately keeps one-shot contexts because `ignore_editmode_filtering`
   * does not support repeated queries on the same context.
   */
  std::unique_ptr<ed::transform::SnapObjectContext, ClaritySnapObjectContextDeleter>
      snap_preview_context;
  /** Region-space mouse the preview was computed for, so a resting pointer costs nothing. */
  int2 snap_preview_mouse = int2(0);
  bool snap_preview_queried = false;
};

/**
 * Momentary snap modes and the keys that hold them.
 *
 * Temporary snapping is driven by physical keys, and every event has to reach exactly one entry
 * point here. The state is keyed by the physical key instead of by the mode it engages: a release
 * only has to name its key, so it can never be dropped because the mode that key would name
 * changed while it was down, and a fresh press of a key that is still listed rebuilds the entry
 * instead of trusting one whose release was lost.
 *
 * Pure state, so the rules are unit tested without a window manager.
 */
class ClaritySnapOverride {
 public:
  /**
   * Key down. False when the state was already what the press asks for, a key repeat included.
   * A press of a key that is still held with another mode replaces it: the only way to get there
   * is a release that never arrived, so the press is the more recent truth.
   *
   * \a window_tracks_key records whether the window reports this key as the one held non-modifier
   * key. That is the only key whose loss #release_window_tracked_keys can prove.
   */
  bool press(const int key, const ClaritySnapMode mode, const bool window_tracks_key = false)
  {
    if (mode == ClaritySnapMode::None) {
      return false;
    }
    for (int64_t i = held_.size() - 1; i >= 0; i--) {
      if (held_[i].key != key) {
        continue;
      }
      if (held_[i].mode == mode) {
        return false;
      }
      held_.remove(i);
    }
    held_.append({key, mode, window_tracks_key});
    return true;
  }

  /**
   * Key up for every key the window used to track and no longer does. Never touches a key whose
   * state cannot be observed, so an overlapping second key keeps its mode.
   */
  bool release_window_tracked_keys()
  {
    bool changed = false;
    for (int64_t i = held_.size() - 1; i >= 0; i--) {
      if (held_[i].window_tracks_key) {
        held_.remove(i);
        changed = true;
      }
    }
    return changed;
  }

  /** Key up. Drops what the key holds, whatever modifiers happened to come with the release. */
  bool release(const int key)
  {
    bool changed = false;
    for (int64_t i = held_.size() - 1; i >= 0; i--) {
      if (held_[i].key == key) {
        held_.remove(i);
        changed = true;
      }
    }
    return changed;
  }

  /** Every key is considered released: lost focus, a preset change, a mode rebuild. */
  bool clear()
  {
    if (held_.is_empty()) {
      return false;
    }
    held_.clear();
    return true;
  }

  /** The mode that wins: the most recently pressed key. */
  ClaritySnapMode active() const
  {
    return held_.is_empty() ? ClaritySnapMode::None : held_.last().mode;
  }

  bool is_empty() const
  {
    return held_.is_empty();
  }

  int64_t held_num() const
  {
    return held_.size();
  }

 private:
  struct HeldKey {
    int key = 0;
    ClaritySnapMode mode = ClaritySnapMode::None;
    bool window_tracks_key = false;
  };

  Vector<HeldKey, 5> held_;
};

struct ClarityTemporaryOverrides {
  ClaritySnapOverride snap;
  bool edit_pivot = false;
};


struct ClaritySelectionSettings {
  bool preserve_component_selection = true;
  /**
   * Clarity keeps these apart, and so does its Move Tool marking menu: one decides whether a `Shift`
   * drag extrudes components, the other whether it duplicates objects.
   */
  bool shift_extrude = true;
  bool shift_duplicate = true;
  bool shift_duplicate_linked = false;
  bool keep_faces_together = true;
  float click_box_size = 4.0f;
  float manipulation_box_size = 10.0f;
  ClarityCameraBasedSelection camera_based_selection = ClarityCameraBasedSelection::Auto;
  bool highlight_backfaces = true;
  /** Clarity `polySelectConstraint`: global, and shown by more than one marking menu. */
  ClaritySelectionConstraint selection_constraint = ClaritySelectionConstraint::Off;
};

struct ClarityWindowRuntime {
  ClarityWindowRuntime();
  ~ClarityWindowRuntime();
  ClarityWindowRuntime(ClarityWindowRuntime &&other);
  ClarityWindowRuntime &operator=(ClarityWindowRuntime &&other);
  ClarityWindowRuntime(const ClarityWindowRuntime &other) = delete;
  ClarityWindowRuntime &operator=(const ClarityWindowRuntime &other) = delete;

  ClarityToolState tool;
  ClarityComponentMode component_mode = ClarityComponentMode::Object;
  ClarityComponentMode last_component_mode = ClarityComponentMode::Vertex;
  ClarityPivotMode pivot_mode = ClarityPivotMode::Object;
  ClarityPivotEditState pivot_edit;
  std::unique_ptr<ClarityPivotUndoState> pivot_undo;
  ClaritySelectionSettings selection_settings;
  ClarityMoveToolSettings move_tool_settings;

  std::unique_ptr<ClarityInteractionSession> active_session;
  std::shared_ptr<ClaritySelectionMemory> selection_memory;
  std::shared_ptr<ClarityShiftTransformState> shift_transform;
  std::unique_ptr<ClarityTransformDebugState> transform_debug;
  /** Cursor overlay that previews subtract/add while `Ctrl`/`Ctrl+Shift` is held in this window. */
  wmPaintCursor *selection_cursor = nullptr;
  /**
   * A marquee is a modal gesture, so what it selected only exists once it ends. The selection
   * constraint cannot run at the moment the marquee starts; it is applied on the first event after
   * the gesture is over.
   */
  bool selection_constraint_pending = false;
  /**
   * The component that was active before the last component pick.
   *
   * A double click arrives after the single click that precedes it, and that click has already
   * moved the active component onto whatever is under the pointer. Every Clarity topology gesture
   * reads the pair - the component that was selected and the one just double clicked - to decide
   * which way a loop runs or which two ends a path joins, so the first of the two has to be
   * remembered before the click overwrites it. Without it every gesture would ask for the way from
   * the clicked component to itself, which is one component long.
   *
   * Kept as a type and an index rather than a pointer because an index survives anything that
   * reallocates the mesh; both are validated against the object they were taken from before use.
   */
  const Object *topology_anchor_object = nullptr;
  int topology_anchor_index = -1;
  char topology_anchor_htype = 0;
  bool transform_active = false;
  uint64_t instance_id = 0;
  uint64_t interaction_revision_seen = 0;
  ClarityTemporaryOverrides temporary;
  ClarityNavigationSettings navigation_settings;
  double last_tool_activation_time = 0.0;
  double last_tool_activation_duration_ms = 0.0;

  bool navigation_active() const;
};

class ClarityTransformTransaction {
 public:
  ClarityTransformTransaction(Depsgraph *depsgraph, Scene *scene);
  ~ClarityTransformTransaction();
  ClarityTransformTransaction(const ClarityTransformTransaction &) = delete;
  ClarityTransformTransaction &operator=(const ClarityTransformTransaction &) = delete;

  bool capture_object(Object &object);
  bool capture_geometry(ID &data);
  bool capture_child(Object &child);
  bool capture_runtime(ClarityManipulatorPivotState &state);
  bool transform_geometry(ID &data, const float4x4 &matrix);

  void commit();
  void rollback();

 private:
  struct Impl;
  std::unique_ptr<Impl> impl_;
};

ClarityWindowRuntime *runtime_get(const bContext *C);
ClarityWindowRuntime *runtime_ensure(const bContext *C);
bool navigation_debug_logging_enabled(const bContext *C);
int navigation_frame_rate_limit_setting(const bContext *C);
/**
 * The viewport performance trace, opened for appending. Rotates the previous run to
 * `clarity_navigation_trace.prev.log` and writes a `RUN` header the first time it is called in a
 * process, so one run is one file and aggregates cannot mix builds.
 */
std::FILE *navigation_trace_file_open();
bool pivot_edit_toggle_persistent(bContext *C, ClarityWindowRuntime &runtime);
bool pivot_edit_resume_persistent(bContext *C, ClarityWindowRuntime &runtime);
bool pivot_edit_pin_toggle(bContext *C, ClarityWindowRuntime &runtime);
void pivot_edit_tool_changed(bContext *C, ClarityWindowRuntime &runtime);
ClarityDispatchResult pivot_edit_click_handle_action(bContext *C,
                                                   ClarityWindowRuntime &runtime,
                                                   const ClarityInputAction &action);
void pivot_edit_selection_changed(bContext *C, ClarityWindowRuntime &runtime);
/**
 * Refresh the hovered snap target used by the pivot snap preview. Clears the target unless Edit
 * Pivot owns a manipulator, a temporary snap key is held and no transform is running, and skips
 * the query while the pointer rests on the position it was last computed for.
 */
void pivot_edit_snap_preview_update(const bContext *C,
                                    ClarityWindowRuntime &runtime,
                                    const int2 &mouse_region);
void pivot_edit_snap_preview_clear(ClarityWindowRuntime &runtime);
/**
 * Radius in pixels a snap target has to be inside of.
 *
 * \a region_size_px is what an unlimited tolerance resolves to, so each query decides for itself
 * what Clarity's "snap to anything viewable" means. Pure, so the rule is unit tested.
 */
float snap_tolerance_radius_px(const ClaritySnapToleranceSettings &settings,
                               int region_size_px,
                               float pixel_size);

/**
 * Mirror the active tool for the UI reads, so the Step Snap widget can show the step of the tool the
 * next drag will use. Called from every place that changes the tool, and from nowhere else.
 */
void tool_mirror_sync(const bContext *C, ClarityToolID tool);
void snap_override_mirror_sync(const bContext *C, const ClarityWindowRuntime &runtime);
void snap_override_revision_reconcile(const bContext *C, ClarityWindowRuntime &runtime);
void snap_override_key_state_reconcile(const bContext *C, ClarityWindowRuntime &runtime);
void pivot_edit_input_reset(bContext *C, ClarityWindowRuntime &runtime);
void pivot_edit_validate(bContext *C, ClarityWindowRuntime &runtime);
void pivot_edit_end(bContext *C, ClarityWindowRuntime &runtime);

}  // namespace ed::clarity
}  // namespace blender
