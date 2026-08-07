"""Regression checks for the Maya 2025 Edit Pivot golden fixture."""

from __future__ import annotations

import json
import math
import unittest
from pathlib import Path


FIXTURE = Path(__file__).parent / "fixtures" / "maya_2025_pivot_reference.json"
TARGET = (9.25, -4.5, 6.75)


def _near_sequence(actual, expected, tolerance=1.0e-9):
    if len(actual) != len(expected):
        return False
    return all(
        math.isclose(float(a), float(b), rel_tol=0.0, abs_tol=tolerance)
        for a, b in zip(actual, expected)
    )


class MayaPivotFixtureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        cls.scenarios = cls.fixture["scenarios"]

    def states(self, scenario):
        captures = self.scenarios[scenario]["captures"]
        return captures[0]["state"], captures[-1]["state"], captures[-1]

    def assertSequenceNear(self, actual, expected, tolerance=1.0e-9):
        self.assertTrue(
            _near_sequence(actual, expected, tolerance),
            f"{actual!r} != {expected!r}",
        )

    def test_adversarial_transform_is_present(self):
        initial, _, _ = self.states("object_pivot_move")
        self.assertLess(initial["scale"][1], 0.0)
        self.assertNotEqual(initial["shear"], [0.0, 0.0, 0.0])
        self.assertNotEqual(
            initial["offsetParentMatrix"],
            [1.0, 0.0, 0.0, 0.0] * 4,
        )

    def test_object_pivot_move_uses_both_channels_and_preserves_world(self):
        initial, result, capture = self.states("object_pivot_move")
        self.assertSequenceNear(result["rotatePivotWorld"], TARGET)
        self.assertSequenceNear(result["scalePivotWorld"], TARGET)
        self.assertSequenceNear(result["worldMatrix"], initial["worldMatrix"])
        self.assertSequenceNear(
            capture["childWorldMatrix"],
            self.scenarios["custom_position_orientation"]["captures"][-1][
                "childWorldMatrix"
            ],
        )
        self.assertNotEqual(result["rotatePivot"], result["scalePivot"])

    def test_manipulator_channels_are_independent(self):
        _, result, _ = self.states("independent_flags")
        manipulator = result["manipPivot"]
        self.assertTrue(manipulator["positionValid"])
        self.assertFalse(manipulator["orientationValid"])
        self.assertTrue(manipulator["pinned"])
        self.assertFalse(manipulator["snapPosition"])
        self.assertTrue(manipulator["snapOrientation"])
        self.assertTrue(manipulator["bakeOrientationAutomatically"])
        self.assertEqual(manipulator["resetMode"], 1)

    def test_center_and_zero_are_distinct(self):
        initial, center, _ = self.states("reset_position_center")
        _, zero, _ = self.states("reset_position_zero")
        self.assertNotEqual(center["rotatePivot"], [0.0, 0.0, 0.0])
        self.assertNotEqual(center["scalePivot"], [0.0, 0.0, 0.0])
        self.assertSequenceNear(zero["rotatePivot"], [0.0, 0.0, 0.0])
        self.assertSequenceNear(zero["scalePivot"], [0.0, 0.0, 0.0])
        self.assertSequenceNear(center["worldMatrix"], initial["worldMatrix"])
        self.assertSequenceNear(zero["worldMatrix"], initial["worldMatrix"])

    def test_zero_reset_also_clears_pivot_translations(self):
        """Zero reset puts the pivot back on the object origin, translations included.

        Both reset scenarios move the pivot first, and `xform -pivots` preserves the overall
        transformation by default, so the state Maya resets from is the one captured by
        `object_pivot_move`: pivots and pivot translations both non-zero. Zeroing only the
        pivot channels would leave the pivot at the compensation offset instead of at the
        origin, which is what `-zeroTransformPivots` exists to avoid.
        """
        _, moved, _ = self.states("object_pivot_move")
        self.assertNotEqual(moved["rotatePivotTranslate"], [0.0, 0.0, 0.0])
        self.assertNotEqual(moved["scalePivotTranslate"], [0.0, 0.0, 0.0])

        initial, zero, _ = self.states("reset_position_zero")
        self.assertSequenceNear(zero["rotatePivotTranslate"], [0.0, 0.0, 0.0])
        self.assertSequenceNear(zero["scalePivotTranslate"], [0.0, 0.0, 0.0])
        self.assertSequenceNear(zero["rotatePivotWorld"], initial["rotatePivotWorld"])
        self.assertSequenceNear(zero["scalePivotWorld"], initial["scalePivotWorld"])
        # The initial pivot sits on the object origin, so the reset one has to as well.
        self.assertSequenceNear(zero["rotatePivotWorld"], zero["worldMatrix"][12:15])

    def test_center_reset_keeps_the_preserving_compensation(self):
        """Center reset is a preserving pivot move, so its compensation channels stay."""
        _, center, _ = self.states("reset_position_center")
        self.assertNotEqual(center["rotatePivotTranslate"], [0.0, 0.0, 0.0])

    def test_orientation_reset_does_not_change_object_channels(self):
        initial, result, _ = self.states("reset_orientation")
        for channel in (
            "translate",
            "rotate",
            "rotateAxis",
            "scale",
            "shear",
            "rotatePivot",
            "scalePivot",
            "worldMatrix",
        ):
            self.assertSequenceNear(result[channel], initial[channel])
        self.assertFalse(result["manipPivot"]["orientationValid"])

    def test_bake_position_zeros_pivots_and_preserves_child(self):
        initial, result, capture = self.states("bake_position")
        self.assertSequenceNear(result["worldMatrix"][12:15], TARGET)
        self.assertSequenceNear(result["rotatePivot"], [0.0, 0.0, 0.0])
        self.assertSequenceNear(result["scalePivot"], [0.0, 0.0, 0.0])
        self.assertSequenceNear(
            capture["childWorldMatrix"],
            self.scenarios["object_pivot_move"]["captures"][-1]["childWorldMatrix"],
        )
        self.assertNotEqual(result["translate"], initial["translate"])

    def test_bake_orientation_preserves_child_and_special_channels(self):
        initial, result, capture = self.states("bake_orientation")
        self.assertNotEqual(result["rotate"], initial["rotate"])
        self.assertSequenceNear(result["rotateAxis"], initial["rotateAxis"])
        self.assertSequenceNear(result["scale"], initial["scale"])
        self.assertSequenceNear(result["shear"], initial["shear"])
        self.assertSequenceNear(
            capture["childWorldMatrix"],
            self.scenarios["object_pivot_move"]["captures"][-1]["childWorldMatrix"],
        )

    def test_tool_and_object_switch_keep_pinned_manipulator(self):
        for scenario in ("tool_switch", "object_switch_pinned"):
            _, result, _ = self.states(scenario)
            manipulator = result["manipPivot"]
            self.assertTrue(manipulator["pinned"])
            self.assertSequenceNear(manipulator["position"][0], TARGET)
            self.assertTrue(manipulator["orientationValid"])


if __name__ == "__main__":
    unittest.main()
