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
  SelectMarquee,
  SelectLoop,
  SelectPath,
  SelectGrow,
  SelectShrink,

  ToggleObjectComponent,
  ComponentVertex,
  ComponentEdge,
  ComponentFace,
  ComponentUV,
  ComponentVertexFace,
  ComponentMulti,

  TemporaryGridSnap,
  TemporaryCurveSnap,
  TemporaryPointSnap,
  TemporaryStepSnap,
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

}  // namespace ed::maya

std::optional<ed::maya::MayaInputAction> ED_maya_input_translate(const bContext *C,
                                                                 const wmEvent &event);

}  // namespace blender
