/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

#include "testing/testing.h"

#include "clarity_selection_menu.hh"

namespace blender::ed::clarity::tests {

static ClaritySelectionMenuContext face_selection()
{
  ClaritySelectionMenuContext context;
  context.object_is_mesh = true;
  context.selected_vert_num = 4;
  context.selected_face_num = 1;
  context.has_selection = true;
  context.has_uv_layer = true;
  context.supports_edge_loop = true;
  context.supports_edge_ring = true;
  return context;
}

TEST(clarity_selection_menu, nothing_runs_without_a_mesh)
{
  const ClaritySelectionMenuContext context;
  EXPECT_FALSE(selection_command_enabled(context, ClaritySelectionCommand::ToVertices));
  EXPECT_FALSE(selection_command_enabled(context, ClaritySelectionCommand::Grow));
  EXPECT_FALSE(selection_command_enabled(context, ClaritySelectionCommand::ToEdgeLoop));
}

TEST(clarity_selection_menu, conversions_need_a_selection)
{
  ClaritySelectionMenuContext context = face_selection();
  EXPECT_TRUE(selection_command_enabled(context, ClaritySelectionCommand::ToVertices));
  EXPECT_TRUE(selection_command_enabled(context, ClaritySelectionCommand::ToEdges));
  EXPECT_TRUE(selection_command_enabled(context, ClaritySelectionCommand::Shrink));

  context.has_selection = false;
  EXPECT_FALSE(selection_command_enabled(context, ClaritySelectionCommand::ToVertices));
  EXPECT_FALSE(selection_command_enabled(context, ClaritySelectionCommand::ToEdges));
  EXPECT_FALSE(selection_command_enabled(context, ClaritySelectionCommand::Shrink));
}

TEST(clarity_selection_menu, a_perimeter_needs_an_area)
{
  ClaritySelectionMenuContext context = face_selection();
  EXPECT_TRUE(selection_command_enabled(context, ClaritySelectionCommand::ToEdgePerimeter));
  EXPECT_TRUE(selection_command_enabled(context, ClaritySelectionCommand::SelectionBoundary));

  /* Loose edges alone bound nothing, so Clarity has no perimeter to give back. */
  context.selected_face_num = 0;
  context.selected_edge_num = 3;
  EXPECT_FALSE(selection_command_enabled(context, ClaritySelectionCommand::ToEdgePerimeter));
  EXPECT_FALSE(selection_command_enabled(context, ClaritySelectionCommand::ToVertexPerimeter));
  EXPECT_FALSE(selection_command_enabled(context, ClaritySelectionCommand::SelectionBoundary));
}

TEST(clarity_selection_menu, uv_commands_need_a_uv_layer)
{
  ClaritySelectionMenuContext context = face_selection();
  EXPECT_TRUE(selection_command_enabled(context, ClaritySelectionCommand::ToUVs));

  context.has_uv_layer = false;
  EXPECT_FALSE(selection_command_enabled(context, ClaritySelectionCommand::ToUVs));
}

TEST(clarity_selection_menu, commands_without_a_backend_stay_greyed_out)
{
  /* These are the entries Clarity has and this fork does not implement yet. Offering them would be
   * worse than greying them out: the menu would promise a result nothing produces. */
  const ClaritySelectionMenuContext context = face_selection();
  EXPECT_FALSE(selection_command_enabled(context, ClaritySelectionCommand::ToFacePath));
  EXPECT_FALSE(selection_command_enabled(context, ClaritySelectionCommand::GrowAlongLoop));
  EXPECT_FALSE(selection_command_enabled(context, ClaritySelectionCommand::ShrinkAlongLoop));
  EXPECT_FALSE(selection_command_enabled(context, ClaritySelectionCommand::ToUVShell));
  EXPECT_FALSE(selection_command_enabled(context, ClaritySelectionCommand::ToShell));
  EXPECT_FALSE(selection_command_enabled(context, ClaritySelectionCommand::ToShellBorder));
  EXPECT_FALSE(selection_command_enabled(context, ClaritySelectionCommand::SelectEdgeLoopTool));
  EXPECT_FALSE(selection_command_enabled(context, ClaritySelectionCommand::SelectEdgeRingTool));
  EXPECT_FALSE(selection_command_enabled(context, ClaritySelectionCommand::SelectBorderEdgeTool));
}

TEST(clarity_selection_menu, loop_and_ring_commands_follow_their_support_flags)
{
  ClaritySelectionMenuContext context = face_selection();
  EXPECT_TRUE(selection_command_enabled(context, ClaritySelectionCommand::ToEdgeLoop));
  EXPECT_TRUE(selection_command_enabled(context, ClaritySelectionCommand::ToEdgeRingAndSplit));

  context.supports_edge_loop = false;
  context.supports_edge_ring = false;
  EXPECT_FALSE(selection_command_enabled(context, ClaritySelectionCommand::ToEdgeLoop));
  EXPECT_FALSE(selection_command_enabled(context, ClaritySelectionCommand::ToEdgeLoopAndDelete));
  EXPECT_FALSE(selection_command_enabled(context, ClaritySelectionCommand::ToEdgeRing));
  EXPECT_FALSE(selection_command_enabled(context, ClaritySelectionCommand::ToEdgeRingAndCollapse));
}

}  // namespace blender::ed::clarity::tests
