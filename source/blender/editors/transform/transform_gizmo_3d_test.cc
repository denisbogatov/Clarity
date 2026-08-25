/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

#include "testing/testing.h"

#include "BLI_math_constants.h"
#include "BLI_math_matrix.h"
#include "BLI_math_rotation.h"
#include "BLI_math_vector.h"

#include "DNA_view3d_types.h"

#include "ED_gizmo_library.hh"

#include "transform_gizmo.hh"
#include "transform_gizmo_clarity_cache.hh"
#include "transform_gizmo_clarity_pick.hh"

namespace blender::ed::transform::tests {

static constexpr bool clarity = true;
static constexpr bool blender_default = false;
static constexpr bool visible = true;
static constexpr bool hidden = false;

TEST(transform_gizmo_3d, ClarityVisualProfileMatchesMayaReferencePixels)
{
  using Profile = ClarityGizmoVisualProfile;
  const float pixels = Profile::reference_size_px;

  /* Move: 20 px to the stem, 60 px to the cone base and about 80 px to its tip. */
  EXPECT_NEAR(Profile::translate_axis_start * pixels, 18.75f, 0.01f);
  EXPECT_NEAR(Profile::translate_axis_end * pixels, 60.0f, 0.01f);
  EXPECT_NEAR((Profile::translate_axis_end + 0.25f) * pixels, 78.75f, 0.01f);

  /* Scale: the cube occupies the ten pixels after the 56 px stem end. */
  EXPECT_NEAR(Profile::scale_axis_start * pixels, 18.75f, 0.01f);
  EXPECT_NEAR(Profile::scale_axis_end * pixels, 56.25f, 0.01f);
  EXPECT_NEAR((Profile::scale_axis_end + 0.10f) * pixels, 63.75f, 0.01f);

  /* Plane diamonds are centred at 45 px normally and 60 px while editing the pivot. */
  EXPECT_NEAR((Profile::plane_length + 0.10f) * pixels, 45.0f, 0.01f);
  EXPECT_NEAR((Profile::maya_edit_pivot_plane_length + 0.10f) * pixels, 60.0f, 0.01f);
  EXPECT_FLOAT_EQ(Profile::plane_fill_alpha, 0.25f);
  EXPECT_FLOAT_EQ(Profile::trackball_alpha, 1.0f);

  EXPECT_NEAR(Profile::translate_center_scale * pixels, 10.125f, 0.01f);
  EXPECT_NEAR(Profile::rotate_axis_scale * pixels, 60.0f, 0.01f);
  EXPECT_NEAR(Profile::rotate_view_scale * pixels, 69.0f, 0.01f);
  EXPECT_NEAR(Profile::maya_edit_pivot_rotate_scale * pixels, 30.0f, 0.01f);
  EXPECT_FLOAT_EQ(Profile::line_width, 1.0f);
  EXPECT_FLOAT_EQ(Profile::ring_select_width, 3.0f);
}

/**
 * The manipulator matrix the Clarity pivot writes stays affine.
 *
 * The reported defect was that an Edit Pivot axis could not be clicked at all - the manipulator was
 * drawn exactly where it belonged, and no press anywhere on an arrow or a ring ever reached it. The
 * cause was one uninitialised element: the axes were written into #RegionView3D::twmat row by row
 * and the fourth row was left alone, so its `w` stayed zero. Multiplying by such a matrix discards
 * the translation of the other one. The draw pass never noticed, because its model-view has no
 * translation to lose. The selection pass puts the view matrix there, so every handle was
 * transformed to the camera and rasterized nowhere near the cursor.
 */
TEST(transform_gizmo_3d, ClarityPivotManipulatorMatrixStaysAffine)
{
  /* A region that has not held a manipulator yet, which is where the zero came from. */
  float matrix[4][4] = {{0.0f}};
  const float axes[3][3] = {{0.0f, 1.0f, 0.0f}, {0.0f, 0.0f, 1.0f}, {1.0f, 0.0f, 0.0f}};
  clarity_gizmo_matrix_axes_set(matrix, axes);

  EXPECT_FLOAT_EQ(matrix[0][1], 1.0f);
  EXPECT_FLOAT_EQ(matrix[1][2], 1.0f);
  EXPECT_FLOAT_EQ(matrix[2][0], 1.0f);
  EXPECT_FLOAT_EQ(matrix[0][3], 0.0f);
  EXPECT_FLOAT_EQ(matrix[1][3], 0.0f);
  EXPECT_FLOAT_EQ(matrix[2][3], 0.0f);
  EXPECT_FLOAT_EQ(matrix[3][3], 1.0f);

  /* And the consequence that made the defect invisible until it was fatal: a handle carrying this
   * matrix has to keep the translation of the view matrix the selection pass multiplies it by. */
  float view[4][4];
  unit_m4(view);
  view[3][2] = -10.0f;
  mul_m4_m4_post(view, matrix);
  EXPECT_FLOAT_EQ(view[3][2], -10.0f);
}

/**
 * Edit Pivot keeps Maya's proportions at a size a hand can use.
 *
 * The measured values above are what Maya draws; these are what this fork draws for the one layout
 * that has to fit rings, plane handles and a centre square around the same arrows.
 */
TEST(transform_gizmo_3d, ClarityEditPivotIsDrawnOneSizeUp)
{
  using Profile = ClarityGizmoVisualProfile;
  const float pixels = Profile::reference_size_px;

  EXPECT_GT(Profile::edit_pivot_size_boost, 1.0f);
  EXPECT_NEAR(Profile::edit_pivot_axis_start * pixels, 26.25f, 0.01f);
  EXPECT_NEAR(Profile::edit_pivot_axis_end * pixels, 84.0f, 0.01f);
  EXPECT_NEAR((Profile::edit_pivot_axis_end + 0.25f) * pixels, 102.75f, 0.01f);
  EXPECT_NEAR(Profile::edit_pivot_rotate_scale * pixels, 42.0f, 0.01f);
  EXPECT_NEAR(Profile::edit_pivot_plane_length * pixels, 73.5f, 0.01f);

  /* Except the centre square, which stays Maya's size so it does not reach over the arrows. */
  EXPECT_FLOAT_EQ(Profile::edit_pivot_center_scale, Profile::translate_center_scale);
  EXPECT_NEAR(Profile::edit_pivot_center_scale * pixels, 10.125f, 0.01f);
  EXPECT_LT(Profile::edit_pivot_center_scale, Profile::edit_pivot_axis_start);

  /* Maya's proportions: every handle grew by the same factor. */
  EXPECT_NEAR(Profile::edit_pivot_axis_end / Profile::edit_pivot_rotate_scale,
              Profile::translate_axis_end / Profile::maya_edit_pivot_rotate_scale,
              0.001f);

  /* What the rings leave of an arrow. Their selection band crosses the stem at 40.5-43.5 px, and
   * the hit cylinder of the stem answers from 26 px to the cone tip: nearly all of the arrow is
   * clear of the band even before the depth bias decides the crossing itself. */
  const float ring_band_outer = Profile::edit_pivot_rotate_scale * pixels +
                                Profile::ring_select_width * 0.5f;
  const float axis_tip = (Profile::edit_pivot_axis_end + 0.25f) * pixels;
  EXPECT_LT(ring_band_outer, axis_tip);
  EXPECT_GT(axis_tip - ring_band_outer, 50.0f);

  /* The pointing tolerance is a pixel width, so it does not follow the boost. */
  EXPECT_NEAR(Profile::edit_pivot_axis_select_radius * pixels * 2.0f, 30.0f, 0.01f);
  EXPECT_GT(Profile::edit_pivot_axis_select_radius * pixels, Profile::line_width);
}

TEST(transform_gizmo_3d, ClarityVisualProfileMatchesMayaReferenceColors)
{
  using Profile = ClarityGizmoVisualProfile;
  EXPECT_EQ(Profile::axis_x.r, 255);
  EXPECT_EQ(Profile::axis_x.g, 1);
  EXPECT_EQ(Profile::axis_x.b, 0);
  EXPECT_EQ(Profile::axis_y.r, 0);
  EXPECT_EQ(Profile::axis_y.g, 255);
  EXPECT_EQ(Profile::axis_y.b, 15);
  EXPECT_EQ(Profile::axis_z.r, 0);
  EXPECT_EQ(Profile::axis_z.g, 0);
  EXPECT_EQ(Profile::axis_z.b, 255);
  EXPECT_EQ(Profile::view.r, 100);
  EXPECT_EQ(Profile::view.g, 220);
  EXPECT_EQ(Profile::view.b, 255);
  EXPECT_EQ(Profile::selected.r, 253);
  EXPECT_EQ(Profile::selected.g, 255);
  EXPECT_EQ(Profile::selected.b, 136);
}

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

/**
 * A ring and an axis handle meet at a shared point, and picking resolves a tie by depth, so the
 * view angle decided which one the click reached. The axis is the smaller target and the one being
 * aimed at, so the ring goes behind it wherever the two layouts overlap.
 */
TEST(transform_gizmo_3d, RingsGiveTheContestedPixelsToTheAxisHandles)
{
  constexpr bool scale_and_rotate = true;
  constexpr bool rotate_only = false;
  const float behind = ClarityGizmoVisualProfile::across_axes_select_bias;

  EXPECT_LT(behind, 0.0f);
  EXPECT_FLOAT_EQ(clarity_gizmo_rotate_select_bias_get(edit_pivot, rotate_only), behind);
  EXPECT_FLOAT_EQ(clarity_gizmo_rotate_select_bias_get(edit_pivot, scale_and_rotate), behind);
  /* Upstream's own rule for a layout that puts rings over the scale handles. */
  EXPECT_FLOAT_EQ(clarity_gizmo_rotate_select_bias_get(no_edit_pivot, scale_and_rotate), behind);
  /* A rotation-only manipulator has nothing to lose the contest to. */
  EXPECT_FLOAT_EQ(clarity_gizmo_rotate_select_bias_get(no_edit_pivot, rotate_only), 0.0f);

  /* The plane diamonds of Edit Pivot sit on diagonals that a view angle can lay along an arrow. */
  EXPECT_FLOAT_EQ(clarity_gizmo_plane_select_bias_get(edit_pivot), behind);
  EXPECT_FLOAT_EQ(clarity_gizmo_plane_select_bias_get(no_edit_pivot), 0.0f);
}

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

TEST(transform_gizmo_3d, ClarityTranslateCenterSquareKeepsCompleteViewBasis)
{
  float basis[4][4];
  unit_m4(basis);
  copy_v3_fl3(basis[3], 4.0f, 5.0f, 6.0f);

  float viewinv[4][4];
  unit_m4(viewinv);
  const float axis[3] = {0.0f, 0.0f, 1.0f};
  axis_angle_to_mat4(viewinv, axis, 0.75f);

  gizmo_3d_view_aligned_basis_rotation_set(basis, viewinv);

  for (int column = 0; column < 3; column++) {
    for (int row = 0; row < 3; row++) {
      EXPECT_FLOAT_EQ(basis[column][row], viewinv[column][row]);
    }
  }
  EXPECT_FLOAT_EQ(basis[3][0], 4.0f);
  EXPECT_FLOAT_EQ(basis[3][1], 5.0f);
  EXPECT_FLOAT_EQ(basis[3][2], 6.0f);
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

/**
 * The rule that replaces depth-buffer arbitration around the manipulator.
 *
 * The defect it answers: the cursor exactly on the X ring, the Y ring passing a few pixels nearer
 * the camera, and the Y ring highlighted. Depth cannot tell those apart; distance can.
 */
TEST(transform_gizmo_3d, ClarityPickTakesTheNearestHandle)
{
  const ClarityPickCandidate on_the_x_ring = {0, ClarityPickKind::Ring, 0.5f};
  const ClarityPickCandidate the_y_ring_nearby = {1, ClarityPickKind::Ring, 7.0f};
  const ClarityPickCandidate candidates[] = {the_y_ring_nearby, on_the_x_ring};

  const ClarityPickCandidate best = clarity_pick_resolve(candidates);
  EXPECT_EQ(best.handle, on_the_x_ring.handle);

  /* The order the handles were gathered in says nothing. */
  const ClarityPickCandidate reversed[] = {on_the_x_ring, the_y_ring_nearby};
  EXPECT_EQ(clarity_pick_resolve(reversed).handle, on_the_x_ring.handle);
}

TEST(transform_gizmo_3d, ClarityPickIgnoresWhatIsOutOfRange)
{
  const ClarityPickCandidate too_far = {3, ClarityPickKind::Axis, clarity_pick_range_px + 0.5f};
  const ClarityPickCandidate candidates[] = {too_far};
  EXPECT_LT(clarity_pick_resolve(candidates).handle, 0);

  const ClarityPickCandidate just_inside = {3, ClarityPickKind::Axis, clarity_pick_range_px};
  const ClarityPickCandidate reachable[] = {just_inside};
  EXPECT_EQ(clarity_pick_resolve(reachable).handle, just_inside.handle);

  /* Nothing at all is not a handle. */
  EXPECT_LT(clarity_pick_resolve({}).handle, 0);
}

/**
 * Where a ring crosses an arrow the two are the same distance away, and the arrow is what a hand
 * is aiming at: it is the smaller target, and the ring sweeps past every handle there is.
 */
TEST(transform_gizmo_3d, ClarityPickBreaksATieByTheKindOfHandle)
{
  const ClarityPickCandidate ring = {0, ClarityPickKind::Ring, 1.0f};
  const ClarityPickCandidate plane = {1, ClarityPickKind::Plane, 2.0f};
  const ClarityPickCandidate arrow = {2, ClarityPickKind::Axis, 2.5f};
  const ClarityPickCandidate centre = {3, ClarityPickKind::Center, 3.0f};
  const ClarityPickCandidate trackball = {4, ClarityPickKind::Trackball, 0.0f};

  const ClarityPickCandidate crowded[] = {trackball, ring, plane, arrow, centre};
  EXPECT_EQ(clarity_pick_resolve(crowded).handle, centre.handle);

  const ClarityPickCandidate without_centre[] = {trackball, ring, plane, arrow};
  EXPECT_EQ(clarity_pick_resolve(without_centre).handle, arrow.handle);

  const ClarityPickCandidate rings_and_planes[] = {trackball, ring, plane};
  EXPECT_EQ(clarity_pick_resolve(rings_and_planes).handle, plane.handle);

  /* The trackball is the whole disc behind the manipulator: it answers only where nothing else
   * does. */
  const ClarityPickCandidate alone[] = {trackball};
  EXPECT_EQ(clarity_pick_resolve(alone).handle, trackball.handle);
}

/**
 * A tie is a band, not an equality - but a handle clearly closer than another still wins, whatever
 * kind either of them is. Without that, an arrow would answer for a ring the cursor is sitting on.
 */
TEST(transform_gizmo_3d, ClarityPickKeepsDistanceAboveKindBeyondTheTie)
{
  const ClarityPickCandidate on_the_ring = {0, ClarityPickKind::Ring, 0.0f};
  const ClarityPickCandidate arrow_further_off = {
      1, ClarityPickKind::Axis, clarity_pick_tie_px + 1.0f};
  const ClarityPickCandidate candidates[] = {on_the_ring, arrow_further_off};
  EXPECT_EQ(clarity_pick_resolve(candidates).handle, on_the_ring.handle);

  /* Inside the band the arrow takes it back. */
  const ClarityPickCandidate arrow_beside_it = {
      1, ClarityPickKind::Axis, clarity_pick_tie_px - 0.5f};
  const ClarityPickCandidate contested[] = {on_the_ring, arrow_beside_it};
  EXPECT_EQ(clarity_pick_resolve(contested).handle, arrow_beside_it.handle);
}

/**
 * The trackball is a disc the size of the manipulator, at distance zero everywhere inside it. Every
 * other handle is drawn within it, so it has to stand aside for all of them - a press on an arrow
 * six pixels off its line is a translation, not a free rotation.
 */
TEST(transform_gizmo_3d, ClarityPickKeepsTheTrackballBehindEverything)
{
  const ClarityPickCandidate trackball = {0, ClarityPickKind::Trackball, 0.0f};
  const ClarityPickCandidate arrow = {1, ClarityPickKind::Axis, 6.0f};
  const ClarityPickCandidate on_an_arrow[] = {trackball, arrow};
  EXPECT_EQ(clarity_pick_resolve(on_an_arrow).handle, arrow.handle);

  const ClarityPickCandidate ring = {2, ClarityPickKind::Ring, 9.0f};
  const ClarityPickCandidate on_a_ring[] = {trackball, ring};
  EXPECT_EQ(clarity_pick_resolve(on_a_ring).handle, ring.handle);

  /* Inside the disc with everything else out of range, it is the handle. */
  const ClarityPickCandidate far_arrow = {1, ClarityPickKind::Axis, clarity_pick_range_px + 1.0f};
  const ClarityPickCandidate empty_space[] = {trackball, far_arrow};
  EXPECT_EQ(clarity_pick_resolve(empty_space).handle, trackball.handle);
}

/** Two of one kind: the nearer one, with no reference to how they were ordered. */
TEST(transform_gizmo_3d, ClarityPickPrefersTheNearerOfTwoRings)
{
  const ClarityPickCandidate near_ring = {0, ClarityPickKind::Ring, 1.0f};
  const ClarityPickCandidate far_ring = {1, ClarityPickKind::Ring, 2.0f};
  const ClarityPickCandidate candidates[] = {far_ring, near_ring};
  EXPECT_EQ(clarity_pick_resolve(candidates).handle, near_ring.handle);
}

/**
 * Where the clip of a rotation ring cuts.
 *
 * Two defects met here. A cut through the centre takes a ring lying in the plane of the view
 * whole - and that ring is its own silhouette, so it should be the one thing left entire. Opening
 * the cut for every ring instead gave the tilted ones an arc longer than a half, and the extra ran
 * back along the far branch of the ellipse, which reads on screen as fragments loose in the middle
 * of nowhere. So: a plain half everywhere, and the whole circle only where the ring faces the
 * camera.
 */
TEST(transform_gizmo_3d, ClarityRingClipCutsAtTheSilhouette)
{
  /* Edge on, and every ordinary angle: the plane stays at the centre, the arc is a half, and its
   * ends land on the silhouette of the sphere the three rings share. */
  EXPECT_FLOAT_EQ(ED_gizmo_dial_clip_radius_bias(0.0f), 0.0f);
  EXPECT_FLOAT_EQ(ED_gizmo_dial_clip_radius_bias(float(M_SQRT1_2)), 0.0f);
  EXPECT_FLOAT_EQ(ED_gizmo_dial_clip_radius_bias(0.9f), 0.0f);
  EXPECT_FLOAT_EQ(ED_gizmo_dial_clip_radius_bias(-0.9f), 0.0f);

  /* Face on: the plane drops a full radius back, so nothing of the ring is cut. */
  EXPECT_FLOAT_EQ(ED_gizmo_dial_clip_radius_bias(1.0f), 1.0f);
  EXPECT_FLOAT_EQ(ED_gizmo_dial_clip_radius_bias(-1.0f), 1.0f);

  /* The threshold is close enough to face on that the ring is nearly a circle by then. */
  EXPECT_GT(ED_GIZMO_DIAL_CLIP_FACING, 0.9f);
  EXPECT_LT(ED_GIZMO_DIAL_CLIP_FACING, 1.0f);

  /* Between the two it only ever opens up, and without a step at either end. */
  float previous = -1.0f;
  for (int step = 0; step <= 20; step++) {
    const float bias = ED_gizmo_dial_clip_radius_bias(float(step) / 20.0f);
    EXPECT_GE(bias, previous - 1e-6f);
    EXPECT_LE(bias, 1.0f);
    previous = bias;
  }
}

}  // namespace blender::ed::transform::tests
