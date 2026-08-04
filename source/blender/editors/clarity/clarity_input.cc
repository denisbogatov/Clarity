/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup editors
 */

#include "clarity_input.hh"

#include "BLI_utildefines.h"

#include "WM_types.hh"
#include "wm_event_types.hh"

namespace blender {

namespace ed::clarity {

ClaritySnapMode snap_key_event_mode_get(const int key_type,
                                     const short key_val,
                                     const uint8_t modifier)
{
  if (!ELEM(key_val, KM_PRESS, KM_RELEASE)) {
    return ClaritySnapMode::None;
  }

  ClaritySnapMode mode = ClaritySnapMode::None;
  /* `Shift` belongs to the drag that `J` is held during, not to another binding of the key: Clarity
   * steps a shift-duplicate drag just like any other. */
  bool shift_allowed = false;
  switch (key_type) {
    case EVT_XKEY:
      mode = ClaritySnapMode::Grid;
      break;
    case EVT_CKEY:
      mode = ClaritySnapMode::Curve;
      break;
    case EVT_VKEY:
      mode = ClaritySnapMode::Point;
      break;
    case EVT_JKEY:
      shift_allowed = true;
      mode = ClaritySnapMode::Step;
      break;
    default:
      return ClaritySnapMode::None;
  }

  if (key_val == KM_RELEASE) {
    /* The key owns the mode, so its release always resolves: the modifiers held now are
     * irrelevant. */
    return mode;
  }

  int blocked = int(KM_CTRL) | int(KM_ALT) | int(KM_OSKEY);
  if (!shift_allowed) {
    blocked |= int(KM_SHIFT);
  }
  return (int(modifier) & blocked) == 0 ? mode : ClaritySnapMode::None;
}

}  // namespace ed::clarity

std::optional<ed::clarity::ClarityInputAction> ED_clarity_input_translate(
    const bContext * /*C*/, const wmEvent &event)
{
  ed::clarity::ClarityInputAction action;
  action.mouse = int2(event.xy);
  action.mouse_region = int2(event.mval);
  action.mouse_delta = int2(event.xy) - int2(event.prev_xy);
  action.shift = event.modifier & KM_SHIFT;
  action.ctrl = event.modifier & KM_CTRL;
  action.alt = event.modifier & KM_ALT;
  action.source_event = &event;

  if (event.type == LEFTMOUSE) {
    action.pointer_button = ed::clarity::ClarityPointerButton::Left;
  }
  else if (event.type == MIDDLEMOUSE) {
    action.pointer_button = ed::clarity::ClarityPointerButton::Middle;
  }
  else if (event.type == RIGHTMOUSE) {
    action.pointer_button = ed::clarity::ClarityPointerButton::Right;
  }

  if (ELEM(event.type, EVT_LEFTALTKEY, EVT_RIGHTALTKEY) && event.val == KM_RELEASE) {
    action.id = ed::clarity::ClarityActionID::EndNavigation;
    action.phase = ed::clarity::ClarityActionPhase::End;
  }
  else if (!action.alt &&
           ((event.type == MIDDLEMOUSE && event.val == KM_PRESS) ||
            ISMOUSE_GESTURE(event.type)))
  {
    action.id = ed::clarity::ClarityActionID::BlockViewportNavigation;
  }
  else if (event.type == MOUSEMOVE) {
    action.id = ed::clarity::ClarityActionID::PointerMove;
    action.phase = ed::clarity::ClarityActionPhase::Update;
  }
  else if (action.alt && action.pointer_button != ed::clarity::ClarityPointerButton::None &&
           event.val == KM_PRESS)
  {
    if (action.pointer_button == ed::clarity::ClarityPointerButton::Left) {
      action.id = ed::clarity::ClarityActionID::BeginOrbit;
      action.phase = ed::clarity::ClarityActionPhase::Begin;
    }
    else if (action.pointer_button == ed::clarity::ClarityPointerButton::Middle) {
      action.id = ed::clarity::ClarityActionID::BeginPan;
      action.phase = ed::clarity::ClarityActionPhase::Begin;
    }
    else if (action.pointer_button == ed::clarity::ClarityPointerButton::Right) {
      action.id = ed::clarity::ClarityActionID::BeginDolly;
      action.phase = ed::clarity::ClarityActionPhase::Begin;
    }
  }
  else if (event.type == EVT_F8KEY && event.val == KM_PRESS && !action.shift && !action.ctrl &&
           !action.alt)
  {
    action.id = ed::clarity::ClarityActionID::ToggleObjectComponent;
    action.phase = ed::clarity::ClarityActionPhase::Begin;
  }
  else if (event.type == EVT_F7KEY && event.val == KM_PRESS && !action.shift && !action.ctrl &&
           !action.alt)
  {
    action.id = ed::clarity::ClarityActionID::ComponentMulti;
    action.phase = ed::clarity::ClarityActionPhase::Begin;
  }
  else if (event.type == EVT_F9KEY && event.val == KM_PRESS && action.alt && !action.shift &&
           !action.ctrl)
  {
    action.id = ed::clarity::ClarityActionID::ComponentVertexFace;
    action.phase = ed::clarity::ClarityActionPhase::Begin;
  }
  else if (ELEM(event.type, EVT_F9KEY, EVT_F10KEY, EVT_F11KEY, EVT_F12KEY) &&
           event.val == KM_PRESS && !action.shift && !action.ctrl && !action.alt)
  {
    if (event.type == EVT_F9KEY) {
      action.id = ed::clarity::ClarityActionID::ComponentVertex;
    }
    else if (event.type == EVT_F10KEY) {
      action.id = ed::clarity::ClarityActionID::ComponentEdge;
    }
    else if (event.type == EVT_F11KEY) {
      action.id = ed::clarity::ClarityActionID::ComponentFace;
    }
    else {
      action.id = ed::clarity::ClarityActionID::ComponentUV;
    }
    action.phase = ed::clarity::ClarityActionPhase::Begin;
  }
  else if (event.type == EVT_FKEY && event.val == KM_PRESS && !action.shift && !action.ctrl &&
           !action.alt)
  {
    action.id = ed::clarity::ClarityActionID::FrameSelected;
    action.phase = ed::clarity::ClarityActionPhase::Begin;
  }
  else if (event.type == EVT_DKEY && ELEM(event.val, KM_PRESS, KM_RELEASE) &&
           (event.val == KM_RELEASE || (!action.shift && !action.ctrl && !action.alt)))
  {
    action.id = event.val == KM_PRESS ? ed::clarity::ClarityActionID::EditPivotKeyPressed :
                                       ed::clarity::ClarityActionID::EditPivotKeyReleased;
    action.phase = event.val == KM_PRESS ? ed::clarity::ClarityActionPhase::Begin :
                                          ed::clarity::ClarityActionPhase::End;
  }
  else if (event.type == EVT_INSERTKEY && event.val == KM_PRESS &&
           (event.flag & WM_EVENT_IS_REPEAT) == 0 && !action.shift && !action.ctrl &&
           !action.alt)
  {
    action.id = ed::clarity::ClarityActionID::TogglePersistentPivot;
    action.phase = ed::clarity::ClarityActionPhase::Begin;
  }
  else if (event.type == WINDEACTIVATE) {
    action.id = ed::clarity::ClarityActionID::FocusLost;
    action.phase = ed::clarity::ClarityActionPhase::Cancel;
  }
  else if (ed::clarity::snap_key_event_mode_get(int(event.type), event.val, event.modifier) !=
           ed::clarity::ClaritySnapMode::None)
  {
    action.id = ed::clarity::ClarityActionID::TemporarySnap;
    action.phase = event.val == KM_PRESS ? ed::clarity::ClarityActionPhase::Begin :
                                          ed::clarity::ClarityActionPhase::End;
  }
  else if (event.type == EVT_JKEY && event.val == KM_PRESS && action.ctrl && !action.shift &&
           !action.alt)
  {
    action.id = ed::clarity::ClarityActionID::Connect;
    action.phase = ed::clarity::ClarityActionPhase::Begin;
  }
  else if (event.type == EVT_BKEY && event.val == KM_PRESS && action.ctrl && action.shift &&
           !action.alt)
  {
    action.id = ed::clarity::ClarityActionID::BridgeOrFill;
    action.phase = ed::clarity::ClarityActionPhase::Begin;
  }
  else if (event.type == EVT_EKEY && event.val == KM_PRESS && action.ctrl && !action.shift &&
           !action.alt)
  {
    action.id = ed::clarity::ClarityActionID::Extrude;
    action.phase = ed::clarity::ClarityActionPhase::Begin;
  }
  else if (event.type == EVT_TWOKEY && event.val == KM_PRESS && action.ctrl && !action.shift &&
           !action.alt)
  {
    action.id = ed::clarity::ClarityActionID::ObjectXRay;
    action.phase = ed::clarity::ClarityActionPhase::Begin;
  }
  else if (event.type == EVT_ZKEY && event.val == KM_PRESS && action.ctrl && action.shift &&
           !action.alt)
  {
    action.id = ed::clarity::ClarityActionID::FaceCenters;
    action.phase = ed::clarity::ClarityActionPhase::Begin;
  }
  else if (event.type == EVT_FIVEKEY && event.val == KM_PRESS && action.alt && !action.shift &&
           !action.ctrl)
  {
    action.id = ed::clarity::ClarityActionID::WireframeOnShaded;
    action.phase = ed::clarity::ClarityActionPhase::Begin;
  }
  else if (event.type == RIGHTMOUSE && event.val == KM_PRESS && !action.shift && !action.ctrl &&
           !action.alt)
  {
    action.id = ed::clarity::ClarityActionID::ComponentMarkingMenu;
    action.phase = ed::clarity::ClarityActionPhase::Begin;
  }
  else if (event.type == LEFTMOUSE && event.val == KM_PRESS && !action.shift && !action.ctrl &&
           !action.alt &&
           ELEM(event.keymodifier, EVT_QKEY, EVT_WKEY, EVT_EKEY, EVT_RKEY))
  {
    /* Clarity opens a tool's marking menu by holding its key and pressing the left button. The held
     * key is the one the window reports as the key modifier, which is also the only place a key
     * that is down without generating events can be read from. */
    if (event.keymodifier == EVT_QKEY) {
      action.tool = ed::clarity::ClarityToolID::Select;
    }
    else if (event.keymodifier == EVT_WKEY) {
      action.tool = ed::clarity::ClarityToolID::Move;
    }
    else if (event.keymodifier == EVT_EKEY) {
      action.tool = ed::clarity::ClarityToolID::Rotate;
    }
    else {
      action.tool = ed::clarity::ClarityToolID::Scale;
    }
    action.id = ed::clarity::ClarityActionID::ToolMarkingMenu;
    action.phase = ed::clarity::ClarityActionPhase::Begin;
  }
  else if (event.type == RIGHTMOUSE && event.val == KM_PRESS && action.ctrl && action.shift &&
           !action.alt)
  {
    /* The same menu for whichever transform tool is active, so it is reachable without holding a
     * key. #ClarityToolID::None means "the active one" here. */
    action.id = ed::clarity::ClarityActionID::ToolMarkingMenu;
    action.phase = ed::clarity::ClarityActionPhase::Begin;
  }
  else if (event.type == RIGHTMOUSE && event.val == KM_PRESS && action.ctrl && !action.shift &&
           !action.alt)
  {
    action.id = ed::clarity::ClarityActionID::SelectionMarkingMenu;
    action.phase = ed::clarity::ClarityActionPhase::Begin;
  }
  else if (event.type == LEFTMOUSE && event.val == KM_DBL_CLICK && !action.alt) {
    /* One action for every modifier combination: whether this selects a loop or a path depends on
     * the mesh, which only the handler can see. `Alt` stays with viewport navigation. */
    action.id = ed::clarity::ClarityActionID::SelectTopology;
    action.phase = ed::clarity::ClarityActionPhase::Begin;
  }
  /* The marquee has no entry here on purpose: Blender never queues a #KM_PRESS_DRAG event, so it is
   * recognized from the motion that crosses the drag threshold. See #left_mouse_marquee_drag_handle. */
  else if (event.type == LEFTMOUSE && event.val == KM_CLICK && !action.alt) {
    if (action.ctrl && action.shift) {
      /* This chord belongs exclusively to the additive marquee. A click without a drag is consumed
       * so it cannot fall back to picking one component. */
      action.id = ed::clarity::ClarityActionID::SelectAddMarquee;
    }
    else if (action.ctrl) {
      action.id = ed::clarity::ClarityActionID::SelectRemove;
    }
    else if (action.shift) {
      action.id = ed::clarity::ClarityActionID::SelectAdd;
    }
    else {
      action.id = ed::clarity::ClarityActionID::SelectPrimary;
    }
    action.phase = ed::clarity::ClarityActionPhase::Begin;
  }
  else if (event.type == EVT_PERIODKEY && event.val == KM_PRESS && action.shift && !action.ctrl &&
           !action.alt)
  {
    action.id = ed::clarity::ClarityActionID::SelectGrow;
    action.phase = ed::clarity::ClarityActionPhase::Begin;
  }
  else if (event.type == EVT_COMMAKEY && event.val == KM_PRESS && action.shift && !action.ctrl &&
           !action.alt)
  {
    action.id = ed::clarity::ClarityActionID::SelectShrink;
    action.phase = ed::clarity::ClarityActionPhase::Begin;
  }
  else if (ELEM(event.type, EVT_ONEKEY, EVT_TWOKEY, EVT_THREEKEY) && event.val == KM_PRESS &&
           !action.shift && !action.ctrl && !action.alt)
  {
    if (event.type == EVT_ONEKEY) {
      action.id = ed::clarity::ClarityActionID::SubdivisionPreviewOff;
    }
    else if (event.type == EVT_TWOKEY) {
      action.id = ed::clarity::ClarityActionID::SubdivisionPreviewOn;
    }
    else {
      action.id = ed::clarity::ClarityActionID::SubdivisionPreviewSurface;
    }
    action.phase = ed::clarity::ClarityActionPhase::Begin;
  }
  else if (ELEM(event.type, EVT_QKEY, EVT_WKEY, EVT_EKEY, EVT_RKEY))
  {
    if (event.type == EVT_QKEY) {
      action.tool = ed::clarity::ClarityToolID::Select;
    }
    else if (event.type == EVT_WKEY) {
      action.tool = ed::clarity::ClarityToolID::Move;
    }
    else if (event.type == EVT_EKEY) {
      action.tool = ed::clarity::ClarityToolID::Rotate;
    }
    else {
      action.tool = ed::clarity::ClarityToolID::Scale;
    }

    if (!action.shift && !action.ctrl && !action.alt && event.val == KM_PRESS) {
      action.id = ed::clarity::ClarityActionID::ActivateTool;
      action.phase = ed::clarity::ClarityActionPhase::Begin;
    }
    else if (event.val == KM_RELEASE) {
      /* Tool keys are permanent switches in Clarity: the release must be consumed so it cannot reach
       * a Blender keymap and start a one-shot operator. */
      action.id = ed::clarity::ClarityActionID::ToolHotkeyReleased;
      action.phase = ed::clarity::ClarityActionPhase::End;
    }
  }
  else if (action.pointer_button != ed::clarity::ClarityPointerButton::None &&
           event.val == KM_RELEASE)
  {
    action.id = ed::clarity::ClarityActionID::Confirm;
    action.phase = ed::clarity::ClarityActionPhase::End;
  }
  else if (event.type == EVT_ESCKEY && event.val == KM_PRESS) {
    action.id = ed::clarity::ClarityActionID::Cancel;
    action.phase = ed::clarity::ClarityActionPhase::Cancel;
  }
  else if (event.val == KM_RELEASE) {
    action.phase = ed::clarity::ClarityActionPhase::End;
  }

  return action;
}

}  // namespace blender
