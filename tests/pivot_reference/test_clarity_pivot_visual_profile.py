"""Bind Clarity's gizmo constants to the measured Maya 2025 visual fixture."""

from __future__ import annotations

import json
import math
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROFILE = ROOT / "source/blender/editors/transform/transform_gizmo_clarity_cache.hh"
TRANSFORM = ROOT / "source/blender/editors/transform/transform_gizmo_3d.cc"
ARROW = ROOT / "source/blender/editors/gizmo_library/gizmo_types/arrow3d_gizmo.cc"
FIXTURE = ROOT / "tests/pivot_reference/fixtures/maya_2025_pivot_visual.json"


def _profile_float(source: str, name: str) -> float:
    match = re.search(
        r"static constexpr float\s+{}\s*=\s*([0-9.]+)f\s*;".format(re.escape(name)),
        source,
    )
    if match is None:
        raise AssertionError("missing profile float {}".format(name))
    return float(match.group(1))


def _profile_rgb(source: str, name: str) -> tuple[int, int, int]:
    match = re.search(
        (
            r"static constexpr ClarityGizmoRGB8\s+%s\s*=\s*"
            r"\{\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\}\s*;"
        )
        % re.escape(name),
        source,
    )
    if match is None:
        raise AssertionError("missing profile color {}".format(name))
    return tuple(int(value) for value in match.groups())


