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

#include "clarity_tool.hh"

namespace blender {

struct bContext;
struct wmEvent;

namespace ed::clarity {

enum class ClarityActionID : uint16_t {
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
  Extrude,
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
  /** `Ctrl+Shift+LMB` without a drag: consumed because this chord belongs to the add marquee. */
  SelectAddMarquee,
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

enum class ClarityActionPhase : uint8_t {
  Begin,
  Update,
  End,
  Cancel,
};

enum class ClarityPointerButton : uint8_t {
  None,
  Left,
  Middle,
  Right,
};

struct ClarityInputAction {
  ClarityActionID id = ClarityActionID::None;
  ClarityActionPhase phase = ClarityActionPhase::Begin;

  int2 mouse;
  int2 mouse_region;
  int2 mouse_delta;

  bool shift = false;
  bool ctrl = false;
  bool alt = false;

  ClarityToolID tool = ClarityToolID::None;
  ClarityPointerButton pointer_button = ClarityPointerButton::None;
  const wmEvent *source_event = nullptr;
};

/**
 * Momentary snap mode a physical key event resolves to, or #ClaritySnapMode::None when the event does
 * not belong to a snap key at all.
 *
 * The single place that maps keys to snap modes. A press honours the modifiers that belong to other
 * bindings, while a release resolves whatever is held with it: the release is the only way back out
 * of the mode, and dropping one because `Ctrl` or `Alt` happened to be down is what used to leave
 * temporary snapping stuck on.
 */
ClaritySnapMode snap_key_event_mode_get(int key_type, short key_val, uint8_t modifier);

/**
 * Whether \a event is the left button release that completes a click rather than a drag.
 *
 * A #KM_CLICK never reaches #ED_clarity_event_dispatch. Blender synthesizes it inside
 * #wm_handlers_do, hands the promoted event to that one handler list and restores it before
 * returning, while the dispatcher runs between the modal and the region handler passes - so it only
 * ever sees the queued #KM_PRESS and #KM_RELEASE. Neither can #wmWindow::event_queue_check_click
 * stand in for the promotion: `view3d.select` sits on the left button *press* in the Industry
 * Compatible keymap Clarity builds on, and handling that press is what clears the flag.
 *
 * This is the same test #wm_handlers_do makes before it promotes a release, so a gesture recognized
 * here is exactly the one Blender would have called a click. The caller still owns the question of
 * whether a press was pending: the release alone cannot tell a click from the tail of a drag that
 * happened to end where it started.
 */
bool left_mouse_click_release_is(const wmEvent &event);

/**
 * Whether \a event is a left button press that can still become a click.
 *
 * The second press of a double click carries #KM_DBL_CLICK instead of #KM_PRESS, and that gesture
 * belongs to topology selection: its release must not also act as a click. `Alt` is viewport
 * navigation from the moment the button goes down.
 */
bool left_mouse_click_press_arms(const wmEvent &event);

}  // namespace ed::clarity

std::optional<ed::clarity::ClarityInputAction> ED_clarity_input_translate(const bContext *C,
                                                                 const wmEvent &event);

}  // namespace blender
