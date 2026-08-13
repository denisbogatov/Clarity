"""Regression checks for the Maya pivot visual-reference contract and alpha solve."""

from __future__ import annotations

import ast
import json
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).parent
FIXTURE = ROOT / "fixtures" / "maya_2025_pivot_visual.json"
RUNNER = ROOT / "capture_reference_pivot_visual.py"
WINDOW = ROOT / "capture_reference_window.py"
_SPEC = importlib.util.spec_from_file_location("pivot_visual_schema", ROOT / "pivot_visual_schema.py")
assert _SPEC is not None and _SPEC.loader is not None
visual = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(visual)


def _composite(foreground, alpha, background):
    return [
        int(round(alpha * foreground[channel] + (1.0 - alpha) * background[channel]))
        for channel in range(3)
    ]


def _srgb_decode(value):
    value /= 255.0
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def _srgb_encode(value):
    encoded = 12.92 * value if value <= 0.0031308 else 1.055 * value ** (1.0 / 2.4) - 0.055
    return int(round(encoded * 255.0))


def _composite_srgb(foreground, alpha, background):
    return [
        _srgb_encode(
            alpha * _srgb_decode(foreground[channel])
            + (1.0 - alpha) * _srgb_decode(background[channel])
        )
        for channel in range(3)
    ]


class PivotVisualSchemaTest(unittest.TestCase):
    def test_runner_is_valid_python_and_window_button_is_wired(self):
        ast.parse(RUNNER.read_text(encoding="utf-8"), filename=str(RUNNER))
        window_source = WINDOW.read_text(encoding="utf-8")
        self.assertIn("import capture_reference_pivot_visual as pivot_visual", window_source)
        self.assertIn("def _run_pivot_visual()", window_source)
        self.assertIn("Записать внешний вид пивота", window_source)
        self.assertIn("command=_guard(_run_pivot_visual)", window_source)

    def test_case_matrix_covers_views_handles_sizes_locks_and_edit_pivot(self):
        cases = visual.case_specs()
        names = [case["name"] for case in cases]
        self.assertEqual(len(names), 45)
        self.assertEqual(len(names), len(set(names)))
        for tool in ("move", "rotate", "scale"):
            for view in visual.VIEWS:
                self.assertIn("{}_{}_default".format(tool, view), names)
        self.assertIn("move_perspective_handle_xy", names)
        self.assertIn("rotate_perspective_handle_arcball", names)
        self.assertIn("scale_perspective_handle_center", names)
        self.assertIn("move_perspective_size_075", names)
        self.assertIn("rotate_perspective_size_150", names)
        self.assertIn("scale_perspective_locked_scaleZ", names)
        self.assertIn("edit_pivot_perspective_pinned", names)
        self.assertIn("rotate_perspective_custom_pinned", names)

    def test_two_background_solve_recovers_translucent_rgb_and_alpha(self):
        foreground = (210, 60, 30)
        alpha = 0.4
        dark = _composite(foreground, alpha, (0, 0, 0))
        light = _composite(foreground, alpha, (255, 255, 255))
        solved = visual.solve_composite_pixel(dark, light)
        for actual, expected in zip(solved[:3], foreground):
            self.assertLessEqual(abs(actual - expected), 1)
        self.assertLessEqual(abs(solved[3] - round(alpha * 255)), 1)

    def test_two_background_solve_uses_measured_non_extreme_backgrounds(self):
        foreground = (32, 180, 240)
        alpha = 0.625
        dark_background = (17, 33, 49)
        light_background = (231, 219, 207)
        dark = _composite(foreground, alpha, dark_background)
        light = _composite(foreground, alpha, light_background)
        solved = visual.solve_composite_pixel(
            dark, light, dark_background, light_background
        )
        for actual, expected in zip(solved[:3], foreground):
            self.assertLessEqual(abs(actual - expected), 2)
        self.assertLessEqual(abs(solved[3] - round(alpha * 255)), 1)

    def test_transparent_background_pixel_stays_transparent(self):
        self.assertEqual(
            visual.solve_composite_pixel((0, 0, 0), (255, 255, 255)),
            (0, 0, 0, 0),
        )

    def test_srgb_linear_light_solve_and_recomposite(self):
        foreground = (230, 70, 25)
        alpha = 0.35
        dark = _composite_srgb(foreground, alpha, (0, 0, 0))
        light = _composite_srgb(foreground, alpha, (255, 255, 255))
        solved = visual.solve_composite_pixel(dark, light, transfer="srgb")
        for actual, expected in zip(solved[:3], foreground):
            self.assertLessEqual(abs(actual - expected), 2)
        middle_background = (128, 128, 128)
        predicted = visual.composite_pixel(solved, middle_background, transfer="srgb")
        actual = _composite_srgb(foreground, alpha, middle_background)
        for predicted_channel, actual_channel in zip(predicted, actual):
            self.assertLessEqual(abs(predicted_channel - actual_channel), 1)

    def test_transfer_residuals_compare_the_same_pixel(self):
        foreground = (230, 70, 25)
        alpha = 0.35
        display = [
            _composite(foreground, alpha, background)
            for background in ((0, 0, 0), (128, 128, 128), (255, 255, 255))
        ]
        srgb = [
            _composite_srgb(foreground, alpha, background)
            for background in ((0, 0, 0), (128, 128, 128), (255, 255, 255))
        ]
        display_residuals = visual.transfer_residuals(*display)
        srgb_residuals = visual.transfer_residuals(*srgb)
        self.assertLess(display_residuals["display"], display_residuals["srgb"])
        self.assertLess(srgb_residuals["srgb"], srgb_residuals["display"])

    def test_native_framebuffer_rgba_preserves_measured_alpha(self):
        self.assertEqual(visual.native_framebuffer_rgba((0, 252, 0, 191)), (0, 252, 0, 191))
        self.assertEqual(visual.native_framebuffer_rgba((91, 27, 4, 0)), (0, 0, 0, 0))

    def test_axis_color_classification(self):
        self.assertEqual(visual.classify_color((220, 45, 38)), "xRed")
        self.assertEqual(visual.classify_color((42, 210, 65)), "yGreen")
        self.assertEqual(visual.classify_color((45, 80, 230)), "zBlue")
        self.assertEqual(visual.classify_color((240, 220, 30)), "selectedYellow")
        self.assertEqual(visual.classify_color((128, 128, 128)), "neutral")

    def test_complete_synthetic_fixture_satisfies_contract(self):
        data = {
            "schemaVersion": visual.SCHEMA_VERSION,
            "environment": {"mayaVersion": "2025"},
            "captures": [
                {
                    "name": case["name"],
                    "artifacts": {
                        "dark": case["name"] + "_dark.png",
                        "middle": case["name"] + "_middle.png",
                        "light": case["name"] + "_light.png",
                        "rgba": case["name"] + "_rgba.png",
                    },
                    "pixelMetrics": {
                        "alphaSource": "nativeFramebuffer",
                        "visiblePixels": 100,
                        "compositingTransferTest": {"selected": "display"},
                    },
                }
                for case in visual.case_specs()
            ],
        }
        self.assertEqual(visual.validate_fixture(data), [])


