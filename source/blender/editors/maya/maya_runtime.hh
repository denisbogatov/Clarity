/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup editors
 */

#pragma once

#include <cstdint>
#include <memory>

#include "BLI_vector.hh"

#include "maya_navigation.hh"
#include "maya_tool.hh"

namespace blender {

struct bContext;
struct ARegion;
struct Object;
struct ScrArea;
struct Scene;
struct WorkSpace;

namespace ed::maya {

class MayaInteractionSession;
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

enum class MayaPivotEditPhase : uint8_t {
  Normal,
  PivotArmed,
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
  bool persistent = false;
  bool exit_after_drag = false;
  bool restart_after_drag = false;
  bool restart_after_cancel = false;
  bool restart_persistent = false;
  bool data_origin_was_enabled = false;
  std::unique_ptr<MayaCustomPivotData> custom;
  bool follow_transform = false;
  float follow_location_initial[3] = {};
  float follow_translation_previous[3] = {};
};

struct MayaTemporaryOverrides {
  Vector<MayaSnapMode, 5> snap_stack;
  bool edit_pivot = false;
};

struct MayaPhysicalInputState {
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
  MayaPhysicalInputState physical_input;
  MayaTemporaryOverrides temporary;
  MayaNavigationSettings navigation_settings;
  double last_tool_activation_time = 0.0;
  double last_tool_activation_duration_ms = 0.0;

  bool navigation_active() const;
};

MayaWindowRuntime *runtime_get(const bContext *C);
MayaWindowRuntime *runtime_ensure(const bContext *C);
bool navigation_debug_logging_enabled(const bContext *C);
int navigation_frame_rate_limit_setting(const bContext *C);
bool pivot_edit_key_press(bContext *C, MayaWindowRuntime &runtime);
bool pivot_edit_key_release(bContext *C, MayaWindowRuntime &runtime);
bool pivot_edit_toggle_persistent(bContext *C, MayaWindowRuntime &runtime);
bool pivot_edit_resume_persistent(bContext *C, MayaWindowRuntime &runtime);
bool pivot_edit_pin_toggle(bContext *C, MayaWindowRuntime &runtime);
void pivot_edit_focus_lost(bContext *C, MayaWindowRuntime &runtime);
void pivot_edit_validate(bContext *C, MayaWindowRuntime &runtime);
void pivot_edit_end(bContext *C, MayaWindowRuntime &runtime);

}  // namespace ed::maya
}  // namespace blender
