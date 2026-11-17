"""Tests for the product rule pack (ortho and change detection).

Standard library only: run with

    python -m unittest geoops.tests.test_rule_packs -v
"""

from __future__ import annotations

import os
import tempfile
import unittest

from geoops.survey import SurveyRuleEngine
from geoops.survey.rules import RuleError, RuleStatus

PACKS = os.path.join(os.path.dirname(os.path.dirname(__file__)), "survey", "packs")


def pack(name: str) -> str:
    return os.path.join(PACKS, name)


class ProductPackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.mkdtemp(prefix="geoops-rulepacks-")
        self.baseline = os.path.join(self.tempdir, "baseline.tif")
        self.comparison = os.path.join(self.tempdir, "comparison.tif")
        self.product = os.path.join(self.tempdir, "ortho.tif")
        for path in (self.baseline, self.comparison, self.product):
            with open(path, "wb") as handle:
                handle.write(b"bytes")
        self.engine = SurveyRuleEngine()
        self.engine.load_pack(pack("p02_products.json"))

    def statuses(self, task_type, context):
        results = self.engine.evaluate(task_type, context)
        return {row.rule_id: row.status for row in results}

    def ortho_context(self, **overrides):
        context = {
            "crs": "EPSG:4547",
            "gsd_m": 0.2,
            "nodata": 0,
            "deliverable_path": self.product,
        }
        context.update(overrides)
        return context

    def test_pack_loads_seven_rules(self) -> None:
        self.assertEqual(len(self.engine.rules()), 7)

    def test_task_type_filter_excludes_the_other_type(self) -> None:
        ortho = self.engine.enabled_rules("ortho_generation")
        change = self.engine.enabled_rules("change_detection")
        self.assertEqual(len(ortho), 4)
        self.assertEqual(len(change), 3)
        self.assertTrue(all(rule.task_type == "ortho_generation" for rule in ortho))

    def test_ortho_context_passes(self) -> None:
        statuses = self.statuses("ortho_generation", self.ortho_context())
        self.assertEqual(statuses["R-OR-001"], RuleStatus.PASS)
        self.assertEqual(statuses["R-OR-002"], RuleStatus.PASS)
        self.assertEqual(statuses["R-OR-003"], RuleStatus.PASS)
        self.assertEqual(statuses["R-OR-004"], RuleStatus.PASS)

    def test_geographic_crs_fails_ortho(self) -> None:
        statuses = self.statuses("ortho_generation", self.ortho_context(crs="EPSG:4490"))
        self.assertEqual(statuses["R-OR-001"], RuleStatus.FAIL)

    def test_crs_that_is_not_epsg_fails(self) -> None:
        statuses = self.statuses("ortho_generation", self.ortho_context(crs="WGS84"))
        self.assertEqual(statuses["R-OR-001"], RuleStatus.FAIL)

    def test_missing_or_bad_gsd_fails(self) -> None:
        statuses = self.statuses("ortho_generation", self.ortho_context(gsd_m=None))
        self.assertEqual(statuses["R-OR-002"], RuleStatus.FAIL)
        statuses = self.statuses("ortho_generation", self.ortho_context(gsd_m="coarse"))
        self.assertEqual(statuses["R-OR-002"], RuleStatus.FAIL)
        statuses = self.statuses("ortho_generation", self.ortho_context(gsd_m=-1))
        self.assertEqual(statuses["R-OR-002"], RuleStatus.FAIL)

    def test_missing_nodata_warns_but_does_not_block(self) -> None:
        context = self.ortho_context()
        del context["nodata"]
        results = self.engine.evaluate("ortho_generation", context)
        statuses = {row.rule_id: row.status for row in results}
        self.assertEqual(statuses["R-OR-003"], RuleStatus.WARNING)
        summary = self.engine.summary(results)
        self.assertEqual(summary["blocking"], 0)

    def test_missing_product_file_fails(self) -> None:
        statuses = self.statuses(
            "ortho_generation", self.ortho_context(deliverable_path=os.path.join(self.tempdir, "gone.tif"))
        )
        self.assertEqual(statuses["R-OR-004"], RuleStatus.FAIL)

    def test_change_detection_passes_and_fails_on_crs(self) -> None:
        context = {
            "baseline_path": self.baseline,
            "comparison_path": self.comparison,
            "crs_baseline": "EPSG:4547",
            "crs_comparison": "EPSG:4547",
            "min_area_m2": 5,
        }
        statuses = self.statuses("change_detection", context)
        self.assertEqual(statuses["R-CD-001"], RuleStatus.PASS)
        self.assertEqual(statuses["R-CD-002"], RuleStatus.PASS)
        self.assertEqual(statuses["R-CD-003"], RuleStatus.PASS)

        mismatched = dict(context, crs_comparison="EPSG:4548")
        statuses = self.statuses("change_detection", mismatched)
        self.assertEqual(statuses["R-CD-002"], RuleStatus.FAIL)

    def test_same_file_for_both_inputs_fails(self) -> None:
        context = {
            "baseline_path": self.baseline,
            "comparison_path": self.baseline,
            "crs_baseline": "EPSG:4547",
            "crs_comparison": "EPSG:4547",
        }
        statuses = self.statuses("change_detection", context)
        self.assertEqual(statuses["R-CD-001"], RuleStatus.FAIL)

    def test_duplicate_rule_id_across_packs_is_refused(self) -> None:
        engine = SurveyRuleEngine()
        engine.load_pack(pack("p01_dataset.json"))
        rows = [rule.to_dict() for rule in engine.rules()]
        with self.assertRaises(RuleError):
            engine.load_dicts(rows[:1])


class UnknownTaskTypeTests(unittest.TestCase):
    def test_a_type_without_rules_returns_nothing(self) -> None:
        engine = SurveyRuleEngine()
        engine.load_pack(pack("p02_products.json"))
        self.assertEqual(engine.evaluate("map_compilation", {}), [])


if __name__ == "__main__":
    unittest.main()
