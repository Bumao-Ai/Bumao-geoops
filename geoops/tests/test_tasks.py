"""Unit tests for the survey task engine.

Standard library only: run with

    python -m unittest geoops.tests.test_tasks -v
"""

from __future__ import annotations

import threading
import unittest

from geoops.domain import DomainRegistry, ObjectType, TaskEngine, TaskError, TaskStatus


class TaskEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = DomainRegistry()
        self.project = self.registry.register(
            ObjectType.PROJECT, "PRJ-TEST-001", {"name": "task engine test project"}
        )
        self.engine = TaskEngine(self.registry)

    def _create(self):
        return self.engine.create(self.project.object_id, "test task", actor="unittest")

    def test_create_rejects_unknown_project(self) -> None:
        with self.assertRaises(TaskError):
            self.engine.create("PRJ-NOT-FOUND", "test task")

    def test_create_rejects_non_project_object(self) -> None:
        tool = self.registry.register(ObjectType.TOOL, "TOOL-TEST-001", {"name": "gdal"})
        with self.assertRaises(TaskError):
            self.engine.create(tool.object_id, "test task")

    def test_create_rejects_empty_name(self) -> None:
        with self.assertRaises(TaskError):
            self.engine.create(self.project.object_id, "   ")

    def test_create_registers_draft_and_mirrors(self) -> None:
        task = self._create()
        self.assertIs(task.status, TaskStatus.DRAFT)
        mirror = self.registry.get(task.task_id)
        self.assertIsNotNone(mirror)
        self.assertEqual(mirror.object_type, ObjectType.SURVEY_TASK)
        self.assertEqual(mirror.status, TaskStatus.DRAFT.value)
        self.assertEqual(self.engine.transition_count(task.task_id), 0)

    def test_legal_path_records_every_edge(self) -> None:
        task = self._create()
        for target, reason in (
            (TaskStatus.READY, "preconditions listed"),
            (TaskStatus.RUNNING, "started"),
            (TaskStatus.PAUSED, "paused"),
            (TaskStatus.RUNNING, "resumed"),
            (TaskStatus.COMPLETED, "archive confirmed"),
        ):
            self.engine.transition(task.task_id, target, reason=reason, actor="unittest")
        final = self.engine.get(task.task_id)
        self.assertIs(final.status, TaskStatus.COMPLETED)
        self.assertEqual(self.engine.transition_count(task.task_id), 5)
        self.assertEqual(final.version, 6)
        self.assertEqual(self.registry.get(task.task_id).version, 6)

    def test_illegal_edges_are_rejected(self) -> None:
        task = self._create()
        for target in (TaskStatus.RUNNING, TaskStatus.PAUSED, TaskStatus.COMPLETED):
            with self.assertRaises(TaskError):
                self.engine.transition(task.task_id, target, reason="skip")
            self.assertIs(self.engine.get(task.task_id).status, TaskStatus.DRAFT)

    def test_reason_required_to_close_a_task(self) -> None:
        task = self._create()
        self.engine.transition(task.task_id, TaskStatus.READY, reason="preconditions listed")
        with self.assertRaises(TaskError):
            self.engine.transition(task.task_id, TaskStatus.CANCELLED, reason="  ")

    def test_failed_task_can_retry_then_complete(self) -> None:
        task = self._create()
        self.engine.transition(task.task_id, TaskStatus.READY, reason="preconditions listed")
        self.engine.transition(task.task_id, TaskStatus.RUNNING, reason="started")
        self.engine.transition(task.task_id, TaskStatus.FAILED, reason="node N2 failed")
        self.engine.transition(task.task_id, TaskStatus.RUNNING, reason="retry from N2")
        self.engine.transition(task.task_id, TaskStatus.COMPLETED, reason="archive confirmed")
        self.assertIs(self.engine.get(task.task_id).status, TaskStatus.COMPLETED)

    def test_identical_transition_is_rejected(self) -> None:
        task = self._create()
        with self.assertRaises(TaskError):
            self.engine.transition(task.task_id, TaskStatus.DRAFT)

    def test_run_attaches_once_and_only_while_running(self) -> None:
        task = self._create()
        with self.assertRaises(TaskError):
            self.engine.attach_run(task.task_id, "RUN-TEST-001")
        self.engine.transition(task.task_id, TaskStatus.READY, reason="preconditions listed")
        self.engine.transition(task.task_id, TaskStatus.RUNNING, reason="started")
        self.engine.attach_run(task.task_id, "RUN-TEST-001")
        with self.assertRaises(TaskError):
            self.engine.attach_run(task.task_id, "RUN-TEST-001")
        with self.assertRaises(TaskError):
            self.engine.attach_run(task.task_id, "")
        self.assertEqual(self.engine.get(task.task_id).workflow_run_ids, ["RUN-TEST-001"])

    def test_concurrent_transitions_apply_only_one_edge(self) -> None:
        task = self._create()
        self.engine.transition(task.task_id, TaskStatus.READY, reason="preconditions listed")
        barrier = threading.Barrier(2)
        successes = []
        failures = []

        def worker():
            barrier.wait(timeout=5)
            try:
                successes.append(
                    self.engine.transition(task.task_id, TaskStatus.RUNNING, reason="started")
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
        self.assertIn("already RUNNING", failures[0])
        self.assertEqual(self.engine.transition_count(task.task_id), 2)

    def test_unknown_task_and_unknown_status(self) -> None:
        with self.assertRaises(TaskError):
            self.engine.transition("TSK-NOT-FOUND", TaskStatus.READY, reason="unknown")
        task = self._create()
        with self.assertRaises(TaskError):
            self.engine.transition(task.task_id, "ARCHIVED", reason="unknown status")

    def test_snapshot_reports_allowed_targets(self) -> None:
        task = self._create()
        self.assertEqual(self.engine.allowed_targets(task.task_id), ["CANCELLED", "READY"])
        snapshot = self.engine.snapshot(task.task_id)
        self.assertEqual(snapshot["status"], "DRAFT")
        self.assertEqual(snapshot["history"][0]["event"], "created")


if __name__ == "__main__":
    unittest.main()
