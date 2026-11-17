"""Tests for deliverables, three-layer quality checks and archival gating."""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from geoops.domain import DeliverableRegistry, DomainRegistry, TaskEngine
from geoops.domain.datasets_store import DatasetRegistry
from geoops.domain.projects import ProjectRegistry
from geoops.quality.service import QualityError, QualityService
from geoops.review import ReviewEngine


class QualityDeliverableTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.mkdtemp(prefix="geoops-quality-")
        self.registry = DomainRegistry()
        self.projects = ProjectRegistry(self.registry)
        self.projects.register(
            "PRJ-QA-1", "QA-1", "质检项目", "survey", "哈尔滨", "EPSG:4547", "1985"
        )
        self.tasks = TaskEngine(self.registry)
        self.task = self.tasks.create("PRJ-QA-1", "质检任务", "change_detection", actor="test")
        self.datasets = DatasetRegistry(self.registry, self.projects)
        self.quality = QualityService(self.registry, self.datasets, report_dir=os.path.join(self.tempdir, "reports"))
        self.deliverables = DeliverableRegistry(self.registry)

        self.dataset_path = os.path.join(self.tempdir, "grid.asc")
        with open(self.dataset_path, "w", encoding="utf-8") as handle:
            handle.write("ncols 2\nnrows 1\nxllcorner 0\nyllcorner 0\ncellsize 1\n1 0\n")
        with open(self.dataset_path + ".json", "w", encoding="utf-8") as handle:
            json.dump({"crs": "EPSG:4547"}, handle)
        self.dataset = self.datasets.register(
            "PRJ-QA-1", self.dataset_path, label="一期", task_id=self.task.task_id
        )

        self.deliverable_path = os.path.join(self.tempdir, "mask.asc")
        with open(self.deliverable_path, "w", encoding="utf-8") as handle:
            handle.write("ncols 2\nnrows 1\n0 1\n")
        self.deliverable = self.deliverables.register(
            self.task.task_id, "变化掩膜", self.deliverable_path, kind="change_mask"
        )

    def test_deliverable_reads_a_real_file_and_records_hash(self) -> None:
        payload = self.deliverable.payload
        self.assertEqual(payload["size_bytes"], os.path.getsize(self.deliverable_path))
        self.assertEqual(len(payload["sha256"]), 64)

    def test_quality_without_professional_sample_is_partial(self) -> None:
        report = self.quality.evaluate("dataset", self.dataset.object_id, task_id=self.task.task_id)
        payload = report.payload
        self.assertEqual(payload["status"], "PARTIAL")
        self.assertEqual(payload["layers"]["professional"]["status"], "PARTIAL")
        self.assertEqual(payload["layers"]["file"]["status"], "PASS")

    def test_quality_with_professional_sample_records_evidence(self) -> None:
        report = self.quality.evaluate(
            "dataset",
            self.dataset.object_id,
            task_id=self.task.task_id,
            professional_sample=True,
            sample_note="抽查 2 个斑块，边界与一期影像一致",
        )
        payload = report.payload
        self.assertEqual(payload["layers"]["professional"]["status"], "PASS")
        self.assertNotEqual(payload["status"], "FAIL")

    def test_quality_detects_a_changed_deliverable_file(self) -> None:
        with open(self.deliverable_path, "a", encoding="utf-8") as handle:
            handle.write("0\n")
        report = self.quality.evaluate("deliverable", self.deliverable.object_id, task_id=self.task.task_id)
        self.assertEqual(report.payload["status"], "FAIL")
        checks = {row["name"]: row["status"] for row in report.payload["checks"]}
        self.assertEqual(checks["file.sha256"], "FAIL")

    def test_report_is_written_and_registered(self) -> None:
        report = self.quality.evaluate("dataset", self.dataset.object_id, task_id=self.task.task_id)
        path = report.payload["report_path"]
        self.assertTrue(os.path.isfile(path), path)
        with open(path, "r", encoding="utf-8") as handle:
            written = json.load(handle)
        self.assertEqual(written["report_id"], report.object_id)
        self.assertEqual(written["status"], report.payload["status"])

    def test_archive_requires_acceptance(self) -> None:
        with self.assertRaises(Exception):
            self.deliverables.archive(self.deliverable.object_id, actor="tester")
        ReviewEngine(self.registry).submit(
            self.task.task_id, self.deliverable.object_id, "reviewer", "APPROVE", "通过"
        )
        archived = self.deliverables.archive(self.deliverable.object_id, actor="tester")
        self.assertEqual(archived.status, "archived")

    def test_professional_sample_requires_a_note(self) -> None:
        with self.assertRaises(QualityError):
            self.quality.evaluate(
                "dataset", self.dataset.object_id, professional_sample=True, sample_note=""
            )


if __name__ == "__main__":
    unittest.main()
