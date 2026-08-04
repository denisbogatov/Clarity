/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

#include "testing/testing.h"

#include "DNA_view3d_types.h"

#include "ED_gizmo_library.hh"

#include "transform_gizmo.hh"
#include "transform_gizmo_clarity_cache.hh"

namespace blender::ed::transform::tests {

static constexpr bool clarity = true;
static constexpr bool blender_default = false;
static constexpr bool visible = true;
static constexpr bool hidden = false;

static bool visible_during_drag(const bool use_clarity_style,
                                const int axis_idx_active,
                                const int axis_idx,
                                const bool visible_before_drag)
{
  return gizmo_3d_axis_visible_during_drag(
      use_clarity_style, axis_idx_active, axis_idx, visible_before_drag);
}

/**
 * The reported defect: dragging the Clarity centre square left it alone on screen, so the pivot looked
 * like it had disappeared. Every handle that was on screen stays on screen.
 */
TEST(transform_gizmo_3d, ClarityDragKeepsTheWholeManipulator)
{
  EXPECT_TRUE(visible_during_drag(clarity, MAN_AXIS_TRANS_C, MAN_AXIS_TRANS_C, visible));
  EXPECT_TRUE(visible_during_drag(clarity, MAN_AXIS_TRANS_C, MAN_AXIS_TRANS_XY, visible));
  EXPECT_TRUE(visible_during_drag(clarity, MAN_AXIS_TRANS_C, MAN_AXIS_ROT_C, visible));
  EXPECT_TRUE(visible_during_drag(clarity, MAN_AXIS_SCALE_X, MAN_AXIS_SCALE_C, visible));
  EXPECT_TRUE(visible_during_drag(clarity, MAN_AXIS_ROT_X, MAN_AXIS_ROT_Z, visible));
}

/** A handle the view-alignment rules had already hidden must not be revealed by the drag. */
TEST(transform_gizmo_3d, ClarityDragDoesNotRevealHiddenHandles)
{
  EXPECT_FALSE(visible_during_drag(clarity, MAN_AXIS_ROT_X, MAN_AXIS_ROT_Z, hidden));
  EXPECT_FALSE(visible_during_drag(clarity, MAN_AXIS_SCALE_X, MAN_AXIS_SCALE_C, hidden));
  /* The dragged handle itself is always drawn. */
  EXPECT_TRUE(visible_during_drag(clarity, MAN_AXIS_ROT_X, MAN_AXIS_ROT_X, hidden));
}

/** Outside the Clarity preset the drag still displays only the active handle. */
TEST(transform_gizmo_3d, BlenderDragDisplaysOnlyTheActiveHandle)
{
  EXPECT_TRUE(visible_during_drag(blender_default, MAN_AXIS_ROT_X, MAN_AXIS_ROT_X, visible));
  EXPECT_FALSE(visible_during_drag(blender_default, MAN_AXIS_ROT_X, MAN_AXIS_ROT_Z, visible));
  EXPECT_FALSE(visible_during_drag(blender_default, MAN_AXIS_SCALE_X, MAN_AXIS_SCALE_C, visible));
  EXPECT_FALSE(visible_during_drag(blender_default, MAN_AXIS_TRANS_C, MAN_AXIS_TRANS_XY, visible));
}

/** Translating keeps the three arrows as a visual reference, in both presets. */
TEST(transform_gizmo_3d, TranslateDragKeepsTheArrowsAsReference)
{
  for (const bool style : {blender_default, clarity}) {
    EXPECT_TRUE(visible_during_drag(style, MAN_AXIS_TRANS_C, MAN_AXIS_TRANS_X, hidden));
    EXPECT_TRUE(visible_during_drag(style, MAN_AXIS_TRANS_C, MAN_AXIS_TRANS_Y, hidden));
    EXPECT_TRUE(visible_during_drag(style, MAN_AXIS_TRANS_C, MAN_AXIS_TRANS_Z, hidden));
    /* Not a translate drag, so the arrows follow the general rule. */
    EXPECT_FALSE(visible_during_drag(style, MAN_AXIS_ROT_X, MAN_AXIS_TRANS_X, hidden));
  }
}

static constexpr bool edit_pivot = true;
static constexpr bool no_edit_pivot = false;

/** Clarity draws a square in the centre and swaps it for a circle while the drag runs. */
TEST(transform_gizmo_3d, ClarityTranslateCenterSquareBecomesCircleWhileDragging)
{
  EXPECT_EQ(gizmo_3d_translate_center_style_get(clarity, false, no_edit_pivot),
            ED_GIZMO_PRIMITIVE_STYLE_PLANE);
  EXPECT_EQ(gizmo_3d_translate_center_style_get(clarity, true, no_edit_pivot),
            ED_GIZMO_PRIMITIVE_STYLE_CIRCLE);
  /* The square is restored once the drag ended. */
  EXPECT_EQ(gizmo_3d_translate_center_style_get(clarity, false, no_edit_pivot),
            ED_GIZMO_PRIMITIVE_STYLE_PLANE);
}

/** Edit Pivot adds the rotation rings on top of the layout the active tool asked for. */
TEST(transform_gizmo_3d, EditPivotAddsRotationToTheActiveToolLayout)
{
  EXPECT_EQ(gizmo_3d_twtype_resolve(edit_pivot, V3D_GIZMO_SHOW_OBJECT_TRANSLATE),
            V3D_GIZMO_SHOW_OBJECT_TRANSLATE | V3D_GIZMO_SHOW_OBJECT_ROTATE);
  EXPECT_EQ(gizmo_3d_twtype_resolve(edit_pivot, V3D_GIZMO_SHOW_OBJECT_ROTATE),
            V3D_GIZMO_SHOW_OBJECT_ROTATE);
  /* A tool with no manipulator of its own still gets handles to drag the pivot by. */
  EXPECT_EQ(gizmo_3d_twtype_resolve(edit_pivot, 0),
            V3D_GIZMO_SHOW_OBJECT_TRANSLATE | V3D_GIZMO_SHOW_OBJECT_ROTATE);
  /* With the mode off the layout is the tool's, untouched. */
  EXPECT_EQ(gizmo_3d_twtype_resolve(no_edit_pivot, V3D_GIZMO_SHOW_OBJECT_TRANSLATE),
            V3D_GIZMO_SHOW_OBJECT_TRANSLATE);
  EXPECT_EQ(gizmo_3d_twtype_resolve(no_edit_pivot, 0), 0);
}

/**
 * The rings surround the translate handles instead of rearranging them: feeding a rotate layout to
 * the arrows shortened them, took their stems away and hid the plane handles, which is what made
 * turning the mode on look like the manipulator was rebuilt.
 */
TEST(transform_gizmo_3d, ClarityTranslateHandlesIgnoreTheRotationLayout)
{
  const int with_rings = V3D_GIZMO_SHOW_OBJECT_TRANSLATE | V3D_GIZMO_SHOW_OBJECT_ROTATE;
  EXPECT_EQ(gizmo_3d_translate_layout_twtype_get(clarity, with_rings),
            V3D_GIZMO_SHOW_OBJECT_TRANSLATE);
  /* Which is the very layout the tool has without the mode, so nothing about them changes. */
  EXPECT_EQ(gizmo_3d_translate_layout_twtype_get(clarity, with_rings),
            gizmo_3d_translate_layout_twtype_get(clarity, V3D_GIZMO_SHOW_OBJECT_TRANSLATE));
  /* Scale is not a rotation layout and is left alone. */
  EXPECT_EQ(gizmo_3d_translate_layout_twtype_get(clarity, V3D_GIZMO_SHOW_OBJECT_SCALE),
            V3D_GIZMO_SHOW_OBJECT_SCALE);
  /* Outside the Clarity preset the layout reaches the handles unchanged. */
  EXPECT_EQ(gizmo_3d_translate_layout_twtype_get(blender_default, with_rings), with_rings);
}

/**
 * The square inside a circle is the Edit Pivot indicator: it is drawn for as long as the mode is
 * on, so neither the start nor the end of a drag may change it.
 */
TEST(transform_gizmo_3d, EditPivotCenterKeepsSquareAndCircle)
{
  EXPECT_EQ(gizmo_3d_translate_center_style_get(clarity, false, edit_pivot),
            ED_GIZMO_PRIMITIVE_STYLE_PLANE_CIRCLE);
  EXPECT_EQ(gizmo_3d_translate_center_style_get(clarity, true, edit_pivot),
            ED_GIZMO_PRIMITIVE_STYLE_PLANE_CIRCLE);
}

/** Blender's translate centre is a circle whether it is dragged or not. */
TEST(transform_gizmo_3d, BlenderTranslateCenterStaysACircle)
{
  for (const bool pivot_mode : {no_edit_pivot, edit_pivot}) {
    EXPECT_EQ(gizmo_3d_translate_center_style_get(blender_default, false, pivot_mode),
              ED_GIZMO_PRIMITIVE_STYLE_CIRCLE);
    EXPECT_EQ(gizmo_3d_translate_center_style_get(blender_default, true, pivot_mode),
              ED_GIZMO_PRIMITIVE_STYLE_CIRCLE);
  }
}

/** The Clarity scale centre is a cube that the drag keeps; Blender turns its annulus into a circle. */
TEST(transform_gizmo_3d, ScaleCenterStyleFollowsThePreset)
{
  EXPECT_EQ(gizmo_3d_scale_center_style_get(clarity, false), ED_GIZMO_PRIMITIVE_STYLE_CUBE);
  EXPECT_EQ(gizmo_3d_scale_center_style_get(clarity, true), ED_GIZMO_PRIMITIVE_STYLE_CUBE);
  EXPECT_EQ(gizmo_3d_scale_center_style_get(blender_default, false),
            ED_GIZMO_PRIMITIVE_STYLE_ANNULUS);
  EXPECT_EQ(gizmo_3d_scale_center_style_get(blender_default, true),
            ED_GIZMO_PRIMITIVE_STYLE_CIRCLE);
}

/**
 * Repeated draw preparation keeps the already applied style, while a layout rebuild or a mode
 * transition forces one atomic reapplication.
 */
TEST(transform_gizmo_3d, ClarityStyleCacheTracksTransitionsAndInvalidation)
{
  const int layout = V3D_GIZMO_SHOW_OBJECT_TRANSLATE | V3D_GIZMO_SHOW_OBJECT_ROTATE;

  ClarityGizmoStyleCache cache{};
  EXPECT_TRUE(cache.update_needed(clarity, no_edit_pivot, layout));

  cache.mark_applied(clarity, no_edit_pivot, layout);
  EXPECT_FALSE(cache.update_needed(clarity, no_edit_pivot, layout));
  EXPECT_TRUE(cache.update_needed(clarity, edit_pivot, layout));
  EXPECT_TRUE(cache.update_needed(blender_default, no_edit_pivot, layout));

  /* The translate handles are laid out from the manipulator layout, so it belongs to the key even
   * when neither style flag moved. */
  EXPECT_TRUE(cache.update_needed(clarity, no_edit_pivot, V3D_GIZMO_SHOW_OBJECT_TRANSLATE));

  cache.mark_applied(clarity, edit_pivot, layout);
  cache.invalidate();
  EXPECT_TRUE(cache.update_needed(clarity, edit_pivot, layout));
}

}  // namespace blender::ed::transform::tests
