"""Unit tests for the deliverable registry.

Standard library only: run with

    python -m unittest geoops.tests.test_artifacts -v
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest

from geoops.artifacts import ArtifactError, ArtifactStore


class ArtifactStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = tempfile.mkdtemp(prefix="geoops-artifacts-")
        self.store = ArtifactStore(root=self.root)
        self.path = os.path.join(self.root, "deliverable.tif")
        with open(self.path, "wb") as handle:
            handle.write(b"real deliverable bytes")

    def test_missing_file_is_refused(self) -> None:
        with self.assertRaises(ArtifactError):
            self.store.register(os.path.join(self.root, "nope.tif"))

    def test_directory_is_refused(self) -> None:
        with self.assertRaises(ArtifactError):
            self.store.register(self.root)

    def test_empty_path_is_refused(self) -> None:
        with self.assertRaises(ArtifactError):
            self.store.register("")

    def test_row_records_real_size_and_hash(self) -> None:
        row = self.store.register(self.path, task_id="TSK-1", kind="ortho")
        self.assertEqual(row["size"], len(b"real deliverable bytes"))
        self.assertEqual(len(row["sha256"]), 64)
        self.assertEqual(row["path"], "deliverable.tif")
        self.assertEqual(row["task_id"], "TSK-1")
        self.assertTrue(row["artifact_id"].startswith("ART-"))

    def test_same_file_twice_is_idempotent(self) -> None:
        first = self.store.register(self.path, task_id="TSK-1")
        second = self.store.register(self.path, task_id="TSK-1")
        self.assertEqual(first["artifact_id"], second["artifact_id"])
        self.assertEqual(len(self.store), 1)

    def test_same_path_with_new_content_is_refused(self) -> None:
        self.store.register(self.path)
        with open(self.path, "wb") as handle:
            handle.write(b"edited after registration")
        with self.assertRaises(ArtifactError):
            self.store.register(self.path)

    def test_verify_catches_an_edit(self) -> None:
        row = self.store.register(self.path)
        with open(self.path, "ab") as handle:
            handle.write(b"!")
        with self.assertRaises(ArtifactError):
            self.store.verify(row["artifact_id"])
        results = self.store.verify_all()
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0]["ok"])

    def test_verify_catches_a_deleted_file(self) -> None:
        row = self.store.register(self.path)
        os.remove(self.path)
        with self.assertRaises(ArtifactError):
            self.store.verify(row["artifact_id"])

    def test_index_round_trip(self) -> None:
        self.store.register(self.path, task_id="TSK-1", kind="ortho")
        index = os.path.join(self.root, "artifacts.json")
        self.store.save(index)
        loaded = ArtifactStore(index_path=index)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded.for_task("TSK-1")[0]["sha256"], self.store.all()[0]["sha256"])
        self.assertEqual(loaded.verify_all()[0]["ok"], True)

    def test_index_with_wrong_format_is_refused(self) -> None:
        index = os.path.join(self.root, "bad.json")
        with open(index, "w", encoding="utf-8") as handle:
            json.dump({"format": "something-else", "version": 1, "artifacts": []}, handle)
        with self.assertRaises(ArtifactError):
            ArtifactStore(index_path=index)


class DeliverableBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        from geoops.domain import DomainRegistry, ObjectType

        self.root = tempfile.mkdtemp(prefix="geoops-artifacts-bind-")
        self.path = os.path.join(self.root, "ortho.tif")
        with open(self.path, "wb") as handle:
            handle.write(b"bound deliverable")
        self.registry = DomainRegistry()
        self.registry.register(ObjectType.DELIVERABLE, "DLV-1", {"name": "ortho"})

    def test_binding_without_a_registry_is_refused(self) -> None:
        store = ArtifactStore(root=self.root)
        with self.assertRaises(ArtifactError):
            store.register(self.path, deliverable_id="DLV-1")

    def test_unknown_deliverable_is_refused(self) -> None:
        store = ArtifactStore(root=self.root, registry=self.registry)
        with self.assertRaises(ArtifactError):
            store.register(self.path, deliverable_id="DLV-404")

    def test_non_deliverable_object_is_refused(self) -> None:
        from geoops.domain import ObjectType

        self.registry.register(ObjectType.PROJECT, "PRJ-1", {"name": "project"})
        store = ArtifactStore(root=self.root, registry=self.registry)
        store.register(self.path, deliverable_id="DLV-1")
        other = os.path.join(self.root, "other.tif")
        with open(other, "wb") as handle:
            handle.write(b"other")
        with self.assertRaises(ArtifactError):
            store.register(other, deliverable_id="PRJ-1")

    def test_bound_row_is_queryable_by_deliverable(self) -> None:
        store = ArtifactStore(root=self.root, registry=self.registry)
        row = store.register(self.path, deliverable_id="DLV-1", kind="ortho")
        self.assertEqual(row["deliverable_id"], "DLV-1")
        self.assertEqual(len(store.for_deliverable("DLV-1")), 1)
        self.assertEqual(store.for_deliverable("DLV-404"), [])


class ReportArtifactSectionTests(unittest.TestCase):
    def test_report_carries_the_registered_file(self) -> None:
        from geoops.quality import build_report

        root = tempfile.mkdtemp(prefix="geoops-report-art-")
        path = os.path.join(root, "result.shp")
        with open(path, "wb") as handle:
            handle.write(b"shapefile placeholder")
        store = ArtifactStore(root=root)
        row = store.register(path, task_id="TSK-9", kind="vector")
        report = build_report(
            {"task_id": "TSK-9", "name": "t", "project_id": "PRJ-1", "task_type": "x", "status": "COMPLETED"},
            artifacts=store.for_task("TSK-9"),
        )
        self.assertEqual(report["artifact_files"]["status"], "RECORDED")
        self.assertEqual(report["artifact_files"]["records"][0]["sha256"], row["sha256"])

    def test_report_without_artifacts_says_not_recorded(self) -> None:
        from geoops.quality import build_report

        report = build_report(
            {"task_id": "TSK-9", "name": "t", "project_id": "PRJ-1", "task_type": "x", "status": "COMPLETED"}
        )
        self.assertEqual(report["artifact_files"]["status"], "NOT_RECORDED")
        self.assertEqual(report["artifact_files"]["count"], 0)


if __name__ == "__main__":
    unittest.main()
