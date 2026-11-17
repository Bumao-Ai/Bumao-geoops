"""Tests for the run journal."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest

from geoops.workflow import (
    JournalError,
    Node,
    NodeResult,
    NodeStatus,
    RunJournal,
    WorkflowEngine,
)


def _pass_node(node_id="N1", name="first"):
    return Node(node_id, name, lambda ctx: NodeResult(NodeStatus.PASS, "ok"))


def _make_run(run_id="RUN-1", nodes=None):
    return WorkflowEngine().start(nodes or [_pass_node()], run_id=run_id)


def _failed_run(run_id="RUN-2"):
    nodes = [
        _pass_node("N1", "first"),
        Node("N2", "second", lambda ctx: NodeResult(NodeStatus.FAIL, "boom")),
        _pass_node("N3", "never"),
    ]
    return WorkflowEngine().start(nodes, run_id=run_id)


class JournalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.mkdtemp(prefix="geoops-journal-")
        self.path = os.path.join(self.tempdir, "runs.jsonl")

    def journal(self):
        return RunJournal(self.path)

    # ----------------------------------------------------------- recording
    def test_recording_keeps_run_and_node_facts(self) -> None:
        journal = RunJournal()
        row = journal.record(_make_run(), task_id="TSK-1", project_id="PRJ-1", actor="test")
        self.assertEqual(row["run_id"], "RUN-1")
        self.assertEqual(row["status"], "PASS")
        self.assertEqual(row["task_id"], "TSK-1")
        self.assertEqual(row["project_id"], "PRJ-1")
        self.assertEqual(row["actor"], "test")
        self.assertEqual(len(row["node_runs"]), 1)
        self.assertEqual(row["node_runs"][0]["status"], "PASS")
        self.assertEqual(len(journal), 1)

    def test_a_duplicate_run_id_is_refused(self) -> None:
        journal = self.journal()
        journal.record(_make_run("RUN-1"))
        with self.assertRaises(JournalError):
            journal.record(_make_run("RUN-1"))
        self.assertEqual(len(journal), 1)
        stored = journal.rows()
        self.assertEqual(stored[0]["run_id"], "RUN-1")

    def test_failed_run_keeps_failed_and_skipped_nodes(self) -> None:
        journal = RunJournal()
        row = journal.record(_failed_run())
        statuses = [node["status"] for node in row["node_runs"]]
        self.assertEqual(statuses[0], "PASS")
        self.assertEqual(statuses[1], "FAIL")
        self.assertEqual(row["status"], "FAIL")
        self.assertGreaterEqual(row["skipped"], 1)

    def test_resumed_from_is_recorded(self) -> None:
        journal = RunJournal()
        failed = _failed_run("RUN-2")
        same_shape = [
            _pass_node("N1", "first"),
            _pass_node("N2", "second"),
            _pass_node("N3", "never"),
        ]
        resumed = WorkflowEngine().resume(failed, same_shape, run_id="RUN-3")
        journal.record(failed)
        row = journal.record(resumed)
        self.assertEqual(row["resumed_from"], "RUN-2")
        self.assertEqual(row["status"], "PASS")

    def test_by_status_counts_each_verdict(self) -> None:
        journal = RunJournal()
        journal.record(_make_run("RUN-A"))
        journal.record(_failed_run("RUN-B"))
        self.assertEqual(journal.by_status(), {"PASS": 1, "FAIL": 1})

    # ---------------------------------------------------------- persistence
    def test_rows_survive_a_reload(self) -> None:
        journal = self.journal()
        journal.record(_make_run("RUN-1"), task_id="TSK-1")
        again = self.journal()
        self.assertEqual(len(again), 1)
        self.assertEqual(again.rows()[0]["run_id"], "RUN-1")
        self.assertEqual(again.rows()[0]["task_id"], "TSK-1")

    def test_a_corrupt_line_refuses_the_whole_file(self) -> None:
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write('{"run_id": "RUN-1", "status": "PASS", "node_runs": []}\n')
            handle.write("{not json\n")
        with self.assertRaises(JournalError):
            RunJournal(self.path)

    def test_a_repeated_run_id_in_the_file_is_refused(self) -> None:
        line = json.dumps({"run_id": "RUN-1", "status": "PASS", "node_runs": []})
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write(line + "\n" + line + "\n")
        with self.assertRaises(JournalError):
            RunJournal(self.path)

    def test_a_missing_directory_is_refused_before_writing(self) -> None:
        missing = os.path.join(self.tempdir, "nope", "runs.jsonl")
        journal = RunJournal()
        journal._path = missing
        with self.assertRaises(JournalError):
            journal.record(_make_run("RUN-1"))
        self.assertEqual(len(journal), 0)

    def test_limit_returns_the_newest_rows(self) -> None:
        journal = self.journal()
        for index in range(5):
            journal.record(_make_run("RUN-%d" % index))
        self.assertEqual(len(journal.rows(limit=2)), 2)
        self.assertEqual(journal.rows(limit=2)[-1]["run_id"], "RUN-4")

    # ---------------------------------------------------------- concurrency
    def test_concurrent_records_are_all_written_once(self) -> None:
        journal = self.journal()
        errors = []

        def worker(index: int) -> None:
            try:
                journal.record(_make_run("RUN-T%d" % index))
            except Exception as exc:  # noqa: BLE001 - the test needs every failure
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(index,)) for index in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        rows = self.journal().rows()
        self.assertEqual(len(rows), 8)
        self.assertEqual(len({row["run_id"] for row in rows}), 8)


if __name__ == "__main__":
    unittest.main()
