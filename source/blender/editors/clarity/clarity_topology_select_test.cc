/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

#include "testing/testing.h"

#include "clarity_input.hh"
#include "clarity_tools.hh"

namespace blender::ed::clarity::tests {

static ClarityInputAction action_with(const ClarityActionID id, const bool ctrl, const bool shift)
{
  ClarityInputAction action;
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

TEST(clarity_topology_select, TheMarqueeClickIsSwallowed)
{
  EXPECT_TRUE(selection_action_is_reserved_for_marquee(
      action_with(ClarityActionID::SelectAddMarquee, true, true)));
}

TEST(clarity_topology_select, TheDoubleClickOfTheSameChordIsNot)
{
  EXPECT_FALSE(selection_action_is_reserved_for_marquee(
      action_with(ClarityActionID::SelectTopology, true, true)));
}

TEST(clarity_topology_select, PlainAndShiftDoubleClicksAreNotSwallowedEither)
{
  EXPECT_FALSE(selection_action_is_reserved_for_marquee(
      action_with(ClarityActionID::SelectTopology, false, false)));
  EXPECT_FALSE(selection_action_is_reserved_for_marquee(
      action_with(ClarityActionID::SelectTopology, false, true)));
  EXPECT_FALSE(selection_action_is_reserved_for_marquee(
      action_with(ClarityActionID::SelectTopology, true, false)));
}

TEST(clarity_topology_select, OrdinaryPicksAreNotSwallowed)
{
  EXPECT_FALSE(
      selection_action_is_reserved_for_marquee(action_with(ClarityActionID::SelectAdd, false, true)));
  EXPECT_FALSE(selection_action_is_reserved_for_marquee(
      action_with(ClarityActionID::SelectPrimary, false, false)));
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Which operation a modifier asks for
 * \{ */

TEST(clarity_topology_select, ModifiersChooseTheOperation)
{
  EXPECT_EQ(topology_select_op_from_action(action_with(ClarityActionID::SelectTopology, false, false)),
            ClarityTopologySelectOp::Replace);
  EXPECT_EQ(topology_select_op_from_action(action_with(ClarityActionID::SelectTopology, false, true)),
            ClarityTopologySelectOp::Toggle);
  EXPECT_EQ(topology_select_op_from_action(action_with(ClarityActionID::SelectTopology, true, false)),
            ClarityTopologySelectOp::Subtract);
  /* `Ctrl Shift` is Clarity's "add to the selection". */
  EXPECT_EQ(topology_select_op_from_action(action_with(ClarityActionID::SelectTopology, true, true)),
            ClarityTopologySelectOp::Add);
}

/** \} */

}  // namespace blender::ed::clarity::tests
