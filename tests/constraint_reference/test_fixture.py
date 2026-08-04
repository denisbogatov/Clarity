"""Regression checks for the Maya 2025 point-constraint fixture."""

from __future__ import annotations

import json
import math
import unittest
from pathlib import Path


FIXTURE = Path(__file__).parent / "fixtures" / "maya_2025_constraints.json"


def _near(a, b, tolerance=1.0e-8):
    return math.isclose(float(a), float(b), rel_tol=0.0, abs_tol=tolerance)


class ClarityConstraintFixtureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        cls.scenarios = cls.data["scenarios"]

    def test_live_maya_metadata(self):
        self.assertEqual(self.data["mayaVersion"], "2025")
        self.assertEqual(self.data["constraintType"], "pointConstraint")

    def test_weighted_result_differs_from_equal_result(self):
        equal = self.scenarios["two_targets_equal"]["evaluated"]["translate"]
        weighted = self.scenarios["two_targets_weighted"]["evaluated"]["translate"]
        self.assertNotEqual(equal, weighted)

    def test_constrained_pivot_reaches_weighted_target_pivots(self):
        for name in ("one_target", "two_targets_equal", "two_targets_weighted"):
            scenario = self.scenarios[name]
            constraint = scenario["constraint"]
            positions = [
                scenario["targets"][target]["rotatePivotWorld"]
                for target in constraint["targets"]
            ]
            weights = constraint["weights"]
            total = sum(weights)
            expected = [
                sum(position[axis] * weight for position, weight in zip(positions, weights))
                / total
                for axis in range(3)
            ]
            actual = scenario["evaluated"]["rotatePivotWorld"]
            self.assertTrue(all(_near(a, b) for a, b in zip(actual, expected)))

    def test_maintain_offset_preserves_initial_world_position(self):
        scenario = self.scenarios["maintain_offset"]
        initial = scenario["initialAuthoredChannels"]["worldMatrix"][12:15]
        evaluated = scenario["evaluated"]["worldMatrix"][12:15]
        self.assertTrue(all(_near(a, b) for a, b in zip(initial, evaluated)))

    def test_skip_y_preserves_authored_y(self):
        scenario = self.scenarios["skip_y"]
        self.assertTrue(
            _near(
                scenario["initialAuthoredChannels"]["translate"][1],
                scenario["evaluated"]["translate"][1],
            )
        )

    def test_adversarial_parent_and_opm_are_present(self):
        scenario = self.scenarios["one_target"]
        parent = scenario["initialAuthoredChannels"]["parentMatrix"]
        opm = scenario["initialAuthoredChannels"]["offsetParentMatrix"]
        self.assertTrue(any(value < 0.0 for value in parent))
        self.assertNotEqual(opm, [1.0, 0.0, 0.0, 0.0] * 4)


if __name__ == "__main__":
    unittest.main()
