"""Concurrency and version-upgrade tests for the snapshot and file stores.

These were written before the fixes they check: a fixed temp filename and no
lock were both present when the suite was written.

Standard library only: run with

    python -m unittest geoops.tests.test_concurrency -v
"""

from __future__ import annotations

import glob
import json
import os
import tempfile
import threading
import unittest

from geoops.api import AuditLog
from geoops.artifacts import ArtifactStore
from geoops.domain import DomainRegistry, ObjectType, TaskEngine
from geoops.store import StoreError, SnapshotStore


def build_state(count: int = 120):
    registry = DomainRegistry()
    for index in range(count):
        registry.register(ObjectType.PROJECT, "PRJ-C-%03d" % index, {"name": "p%d" % index})
    tasks = TaskEngine(registry)
    return registry, tasks


class RegistryConcurrencyTests(unittest.TestCase):
    def test_parallel_duplicate_id_only_one_registration_wins(self) -> None:
        registry = DomainRegistry()
        barrier = threading.Barrier(2)
        successes = []
        failures = []

        def worker():
            barrier.wait(timeout=5)
            try:
                successes.append(
                    registry.register(ObjectType.PROJECT, "PRJ-RACE", {"name": "race"})
                )
            except Exception as exc:
                failures.append("%s: %s" % (type(exc).__name__, exc))

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(failures), 1)
        self.assertIn("duplicate object_id", failures[0])


class SnapshotConcurrencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.mkdtemp(prefix="geoops-concurrency-")
        self.path = os.path.join(self.tempdir, "state.json")
        self.registry, self.tasks = build_state()
        self.store = SnapshotStore(self.path)

    def test_concurrent_saves_all_succeed_and_leave_one_valid_snapshot(self) -> None:
        errors = []
        barrier = threading.Barrier(8)

        def worker():
            try:
                barrier.wait(timeout=5)
                self.store.save(self.registry, self.tasks)
            except Exception as exc:  # recorded, then asserted below
                errors.append("%s: %s" % (type(exc).__name__, exc))

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        data = self.store.load()
        self.assertEqual(len(data["objects"]), 120)
        self.assertEqual(len(data["tasks"]), 0)

    def test_a_reader_never_sees_a_partial_file(self) -> None:
        self.store.save(self.registry, self.tasks)
        failures = []
        loads = []
        stop = threading.Event()

        def writer():
            while not stop.is_set():
                try:
                    self.store.save(self.registry, self.tasks)
                except Exception as exc:  # a writer failure must fail the test
                    failures.append("writer: %s: %s" % (type(exc).__name__, exc))
                    stop.set()

        def reader():
            while not stop.is_set():
                try:
                    data = self.store.load()
                    loads.append(len(data["objects"]))
                except Exception as exc:  # any reader error fails the test too
                    failures.append("reader: %s: %s" % (type(exc).__name__, exc))

        write_thread = threading.Thread(target=writer)
        read_threads = [threading.Thread(target=reader) for _ in range(3)]
        write_thread.start()
        for thread in read_threads:
            thread.start()
        threading.Event().wait(1.0)
        stop.set()
        write_thread.join()
        for thread in read_threads:
            thread.join()
        self.assertEqual(failures, [])
        self.assertTrue(loads)
        self.assertTrue(all(count == 120 for count in loads))

    def test_no_temp_files_are_left_behind(self) -> None:
        self.store.save(self.registry, self.tasks)
        self.assertEqual(glob.glob(os.path.join(self.tempdir, "*.tmp")), [])

    def _write_version(self, version):
        payload = {
            "format": "geoops-snapshot",
            "version": version,
            "saved_at": "2026-11-16T00:00:00Z",
            "objects": [],
            "tasks": [],
        }
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)

    def test_older_snapshot_version_is_refused_with_a_migration_reason(self) -> None:
        self._write_version(0)
        with self.assertRaises(StoreError) as caught:
            self.store.load()
        self.assertIn("older", str(caught.exception))

    def test_newer_snapshot_version_is_refused(self) -> None:
        self._write_version(2)
        with self.assertRaises(StoreError) as caught:
            self.store.load()
        self.assertIn("newer", str(caught.exception))


class ArtifactConcurrencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.mkdtemp(prefix="geoops-artifacts-concurrency-")
        self.store = ArtifactStore(root=self.tempdir)
        self.files = []
        for index in range(6):
            path = os.path.join(self.tempdir, "file-%d.tif" % index)
            with open(path, "wb") as handle:
                handle.write(b"content %d" % index)
            self.files.append(path)

    def test_parallel_registration_of_distinct_files_keeps_them_all(self) -> None:
        errors = []
        barrier = threading.Barrier(len(self.files))

        def worker(path):
            try:
                barrier.wait(timeout=5)
                self.store.register(path, kind="ortho")
            except Exception as exc:
                errors.append("%s: %s" % (type(exc).__name__, exc))

        threads = [threading.Thread(target=worker, args=(path,)) for path in self.files]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(self.store), 6)

    def test_parallel_registration_of_one_file_keeps_one_row(self) -> None:
        errors = []
        barrier = threading.Barrier(8)

        def worker():
            try:
                barrier.wait(timeout=5)
                self.store.register(self.files[0], kind="ortho")
            except Exception as exc:
                errors.append("%s: %s" % (type(exc).__name__, exc))

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(self.store), 1)


class AuditConcurrencyTests(unittest.TestCase):
    def test_parallel_appends_are_not_lost(self) -> None:
        tempdir = tempfile.mkdtemp(prefix="geoops-audit-concurrency-")
        path = os.path.join(tempdir, "audit.jsonl")
        log = AuditLog(limit=1000, path=path)
        per_thread = 25
        starts = [threading.Barrier(4)]

        def worker(index):
            starts[0].wait(timeout=5)
            for row in range(per_thread):
                log.record("GET", "/api/v1/health", "tok-%d" % index, "allow", "row %d" % row, 200)

        threads = [threading.Thread(target=worker, args=(index,)) for index in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        reloaded = AuditLog(limit=1000, path=path)
        self.assertEqual(len(reloaded.rows()), 4 * per_thread)
        self.assertTrue(all(row["method"] == "GET" for row in reloaded.rows()))


if __name__ == "__main__":
    unittest.main()
