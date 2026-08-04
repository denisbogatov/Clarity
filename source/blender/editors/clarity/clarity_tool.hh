/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup editors
 */

#pragma once

#include <cstdint>

#include "BLI_enum_flags.hh"
#include "BLI_math_quaternion_types.hh"
#include "BLI_math_vector_types.hh"

#include "ED_clarity.hh"

namespace blender {

struct bContext;

namespace ed::clarity {

struct ClarityWindowRuntime;

enum class ClarityToolID : uint8_t {
  None,
  Select,
  Move,
  Rotate,
  Scale,
  MultiCut,
  TargetWeld,
  QuadDraw,
};

struct ClarityManipulatorPivotState {
  double3 position_world = double3(0.0);
  math::QuaternionBase<double> orientation_world = math::QuaternionBase<double>::identity();
  bool position_valid = false;
  bool orientation_valid = false;
  bool pin_component_pivot = false;
  bool snap_position = true;
  bool snap_orientation = true;
  eClarityPivotResetMode reset_mode = CLARITY_PIVOT_RESET_CENTER;
  bool bake_orientation_automatically = false;
  bool preserve_children = true;
  bool show_orientation_handle = true;
  ClarityObjectRuntimeRef last_object;
  int active_axis = 0;
  /**
   * Orientation the manipulator had the last time it was derived from a world matrix. An
   * orthonormalized basis has several valid solutions that differ by a half turn, and the raw
   * choice can flip between entries on mirrored or negatively scaled objects. Keeping the previous
   * result lets the closest solution win, so the handles stay where the user left them.
   */
  math::QuaternionBase<double> previous_world_orientation =
      math::QuaternionBase<double>::identity();
  bool previous_world_orientation_valid = false;
};

struct ClarityToolState {
  ClarityToolID active = ClarityToolID::Select;
  ClarityToolID previous = ClarityToolID::Select;
  /** Physical `Q/W/E/R` currently held, independent of Blender's single generic key-modifier. */
  ClarityToolID held_hotkey = ClarityToolID::None;
  uint64_t revision = 0;
  /**
   * The window runtime is not serialized, so a fresh runtime adopts the tool from the 3D View
   * manipulator state once. This keeps the active tool across file load and new windows instead of
   * silently resetting it to Select.
   */
  bool adopted_from_view = false;
  ClarityManipulatorPivotState manipulator_pivot;
};

enum class ClarityToolCapability : uint32_t {
  None = 0,
  UsesSelection = 1 << 0,
  UsesManipulator = 1 << 1,
  SupportsObject = 1 << 2,
  SupportsComponents = 1 << 3,
};
ENUM_OPERATORS(ClarityToolCapability);

struct ClarityToolType {
  ClarityToolID id;
  const char *idname;
  const char *label;

  ClarityToolCapability capabilities;

  bool (*poll)(const bContext *C, const ClarityWindowRuntime &runtime);
  void (*activate)(bContext *C, ClarityWindowRuntime &runtime);
  void (*deactivate)(bContext *C, ClarityWindowRuntime &runtime);
};

enum class ClarityToolActivationReason : uint8_t {
  Hotkey,
  Shelf,
  MarkingMenu,
  Startup,
  ContextFallback,
  Internal,
};

enum class ClarityToolActivationResult : uint8_t {
  Activated,
  AlreadyActive,
  Rejected,
  BlockedBySession,
};

}  // namespace ed::clarity

const ed::clarity::ClarityToolType *ED_clarity_tool_type_find(ed::clarity::ClarityToolID tool_id);
/**
 * Keep the globally active Clarity tool and the 3D View under the cursor in sync: adopt the tool from
 * the view once for a fresh runtime, then re-apply the manipulator to new areas, other workspaces,
 * and views changed outside the Clarity tools.
 */
void ED_clarity_tool_gizmo_state_ensure(bContext *C, ed::clarity::ClarityToolState &tool);
ed::clarity::ClarityToolActivationResult ED_clarity_tool_activate(
    bContext *C,
    ed::clarity::ClarityToolID tool_id,
    ed::clarity::ClarityToolActivationReason reason);

}  // namespace blender
