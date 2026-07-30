/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup editors
 */

#pragma once

#include <cstdint>
#include <memory>

#include "BLI_math_matrix_types.hh"
#include "BLI_math_quaternion_types.hh"
#include "BLI_math_vector_types.hh"
#include "BLI_vector.hh"

#include "maya_navigation.hh"
#include "maya_tool.hh"

namespace blender {

struct bContext;
struct ARegion;
struct Depsgraph;
struct ID;
struct Object;
struct ScrArea;
struct Scene;
struct WorkSpace;

namespace ed::maya {

class MayaInteractionSession;
struct MayaInputAction;
struct MayaPivotUndoState;
struct MayaSelectionMemory;
struct MayaShiftTransformState;
struct MayaTransformDebugState;

enum class MayaComponentMode : uint8_t {
  Object,
  Vertex,
  Edge,
  Face,
  UV,
  VertexFace,
  Multi,
};

enum class MayaPivotMode : uint8_t {
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
enum class MayaPivotEditPhase : uint8_t {
  Normal,
  PivotDragging,
  PivotCommitPending,
  PersistentPivot,
};

enum class MayaCameraBasedSelection : uint8_t {
  Off,
  On,
  Auto,
};

struct MayaCustomPivotData {
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

struct MayaPivotEditState {
  MayaPivotEditPhase phase = MayaPivotEditPhase::Normal;
  MayaPivotEditTarget target = MayaPivotEditTarget::None;
  Scene *scene = nullptr;
  Object *object = nullptr;
  WorkSpace *workspace = nullptr;
  ScrArea *area = nullptr;
  ARegion *region = nullptr;
  MayaToolID tool = MayaToolID::None;
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
  std::unique_ptr<MayaCustomPivotData> custom;
  bool follow_transform = false;
  float follow_location_initial[3] = {};
  float follow_translation_previous[3] = {};
  /**
   * Element under the mouse while a snap key is held, so the overlay can preview where a click
   * would put the pivot. #MayaPivotSnapTargetType::None means there is nothing to draw.
   */
  MayaPivotSnapResult snap_preview;
  /** Region-space mouse the preview was computed for, so a resting pointer costs nothing. */
  int2 snap_preview_mouse = int2(0);
  bool snap_preview_queried = false;
};

/**
 * Momentary snap modes and the keys that hold them.
 *
 * Temporary snapping is driven by physical keys, and every event has to reach exactly one entry
 * point here. Appending to a bare stack from several call sites is what let a mode stay held after
 * its key was already up — a repeated press stacked a second copy, and a release that never arrived
 * (a popup or another editor swallowed it) left the mode on with no way back.
 *
 * Pure state, so the rules are unit tested without a window manager.
 */
class MayaSnapOverride {
 public:
  /** `Shift+J` and `J` are the same physical key, so the two step modes never stack. */
  static bool modes_share_key(MayaSnapMode a, MayaSnapMode b)
  {
    if (a == b) {
      return true;
    }
    const auto is_step = [](const MayaSnapMode mode) {
      return ELEM(mode, MayaSnapMode::StepAbsolute, MayaSnapMode::StepRelative);
    };
    return is_step(a) && is_step(b);
  }

  /** Key down. False when the state was already what the press asks for, a key repeat included. */
  bool press(const MayaSnapMode mode)
  {
    if (mode == MayaSnapMode::None || holds_key_of(mode)) {
      return false;
    }
    held_.append(mode);
    return true;
  }

