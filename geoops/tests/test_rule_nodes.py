"""Unit tests for the rule check workflow node.

Standard library only: run with

    python -m unittest geoops.tests.test_rule_nodes -v
"""

from __future__ import annotations

import unittest

from geoops.survey import SurveyRuleEngine, rule_check_node
from geoops.workflow import Node, NodeResult, NodeStatus, run


def _rule(**overrides):
    base = {
        "rule_id": "R-N-001",
        "rule_name": "crs rule",
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


def _deliverable(context):
    return NodeResult(NodeStatus.PASS, "deliverable written")


class RuleNodeTests(unittest.TestCase):
    def _engine(self, *rows):
        engine = SurveyRuleEngine()
        engine.load_dicts(list(rows))
        return engine

    def test_blocking_rule_fails_node_and_stops_later_nodes(self) -> None:
        engine = self._engine(_rule())
        context = {"crs": ""}
        result = run(
            [
                rule_check_node("R1", "rule gate", engine, "land_use_classification"),
                Node("R2", "deliverable", _deliverable),
            ],
            context,
            run_id="RUN-N-001",
        )
        self.assertIs(result.status, NodeStatus.FAIL)
        self.assertEqual(result.node_runs[0].status, NodeStatus.FAIL)
        self.assertIn("R-N-001(FAIL)", result.node_runs[0].detail)
        self.assertEqual(result.node_runs[1].status, NodeStatus.SKIPPED)
        self.assertEqual(context["rule_results"]["R1"][0]["status"], "FAIL")

    def test_warning_only_rule_passes_with_warning_recorded(self) -> None:
        engine = self._engine(_rule(severity="warning"))
        context = {"crs": ""}
        result = run(
            [rule_check_node("R1", "rule gate", engine, "land_use_classification")],
            context,
            run_id="RUN-N-002",
        )
        self.assertIs(result.status, NodeStatus.PASS)
        stored = context["rule_results"]["R1"][0]
        self.assertEqual(stored["status"], "WARNING")
        self.assertIn("warning=1", result.node_runs[0].detail)

    def test_zero_rules_is_skip_not_pass(self) -> None:
        engine = self._engine(_rule())
        result = run(
            [rule_check_node("R1", "rule gate", engine, "ortho_generation")],
            {},
            run_id="RUN-N-003",
        )
        # SKIP does not abort the run, but the node record must not claim PASS.
        self.assertIs(result.node_runs[0].status, NodeStatus.SKIP)
        self.assertIn("nothing was checked", result.node_runs[0].detail)

    def test_validator_exception_makes_node_error(self) -> None:
        def boom(context):
            raise RuntimeError("tool crashed")

        engine = SurveyRuleEngine()
        engine.register("boom", boom)
        engine.load_dicts([_rule(validator="boom")])
        result = run(
            [rule_check_node("R1", "rule gate", engine, "land_use_classification")],
            {"crs": "EPSG:4490"},
            run_id="RUN-N-004",
        )
        self.assertIs(result.status, NodeStatus.ERROR)
        self.assertIn("R-N-001(ERROR)", result.node_runs[0].detail)

    def test_context_builder_selects_the_rule_context(self) -> None:
        engine = self._engine(_rule())
        seen = {}

        def builder(context):
            seen["input"] = dict(context)
            return {"crs": "EPSG:4490"}

        result = run(
            [
                rule_check_node(
                    "R1", "rule gate", engine, "land_use_classification", builder
                )
            ],
            {"crs": "", "other": "kept out"},
            run_id="RUN-N-005",
        )
        self.assertIs(result.status, NodeStatus.PASS)
        self.assertEqual(seen["input"]["crs"], "")

    def test_builder_exception_is_error_not_pass(self) -> None:
        def builder(context):
            raise ValueError("cannot build context")

        engine = self._engine(_rule())
        result = run(
            [
                rule_check_node(
                    "R1", "rule gate", engine, "land_use_classification", builder
                )
            ],
            {"crs": "EPSG:4490"},
            run_id="RUN-N-006",
        )
        self.assertIs(result.status, NodeStatus.ERROR)
        self.assertIn("ValueError", result.node_runs[0].detail)

    def test_skipped_condition_does_not_block(self) -> None:
        engine = self._engine(_rule(condition={"data_kind": "imagery"}))
        result = run(
            [rule_check_node("R1", "rule gate", engine, "land_use_classification")],
            {"crs": ""},
            run_id="RUN-N-007",
        )
        self.assertIs(result.status, NodeStatus.PASS)
        self.assertIn("skipped=1", result.node_runs[0].detail)


if __name__ == "__main__":
    unittest.main()
