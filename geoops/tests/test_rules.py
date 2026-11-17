"""Unit tests for the survey rule engine.

Standard library only: run with

    python -m unittest geoops.tests.test_rules -v
"""

from __future__ import annotations

import os
import unittest

from geoops.survey import RuleError, RuleStatus, SurveyRuleEngine

PACK = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "survey",
    "packs",
    "p01_dataset.json",
)


def _rule(**overrides):
    base = {
        "rule_id": "R-T-001",
        "rule_name": "test rule",
        "domain": "geospatial",
        "task_type": "land_use_classification",
        "description": "test only",
        "condition": {},
        "validator": "crs_present",
        "severity": "error",
        "failure_action": "block",
        "evidence_requirement": "crs",
        "version": "0.1",
        "enabled": True,
    }
    base.update(overrides)
    return base


class SurveyRuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = SurveyRuleEngine()

    def test_pack_loads_all_rules(self) -> None:
        rules = self.engine.load_pack(PACK)
        self.assertEqual(
            sorted(rule.rule_id for rule in rules),
            ["R-DS-001", "R-DS-002", "R-DS-003", "R-TASK-001"],
        )
        self.assertEqual(len(self.engine.enabled_rules("land_use_classification")), 4)

    def test_duplicate_rule_id_in_one_load_is_rejected(self) -> None:
        with self.assertRaises(RuleError):
            self.engine.load_dicts([_rule(), _rule()])
        self.assertEqual(self.engine.rules(), [])

    def test_missing_field_is_rejected(self) -> None:
        row = _rule()
        del row["evidence_requirement"]
        with self.assertRaises(RuleError):
            self.engine.load_dicts([row])

    def test_unknown_severity_is_rejected(self) -> None:
        with self.assertRaises(RuleError):
            self.engine.load_dicts([_rule(severity="fatal")])

    def test_bad_pack_does_not_load_partially(self) -> None:
        with self.assertRaises(RuleError):
            self.engine.load_dicts([_rule(rule_id="R-OK-001"), _rule(severity="fatal")])
        self.assertEqual(self.engine.rules(), [])

    def test_disabled_rule_is_not_evaluated(self) -> None:
        self.engine.load_dicts([_rule(enabled=False)])
        results = self.engine.evaluate("land_use_classification", {"crs": ""})
        self.assertEqual(results, [])

    def test_condition_not_met_is_skipped_not_pass(self) -> None:
        self.engine.load_dicts([_rule(condition={"crs": "EPSG:4490"})])
        results = self.engine.evaluate("land_use_classification", {"crs": "EPSG:4326"})
        self.assertEqual(len(results), 1)
        self.assertIs(results[0].status, RuleStatus.SKIPPED)
        self.assertIn("EPSG:4490", results[0].detail)

    def test_unknown_validator_is_error_not_pass(self) -> None:
        self.engine.load_dicts([_rule(validator="not_registered")])
        results = self.engine.evaluate("land_use_classification", {"crs": "EPSG:4490"})
        self.assertIs(results[0].status, RuleStatus.ERROR)
        self.assertIn("not registered", results[0].detail)
        self.assertEqual(self.engine.summary(results)["blocking"], 1)

    def test_validator_exception_is_error(self) -> None:
        def boom(context):
            raise RuntimeError("tool crashed")

        self.engine.register("boom", boom)
        self.engine.load_dicts([_rule(validator="boom")])
        results = self.engine.evaluate("land_use_classification", {})
        self.assertIs(results[0].status, RuleStatus.ERROR)
        self.assertIn("RuntimeError", results[0].detail)

    def test_false_result_maps_to_fail_or_warning_by_severity(self) -> None:
        self.engine.load_dicts(
            [
                _rule(rule_id="R-E-001", severity="error"),
                _rule(rule_id="R-W-001", severity="warning"),
            ]
        )
        results = self.engine.evaluate("land_use_classification", {"crs": ""})
        by_id = {result.rule_id: result for result in results}
        self.assertIs(by_id["R-E-001"].status, RuleStatus.FAIL)
        self.assertIs(by_id["R-W-001"].status, RuleStatus.WARNING)
        summary = self.engine.summary(results)
        self.assertEqual(summary["FAIL"], 1)
        self.assertEqual(summary["WARNING"], 1)
        self.assertEqual(summary["blocking"], 1)

    def test_empty_path_does_not_pass(self) -> None:
        self.engine.load_dicts([_rule(rule_id="R-P-001", validator="path_exists")])
        results = self.engine.evaluate("land_use_classification", {})
        self.assertIs(results[0].status, RuleStatus.FAIL)
        self.assertIn("no path supplied", results[0].detail)

    def test_rule_id_clash_between_loads_is_rejected(self) -> None:
        self.engine.load_dicts([_rule(rule_id="R-C-001")])
        with self.assertRaises(RuleError):
            self.engine.load_dicts([_rule(rule_id="R-C-001")])
        self.assertEqual(len(self.engine.rules()), 1)


if __name__ == "__main__":
    unittest.main()
