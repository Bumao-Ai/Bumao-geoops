"""Sequential workflow executor with resume from a failed node.

A failing node stops the run and is recorded. A ``SKIP`` node is recorded and
the run continues, so a missing optional dataset does not abort later nodes.

A failed run can be resumed: nodes that already passed are carried forward as
``REUSED`` with their original output, and execution restarts at the node that
failed. Resuming is refused when the node list no longer matches the run that
is being resumed, so a retry can never silently run a different workflow under
the old record.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


class NodeStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"
    SKIP = "SKIP"
    SKIPPED = "SKIPPED"
    # Carried forward from an earlier run; not executed again on resume.
    REUSED = "REUSED"


@dataclass
class NodeResult:
    status: NodeStatus
    detail: str = ""
    output: Any = None


@dataclass
class Node:
    node_id: str
    name: str
    action: Callable[[Dict[str, Any]], Any]


@dataclass
class NodeRun:
    node_id: str
    name: str
    status: NodeStatus
    detail: str
    output: Any = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "name": self.name,
            "status": self.status.value,
            "detail": self.detail,
            "output": self.output,
        }


@dataclass
class WorkflowRun:
    run_id: str
    status: NodeStatus
    node_runs: List[NodeRun] = field(default_factory=list)
    skipped: int = 0
    resumed_from: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status.value,
            "skipped": self.skipped,
            "resumed_from": self.resumed_from,
            "node_runs": [record.to_dict() for record in self.node_runs],
        }


def _normalize(result: Any) -> NodeResult:
    if isinstance(result, NodeResult):
        return result
    if isinstance(result, tuple) and len(result) >= 2:
        return NodeResult(
            NodeStatus.PASS if result[0] else NodeStatus.FAIL, str(result[1])
        )
    return NodeResult(NodeStatus.PASS if result else NodeStatus.FAIL, "")


def _execute(
    nodes: List[Node],
    context: Dict[str, Any],
    records: List[NodeRun],
    start: int,
) -> NodeStatus:
    """Run nodes from ``start`` onward, appending records. Stops on FAIL/ERROR."""
    status = NodeStatus.PASS
    stopped = False
    for node in nodes[start:]:
        if stopped:
            records.append(
                NodeRun(node.node_id, node.name, NodeStatus.SKIPPED, "upstream node failed")
            )
            continue
        try:
            result = _normalize(node.action(context))
        except Exception as exc:
            records.append(
                NodeRun(
                    node.node_id,
                    node.name,
                    NodeStatus.ERROR,
                    "%s: %s" % (type(exc).__name__, exc),
                )
            )
            status = NodeStatus.ERROR
            stopped = True
            continue

        records.append(NodeRun(node.node_id, node.name, result.status, result.detail, result.output))
        # Every node's real output is addressable by downstream nodes. A node
        # can read context["node_outputs"][<node_id>] instead of relying on a
        # side effect or a shared mutable prompt.
        context.setdefault("node_outputs", {})[node.node_id] = result.output
        if result.status in (NodeStatus.FAIL, NodeStatus.ERROR):
            status = result.status
            stopped = True
    return status


def _count_skipped(records: List[NodeRun]) -> int:
    return sum(
        1 for record in records if record.status in (NodeStatus.SKIP, NodeStatus.SKIPPED)
    )


def run(
    nodes: List[Node],
    context: Optional[Dict[str, Any]] = None,
    run_id: Optional[str] = None,
) -> WorkflowRun:
    """Run nodes in registration order and stop on the first FAIL or ERROR."""
    ctx = {} if context is None else context
    records: List[NodeRun] = []
    status = _execute(nodes, ctx, records, 0)
    return WorkflowRun(
        run_id=run_id or "RUN-" + uuid.uuid4().hex[:12],
        status=status,
        node_runs=records,
        skipped=_count_skipped(records),
    )


def _resume_point(nodes: List[Node], previous: WorkflowRun) -> int:
    """Validate that ``previous`` belongs to ``nodes`` and return its restart index."""
    if previous.status not in (NodeStatus.FAIL, NodeStatus.ERROR):
        raise ValueError(
            "only a FAIL or ERROR run can be resumed; %s is %s"
            % (previous.run_id, previous.status.value)
        )
    if len(previous.node_runs) != len(nodes):
        raise ValueError(
            "workflow shape changed: %s has %d nodes, the definition has %d"
            % (previous.run_id, len(previous.node_runs), len(nodes))
        )
    start: Optional[int] = None
    for index, (record, node) in enumerate(zip(previous.node_runs, nodes)):
        if record.node_id != node.node_id or record.name != node.name:
            raise ValueError(
                "node %d changed: %s/%s in %s, %s/%s in the definition"
                % (index, record.node_id, record.name, previous.run_id, node.node_id, node.name)
            )
        if start is None and record.status in (NodeStatus.FAIL, NodeStatus.ERROR):
            start = index
    if start is None:
        raise ValueError("run %s has no failed node to resume from" % previous.run_id)
    return start


def resume(
    nodes: List[Node],
    previous: WorkflowRun,
    context: Optional[Dict[str, Any]] = None,
    run_id: Optional[str] = None,
) -> WorkflowRun:
    """Resume a failed run at its failed node, reusing nodes that already passed."""
    ctx = {} if context is None else context
    start = _resume_point(nodes, previous)
    new_id = run_id or "RUN-" + uuid.uuid4().hex[:12]
    if new_id == previous.run_id:
        raise ValueError("resume needs a new run_id; %s is the previous run" % new_id)

    outputs = ctx.setdefault("node_outputs", {})
    records: List[NodeRun] = []
    for index in range(start):
        prior = previous.node_runs[index]
        if prior.status is not NodeStatus.PASS:
            raise ValueError(
                "cannot reuse node %s in state %s" % (prior.node_id, prior.status.value)
            )
        outputs[prior.node_id] = prior.output
        records.append(
            NodeRun(
                prior.node_id,
                prior.name,
                NodeStatus.REUSED,
                "reused from %s" % previous.run_id,
                prior.output,
            )
        )

    status = _execute(nodes, ctx, records, start)
    return WorkflowRun(
        run_id=new_id,
        status=status,
        node_runs=records,
        skipped=_count_skipped(records),
        resumed_from=previous.run_id,
    )


class WorkflowEngine:
    """Keep runs in memory and refuse records that would contradict each other."""

    def __init__(self) -> None:
        self._runs: Dict[str, WorkflowRun] = {}

    def start(
        self,
        nodes: List[Node],
        context: Optional[Dict[str, Any]] = None,
        run_id: Optional[str] = None,
    ) -> WorkflowRun:
        if run_id and run_id in self._runs:
            raise ValueError("duplicate run_id: %s" % run_id)
        result = run(nodes, context, run_id)
        self._remember(result)
        return result

    def resume(
        self,
        previous: Any,
        nodes: List[Node],
        context: Optional[Dict[str, Any]] = None,
        run_id: Optional[str] = None,
    ) -> WorkflowRun:
        previous_run = self.get(previous) if isinstance(previous, str) else previous
        if not isinstance(previous_run, WorkflowRun):
            raise ValueError("unknown previous run: %r" % (previous,))
        if run_id and run_id in self._runs:
            raise ValueError("duplicate run_id: %s" % run_id)
        result = resume(nodes, previous_run, context, run_id)
        self._remember(result)
        return result

    def get(self, run_id: str) -> Optional[WorkflowRun]:
        return self._runs.get(str(run_id or ""))

    def history(self) -> List[WorkflowRun]:
        return list(self._runs.values())

    def _remember(self, result: WorkflowRun) -> None:
        if result.run_id in self._runs:
            raise ValueError("duplicate run_id: %s" % result.run_id)
        self._runs[result.run_id] = result
