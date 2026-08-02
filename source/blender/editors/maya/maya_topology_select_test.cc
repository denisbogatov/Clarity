/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

#include "testing/testing.h"

#include "maya_input.hh"
#include "maya_tools.hh"

namespace blender::ed::maya::tests {

static MayaInputAction action_with(const MayaActionID id, const bool ctrl, const bool shift)
{
  MayaInputAction action;
  action.id = id;
  action.ctrl = ctrl;
  action.shift = shift;
  return action;
}

/* -------------------------------------------------------------------- */
/** \name Which gesture the additive marquee owns
 *
 * `Ctrl Shift` drag is the additive marquee, and a click of that chord that never became a drag is
 * swallowed so it cannot fall back to picking one component. The double click of the same chord is
 * a different gesture and must not be swallowed with it: that is how a loop is added to a selection
 * that already has one, and swallowing it left every topology branch unreachable.
 * \{ */

TEST(maya_topology_select, TheMarqueeClickIsSwallowed)
{
  EXPECT_TRUE(selection_action_is_reserved_for_marquee(
      action_with(MayaActionID::SelectAddMarquee, true, true)));
}

TEST(maya_topology_select, TheDoubleClickOfTheSameChordIsNot)
{
  EXPECT_FALSE(selection_action_is_reserved_for_marquee(
      action_with(MayaActionID::SelectTopology, true, true)));
}

TEST(maya_topology_select, PlainAndShiftDoubleClicksAreNotSwallowedEither)
{
  EXPECT_FALSE(selection_action_is_reserved_for_marquee(
      action_with(MayaActionID::SelectTopology, false, false)));
  EXPECT_FALSE(selection_action_is_reserved_for_marquee(
      action_with(MayaActionID::SelectTopology, false, true)));
  EXPECT_FALSE(selection_action_is_reserved_for_marquee(
      action_with(MayaActionID::SelectTopology, true, false)));
}

TEST(maya_topology_select, OrdinaryPicksAreNotSwallowed)
{
  EXPECT_FALSE(
      selection_action_is_reserved_for_marquee(action_with(MayaActionID::SelectAdd, false, true)));
  EXPECT_FALSE(selection_action_is_reserved_for_marquee(
      action_with(MayaActionID::SelectPrimary, false, false)));
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Which operation a modifier asks for
 * \{ */

TEST(maya_topology_select, ModifiersChooseTheOperation)
{
  EXPECT_EQ(topology_select_op_from_action(action_with(MayaActionID::SelectTopology, false, false)),
            MayaTopologySelectOp::Replace);
  EXPECT_EQ(topology_select_op_from_action(action_with(MayaActionID::SelectTopology, false, true)),
            MayaTopologySelectOp::Toggle);
  EXPECT_EQ(topology_select_op_from_action(action_with(MayaActionID::SelectTopology, true, false)),
            MayaTopologySelectOp::Subtract);
  /* `Ctrl Shift` is Maya's "add to the selection". */
  EXPECT_EQ(topology_select_op_from_action(action_with(MayaActionID::SelectTopology, true, true)),
            MayaTopologySelectOp::Add);
}

/** \} */

}  // namespace blender::ed::maya::tests