  /** Key up. Drops every mode the key owns, so a stray release cannot corrupt the stack. */
  bool release(const MayaSnapMode mode)
  {
    if (mode == MayaSnapMode::None) {
      return false;
    }
    bool changed = false;
    for (int64_t i = held_.size() - 1; i >= 0; i--) {
      if (modes_share_key(held_[i], mode)) {
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
  MayaSnapMode active() const
  {
    return held_.is_empty() ? MayaSnapMode::None : held_.last();
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
  bool holds_key_of(const MayaSnapMode mode) const
  {
    for (const MayaSnapMode held : held_) {
      if (modes_share_key(held, mode)) {
        return true;
      }
    }
    return false;
  }

  Vector<MayaSnapMode, 5> held_;
};

struct MayaTemporaryOverrides {
  MayaSnapOverride snap;
  bool edit_pivot = false;
};


struct MayaSelectionSettings {
  bool preserve_component_selection = true;
  bool shift_drag_duplicate = true;
  bool shift_duplicate_linked = false;
  bool keep_faces_together = true;
  float click_box_size = 4.0f;
  float manipulation_box_size = 10.0f;
  MayaCameraBasedSelection camera_based_selection = MayaCameraBasedSelection::Off;
  bool highlight_backfaces = true;
};

struct MayaWindowRuntime {
  MayaWindowRuntime();
  ~MayaWindowRuntime();
  MayaWindowRuntime(MayaWindowRuntime &&other);
  MayaWindowRuntime &operator=(MayaWindowRuntime &&other);
  MayaWindowRuntime(const MayaWindowRuntime &other) = delete;
  MayaWindowRuntime &operator=(const MayaWindowRuntime &other) = delete;

  MayaToolState tool;
  MayaComponentMode component_mode = MayaComponentMode::Object;
  MayaComponentMode last_component_mode = MayaComponentMode::Vertex;
  MayaPivotMode pivot_mode = MayaPivotMode::Object;
  MayaPivotEditState pivot_edit;
  std::unique_ptr<MayaPivotUndoState> pivot_undo;
  MayaSelectionSettings selection_settings;

  std::unique_ptr<MayaInteractionSession> active_session;
  std::shared_ptr<MayaSelectionMemory> selection_memory;
  std::shared_ptr<MayaShiftTransformState> shift_transform;
  std::unique_ptr<MayaTransformDebugState> transform_debug;
  bool transform_active = false;
  uint64_t instance_id = 0;
  uint64_t interaction_revision_seen = 0;
  MayaTemporaryOverrides temporary;
  MayaNavigationSettings navigation_settings;
  double last_tool_activation_time = 0.0;
  double last_tool_activation_duration_ms = 0.0;

  bool navigation_active() const;
};

class MayaTransformTransaction {
 public:
  MayaTransformTransaction(Depsgraph *depsgraph, Scene *scene);
  ~MayaTransformTransaction();
  MayaTransformTransaction(const MayaTransformTransaction &) = delete;
  MayaTransformTransaction &operator=(const MayaTransformTransaction &) = delete;

  bool capture_object(Object &object);
  bool capture_geometry(ID &data);
  bool capture_child(Object &child);
  bool capture_runtime(MayaManipulatorPivotState &state);
  bool transform_geometry(ID &data, const float4x4 &matrix);

  void commit();
  void rollback();

 private:
  struct Impl;
  std::unique_ptr<Impl> impl_;
};

MayaWindowRuntime *runtime_get(const bContext *C);
MayaWindowRuntime *runtime_ensure(const bContext *C);
bool navigation_debug_logging_enabled(const bContext *C);
int navigation_frame_rate_limit_setting(const bContext *C);
bool pivot_edit_toggle_persistent(bContext *C, MayaWindowRuntime &runtime);
bool pivot_edit_resume_persistent(bContext *C, MayaWindowRuntime &runtime);
bool pivot_edit_pin_toggle(bContext *C, MayaWindowRuntime &runtime);
MayaDispatchResult pivot_edit_click_handle_action(bContext *C,
                                                   MayaWindowRuntime &runtime,
                                                   const MayaInputAction &action);
void pivot_edit_selection_changed(bContext *C, MayaWindowRuntime &runtime);
/**
 * Refresh the hovered snap target used by the pivot snap preview. Clears the target unless Edit
 * Pivot owns a manipulator, a temporary snap key is held and no transform is running, and skips
 * the query while the pointer rests on the position it was last computed for.
 */
void pivot_edit_snap_preview_update(const bContext *C,
                                    MayaWindowRuntime &runtime,
                                    const int2 &mouse_region);
void pivot_edit_snap_preview_clear(MayaWindowRuntime &runtime);
void snap_override_mirror_sync(const bContext *C, const MayaWindowRuntime &runtime);
void snap_override_revision_reconcile(const bContext *C, MayaWindowRuntime &runtime);
void pivot_edit_input_reset(bContext *C, MayaWindowRuntime &runtime);
void pivot_edit_validate(bContext *C, MayaWindowRuntime &runtime);
void pivot_edit_end(bContext *C, MayaWindowRuntime &runtime);

}  // namespace ed::maya
}  // namespace blender
