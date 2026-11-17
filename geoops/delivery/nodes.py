"""Artifact registration as a workflow node.

Placing registration after the rule gate makes one run produce both the rule
verdicts and the file hash, and makes a bad product stop the run before it is
registered. A registration failure is a ``FAIL`` node, never a ``PASS`` with a
missing hash.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from geoops.artifacts import ArtifactError, ArtifactStore
from geoops.workflow import Node, NodeResult, NodeStatus


def artifact_register_node(
    node_id: str,
    name: str,
    store: ArtifactStore,
    deliverable_id: Optional[str] = None,
    path_key: str = "deliverable_path",
    task_id: Optional[str] = None,
    kind: Optional[str] = None,
    label: Optional[str] = None,
) -> Node:
    """Build a node that registers the file named by ``context[path_key]``."""

    def action(context: Dict[str, Any]) -> NodeResult:
        path = str(context.get(path_key) or "").strip()
        if not path:
            return NodeResult(
                NodeStatus.FAIL, "%s is empty; there is no file to register" % path_key
            )
        bound = deliverable_id or context.get("deliverable_id")
        owned_by = task_id or context.get("task_id")
        try:
            row = store.register(
                path,
                task_id=owned_by,
                kind=kind,
                label=label,
                deliverable_id=bound,
            )
            store.verify(row["artifact_id"])
        except ArtifactError as exc:
            return NodeResult(NodeStatus.FAIL, str(exc), {"path": path})
        context.setdefault("artifacts", {}).setdefault(node_id, row)
        return NodeResult(
            NodeStatus.PASS,
            "registered %s (%d bytes) sha256=%s"
            % (row["artifact_id"], row["size"], row["sha256"][:12]),
            {
                "artifact_id": row["artifact_id"],
                "sha256": row["sha256"],
                "size": row["size"],
                "path": row["path"],
            },
        )

    return Node(node_id, name, action)
