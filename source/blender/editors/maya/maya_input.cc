/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup editors
 */

#include "maya_input.hh"

#include "BLI_utildefines.h"

#include "WM_types.hh"
#include "wm_event_types.hh"

namespace blender {

namespace ed::maya {

MayaSnapMode snap_key_event_mode_get(const int key_type,
                                     const short key_val,
                                     const uint8_t modifier)
{
  if (!ELEM(key_val, KM_PRESS, KM_RELEASE)) {
    return MayaSnapMode::None;
  }

  MayaSnapMode mode = MayaSnapMode::None;
  /* `Shift` belongs to the drag that `J` is held during, not to another binding of the key: Maya
   * steps a shift-duplicate drag just like any other. */
  bool shift_allowed = false;
  switch (key_type) {
    case EVT_XKEY:
      mode = MayaSnapMode::Grid;
      break;
    case EVT_CKEY:
      mode = MayaSnapMode::Curve;
      break;
    case EVT_VKEY:
      mode = MayaSnapMode::Point;
      break;
    case EVT_JKEY:
      shift_allowed = true;
      mode = MayaSnapMode::Step;
      break;
    default:
      return MayaSnapMode::None;
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
  return (int(modifier) & blocked) == 0 ? mode : MayaSnapMode::None;
}

}  // namespace ed::maya

std::optional<ed::maya::MayaInputAction> ED_maya_input_translate(
    const bContext * /*C*/, const wmEvent &event)
{
  ed::maya::MayaInputAction action;
  action.mouse = int2(event.xy);
  action.mouse_region = int2(event.mval);
  action.mouse_delta = int2(event.xy) - int2(event.prev_xy);
  action.shift = event.modifier & KM_SHIFT;
  action.ctrl = event.modifier & KM_CTRL;
  action.alt = event.modifier & KM_ALT;
  action.source_event = &event;

  if (event.type == LEFTMOUSE) {
    action.pointer_button = ed::maya::MayaPointerButton::Left;
  }
  else if (event.type == MIDDLEMOUSE) {
    action.pointer_button = ed::maya::MayaPointerButton::Middle;
  }
  else if (event.type == RIGHTMOUSE) {
    action.pointer_button = ed::maya::MayaPointerButton::Right;
  }

  if (ELEM(event.type, EVT_LEFTALTKEY, EVT_RIGHTALTKEY) && event.val == KM_RELEASE) {
    action.id = ed::maya::MayaActionID::EndNavigation;
    action.phase = ed::maya::MayaActionPhase::End;
  }
  else if (!action.alt &&
           ((event.type == MIDDLEMOUSE && event.val == KM_PRESS) ||
            ISMOUSE_GESTURE(event.type)))
  {
    action.id = ed::maya::MayaActionID::BlockViewportNavigation;
  }
  else if (event.type == MOUSEMOVE) {
    action.id = ed::maya::MayaActionID::PointerMove;
    action.phase = ed::maya::MayaActionPhase::Update;
  }
  else if (action.alt && action.pointer_button != ed::maya::MayaPointerButton::None &&
           event.val == KM_PRESS)
  {
    if (action.pointer_button == ed::maya::MayaPointerButton::Left) {
      action.id = ed::maya::MayaActionID::BeginOrbit;
      action.phase = ed::maya::MayaActionPhase::Begin;
    }
    else if (action.pointer_button == ed::maya::MayaPointerButton::Middle) {
      action.id = ed::maya::MayaActionID::BeginPan;
      action.phase = ed::maya::MayaActionPhase::Begin;
    }
    else if (action.pointer_button == ed::maya::MayaPointerButton::Right) {
      action.id = ed::maya::MayaActionID::BeginDolly;
      action.phase = ed::maya::MayaActionPhase::Begin;
    }
  }
  else if (event.type == EVT_F8KEY && event.val == KM_PRESS && !action.shift && !action.ctrl &&
           !action.alt)
  {
    action.id = ed::maya::MayaActionID::ToggleObjectComponent;
    action.phase = ed::maya::MayaActionPhase::Begin;
  }
  else if (event.type == EVT_F7KEY && event.val == KM_PRESS && !action.shift && !action.ctrl &&
           !action.alt)
  {
    action.id = ed::maya::MayaActionID::ComponentMulti;
    action.phase = ed::maya::MayaActionPhase::Begin;
  }
  else if (event.type == EVT_F9KEY && event.val == KM_PRESS && action.alt && !action.shift &&
           !action.ctrl)
  {
    action.id = ed::maya::MayaActionID::ComponentVertexFace;
    action.phase = ed::maya::MayaActionPhase::Begin;
  }
  else if (ELEM(event.type, EVT_F9KEY, EVT_F10KEY, EVT_F11KEY, EVT_F12KEY) &&
           event.val == KM_PRESS && !action.shift && !action.ctrl && !action.alt)
  {
    if (event.type == EVT_F9KEY) {
      action.id = ed::maya::MayaActionID::ComponentVertex;
    }
    else if (event.type == EVT_F10KEY) {
      action.id = ed::maya::MayaActionID::ComponentEdge;
    }
    else if (event.type == EVT_F11KEY) {
      action.id = ed::maya::MayaActionID::ComponentFace;
    }
    else {
      action.id = ed::maya::MayaActionID::ComponentUV;
    }
    action.phase = ed::maya::MayaActionPhase::Begin;
  }
  else if (event.type == EVT_FKEY && event.val == KM_PRESS && !action.shift && !action.ctrl &&
           !action.alt)
  {
    action.id = ed::maya::MayaActionID::FrameSelected;
    action.phase = ed::maya::MayaActionPhase::Begin;
  }
  else if (event.type == EVT_DKEY && ELEM(event.val, KM_PRESS, KM_RELEASE) &&
           (event.val == KM_RELEASE || (!action.shift && !action.ctrl && !action.alt)))
  {
    action.id = event.val == KM_PRESS ? ed::maya::MayaActionID::EditPivotKeyPressed :
                                       ed::maya::MayaActionID::EditPivotKeyReleased;
    action.phase = event.val == KM_PRESS ? ed::maya::MayaActionPhase::Begin :
                                          ed::maya::MayaActionPhase::End;
  }
  else if (event.type == EVT_INSERTKEY && event.val == KM_PRESS &&
           (event.flag & WM_EVENT_IS_REPEAT) == 0 && !action.shift && !action.ctrl &&
           !action.alt)
  {
    action.id = ed::maya::MayaActionID::TogglePersistentPivot;
    action.phase = ed::maya::MayaActionPhase::Begin;
  }
  else if (event.type == WINDEACTIVATE) {
    action.id = ed::maya::MayaActionID::FocusLost;
    action.phase = ed::maya::MayaActionPhase::Cancel;
  }
  else if (ed::maya::snap_key_event_mode_get(int(event.type), event.val, event.modifier) !=
           ed::maya::MayaSnapMode::None)
  {
    action.id = ed::maya::MayaActionID::TemporarySnap;
    action.phase = event.val == KM_PRESS ? ed::maya::MayaActionPhase::Begin :
                                          ed::maya::MayaActionPhase::End;
  }
  else if (event.type == EVT_JKEY && event.val == KM_PRESS && action.ctrl && !action.shift &&
           !action.alt)
  {
    action.id = ed::maya::MayaActionID::Connect;
    action.phase = ed::maya::MayaActionPhase::Begin;
  }
  else if (event.type == EVT_BKEY && event.val == KM_PRESS && action.ctrl && action.shift &&
           !action.alt)
  {
    action.id = ed::maya::MayaActionID::BridgeOrFill;
    action.phase = ed::maya::MayaActionPhase::Begin;
  }
  else if (event.type == EVT_EKEY && event.val == KM_PRESS && action.ctrl && !action.shift &&
           !action.alt)
  {
    action.id = ed::maya::MayaActionID::Extrude;
    action.phase = ed::maya::MayaActionPhase::Begin;
  }
  else if (event.type == EVT_TWOKEY && event.val == KM_PRESS && action.ctrl && !action.shift &&
           !action.alt)
  {
    action.id = ed::maya::MayaActionID::ObjectXRay;
    action.phase = ed::maya::MayaActionPhase::Begin;
  }
  else if (event.type == EVT_ZKEY && event.val == KM_PRESS && action.ctrl && action.shift &&
           !action.alt)
  {
    action.id = ed::maya::MayaActionID::FaceCenters;
    action.phase = ed::maya::MayaActionPhase::Begin;
  }
  else if (event.type == EVT_FIVEKEY && event.val == KM_PRESS && action.alt && !action.shift &&
           !action.ctrl)
  {
    action.id = ed::maya::MayaActionID::WireframeOnShaded;
    action.phase = ed::maya::MayaActionPhase::Begin;
  }
  else if (event.type == RIGHTMOUSE && event.val == KM_PRESS && !action.shift && !action.ctrl &&
           !action.alt)
  {
    action.id = ed::maya::MayaActionID::ComponentMarkingMenu;
    action.phase = ed::maya::MayaActionPhase::Begin;
  }
  else if (event.type == LEFTMOUSE && event.val == KM_PRESS && !action.shift && !action.ctrl &&
           !action.alt &&
           ELEM(event.keymodifier, EVT_QKEY, EVT_WKEY, EVT_EKEY, EVT_RKEY))
  {
    /* Maya opens a tool's marking menu by holding its key and pressing the left button. The held
     * key is the one the window reports as the key modifier, which is also the only place a key
     * that is down without generating events can be read from. */
    if (event.keymodifier == EVT_QKEY) {
      action.tool = ed::maya::MayaToolID::Select;
    }
    else if (event.keymodifier == EVT_WKEY) {
      action.tool = ed::maya::MayaToolID::Move;
    }
    else if (event.keymodifier == EVT_EKEY) {
      action.tool = ed::maya::MayaToolID::Rotate;
    }
    else {
      action.tool = ed::maya::MayaToolID::Scale;
    }
    action.id = ed::maya::MayaActionID::ToolMarkingMenu;
    action.phase = ed::maya::MayaActionPhase::Begin;
  }
  else if (event.type == RIGHTMOUSE && event.val == KM_PRESS && action.ctrl && action.shift &&
           !action.alt)
  {
    /* The same menu for whichever transform tool is active, so it is reachable without holding a
     * key. #MayaToolID::None means "the active one" here. */
    action.id = ed::maya::MayaActionID::ToolMarkingMenu;
    action.phase = ed::maya::MayaActionPhase::Begin;
  }
  else if (event.type == RIGHTMOUSE && event.val == KM_PRESS && action.ctrl && !action.shift &&
           !action.alt)
  {
    action.id = ed::maya::MayaActionID::SelectionMarkingMenu;
    action.phase = ed::maya::MayaActionPhase::Begin;
  }
  else if (event.type == LEFTMOUSE && event.val == KM_DBL_CLICK && !action.alt) {
    /* One action for every modifier combination: whether this selects a loop or a path depends on
     * the mesh, which only the handler can see. `Alt` stays with viewport navigation. */
    action.id = ed::maya::MayaActionID::SelectTopology;
    action.phase = ed::maya::MayaActionPhase::Begin;
  }
  /* The marquee has no entry here on purpose: Blender never queues a #KM_PRESS_DRAG event, so it is
   * recognized from the motion that crosses the drag threshold. See #left_mouse_marquee_drag_handle. */
  else if (event.type == LEFTMOUSE && event.val == KM_CLICK && !action.alt) {
    if (action.ctrl && action.shift) {
      /* This chord belongs exclusively to the additive marquee. A click without a drag is consumed
       * so it cannot fall back to picking one component. */
      action.id = ed::maya::MayaActionID::SelectAddMarquee;
    }
    else if (action.ctrl) {
      action.id = ed::maya::MayaActionID::SelectRemove;
    }
    else if (action.shift) {
      action.id = ed::maya::MayaActionID::SelectAdd;
    }
    else {
      action.id = ed::maya::MayaActionID::SelectPrimary;
    }
    action.phase = ed::maya::MayaActionPhase::Begin;
  }
  else if (event.type == EVT_PERIODKEY && event.val == KM_PRESS && action.shift && !action.ctrl &&
           !action.alt)
  {
    action.id = ed::maya::MayaActionID::SelectGrow;
    action.phase = ed::maya::MayaActionPhase::Begin;
  }
  else if (event.type == EVT_COMMAKEY && event.val == KM_PRESS && action.shift && !action.ctrl &&
           !action.alt)
  {
    action.id = ed::maya::MayaActionID::SelectShrink;
    action.phase = ed::maya::MayaActionPhase::Begin;
  }
  else if (ELEM(event.type, EVT_ONEKEY, EVT_TWOKEY, EVT_THREEKEY) && event.val == KM_PRESS &&
           !action.shift && !action.ctrl && !action.alt)
  {
    if (event.type == EVT_ONEKEY) {
      action.id = ed::maya::MayaActionID::SubdivisionPreviewOff;
    }
    else if (event.type == EVT_TWOKEY) {
      action.id = ed::maya::MayaActionID::SubdivisionPreviewOn;
    }
    else {
      action.id = ed::maya::MayaActionID::SubdivisionPreviewSurface;
    }
    action.phase = ed::maya::MayaActionPhase::Begin;
  }
  else if (ELEM(event.type, EVT_QKEY, EVT_WKEY, EVT_EKEY, EVT_RKEY))
  {
    if (event.type == EVT_QKEY) {
      action.tool = ed::maya::MayaToolID::Select;
    }
    else if (event.type == EVT_WKEY) {
      action.tool = ed::maya::MayaToolID::Move;
    }
    else if (event.type == EVT_EKEY) {
      action.tool = ed::maya::MayaToolID::Rotate;
    }
    else {
      action.tool = ed::maya::MayaToolID::Scale;
    }

    if (!action.shift && !action.ctrl && !action.alt && event.val == KM_PRESS) {
      action.id = ed::maya::MayaActionID::ActivateTool;
      action.phase = ed::maya::MayaActionPhase::Begin;
    }
    else if (event.val == KM_RELEASE) {
      /* Tool keys are permanent switches in Maya: the release must be consumed so it cannot reach
       * a Blender keymap and start a one-shot operator. */
      action.id = ed::maya::MayaActionID::ToolHotkeyReleased;
      action.phase = ed::maya::MayaActionPhase::End;
    }
  }
  else if (action.pointer_button != ed::maya::MayaPointerButton::None &&
           event.val == KM_RELEASE)
  {
    action.id = ed::maya::MayaActionID::Confirm;
    action.phase = ed::maya::MayaActionPhase::End;
  }
  else if (event.type == EVT_ESCKEY && event.val == KM_PRESS) {
    action.id = ed::maya::MayaActionID::Cancel;
    action.phase = ed::maya::MayaActionPhase::Cancel;
  }
  else if (event.val == KM_RELEASE) {
    action.phase = ed::maya::MayaActionPhase::End;
  }

  return action;
}

}  // namespace blender
