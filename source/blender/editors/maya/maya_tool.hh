/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup editors
 */

#pragma once

#include <cstdint>

#include "BLI_enum_flags.hh"

namespace blender {

struct bContext;

namespace ed::maya {

struct MayaWindowRuntime;

enum class MayaToolID : uint8_t {
  None,
  Select,
  Move,
  Rotate,
  Scale,
  MultiCut,
  TargetWeld,
  QuadDraw,
};

struct MayaToolState {
  MayaToolID active = MayaToolID::Select;
  MayaToolID previous = MayaToolID::Select;
  uint64_t revision = 0;
};

enum class MayaToolCapability : uint32_t {
  None = 0,
  UsesSelection = 1 << 0,
  UsesManipulator = 1 << 1,
  SupportsObject = 1 << 2,
  SupportsComponents = 1 << 3,
};
ENUM_OPERATORS(MayaToolCapability);

struct MayaToolType {
  MayaToolID id;
  const char *idname;
  const char *label;

  MayaToolCapability capabilities;

  bool (*poll)(const bContext *C, const MayaWindowRuntime &runtime);
  void (*activate)(bContext *C, MayaWindowRuntime &runtime);
  void (*deactivate)(bContext *C, MayaWindowRuntime &runtime);
};

enum class MayaToolActivationReason : uint8_t {
  Hotkey,
  Shelf,
  MarkingMenu,
  Startup,
  ContextFallback,
  Internal,
};

enum class MayaToolActivationResult : uint8_t {
  Activated,
  AlreadyActive,
  Rejected,
  BlockedBySession,
};

}  // namespace ed::maya

const ed::maya::MayaToolType *ED_maya_tool_type_find(ed::maya::MayaToolID tool_id);
ed::maya::MayaToolActivationResult ED_maya_tool_activate(
    bContext *C,
    ed::maya::MayaToolID tool_id,
    ed::maya::MayaToolActivationReason reason);

}  // namespace blender
