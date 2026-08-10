"""Host-Python checks for the Maya/Blender model-snapping contract."""

from __future__ import annotations

import ast
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).parent
BLENDER_RUNNER = ROOT / "capture_clarity_model_snapping.py"
MAYA_FIXTURE = ROOT / "fixtures" / "maya_2025_pivot_gestures_model_snapping.json"
COMPARATOR = ROOT / "compare_model_snapping.py"


def _scenario_literal(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "SCENARIOS":
                return ast.literal_eval(node.value)
    raise AssertionError("SCENARIOS literal not found in {}".format(path))


def _literal(path: Path, name: str):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == name:
                return ast.literal_eval(node.value)
        if isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
                return ast.literal_eval(node.value)
    raise AssertionError("{} literal not found in {}".format(name, path))


def _load_comparator():
    spec = importlib.util.spec_from_file_location("compare_model_snapping", COMPARATOR)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ModelSnappingSchemaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scenarios = _scenario_literal(BLENDER_RUNNER)
        cls.parity_count = _literal(BLENDER_RUNNER, "MAYA_PARITY_SCENARIO_COUNT")
        cls.unsupported = _literal(BLENDER_RUNNER, "UNSUPPORTED_SCENARIOS")
        cls.maya = json.loads(MAYA_FIXTURE.read_text(encoding="utf-8"))

    def test_blender_runner_is_valid_python(self):
        ast.parse(BLENDER_RUNNER.read_text(encoding="utf-8"), filename=str(BLENDER_RUNNER))

    def test_regression_fixes_from_the_first_blender_capture(self):
        source = BLENDER_RUNNER.read_text(encoding="utf-8")
        self.assertIn('pivot_reset(action="BOTH", mode="ZERO")', source)
        self.assertNotIn('pivot_reset(action="ALL"', source)
        self.assertNotIn('_undo_push("Clarity model snap initial state")', source)
        self.assertEqual(source.count('_undo_push("Clarity model snap before move")'), 2)
        self.assertEqual(source.count('_undo_push("Clarity model snap after move")'), 2)
        self.assertIn('meta["undoDistanceToInitial"]', source)
        self.assertIn("_set_pivot_world(\n        pivot_target,", source)
        self.assertIn('target = _pivot_world(scene["pivot_target"])', source)

        hierarchy = source.split('elif mode.startswith("hierarchy_"):', 1)[1].split(
            'elif mode.startswith("duplicate"):', 1
        )[0]
        parent_update = hierarchy.index("bpy.context.view_layer.update()")
        preserve_world = hierarchy.index("world = obj.matrix_world.copy()")
        assign_parent = hierarchy.index("obj.parent = parent")
        child_update = hierarchy.index("bpy.context.view_layer.update()", parent_update + 1)
        move = hierarchy.index("_move_pivot_to(obj, _POINT)")
        self.assertLess(parent_update, preserve_world)
        self.assertLess(preserve_world, assign_parent)
        self.assertLess(assign_parent, child_update)
        self.assertLess(child_update, move)

    def test_exact_55_name_mode_tool_contract(self):
        expected = [
            (record["name"], record["mode"], record["tool"])
            for record in self.maya["tests"]
        ]
        self.assertEqual(len(expected), 55)
        self.assertEqual(list(self.scenarios), expected)
        self.assertEqual(len({name for name, _mode, _tool in self.scenarios}), 55)

    def test_current_boundary_is_all_supported_cases_and_live_surface_is_explicitly_excluded(self):
        expected = [
            (record["name"], record["mode"], record["tool"])
            for record in self.maya["tests"]
        ]
        self.assertEqual(self.parity_count, 55)
        self.assertEqual(list(self.scenarios[: self.parity_count]), expected)
        self.assertEqual(self.unsupported, ("live_surface_snap",))
        supported = [row for row in expected if row[0] not in self.unsupported]
        self.assertEqual(len(supported), 54)

    def test_comparator_reports_status_divergence_separately_from_fidelity(self):
        comparator = _load_comparator()
        maya = {
            "schema": 7,
            "tests": [
                {"name": "case", "mode": "point", "tool": "move", "analysis": {"passed": False}}
            ],
        }
        blender = {
            "schema": 7,
            "executionFidelity": "operator_equivalent",
            "tests": [
                {"name": "case", "mode": "point", "tool": "move", "analysis": {"passed": True}}
            ],
        }
        result = comparator.compare(maya, blender)
        self.assertFalse(result["allResultsAgree"])
        self.assertFalse(result["nativeInputComparable"])
        self.assertEqual(result["divergences"], ["case"])


if __name__ == "__main__":
    unittest.main()