def _quantized(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    return tuple(min(255, int(round(value / 8.0) * 8)) for value in rgb)


@unittest.skipUnless(FIXTURE.exists(), "Maya visual fixture has not been captured")
class ClarityPivotVisualProfileTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = PROFILE.read_text(encoding="utf-8")
        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        cls.captures = {capture["name"]: capture for capture in data["captures"]}
        cls.unit = _profile_float(cls.source, "reference_size_px")

    def value(self, name: str) -> float:
        return _profile_float(self.source, name)

    def test_move_and_scale_axis_extents_match_front_view(self):
        move_x = self.captures["move_front_default"]["pixelMetrics"]["colorClasses"]["xRed"]
        self.assertAlmostEqual(
            self.value("translate_axis_start") * self.unit,
            move_x["boundsFromPivot"][0],
            delta=1.5,
        )
        # Blender's normal arrow cone extends 0.25 gizmo units beyond its stem.
        self.assertAlmostEqual(
            (self.value("translate_axis_end") + 0.25) * self.unit,
            move_x["boundsFromPivot"][2],
            delta=1.5,
        )

        scale_x = self.captures["scale_front_default"]["pixelMetrics"]["colorClasses"]["xRed"]
        self.assertAlmostEqual(
            self.value("scale_axis_start") * self.unit,
            scale_x["boundsFromPivot"][0],
            delta=1.5,
        )
        # The scale cube spans 0.10 units from the end of its stem.
        self.assertAlmostEqual(
            (self.value("scale_axis_end") + 0.10) * self.unit,
            scale_x["boundsFromPivot"][2],
            delta=1.5,
        )

    def test_center_plane_and_fill_alpha_match_front_view(self):
        metrics = self.captures["move_front_default"]["pixelMetrics"]
        center_bounds = metrics["colorClasses"]["selectedYellow"]["boundsFromPivot"]
        measured_half_width = max(abs(value) for value in center_bounds)
        self.assertAlmostEqual(
            self.value("translate_center_scale") * self.unit,
            measured_half_width,
            delta=1.0,
        )

        plane = metrics["colorClasses"]["zBlue"]
        plane_bounds = plane["boundsFromPivot"]
        measured_center = (plane_bounds[0] + plane_bounds[2]) * 0.5
        # The diamond's local vertices place its centre 0.10 units after `length`.
        self.assertAlmostEqual(
            (self.value("plane_length") + 0.10) * self.unit,
            measured_center,
            delta=1.0,
        )
        self.assertAlmostEqual(
            self.value("plane_fill_alpha"), plane["alpha"]["p10"], delta=0.01
        )

        scale_center_bounds = self.captures["scale_front_default"]["pixelMetrics"][
            "colorClasses"
        ]["selectedYellow"]["boundsFromPivot"]
        self.assertAlmostEqual(
            self.value("scale_center_scale") * self.unit,
            max(abs(value) for value in scale_center_bounds),
            delta=0.5,
        )

        edit_blue = self.captures["edit_pivot_front_default"]["pixelMetrics"]["colorClasses"][
            "zBlue"
        ]
        edit_plane_bins = [
            item for item in edit_blue["radialAlphaProfile"] if item["radiusPixels"] >= 64
        ]
        measured_edit_plane_radius = max(edit_plane_bins, key=lambda item: item["pixels"])[
            "radiusPixels"
        ]
        self.assertAlmostEqual(
            math.sqrt(2.0) * (self.value("edit_pivot_plane_length") + 0.10) * self.unit,
            measured_edit_plane_radius,
            delta=1.0,
        )

        # Maya's arcball remains selectable without drawing Blender's translucent filled disc.
        self.assertEqual(self.value("trackball_alpha"), 0.0)
        self.assertLess(
            self.captures["rotate_perspective_handle_arcball"]["pixelMetrics"]["visiblePixels"],
            2000,
        )

    def test_rotation_radii_match_front_view(self):
        rotate = self.captures["rotate_front_default"]["pixelMetrics"]["colorClasses"]
        self.assertAlmostEqual(
            self.value("rotate_axis_scale") * self.unit,
            rotate["zBlue"]["radiusPixels"]["p50"],
            delta=1.0,
        )
        self.assertAlmostEqual(
            self.value("rotate_view_scale") * self.unit,
            rotate["selectedYellow"]["radiusPixels"]["p50"],
            delta=1.0,
        )

        edit_blue = self.captures["edit_pivot_front_default"]["pixelMetrics"]["colorClasses"][
            "zBlue"
        ]
        ring_bins = [
            item for item in edit_blue["radialAlphaProfile"] if item["radiusPixels"] <= 40
        ]
        measured_edit_radius = max(ring_bins, key=lambda item: item["pixels"])["radiusPixels"]
        self.assertAlmostEqual(
            self.value("maya_edit_pivot_rotate_scale") * self.unit,
            measured_edit_radius,
            delta=1.0,
        )
        self.assertGreater(
            self.value("edit_pivot_rotate_scale"), self.value("maya_edit_pivot_rotate_scale")
        )
        self.assertEqual(self.value("line_width"), 1.0)

    def test_edit_pivot_axes_keep_thin_lines_with_a_wider_hit_target(self):
        hit_width = self.value("edit_pivot_axis_select_radius") * self.unit * 2.0
        self.assertAlmostEqual(hit_width, 18.0, delta=0.01)
        self.assertGreater(hit_width, self.value("line_width"))
        self.assertEqual(self.value("edit_pivot_ring_select_width"), 14.0)

    def test_palette_matches_dominant_fixture_colors(self):
        dominant = set()
        for name in ("move_front_default", "rotate_perspective_default"):
            dominant.update(
                tuple(item["rgb"])
                for item in self.captures[name]["pixelMetrics"]["dominantDisplayColors"]
            )
        for name in ("axis_x", "axis_y", "axis_z", "view", "selected"):
            self.assertIn(_quantized(_profile_rgb(self.source, name)), dominant, name)

    def test_cpp_draw_paths_use_the_profile(self):
        transform = TRANSFORM.read_text(encoding="utf-8")
        arrow = ARROW.read_text(encoding="utf-8")
        for name in (
            "translate_axis_start",
            "translate_axis_end",
            "scale_axis_start",
            "scale_axis_end",
            "plane_length",
            "edit_pivot_plane_length",
            "plane_fill_alpha",
            "trackball_alpha",
            "translate_center_scale",
            "scale_center_scale",
            "rotate_axis_scale",
            "rotate_view_scale",
            "edit_pivot_rotate_scale",
            "line_width",
            "edit_pivot_axis_select_radius",
            "edit_pivot_ring_select_width",
        ):
            self.assertIn("ClarityGizmoVisualProfile::" + name, transform)
        for name in ("axis_x", "axis_y", "axis_z", "view", "selected"):
            self.assertIn("ClarityGizmoVisualProfile::" + name, transform)
        self.assertIn('RNA_float_get(arrow->gizmo.ptr, "fill_alpha")', arrow)
        self.assertIn('RNA_float_get(arrow->gizmo.ptr, "stem_select_radius")', arrow)
        dial = (
            ROOT
            / "source/blender/editors/gizmo_library/gizmo_types/dial3d_gizmo.cc"
        ).read_text(encoding="utf-8")
        self.assertIn('RNA_float_get(gz->ptr, "select_line_width")', dial)
        self.assertIn("use_clarity_edit_pivot_style ?", transform)
        self.assertIn('RNA_def_float_factor(gzt->srna,\n                       "fill_alpha"', arrow)


if __name__ == "__main__":
    unittest.main()
