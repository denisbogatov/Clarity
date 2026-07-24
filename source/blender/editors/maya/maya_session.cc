/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup editors
 */

#include "maya_session.hh"

#include "CLG_log.h"

namespace blender::ed::maya {

static CLG_LogRef LOG = {"ed.maya.session"};

MayaInteractionSession::MayaInteractionSession(MayaSessionContext context) : context_(context) {}

const MayaSessionContext &MayaInteractionSession::context() const
{
  return context_;
}

MayaSessionResult MayaEditableSession::handle_event(bContext *C, const MayaInputAction &action)
{
  if (action.id == MayaActionID::PointerMove) {
    update(C, action);
    return MayaSessionResult::Running;
  }
  if (action.id == MayaActionID::Confirm &&
      action.pointer_button == MayaPointerButton::Left)
  {
    confirm(C);
    return MayaSessionResult::Finished;
  }
  if (action.id == MayaActionID::Cancel) {
    cancel(C);
    return MayaSessionResult::Cancelled;
  }
  return MayaSessionResult::PassThrough;
}

void MayaEditableSession::cancel(bContext *C)
{
  restore_initial_state(C);
}

MayaDebugDragSession::MayaDebugDragSession(MayaSessionContext context, const int2 initial_mouse)
    : MayaInteractionSession(context), initial_mouse_(initial_mouse)
{
  CLOG_INFO_NOCHECK(&LOG, "Debug drag started at (%d, %d)", initial_mouse_.x, initial_mouse_.y);
}

MayaSessionKind MayaDebugDragSession::kind() const
{
  return MayaSessionKind::Tool;
}

MayaSessionResult MayaDebugDragSession::handle_event(bContext *C,
                                                     const MayaInputAction &action)
{
  if (action.id == MayaActionID::PointerMove) {
    const int2 total_delta = action.mouse - initial_mouse_;
    CLOG_INFO_NOCHECK(&LOG,
                      "Debug drag delta (%d, %d), total (%d, %d)",
                      action.mouse_delta.x,
                      action.mouse_delta.y,
                      total_delta.x,
                      total_delta.y);
    return MayaSessionResult::Running;
  }
  if (action.id == MayaActionID::Confirm) {
    CLOG_STR_INFO_NOCHECK(&LOG, "Debug drag finished");
    return MayaSessionResult::Finished;
  }
  if (action.id == MayaActionID::Cancel) {
    cancel(C);
    return MayaSessionResult::Cancelled;
  }
  return MayaSessionResult::PassThrough;
}

void MayaDebugDragSession::cancel(bContext * /*C*/)
{
  CLOG_STR_INFO_NOCHECK(&LOG, "Debug drag cancelled");
}

}  // namespace blender::ed::maya
