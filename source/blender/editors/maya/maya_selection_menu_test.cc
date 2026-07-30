/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

#include "testing/testing.h"

#include "maya_selection_menu.hh"

namespace blender::ed::maya::tests {

static MayaSelectionMenuContext face_selection()
{
  MayaSelectionMenuContext context;
  context.object_is_mesh = true;
  context.selected_vert_num = 4;
  context.selected_face_num = 1;
  context.has_selection = true;
  context.has_uv_layer = true;
  context.supports_edge_loop = true;
  context.supports_edge_ring = true;
  return context;
}

TEST(maya_selection_menu, nothing_runs_without_a_mesh)
{
  const MayaSelectionMenuContext context;
  EXPECT_FALSE(selection_command_enabled(context, MayaSelectionCommand::ToVertices));
  EXPECT_FALSE(selection_command_enabled(context, MayaSelectionCommand::Grow));
  EXPECT_FALSE(selection_command_enabled(context, MayaSelectionCommand::ToEdgeLoop));
}

TEST(maya_selection_menu, conversions_need_a_selection)
{
  MayaSelectionMenuContext context = face_selection();
  EXPECT_TRUE(selection_command_enabled(context, MayaSelectionCommand::ToVertices));
  EXPECT_TRUE(selection_command_enabled(context, MayaSelectionCommand::ToEdges));
  EXPECT_TRUE(selection_command_enabled(context, MayaSelectionCommand::Shrink));

  context.has_selection = false;
  EXPECT_FALSE(selection_command_enabled(context, MayaSelectionCommand::ToVertices));
  EXPECT_FALSE(selection_command_enabled(context, MayaSelectionCommand::ToEdges));
  EXPECT_FALSE(selection_command_enabled(context, MayaSelectionCommand::Shrink));
}

TEST(maya_selection_menu, a_perimeter_needs_an_area)
{
  MayaSelectionMenuContext context = face_selection();
  EXPECT_TRUE(selection_command_enabled(context, MayaSelectionCommand::ToEdgePerimeter));
  EXPECT_TRUE(selection_command_enabled(context, MayaSelectionCommand::SelectionBoundary));

  /* Loose edges alone bound nothing, so Maya has no perimeter to give back. */
  context.selected_face_num = 0;
  context.selected_edge_num = 3;
  EXPECT_FALSE(selection_command_enabled(context, MayaSelectionCommand::ToEdgePerimeter));
  EXPECT_FALSE(selection_command_enabled(context, MayaSelectionCommand::ToVertexPerimeter));
  EXPECT_FALSE(selection_command_enabled(context, MayaSelectionCommand::SelectionBoundary));
}

TEST(maya_selection_menu, uv_commands_need_a_uv_layer)
{
  MayaSelectionMenuContext context = face_selection();
  EXPECT_TRUE(selection_command_enabled(context, MayaSelectionCommand::ToUVs));

  context.has_uv_layer = false;
  EXPECT_FALSE(selection_command_enabled(context, MayaSelectionCommand::ToUVs));
}

TEST(maya_selection_menu, commands_without_a_backend_stay_greyed_out)
{
  /* These are the entries Maya has and this fork does not implement yet. Offering them would be
   * worse than greying them out: the menu would promise a result nothing produces. */
  const MayaSelectionMenuContext context = face_selection();
  EXPECT_FALSE(selection_command_enabled(context, MayaSelectionCommand::ToFacePath));
  EXPECT_FALSE(selection_command_enabled(context, MayaSelectionCommand::GrowAlongLoop));
  EXPECT_FALSE(selection_command_enabled(context, MayaSelectionCommand::ShrinkAlongLoop));
  EXPECT_FALSE(selection_command_enabled(context, MayaSelectionCommand::ToUVShell));
  EXPECT_FALSE(selection_command_enabled(context, MayaSelectionCommand::ToShell));
  EXPECT_FALSE(selection_command_enabled(context, MayaSelectionCommand::ToShellBorder));
  EXPECT_FALSE(selection_command_enabled(context, MayaSelectionCommand::SelectEdgeLoopTool));
  EXPECT_FALSE(selection_command_enabled(context, MayaSelectionCommand::SelectEdgeRingTool));
  EXPECT_FALSE(selection_command_enabled(context, MayaSelectionCommand::SelectBorderEdgeTool));
}

TEST(maya_selection_menu, loop_and_ring_commands_follow_their_support_flags)
{
  MayaSelectionMenuContext context = face_selection();
  EXPECT_TRUE(selection_command_enabled(context, MayaSelectionCommand::ToEdgeLoop));
  EXPECT_TRUE(selection_command_enabled(context, MayaSelectionCommand::ToEdgeRingAndSplit));

  context.supports_edge_loop = false;
  context.supports_edge_ring = false;
  EXPECT_FALSE(selection_command_enabled(context, MayaSelectionCommand::ToEdgeLoop));
  EXPECT_FALSE(selection_command_enabled(context, MayaSelectionCommand::ToEdgeLoopAndDelete));
  EXPECT_FALSE(selection_command_enabled(context, MayaSelectionCommand::ToEdgeRing));
  EXPECT_FALSE(selection_command_enabled(context, MayaSelectionCommand::ToEdgeRingAndCollapse));
}

}  // namespace blender::ed::maya::tests
