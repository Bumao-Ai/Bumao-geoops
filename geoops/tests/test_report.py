"""Unit tests for the execution report.

Standard library only: run with

    python -m unittest geoops.tests.test_report -v
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from geoops.domain import DomainRegistry, TaskEngine, TaskStatus
from geoops.quality import (
    ReportError,
    build_report,
    check_dataset,
    render_markdown,
    write_report,
)
from geoops.workflow import Node, NodeResult, NodeStatus, run


def _task(registry):
    registry.register("Project", "PRJ-R-001", {"name": "report test project"})
    tasks = TaskEngine(registry)
    task = tasks.create("PRJ-R-001", "report test task")
    tasks.transition(task.task_id, TaskStatus.READY, reason="preconditions listed")
    tasks.transition(task.task_id, TaskStatus.RUNNING, reason="started")
    tasks.transition(task.task_id, TaskStatus.COMPLETED, reason="archived")
    return task


class ReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.mkdtemp(prefix="geoops-report-test-")
        self.registry = DomainRegistry()
        self.task = _task(self.registry)
        self.run = run(
            [Node("N1", "step", lambda ctx: NodeResult(NodeStatus.PASS, "done"))],
            run_id="RUN-R-001",
        )

    def test_report_requires_a_task(self) -> None:
        with self.assertRaises(ReportError):
            build_report(None, [self.run])

    def test_report_requires_a_task_id(self) -> None:
        with self.assertRaises(ReportError):
            build_report({"name": "no id"})

    def test_report_copies_records_and_counts_rules(self) -> None:
        report = build_report(
            self.task,
            [self.run],
            {"R1": [
                {"rule_id": "R-DS-001", "status": "PASS", "detail": "crs ok"},
                {"rule_id": "R-DS-003", "status": "WARNING", "detail": "no sidecar"},
            ]},
            check_dataset(os.path.join(os.path.dirname(__file__), "..", "..", "README.md"), {}),
            {"object_id": "DLV-R-001", "status": "registered"},
        )
        self.assertEqual(report["format"], "geoops-report")
        self.assertEqual(report["task"]["task_id"], self.task.task_id)
        self.assertEqual(report["workflow_runs"][0]["run_id"], "RUN-R-001")
        self.assertEqual(report["rules"]["counts"], {"PASS": 1, "WARNING": 1})
        self.assertEqual(report["quality"]["report"]["status"], "FAIL")
        self.assertEqual(report["deliverable"]["status"], "RECORDED")

    def test_missing_sections_are_marked_not_recorded(self) -> None:
        report = build_report(self.task, [self.run], {}, None, None, None)
        self.assertEqual(report["quality"]["status"], "NOT_RECORDED")
        self.assertEqual(report["deliverable"]["status"], "NOT_RECORDED")
        self.assertEqual(report["review"]["status"], "NOT_RECORDED")
        self.assertEqual(report["rules"]["status"], "NOT_RECORDED")

    def test_markdown_render_names_the_task_and_the_gaps(self) -> None:
        report = build_report(self.task, [self.run], {}, check_dataset(None, {}))
        markdown = render_markdown(report)
        self.assertIn(self.task.task_id, markdown)
        self.assertIn("COMPLETED", markdown)
        self.assertIn("NOT_RECORDED", markdown)
        self.assertIn("RUN-R-001", markdown)

    def test_write_json_is_atomic_and_parses_back(self) -> None:
        report = build_report(self.task, [self.run], {}, check_dataset(None, {}))
        path = write_report(report, os.path.join(self.tempdir, "report.json"))
        self.assertTrue(os.path.exists(path))
        self.assertFalse(os.path.exists(path + ".tmp"))
        with open(path, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), report)

    def test_write_markdown_and_reject_unknown_format(self) -> None:
        report = build_report(self.task, [self.run], {}, check_dataset(None, {}))
        md_path = write_report(report, os.path.join(self.tempdir, "report.md"), fmt="md")
        with open(md_path, encoding="utf-8") as handle:
            self.assertIn(self.task.task_id, handle.read())
        with self.assertRaises(ReportError):
            write_report(report, os.path.join(self.tempdir, "x.pdf"), fmt="pdf")
        with self.assertRaises(ReportError):
            write_report({"format": "something-else"}, os.path.join(self.tempdir, "x.json"))


if __name__ == "__main__":
    unittest.main()
