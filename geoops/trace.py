"""Structured trace from a task back to its sources, runs, rules and review.

The trace is assembled from records that exist. Every link that is absent is
listed as ``NOT_RECORDED`` with a reason, so a reader can tell "no dataset was
bound" from "a dataset was bound and later deleted". It is a chain object, not
a paragraph of prose.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from geoops.domain.registry import DomainRegistry, ObjectType


def _ids(rows: List[Any]) -> List[str]:
    return [row.object_id for row in rows]


def _missing(name: str, reason: str) -> Dict[str, str]:
    return {"name": name, "status": "NOT_RECORDED", "reason": reason}


def build_trace(
    registry: DomainRegistry,
    task_id: str,
    journal: Optional[Any] = None,
    artifacts: Optional[Any] = None,
    reviews: Optional[Any] = None,
) -> Dict[str, Any]:
    task = registry.get(task_id)
    if task is None or task.object_type is not ObjectType.SURVEY_TASK:
        raise ValueError("unknown task_id: %s" % task_id)
    missing: List[Dict[str, str]] = []

    project_id = str(task.payload.get("project_id") or "")
    project = registry.get(project_id)
    project_ok = project is not None and project.object_type is ObjectType.PROJECT
    if not project_ok:
        missing.append(_missing("project", "no registered project for %s" % (project_id or "task")))

    datasets = [
        row
        for row in registry.list_by_type(ObjectType.DATASET)
        if row.payload.get("task_id") == task_id
        or (not row.payload.get("task_id") and project_id and row.payload.get("project_id") == project_id)
    ]
    if not datasets:
        missing.append(_missing("datasets", "no dataset bound to this task"))

    run_ids = list(task.payload.get("workflow_run_ids") or [])
    run_rows: List[Dict[str, Any]] = []
    if journal is not None:
        for row in journal.rows():
            if row.get("task_id") == task_id or row.get("run_id") in run_ids:
                run_rows.append(row)
    if not run_rows:
        missing.append(_missing("workflow_runs", "no run recorded for this task"))

    rules: List[Dict[str, Any]] = []
    for run in run_rows:
        for node in run.get("node_runs", []):
            detail = str(node.get("skill") or node.get("detail") or "")
            if "rule" in str(node.get("name") or "").lower() or "规则" in str(node.get("name") or ""):
                rules.append(
                    {
                        "run_id": run.get("run_id"),
                        "node_id": node.get("node_id"),
                        "status": node.get("status"),
                        "detail": node.get("detail"),
                    }
                )
    if not rules:
        missing.append(_missing("rule_results", "no rule-check node in the recorded runs"))

    deliverables = [
        row
        for row in registry.list_by_type(ObjectType.DELIVERABLE)
        if row.payload.get("task_id") == task_id
    ]
    if not deliverables:
        missing.append(_missing("deliverables", "no deliverable registered for this task"))

    artifact_rows: List[Dict[str, Any]] = []
    if artifacts is not None:
        artifact_rows = [row for row in artifacts.all() if row.get("task_id") == task_id]
    if deliverables and not artifact_rows:
        missing.append(_missing("artifacts", "deliverable exists but no file is registered"))

    review_rows: List[Dict[str, Any]] = []
    if reviews is not None:
        review_rows = [row.to_dict() for row in reviews.list(task_id=task_id)]
    if not review_rows:
        missing.append(_missing("review", "no human review recorded"))

    links = []
    if project_ok:
        links.append({"from": project.object_id, "to": task.object_id, "kind": "project→task"})
    for dataset in datasets:
        links.append({"from": dataset.object_id, "to": task.object_id, "kind": "dataset→task"})
    for run in run_rows:
        links.append({"from": run.get("run_id"), "to": task.object_id, "kind": "run→task"})
    for delivery in deliverables:
        links.append({"from": delivery.object_id, "to": task.object_id, "kind": "deliverable→task"})
    for row in artifact_rows:
        links.append({"from": row.get("artifact_id"), "to": row.get("deliverable_id") or "", "kind": "artifact→deliverable"})
    for row in review_rows:
        links.append({"from": row.get("object_id"), "to": row.get("payload", {}).get("deliverable_id"), "kind": "review→deliverable"})

    return {
        "task_id": task_id,
        "task_status": task.status,
        "project": project.to_dict() if project_ok else None,
        "datasets": [row.to_dict() for row in datasets],
        "runs": run_rows,
        "rules": rules,
        "deliverables": [row.to_dict() for row in deliverables],
        "artifacts": artifact_rows,
        "reviews": review_rows,
        "links": links,
        "missing": missing,
        "complete": not missing,
    }
