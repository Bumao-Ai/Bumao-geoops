"""Unit tests for the JSON snapshot store.

Standard library only: run with

    python -m unittest geoops.tests.test_store -v
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from geoops.domain import DomainRegistry, ObjectType, TaskEngine, TaskStatus
from geoops.store import FORMAT, SnapshotStore, StoreError


class SnapshotStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.mkdtemp(prefix="geoops-store-test-")
        self.path = os.path.join(self.tempdir, "state.json")
        self.store = SnapshotStore(self.path)

    def _state(self):
        registry = DomainRegistry()
        registry.register(ObjectType.PROJECT, "PRJ-S-001", {"name": "store test project"})
        tasks = TaskEngine(registry)
        task = tasks.create("PRJ-S-001", "store test task")
        tasks.transition(task.task_id, TaskStatus.READY, reason="preconditions listed")
        tasks.transition(task.task_id, TaskStatus.RUNNING, reason="started")
        tasks.transition(task.task_id, TaskStatus.COMPLETED, reason="archived")
        return registry, tasks, task

    def test_roundtrip_keeps_objects_tasks_and_versions(self) -> None:
        registry, tasks, task = self._state()
        self.store.save(registry, tasks)

        restored_registry = DomainRegistry()
        restored_tasks = TaskEngine(restored_registry)
        summary = self.store.restore(restored_registry, restored_tasks)

        self.assertEqual(summary, {"objects": 2, "tasks": 1})
        self.assertEqual(len(restored_registry), 2)
        restored_task = restored_tasks.get(task.task_id)
        self.assertIsNotNone(restored_task)
        self.assertIs(restored_task.status, TaskStatus.COMPLETED)
        self.assertEqual(restored_task.version, task.version)
        self.assertEqual(restored_tasks.transition_count(task.task_id), 3)
        mirror = restored_registry.get(task.task_id)
        self.assertEqual(mirror.version, task.version)
        self.assertEqual(mirror.status, "COMPLETED")

    def test_save_is_atomic_and_leaves_no_temp_file(self) -> None:
        registry, tasks, _ = self._state()
        self.store.save(registry, tasks)
        self.assertTrue(os.path.exists(self.path))
        self.assertFalse(os.path.exists(self.path + ".tmp"))

    def test_missing_file_is_an_error(self) -> None:
        with self.assertRaises(StoreError):
            self.store.load()

    def test_corrupt_json_is_an_error(self) -> None:
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("{ this is not json")
        with self.assertRaises(StoreError):
            self.store.load()

    def test_wrong_format_is_an_error(self) -> None:
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump({"format": "something-else", "version": 1, "objects": []}, handle)
        with self.assertRaises(StoreError):
            self.store.load()

    def test_duplicate_ids_abort_before_the_live_state_is_touched(self) -> None:
        row = {
            "object_id": "PRJ-DUP-001",
            "object_type": "Project",
            "version": 1,
            "status": "registered",
            "created_at": "2026-11-16T00:00:00Z",
            "payload": {"name": "dup"},
        }
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "format": FORMAT,
                    "version": 1,
                    "saved_at": "2026-11-16T00:00:00Z",
                    "objects": [row, dict(row)],
                    "tasks": [],
                },
                handle,
            )
        registry = DomainRegistry()
        with self.assertRaises(StoreError):
            self.store.restore(registry)
        self.assertEqual(len(registry), 0)

    def test_clash_with_live_objects_is_refused(self) -> None:
        registry, tasks, _ = self._state()
        self.store.save(registry, tasks)
        live = DomainRegistry()
        live.register(ObjectType.PROJECT, "PRJ-S-001", {"name": "already here"})
        with self.assertRaises(StoreError):
            self.store.restore(live)
        self.assertEqual(len(live), 1)

    def test_bad_task_status_aborts_the_whole_restore(self) -> None:
        registry, tasks, task = self._state()
        payload = self.store.save(registry, tasks)
        payload["tasks"][0]["status"] = "ARCHIVED"
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        fresh = DomainRegistry()
        with self.assertRaises(StoreError):
            self.store.restore(fresh, TaskEngine(fresh))
        self.assertEqual(len(fresh), 0)


if __name__ == "__main__":
    unittest.main()
