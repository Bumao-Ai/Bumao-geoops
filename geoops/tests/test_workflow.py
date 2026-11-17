"""Unit tests for the workflow executor and resume rules.

Standard library only: run with

    python -m unittest geoops.tests.test_workflow -v
"""

from __future__ import annotations

import unittest

from geoops.workflow import Node, NodeResult, NodeStatus, WorkflowEngine, run


def _ok(name="ok"):
    def action(context):
        return NodeResult(NodeStatus.PASS, name)

    return action


def _fail(name="failed"):
    def action(context):
        return NodeResult(NodeStatus.FAIL, name)

    return action


def _nodes(n1=_ok(), n2=_fail(), n3=_ok()):
    return [
        Node("N1", "first", n1),
        Node("N2", "second", n2),
        Node("N3", "third", n3),
    ]


class WorkflowTests(unittest.TestCase):
    def test_fail_stops_and_skips_later_nodes(self) -> None:
        result = run(_nodes(), run_id="RUN-T-001")
        self.assertIs(result.status, NodeStatus.FAIL)
        self.assertEqual(result.node_runs[0].status, NodeStatus.PASS)
        self.assertEqual(result.node_runs[1].status, NodeStatus.FAIL)
        self.assertEqual(result.node_runs[2].status, NodeStatus.SKIPPED)
        self.assertEqual(result.skipped, 1)

    def test_error_is_not_a_pass(self) -> None:
        def boom(context):
            raise RuntimeError("tool crashed")

        result = run(_nodes(n2=boom), run_id="RUN-T-002")
        self.assertIs(result.status, NodeStatus.ERROR)
        self.assertIn("RuntimeError", result.node_runs[1].detail)
        self.assertEqual(result.node_runs[2].status, NodeStatus.SKIPPED)

    def test_resume_reuses_passed_nodes_and_restarts_at_failure(self) -> None:
        from geoops.workflow import resume

        first = run(_nodes(), run_id="RUN-T-003")
        second = resume(_nodes(n2=_ok("second ok")), first, run_id="RUN-T-004")
        self.assertIs(second.status, NodeStatus.PASS)
        self.assertEqual(second.node_runs[0].status, NodeStatus.REUSED)
        self.assertIn("RUN-T-003", second.node_runs[0].detail)
        self.assertEqual(second.node_runs[1].status, NodeStatus.PASS)
        self.assertEqual(second.node_runs[2].status, NodeStatus.PASS)
        self.assertEqual(second.skipped, 0)

    def test_resume_requires_a_failed_run(self) -> None:
        from geoops.workflow import resume

        passed = run(_nodes(n2=_ok()), run_id="RUN-T-005")
        with self.assertRaises(ValueError):
            resume(_nodes(), passed, run_id="RUN-T-006")

    def test_resume_rejects_changed_node_count(self) -> None:
        from geoops.workflow import resume

        first = run(_nodes(), run_id="RUN-T-007")
        with self.assertRaises(ValueError):
            resume(_nodes()[:2], first, run_id="RUN-T-008")

    def test_resume_rejects_changed_node_identity(self) -> None:
        from geoops.workflow import resume

        first = run(_nodes(), run_id="RUN-T-009")
        changed = _nodes()
        changed[1] = Node("N2-OTHER", "second", _ok())
        with self.assertRaises(ValueError):
            resume(changed, first, run_id="RUN-T-010")

    def test_resume_rejects_same_run_id(self) -> None:
        from geoops.workflow import resume

        first = run(_nodes(), run_id="RUN-T-011")
        with self.assertRaises(ValueError):
            resume(_nodes(n2=_ok()), first, run_id="RUN-T-011")

    def test_resume_rejects_reusing_a_non_pass_node(self) -> None:
        from geoops.workflow import resume

        first = run(
            [
                Node("N1", "first", lambda ctx: NodeResult(NodeStatus.SKIP, "optional")),
                Node("N2", "second", _fail()),
                Node("N3", "third", _ok()),
            ],
            run_id="RUN-T-012",
        )
        with self.assertRaises(ValueError):
            resume(
                [
                    Node("N1", "first", _ok()),
                    Node("N2", "second", _ok()),
                    Node("N3", "third", _ok()),
                ],
                first,
                run_id="RUN-T-013",
            )

    def test_engine_refuses_duplicate_run_ids(self) -> None:
        engine = WorkflowEngine()
        engine.start(_nodes(), run_id="RUN-T-014")
        with self.assertRaises(ValueError):
            engine.start(_nodes(), run_id="RUN-T-014")

    def test_engine_records_history_and_resumes_by_id(self) -> None:
        engine = WorkflowEngine()
        first = engine.start(_nodes(), run_id="RUN-T-015")
        second = engine.resume("RUN-T-015", _nodes(n2=_ok()), run_id="RUN-T-016")
        self.assertEqual([r.run_id for r in engine.history()], ["RUN-T-015", "RUN-T-016"])
        self.assertIs(engine.get("RUN-T-016"), second)
        self.assertEqual(second.resumed_from, first.run_id)

    def test_resume_carries_prior_output_into_context(self) -> None:
        engine = WorkflowEngine()

        def produce(context):
            context["value"] = 42
            return NodeResult(NodeStatus.PASS, "produced", {"value": 42})

        first = engine.start(
            [Node("N1", "produce", produce), Node("N2", "second step", _fail())],
            run_id="RUN-T-017",
        )
        seen = {}

        def consume(context):
            seen["value"] = context.get("node_outputs", {}).get("N1")
            return NodeResult(NodeStatus.PASS, "consumed")

        second = engine.resume(
            "RUN-T-017",
            [Node("N1", "produce", produce), Node("N2", "second step", consume)],
            run_id="RUN-T-018",
        )
        self.assertIs(second.status, NodeStatus.PASS)
        self.assertEqual(seen["value"], {"value": 42})


if __name__ == "__main__":
    unittest.main()
