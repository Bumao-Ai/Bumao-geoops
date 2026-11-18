"""Tests for declared preconditions, outputs aliases and success conditions."""

from __future__ import annotations

import unittest

from geoops.workflow.executor import Node, NodeResult, NodeStatus, run


def _pass(output=None):
    return lambda context: NodeResult(NodeStatus.PASS, "", output)


class ExecutorPolicyTests(unittest.TestCase):
    def test_outputs_mapping_feeds_a_downstream_node(self) -> None:
        context = {}
        nodes = [
            Node("first", "first", _pass({"count": 7}), outputs={"seven": "count"}),
            Node(
                "second",
                "second",
                lambda ctx: NodeResult(NodeStatus.PASS, "", {"doubled": ctx["seven"] * 2}),
            ),
        ]
        result = run(nodes, context)
        self.assertEqual(result.status, NodeStatus.PASS)
        self.assertEqual(context["node_outputs"]["first"]["count"], 7)
        self.assertEqual(context["seven"], 7)
        self.assertEqual(context["node_outputs"]["second"]["doubled"], 14)

    def test_missing_precondition_stops_the_node(self) -> None:
        node = Node("guard", "guard", _pass({"ok": True}), preconditions=["dataset_id"])
        result = run([node], {})
        self.assertEqual(result.status, NodeStatus.FAIL)
        self.assertIn("precondition not met", result.node_runs[0].detail)
        self.assertEqual(result.node_runs[0].attempts, 1)

    def test_precondition_can_read_an_upstream_node_output(self) -> None:
        nodes = [
            Node("prepare", "prepare", _pass({"ready": True})),
            Node(
                "use",
                "use",
                _pass({"used": True}),
                preconditions=["node_outputs.prepare.ready"],
            ),
        ]
        result = run(nodes, {})
        self.assertEqual(result.status, NodeStatus.PASS)

    def test_numeric_success_condition_can_fail(self) -> None:
        node = Node(
            "measure",
            "measure",
            _pass({"changed_cells": 1}),
            success_condition="changed_cells >= 2",
        )
        result = run([node], {})
        self.assertEqual(result.status, NodeStatus.FAIL)
        self.assertIn("success condition failed", result.node_runs[0].detail)

    def test_numeric_success_condition_can_pass(self) -> None:
        node = Node(
            "measure",
            "measure",
            _pass({"changed_cells": 3}),
            success_condition="changed_cells >= 2",
        )
        result = run([node], {})
        self.assertEqual(result.status, NodeStatus.PASS)

    def test_unsupported_success_condition_is_refused(self) -> None:
        node = Node("measure", "measure", _pass({"x": 1}), success_condition="looks fine")
        result = run([node], {})
        self.assertEqual(result.status, NodeStatus.FAIL)
        self.assertIn("unsupported success_condition", result.node_runs[0].detail)

    def test_outputs_mapping_requires_a_dict_output(self) -> None:
        node = Node("bad", "bad", _pass("not-a-dict"), outputs={"alias": "value"})
        result = run([node], {})
        self.assertEqual(result.status, NodeStatus.ERROR)
        self.assertIn("requires a dict output", result.node_runs[0].detail)

    def test_status_condition_uses_the_real_node_status(self) -> None:
        node = Node("check", "check", _pass({"x": 1}), success_condition="status == PASS")
        self.assertEqual(run([node], {}).status, NodeStatus.PASS)


if __name__ == "__main__":
    unittest.main()