@unittest.skipUnless(FIXTURE.exists(), "Maya visual fixture has not been captured on the Maya host")
class MayaPivotVisualFixtureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_fixture_contract_and_artifacts(self):
        self.assertEqual(visual.validate_fixture(self.data), [])
        for capture in self.data["captures"]:
            for filename in capture["artifacts"].values():
                self.assertTrue((FIXTURE.parent / filename).is_file(), filename)

    def test_perspective_tools_have_xyz_pixels(self):
        captures = {capture["name"]: capture for capture in self.data["captures"]}
        for tool in ("move", "rotate", "scale"):
            colors = captures["{}_perspective_default".format(tool)]["pixelMetrics"][
                "colorClasses"
            ]
            for axis in ("xRed", "yGreen", "zBlue"):
                self.assertGreater(colors.get(axis, {}).get("pixels", 0), 0)

    def test_fixture_uses_stable_native_framebuffer_alpha(self):
        for capture in self.data["captures"]:
            metrics = capture["pixelMetrics"]
            self.assertEqual(metrics["alphaSource"], "nativeFramebuffer", capture["name"])
            native = metrics["nativeFramebufferAlphaTest"]
            self.assertTrue(native["usable"], capture["name"])
            self.assertTrue(native["mapsIdentical"], capture["name"])
            self.assertEqual(native["differentPixels"], 0, capture["name"])
            tested = metrics["compositingTransferTest"]["testedPixels"]
            self.assertEqual(tested["display"], tested["srgb"], capture["name"])

    def test_rotate_and_edit_pivot_record_translucent_circle_pixels(self):
        captures = {capture["name"]: capture for capture in self.data["captures"]}
        for name in ("rotate_perspective_default", "edit_pivot_perspective_default"):
            bands = captures[name]["pixelMetrics"]["coverageByAlphaBand"]
            self.assertGreater(bands["translucent"], 0, name)


if __name__ == "__main__":
    unittest.main()
