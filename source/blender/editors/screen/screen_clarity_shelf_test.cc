/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

#include "testing/testing.h"

#include "ED_screen.hh"

namespace blender::tests {

/* The interface at its default size: a 20 px widget unit and a 26 px header. */
static constexpr int header_default = 26;
static constexpr int widget_unit_default = 20;
/* The two scales the shelf is drawn at, from `interface_widgets.cc` and `space_topbar.py`. */
static constexpr float icon_scale_default = 1.53f;
static constexpr float icon_scale_y_default = 1.32f;

static ClarityShelfMetrics metrics_at(const float ui_scale)
{
  return ED_clarity_shelf_metrics_calc(int(header_default * ui_scale),
                                       int(widget_unit_default * ui_scale),
                                       icon_scale_default,
                                       icon_scale_y_default,
                                       ui_scale);
}

/**
 * The gaps a user measures are the ones asked for.
 *
 * They are measured from the icon and not from the button around it, and that distinction is the
 * whole reason this is pinned down: the button is a little taller than its artwork, so a row that
 * padded the button by the requested amount left more space on screen than was asked for - seven
 * pixels above the first row where six were wanted, and four below the second.
 */
TEST(screen_clarity_shelf, GapsAroundTheIconsAreTheOnesAskedFor)
{
  const ClarityShelfMetrics metrics = metrics_at(1.0f);

  /* Above the first row: what the row keeps over its button, plus the space the button already
   * leaves around the icon. */
  const int top_padding = metrics.upper_row - metrics.button - metrics.upper_bottom_padding;
  EXPECT_EQ(top_padding + metrics.inner, metrics.gap_top);

  /* Below the second row, the same way. */
  EXPECT_EQ(metrics.lower_bottom_padding + metrics.inner, metrics.gap_bottom);

  /* And between them: what the upper row leaves under its icon plus what the lower row leaves
   * over its own. */
  const int lower_top_padding = metrics.lower_row - metrics.button - metrics.lower_bottom_padding;
  EXPECT_EQ((metrics.upper_bottom_padding + metrics.inner) + (lower_top_padding + metrics.inner),
            metrics.gap_between);
}

/** The Top Bar is its menu and its two rows, and the rows are their gaps and their icons. */
TEST(screen_clarity_shelf, TopBarIsItsMenuAndTwoRows)
{
  const ClarityShelfMetrics metrics = metrics_at(1.0f);

  EXPECT_EQ(metrics.total, header_default + metrics.upper_row + metrics.lower_row);
  EXPECT_EQ(metrics.total,
            header_default + metrics.gap_top + metrics.gap_between + metrics.gap_bottom +
                2 * metrics.icon);
}

/** Both rows hold an icon button whole. Either one short of that clips its own icons. */
TEST(screen_clarity_shelf, BothRowsHoldTheirIcons)
{
  for (const float ui_scale : {1.0f, 1.25f, 1.5f, 2.0f}) {
    const ClarityShelfMetrics metrics = metrics_at(ui_scale);

    EXPECT_GE(metrics.upper_row, metrics.button) << "upper row at scale " << ui_scale;
    EXPECT_GE(metrics.lower_row, metrics.button) << "lower row at scale " << ui_scale;
    EXPECT_GE(metrics.button, metrics.icon) << "button at scale " << ui_scale;
    EXPECT_GE(metrics.upper_bottom_padding, 0) << "upper padding at scale " << ui_scale;
    EXPECT_GE(metrics.lower_bottom_padding, 0) << "lower padding at scale " << ui_scale;
  }
}

/** The gap under the menu and the gap at the window edge are the same size. */
TEST(screen_clarity_shelf, TheShelfIsEvenlyInset)
{
  const ClarityShelfMetrics metrics = metrics_at(1.0f);

  EXPECT_EQ(metrics.gap_top, metrics.gap_bottom);
  /* And neither is larger than the space between the rows, which would read as the shelf floating
   * away from the menu. */
  EXPECT_LE(metrics.gap_top, metrics.gap_between);
}

/** The rows follow the icon, and the gaps do not grow with it. */
TEST(screen_clarity_shelf, RowsFollowTheIconSize)
{
  const ClarityShelfMetrics small = ED_clarity_shelf_metrics_calc(
      header_default, widget_unit_default, 1.0f, 1.0f, 1.0f);
  const ClarityShelfMetrics large = ED_clarity_shelf_metrics_calc(
      header_default, widget_unit_default, 2.0f, 2.0f, 1.0f);

  EXPECT_LT(small.icon, large.icon);
  EXPECT_LT(small.total, large.total);
  EXPECT_EQ(large.total - small.total, 2 * (large.icon - small.icon));
  EXPECT_EQ(small.gap_top, large.gap_top);
  EXPECT_EQ(small.gap_between, large.gap_between);
}

/** Interface scale reaches the gaps as well as the icons. */
TEST(screen_clarity_shelf, InterfaceScaleReachesEveryPart)
{
  const ClarityShelfMetrics unscaled = metrics_at(1.0f);
  const ClarityShelfMetrics doubled = metrics_at(2.0f);

  EXPECT_GE(doubled.icon, unscaled.icon * 2 - 1);
  EXPECT_GE(doubled.gap_top, unscaled.gap_top * 2 - 1);
  EXPECT_GE(doubled.gap_between, unscaled.gap_between * 2 - 1);
  EXPECT_GE(doubled.total, unscaled.total * 2 - 4);
}

}  // namespace blender::tests
