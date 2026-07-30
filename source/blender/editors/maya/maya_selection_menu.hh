/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup editors
 *
 * The Maya polygon component selection marking menu.
 */

#pragma once

#include <cstdint>

#include "maya_marking_menu.hh"

namespace blender {

struct bContext;

namespace ed::maya {

enum class MayaComponentMode : uint8_t;

/** Every entry of the selection marking menu. None of them carries state. */
enum class MayaSelectionCommand : uint8_t {
  ToVertices = 0,
  ToVertexPerimeter,
  ToEdges,
  ToContainedEdges,
  ToEdgePerimeter,
  ToFaces,
  ToContainedFaces,
  ToFacePerimeter,
  ToUVs,
  ToUVPerimeter,
  ToUVEdgeLoop,
  Grow,
  GrowAlongLoop,
  Shrink,
  ShrinkAlongLoop,
  ToEdgeRing,
  SelectEdgeRingTool,
  ToEdgeRingAndSplit,
  ToEdgeRingAndCollapse,
  ToEdgeLoop,
  SelectEdgeLoopTool,
  ToEdgeLoopAndDuplicate,
  ToEdgeLoopAndDelete,
  ToFacePath,
  ToUVShell,
  ToShell,
  ToShellBorder,
  SelectBorderEdgeTool,
  SelectionBoundary,
};

/**
 * What the menu has to know about the selection before it can decide which entries may run.
 *
 * Gathered once per menu open. Maya asks the same questions, and the answers are what decides
 * between an entry that works and an entry that is greyed out.
 */
struct MayaSelectionMenuContext {
  bool object_is_mesh = false;
  /** `0` is #MayaComponentMode::Object; the enumerators live in `maya_runtime.hh`. */
  MayaComponentMode component_mode = MayaComponentMode(0);
  int selected_vert_num = 0;
  int selected_edge_num = 0;
  int selected_face_num = 0;
  bool has_selection = false;
  bool has_uv_layer = false;
  bool has_border_edges = false;
  bool supports_edge_loop = false;
  bool supports_edge_ring = false;
  MayaSelectionConstraint selection_constraint = MayaSelectionConstraint::Off;
};

MayaSelectionMenuContext selection_menu_context_get(const bContext *C);

/**
 * Whether \a command may run on the selection \a context describes.
 *
 * Pure, and the only place the rule lives: the menu greys an entry out with it and the operator
 * refuses with it, so a shortcut can never reach a command the menu would not have offered.
 */
bool selection_command_enabled(const MayaSelectionMenuContext &context,
                               MayaSelectionCommand command);

void register_selection_menu_types();

}  // namespace ed::maya
}  // namespace blender
