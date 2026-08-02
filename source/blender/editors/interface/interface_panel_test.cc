/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

#include "BKE_screen.hh"

#include "DNA_screen_types.h"

#include "UI_interface_c.hh"

#include "testing/testing.h"

namespace blender::ui::tests {

/**
 * #PANEL_TYPE_ALWAYS_OPEN exists for the floating redo region, whose panel is the whole content of
 * the region: collapsed it leaves a title bar and nothing to adjust. These cover the one function
 * every caller asks - the expand arrow, the layout, the region height and the collapse gestures all
 * read #panel_is_closed.
 */
TEST(panel_always_open, AnAlwaysOpenPanelReportsItselfOpen)
{
  PanelType type = {};
  type.flag = PANEL_TYPE_ALWAYS_OPEN;
  Panel panel = {};
  panel.type = &type;

  EXPECT_FALSE(panel_is_closed(&panel));
}

/** A file saved while the panel could still collapse must not come back collapsed. */
TEST(panel_always_open, AStoredClosedFlagIsIgnored)
{
  PanelType type = {};
  type.flag = PANEL_TYPE_ALWAYS_OPEN;
  Panel panel = {};
  panel.type = &type;
  panel.flag = PNL_CLOSED;

  EXPECT_FALSE(panel_is_closed(&panel));
}

/** The flag is opt-in: every other panel keeps answering from its stored state. */
TEST(panel_always_open, OrdinaryPanelsStillCollapse)
{
  PanelType type = {};
  Panel panel = {};
  panel.type = &type;
  panel.flag = PNL_CLOSED;

  EXPECT_TRUE(panel_is_closed(&panel));

  panel.flag = ePanel_Flag(0);
  EXPECT_FALSE(panel_is_closed(&panel));
}

}  // namespace blender::ui::tests
