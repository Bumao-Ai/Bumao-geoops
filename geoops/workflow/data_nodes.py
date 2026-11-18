"""Workflow nodes that read the real domain registries.

These nodes never invent a dataset or a review decision. A missing record is a
FAIL; a registry exception is an ERROR. Only a real record (or a real final
review) can pass.
"""

from __future__ import annotations

from typing import Any, Dict

from geoops.workflow.executor import Node, NodeResult, NodeStatus


def data_input_node(node_id: str, name: str, datasets: Any, dataset_key: str = "dataset_id",
                    dataset_id: str = "") -> Node:
    def action(context: Dict[str, Any]) -> NodeResult:
        resolved_id = str(context.get(dataset_key) or dataset_id or "").strip()
        if not resolved_id:
            return NodeResult(NodeStatus.FAIL, "dataset_id is empty; nothing to load")
        record = datasets.get(resolved_id)
        if record is None:
            return NodeResult(NodeStatus.FAIL, "unknown dataset_id: %s" % resolved_id)
        context["dataset"] = record.payload
        context.setdefault("node_outputs", {})[node_id] = record.payload
        requested_project = str(context.get("project_id") or "").strip()
        if requested_project and record.payload.get("project_id") != requested_project:
            return NodeResult(
                NodeStatus.FAIL,
                "dataset %s belongs to %s, not %s"
                % (resolved_id, record.payload.get("project_id"), requested_project),
            )
        return NodeResult(
            NodeStatus.PASS,
            "dataset %s is %s (%s)" % (resolved_id, record.payload.get("status"), record.payload.get("path")),
            {"dataset_id": resolved_id, "project_id": record.payload.get("project_id")},
        )

    return Node(node_id, name, action)


def data_check_node(node_id: str, name: str, datasets: Any, dataset_key: str = "dataset_id",
                    dataset_id: str = "") -> Node:
    def action(context: Dict[str, Any]) -> NodeResult:
        resolved_id = str(context.get(dataset_key) or dataset_id or "").strip()
        if not resolved_id:
            return NodeResult(NodeStatus.FAIL, "dataset_id is empty; nothing to validate")
        result = datasets.validate(resolved_id)
        context.setdefault("dataset_checks", {})[node_id] = result
        status = result.get("status")
        if status == "PASS":
            node_status = NodeStatus.PASS
        elif status == "ERROR":
            node_status = NodeStatus.ERROR
        else:
            node_status = NodeStatus.FAIL
        context.setdefault("node_outputs", {})[node_id] = result
        return NodeResult(node_status, "dataset %s validation: %s" % (resolved_id, status), result)

    return Node(node_id, name, action)


def review_gate_node(node_id: str, name: str, reviews: Any, review_key: str = "review_id",
                     deliverable_key: str = "deliverable_id") -> Node:
    def action(context: Dict[str, Any]) -> NodeResult:
        review_id = str(context.get(review_key) or "").strip()
        deliverable_id = str(context.get(deliverable_key) or "").strip()
        if review_id:
            record = reviews.get(review_id)
            if record is None:
                return NodeResult(NodeStatus.FAIL, "unknown review_id: %s" % review_id)
            if record.payload.get("decision") != "APPROVE":
                return NodeResult(
                    NodeStatus.FAIL,
                    "review %s is %s; final approval is required" % (review_id, record.payload.get("decision")),
                )
            return NodeResult(NodeStatus.PASS, "review %s is APPROVE" % review_id, record.payload)
        if deliverable_id:
            if not reviews.is_finally_accepted(deliverable_id):
                return NodeResult(
                    NodeStatus.FAIL,
                    "deliverable %s is not finally accepted; a human review is required" % deliverable_id,
                )
            return NodeResult(NodeStatus.PASS, "deliverable %s is finally accepted" % deliverable_id)
        return NodeResult(
            NodeStatus.FAIL,
            "no review_id or deliverable_id in context; manual approval cannot be fabricated",
        )

    return Node(node_id, name, action)
