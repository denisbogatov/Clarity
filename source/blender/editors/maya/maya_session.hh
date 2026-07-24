/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup editors
 */

#pragma once

#include <cstdint>

#include "maya_input.hh"
#include "maya_session_context.hh"

namespace blender {

struct bContext;

namespace ed::maya {

enum class MayaSessionKind : uint8_t {
  Navigation,
  Selection,
  Transform,
  Tool,
  Gizmo,
  MarkingMenu,
};

enum class MayaSessionResult : uint8_t {
  Running,
  Finished,
  Cancelled,
  PassThrough,
};

class MayaInteractionSession {
 public:
  explicit MayaInteractionSession(MayaSessionContext context);
  virtual ~MayaInteractionSession() = default;

  virtual MayaSessionKind kind() const = 0;
  virtual MayaSessionResult handle_event(bContext *C, const MayaInputAction &action) = 0;
  virtual void cancel(bContext *C) = 0;

  virtual bool blocks_blender_events() const
  {
    return true;
  }

  virtual bool uses_undo() const
  {
    return false;
  }

  const MayaSessionContext &context() const;

 private:
  MayaSessionContext context_;
};

class MayaEditableSession : public MayaInteractionSession {
 public:
  using MayaInteractionSession::MayaInteractionSession;

  virtual bool begin(bContext *C) = 0;
  virtual void update(bContext *C, const MayaInputAction &action) = 0;
  virtual void confirm(bContext *C) = 0;
  virtual void restore_initial_state(bContext *C) = 0;

  MayaSessionResult handle_event(bContext *C, const MayaInputAction &action) override;
  void cancel(bContext *C) override;

  bool uses_undo() const override
  {
    return true;
  }
};

class MayaDebugDragSession final : public MayaInteractionSession {
 public:
  MayaDebugDragSession(MayaSessionContext context, int2 initial_mouse);

  MayaSessionKind kind() const override;
  MayaSessionResult handle_event(bContext *C, const MayaInputAction &action) override;
  void cancel(bContext *C) override;

 private:
  int2 initial_mouse_;
};

}  // namespace ed::maya
}  // namespace blender
