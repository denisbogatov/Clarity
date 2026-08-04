/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup editors
 */

#include "clarity_session.hh"

#include "CLG_log.h"

namespace blender::ed::clarity {

static CLG_LogRef LOG = {"ed.clarity.session"};

ClarityInteractionSession::ClarityInteractionSession(ClaritySessionContext context) : context_(context) {}

const ClaritySessionContext &ClarityInteractionSession::context() const
{
  return context_;
}

ClaritySessionResult ClarityEditableSession::handle_event(bContext *C, const ClarityInputAction &action)
{
  if (action.id == ClarityActionID::PointerMove) {
    update(C, action);
    return ClaritySessionResult::Running;
  }
  if (action.id == ClarityActionID::Confirm &&
      action.pointer_button == ClarityPointerButton::Left)
  {
    confirm(C);
    return ClaritySessionResult::Finished;
  }
  if (action.id == ClarityActionID::Cancel) {
    cancel(C);
    return ClaritySessionResult::Cancelled;
  }
  return ClaritySessionResult::PassThrough;
}

void ClarityEditableSession::cancel(bContext *C)
{
  restore_initial_state(C);
}

ClarityDebugDragSession::ClarityDebugDragSession(ClaritySessionContext context, const int2 initial_mouse)
    : ClarityInteractionSession(context), initial_mouse_(initial_mouse)
{
  CLOG_INFO_NOCHECK(&LOG, "Debug drag started at (%d, %d)", initial_mouse_.x, initial_mouse_.y);
}

ClaritySessionKind ClarityDebugDragSession::kind() const
{
  return ClaritySessionKind::Tool;
}

ClaritySessionResult ClarityDebugDragSession::handle_event(bContext *C,
                                                     const ClarityInputAction &action)
{
  if (action.id == ClarityActionID::PointerMove) {
    const int2 total_delta = action.mouse - initial_mouse_;
    CLOG_INFO_NOCHECK(&LOG,
                      "Debug drag delta (%d, %d), total (%d, %d)",
                      action.mouse_delta.x,
                      action.mouse_delta.y,
                      total_delta.x,
                      total_delta.y);
    return ClaritySessionResult::Running;
  }
  if (action.id == ClarityActionID::Confirm) {
    CLOG_STR_INFO_NOCHECK(&LOG, "Debug drag finished");
    return ClaritySessionResult::Finished;
  }
  if (action.id == ClarityActionID::Cancel) {
    cancel(C);
    return ClaritySessionResult::Cancelled;
  }
  return ClaritySessionResult::PassThrough;
}

void ClarityDebugDragSession::cancel(bContext * /*C*/)
{
  CLOG_STR_INFO_NOCHECK(&LOG, "Debug drag cancelled");
}

}  // namespace blender::ed::clarity
