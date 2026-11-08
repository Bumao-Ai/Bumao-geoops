"""Sequential workflow executor.

A failing node stops the run and is recorded. A ``SKIP`` node is recorded and
the run continues, so a missing optional dataset does not abort later nodes.
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
        }


@dataclass
class WorkflowRun:
    run_id: str
    status: NodeStatus
    node_runs: List[NodeRun] = field(default_factory=list)
    skipped: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status.value,
            "skipped": self.skipped,
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


def run(
    nodes: List[Node],
    context: Optional[Dict[str, Any]] = None,
    run_id: Optional[str] = None,
) -> WorkflowRun:
    """Run nodes in registration order and stop on the first FAIL or ERROR."""
    ctx = {} if context is None else context
    records: List[NodeRun] = []
    status = NodeStatus.PASS
    stopped = False

    for node in nodes:
        if stopped:
            records.append(
                NodeRun(node.node_id, node.name, NodeStatus.SKIPPED, "upstream node failed")
            )
            continue
        try:
            result = _normalize(node.action(ctx))
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
        if result.status in (NodeStatus.FAIL, NodeStatus.ERROR):
            status = result.status
            stopped = True

    skipped = sum(
        1 for record in records if record.status in (NodeStatus.SKIP, NodeStatus.SKIPPED)
    )
    return WorkflowRun(
        run_id=run_id or "RUN-" + uuid.uuid4().hex[:12],
        status=status,
        node_runs=records,
        skipped=skipped,
    )
