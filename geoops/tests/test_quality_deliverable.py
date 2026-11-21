"""Tests for deliverables, three-layer quality checks and archival gating."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest

from geoops.domain import DeliverableError, DeliverableRegistry, DomainRegistry, TaskEngine
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
            "PRJ-QA-1", self.dataset_path, label="一期", task_id=self.task.task_id, synthetic=True
        )

        self.deliverable_path = os.path.join(self.tempdir, "mask.asc")
        with open(self.deliverable_path, "w", encoding="utf-8") as handle:
            handle.write(
                "ncols 2\nnrows 1\nxllcorner 0\nyllcorner 0\ncellsize 1\nNODATA_value -9999\n1 0\n"
            )
        with open(self.deliverable_path + ".json", "w", encoding="utf-8") as handle:
            json.dump({"crs": "EPSG:4547"}, handle)
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
        self.assertTrue(payload["synthetic"])
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
        self.assertIn("basis", written)
        self.assertIn("method", written)
        self.assertEqual(written["data"]["target_id"], self.dataset.object_id)
        self.assertEqual(written["evidence"]["target_id"], self.dataset.object_id)
        self.assertEqual(written["evidence"]["target_sha256"], self.dataset.payload["sha256"])

    def test_concurrent_approvals_only_one_signs_off(self) -> None:
        engine = ReviewEngine(self.registry)
        barrier = threading.Barrier(2)
        successes = []
        failures = []

        def worker(reviewer):
            barrier.wait(timeout=5)
            try:
                successes.append(
                    engine.submit(self.task.task_id, self.deliverable.object_id, reviewer, "APPROVE")
                )
            except Exception as exc:
                failures.append("%s: %s" % (type(exc).__name__, exc))

        threads = [threading.Thread(target=worker, args=("reviewer-%d" % i,)) for i in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(failures), 1)
        self.assertIn("already finally accepted", failures[0])
        self.assertEqual(self.deliverables.get(self.deliverable.object_id).status, "accepted")

    def test_archive_requires_acceptance(self) -> None:
        with self.assertRaises(Exception):
            self.deliverables.archive(self.deliverable.object_id, actor="tester")
        ReviewEngine(self.registry).submit(
            self.task.task_id, self.deliverable.object_id, "reviewer", "APPROVE", "通过"
        )
        archived = self.deliverables.archive(self.deliverable.object_id, actor="tester")
        self.assertEqual(archived.status, "archived")

    def test_archive_refuses_a_file_changed_after_review(self) -> None:
        ReviewEngine(self.registry).submit(
            self.task.task_id, self.deliverable.object_id, "reviewer", "APPROVE", "通过"
        )
        with open(self.deliverable_path, "a", encoding="utf-8") as handle:
            handle.write("0 1\n")
        with self.assertRaises(DeliverableError) as caught:
            self.deliverables.archive(self.deliverable.object_id, actor="tester")
        self.assertIn("changed since registration", str(caught.exception))
        self.assertEqual(self.deliverables.get(self.deliverable.object_id).status, "accepted")

    def test_archive_copies_the_verified_file_and_writes_a_manifest(self) -> None:
        ReviewEngine(self.registry).submit(
            self.task.task_id, self.deliverable.object_id, "reviewer", "APPROVE", "通过"
        )
        archive_dir = os.path.join(self.tempdir, "archive")
        archived = DeliverableRegistry(self.registry, archive_dir=archive_dir).archive(
            self.deliverable.object_id, actor="tester", note="最终归档"
        )
        self.assertEqual(archived.status, "archived")
        payload = archived.payload
        self.assertTrue(os.path.isfile(payload["archive_file"]))
        self.assertTrue(os.path.isfile(payload["archive_manifest"]))
        self.assertEqual(payload["archive_sha256"], payload["sha256"])
        with open(payload["archive_manifest"], encoding="utf-8") as handle:
            manifest = json.load(handle)
        self.assertEqual(manifest["deliverable_id"], self.deliverable.object_id)
        self.assertEqual(manifest["files"][0]["sha256"], payload["sha256"])
        self.assertEqual(manifest["archived_by"], "tester")

    def test_archive_verification_detects_a_tampered_copy(self) -> None:
        ReviewEngine(self.registry).submit(
            self.task.task_id, self.deliverable.object_id, "reviewer", "APPROVE", "通过"
        )
        archive_dir = os.path.join(self.tempdir, "verify-archive")
        archived = DeliverableRegistry(self.registry, archive_dir=archive_dir).archive(
            self.deliverable.object_id, actor="tester", note="最终归档"
        )
        registry = DeliverableRegistry(self.registry, archive_dir=archive_dir)
        report = registry.verify_archive(self.deliverable.object_id)
        self.assertTrue(report["ok"])
        self.assertEqual(len(report["files"]), 1)
        with open(archived.payload["archive_file"], "ab") as handle:
            handle.write(b"\n")
        tampered = registry.verify_archive(self.deliverable.object_id)
        self.assertFalse(tampered["ok"])
        self.assertTrue(any("does not match" in problem for problem in tampered["problems"]))

    def test_archive_verification_refuses_a_symlink_outside_the_archive(self) -> None:
        ReviewEngine(self.registry).submit(
            self.task.task_id, self.deliverable.object_id, "reviewer", "APPROVE", "通过"
        )
        archive_dir = os.path.join(self.tempdir, "symlink-archive")
        archived = DeliverableRegistry(self.registry, archive_dir=archive_dir).archive(
            self.deliverable.object_id, actor="tester", note="最终归档"
        )
        target = archived.payload["archive_file"]
        outside = os.path.join(self.tempdir, "outside-copy.asc")
        with open(target, "rb") as source, open(outside, "wb") as destination:
            destination.write(source.read())
        os.remove(target)
        try:
            os.symlink(outside, target)
        except (OSError, NotImplementedError) as exc:
            self.skipTest("symlink creation is unavailable: %s" % exc)
        report = DeliverableRegistry(self.registry, archive_dir=archive_dir).verify_archive(
            self.deliverable.object_id
        )
        self.assertFalse(report["ok"])
        self.assertTrue(any("outside the archive" in problem for problem in report["problems"]))

    def test_professional_sample_requires_a_note(self) -> None:
        with self.assertRaises(QualityError):
            self.quality.evaluate(
                "dataset", self.dataset.object_id, professional_sample=True, sample_note=""
            )

    def test_accuracy_report_records_a_real_confusion_matrix(self) -> None:
        report = self.quality.evaluate(
            "deliverable",
            self.deliverable.object_id,
            task_id=self.task.task_id,
            professional_sample=True,
            sample_note="合成掩膜逐格核对",
            reference_path=self.dataset_path,
            predicted_path=self.deliverable_path,
            synthetic_reference=True,
            accuracy_thresholds={"pixel_accuracy": 1.0, "precision": 1.0},
        )
        accuracy = report.payload["accuracy"]
        self.assertTrue(accuracy["synthetic_reference"])
        self.assertEqual(accuracy["cells"]["tp"], 1)
        self.assertEqual(accuracy["cells"]["tn"], 1)
        self.assertEqual(accuracy["metrics"]["pixel_accuracy"], 1.0)
        self.assertEqual(accuracy["thresholds"]["precision"], 1.0)
        checks = {row["name"]: row["status"] for row in report.payload["checks"]}
        self.assertEqual(checks["professional.accuracy"], "PASS")
        self.assertEqual(checks["professional.accuracy_threshold"], "PASS")

    def test_accuracy_below_a_declared_threshold_fails(self) -> None:
        reference = os.path.join(self.tempdir, "ref_threshold.asc")
        predicted = os.path.join(self.tempdir, "pred_threshold.asc")
        with open(reference, "w", encoding="utf-8") as handle:
            handle.write("ncols 2\nnrows 1\nxllcorner 0\nyllcorner 0\ncellsize 1\n1 0\n")
        with open(predicted, "w", encoding="utf-8") as handle:
            handle.write("ncols 2\nnrows 1\nxllcorner 0\nyllcorner 0\ncellsize 1\n1 1\n")
        report = self.quality.evaluate(
            "deliverable",
            self.deliverable.object_id,
            task_id=self.task.task_id,
            professional_sample=True,
            sample_note="阈值失败路径",
            reference_path=reference,
            predicted_path=predicted,
            accuracy_thresholds={"pixel_accuracy": 0.9},
        )
        checks = {row["name"]: row["status"] for row in report.payload["checks"]}
        self.assertEqual(checks["professional.accuracy_threshold"], "FAIL")
        self.assertEqual(report.payload["status"], "FAIL")

    def test_an_invalid_accuracy_threshold_is_refused(self) -> None:
        with self.assertRaises(QualityError):
            self.quality.evaluate(
                "deliverable",
                self.deliverable.object_id,
                reference_path=self.dataset_path,
                accuracy_thresholds={"pixel_accuracy": 1.5},
            )
        with self.assertRaises(QualityError):
            self.quality.evaluate(
                "deliverable",
                self.deliverable.object_id,
                accuracy_thresholds={"pixel_accuracy": 0.9},
            )

    def test_synthetic_deliverable_cannot_be_finally_approved(self) -> None:
        path = os.path.join(self.tempdir, "synthetic.asc")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("ncols 2\nnrows 1\n0 1\n")
        synthetic = self.deliverables.register(
            self.task.task_id, "合成掩膜", path, kind="change_mask", synthetic=True
        )
        with self.assertRaises(Exception):
            ReviewEngine(self.registry).submit(
                self.task.task_id, synthetic.object_id, "reviewer", "APPROVE", "通过"
            )

    def test_approving_review_requires_a_pass_quality_report(self) -> None:
        report = self.quality.evaluate(
            "deliverable",
            self.deliverable.object_id,
            task_id=self.task.task_id,
            professional_sample=True,
            sample_note="抽查",
        )
        self.assertNotEqual(report.payload["status"], "PASS")
        with self.assertRaises(Exception):
            ReviewEngine(self.registry).submit(
                self.task.task_id,
                self.deliverable.object_id,
                "reviewer",
                "APPROVE",
                "通过",
                quality_report_id=report.object_id,
            )


if __name__ == "__main__":
    unittest.main()
