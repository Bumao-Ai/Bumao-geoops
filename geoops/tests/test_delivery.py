"""Tests for the artifact registration node.

Standard library only: run with

    python -m unittest geoops.tests.test_delivery -v
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import unittest

from geoops.artifacts import ArtifactStore
from geoops.delivery import artifact_register_node
from geoops.domain import DomainRegistry, ObjectType
from geoops.workflow import NodeStatus, run


class ArtifactNodeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.mkdtemp(prefix="geoops-delivery-")
        self.path = os.path.join(self.tempdir, "ortho.tif")
        with open(self.path, "wb") as handle:
            handle.write(b"product bytes for the node")
        self.registry = DomainRegistry()
        self.registry.register(ObjectType.DELIVERABLE, "DLV-1", {"name": "ortho"})
        self.store = ArtifactStore(root=self.tempdir, registry=self.registry)

    def digest(self) -> str:
        with open(self.path, "rb") as handle:
            return hashlib.sha256(handle.read()).hexdigest()

    def test_node_registers_and_reports_the_hash(self) -> None:
        node = artifact_register_node("A1", "register", self.store, deliverable_id="DLV-1", task_id="TSK-1")
        outcome = run([node], {"deliverable_path": self.path}, run_id="RUN-D-1")
        self.assertEqual(outcome.status, NodeStatus.PASS)
        node_run = outcome.node_runs[0]
        self.assertIn("sha256=", node_run.detail)
        self.assertEqual(node_run.output["sha256"], self.digest())
        self.assertEqual(node_run.output["size"], os.path.getsize(self.path))

    def test_row_lands_in_the_context(self) -> None:
        node = artifact_register_node("A1", "register", self.store, deliverable_id="DLV-1", task_id="TSK-1")
        context = {"deliverable_path": self.path}
        run([node], context, run_id="RUN-D-2")
        row = context["artifacts"]["A1"]
        self.assertEqual(row["deliverable_id"], "DLV-1")
        self.assertEqual(row["task_id"], "TSK-1")
        self.assertEqual(self.store.for_deliverable("DLV-1")[0]["sha256"], self.digest())

    def test_missing_file_fails_the_node(self) -> None:
        node = artifact_register_node("A1", "register", self.store)
        context = {"deliverable_path": os.path.join(self.tempdir, "gone.tif")}
        outcome = run([node], context, run_id="RUN-D-3")
        self.assertEqual(outcome.status, NodeStatus.FAIL)
        self.assertNotIn("artifacts", context)

    def test_empty_path_fails_the_node(self) -> None:
        node = artifact_register_node("A1", "register", self.store)
        outcome = run([node], {"deliverable_path": "   "}, run_id="RUN-D-4")
        self.assertEqual(outcome.status, NodeStatus.FAIL)

    def test_unregistered_deliverable_fails_the_node(self) -> None:
        node = artifact_register_node("A1", "register", self.store, deliverable_id="DLV-404")
        outcome = run([node], {"deliverable_path": self.path}, run_id="RUN-D-5")
        self.assertEqual(outcome.status, NodeStatus.FAIL)
        self.assertIn("not registered", outcome.node_runs[0].detail)

    def test_a_later_node_is_skipped_when_registration_fails(self) -> None:
        from geoops.workflow import Node, NodeResult

        node = artifact_register_node("A1", "register", self.store)
        after = Node("A2", "publish", lambda ctx: NodeResult(NodeStatus.PASS, "published"))
        outcome = run(
            [node, after], {"deliverable_path": os.path.join(self.tempdir, "gone.tif")},
            run_id="RUN-D-6",
        )
        self.assertEqual(outcome.node_runs[0].status, NodeStatus.FAIL)
        self.assertEqual(outcome.node_runs[1].status, NodeStatus.SKIPPED)

    def test_two_runs_of_the_same_file_stay_consistent(self) -> None:
        node = artifact_register_node("A1", "register", self.store, deliverable_id="DLV-1")
        first = run([node], {"deliverable_path": self.path}, run_id="RUN-D-7")
        second = run([node], {"deliverable_path": self.path}, run_id="RUN-D-8")
        self.assertEqual(first.node_runs[0].output["artifact_id"], second.node_runs[0].output["artifact_id"])
        self.assertEqual(len(self.store), 1)


if __name__ == "__main__":
    unittest.main()
