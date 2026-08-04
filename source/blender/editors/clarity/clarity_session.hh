/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup editors
 */

#pragma once

#include <cstdint>

#include "clarity_input.hh"
#include "clarity_session_context.hh"

namespace blender {

struct bContext;

namespace ed::clarity {

enum class ClaritySessionKind : uint8_t {
  Navigation,
  Selection,
  Transform,
  Tool,
  Gizmo,
  MarkingMenu,
};

enum class ClaritySessionResult : uint8_t {
  Running,
  Finished,
  Cancelled,
  PassThrough,
};

class ClarityInteractionSession {
 public:
  explicit ClarityInteractionSession(ClaritySessionContext context);
  virtual ~ClarityInteractionSession() = default;

  virtual ClaritySessionKind kind() const = 0;
  virtual ClaritySessionResult handle_event(bContext *C, const ClarityInputAction &action) = 0;
  virtual void cancel(bContext *C) = 0;

  virtual bool blocks_blender_events() const
  {
    return true;
  }

  virtual bool uses_undo() const
  {
    return false;
  }

  const ClaritySessionContext &context() const;

 private:
  ClaritySessionContext context_;
};

class ClarityEditableSession : public ClarityInteractionSession {
 public:
  using ClarityInteractionSession::ClarityInteractionSession;

  virtual bool begin(bContext *C) = 0;
  virtual void update(bContext *C, const ClarityInputAction &action) = 0;
  virtual void confirm(bContext *C) = 0;
  virtual void restore_initial_state(bContext *C) = 0;

  ClaritySessionResult handle_event(bContext *C, const ClarityInputAction &action) override;
  void cancel(bContext *C) override;

  bool uses_undo() const override
  {
    return true;
  }
};

class ClarityDebugDragSession final : public ClarityInteractionSession {
 public:
  ClarityDebugDragSession(ClaritySessionContext context, int2 initial_mouse);

  ClaritySessionKind kind() const override;
  ClaritySessionResult handle_event(bContext *C, const ClarityInputAction &action) override;
  void cancel(bContext *C) override;

 private:
  int2 initial_mouse_;
};

}  // namespace ed::clarity
}  // namespace blender
