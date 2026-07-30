/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup editors
 */

#pragma once

#include <cstdint>
#include <optional>

#include "BLI_math_vector_types.hh"

#include "maya_tool.hh"

namespace blender {

struct bContext;
struct wmEvent;

namespace ed::maya {

enum class MayaActionID : uint16_t {
  None,

  Confirm,
  Cancel,
  PointerMove,
  DebugDrag,

  BeginOrbit,
  BeginPan,
  BeginDolly,
  EndNavigation,
  BlockViewportNavigation,
  FrameSelected,
  Connect,
  BridgeOrFill,
  SubdivisionPreviewOff,
  SubdivisionPreviewOn,
  SubdivisionPreviewSurface,
  ObjectXRay,
  FaceCenters,
  WireframeOnShaded,
  ComponentMarkingMenu,
  /** The marking menu of a transform tool: hold its key and press `LMB`, or `Ctrl+Shift+RMB`. */
  ToolMarkingMenu,
  /** Polygon component selection marking menu: `Ctrl+RMB` over a component selection. */
  SelectionMarkingMenu,
  EditPivotKeyPressed,
  EditPivotKeyReleased,
  TogglePersistentPivot,
  FocusLost,

  ActivateTool,
  ToolHotkeyReleased,

  SelectPrimary,
  SelectAdd,
  SelectRemove,
  SelectToggle,
  /** Double click. The modifiers decide the set operation, the mesh decides loop versus path. */
  SelectTopology,
  SelectGrow,
  SelectShrink,

  ToggleObjectComponent,
  ComponentVertex,
  ComponentEdge,
  ComponentFace,
  ComponentUV,
  ComponentVertexFace,
  ComponentMulti,

  TemporarySnap,
};

enum class MayaActionPhase : uint8_t {
  Begin,
  Update,
  End,
  Cancel,
};

enum class MayaPointerButton : uint8_t {
  None,
  Left,
  Middle,
  Right,
};

struct MayaInputAction {
  MayaActionID id = MayaActionID::None;
  MayaActionPhase phase = MayaActionPhase::Begin;

  int2 mouse;
  int2 mouse_region;
  int2 mouse_delta;

  bool shift = false;
  bool ctrl = false;
  bool alt = false;

  MayaToolID tool = MayaToolID::None;
  MayaPointerButton pointer_button = MayaPointerButton::None;
  const wmEvent *source_event = nullptr;
};

/**
 * Momentary snap mode a physical key event resolves to, or #MayaSnapMode::None when the event does
 * not belong to a snap key at all.
 *
 * The single place that maps keys to snap modes. A press honours the modifiers that belong to other
 * bindings, while a release resolves whatever is held with it: the release is the only way back out
 * of the mode, and dropping one because `Ctrl` or `Alt` happened to be down is what used to leave
 * temporary snapping stuck on.
 */
MayaSnapMode snap_key_event_mode_get(int key_type, short key_val, uint8_t modifier);

}  // namespace ed::maya

std::optional<ed::maya::MayaInputAction> ED_maya_input_translate(const bContext *C,
                                                                 const wmEvent &event);

}  // namespace blender
