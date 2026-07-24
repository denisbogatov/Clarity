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
  else if (event.type == EVT_F8KEY && event.val == KM_PRESS) {
    action.id = ed::maya::MayaActionID::DebugDrag;
    action.phase = ed::maya::MayaActionPhase::Begin;
  }
  else if (event.type == EVT_FKEY && event.val == KM_PRESS && !action.shift && !action.ctrl &&
           !action.alt)
  {
    action.id = ed::maya::MayaActionID::FrameSelected;
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
