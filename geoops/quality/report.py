"""Execution report built from recorded objects, then written to disk.

The report never fills a gap with a guess. A section that was not recorded is
written as ``"status": "NOT_RECORDED"`` with the reason, so a reader can tell
"nothing was checked" from "checked and passed". Only values that already exist
in the task, the runs, the rule results or the quality report are copied.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional

FORMAT = "geoops-report"
VERSION = 1


class ReportError(ValueError):
    """Raised when a report cannot be built from the supplied records."""


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _section_status(present: bool) -> Dict[str, str]:
    if present:
        return {"status": "RECORDED"}
    return {"status": "NOT_RECORDED", "reason": "not supplied when the report was built"}


def build_report(
    task: Any,
    runs: Optional[List[Any]] = None,
    rule_results: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    quality: Optional[Any] = None,
    deliverable: Optional[Any] = None,
    review: Optional[Any] = None,
    artifacts: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Assemble a report from real objects. Refuses when there is no task."""
    if task is None:
        raise ReportError("a task record is required to build a report")

    task_payload = task.to_dict() if hasattr(task, "to_dict") else dict(task)
    if not task_payload.get("task_id"):
        raise ReportError("the task record has no task_id")

    run_payloads = [
        run.to_dict() if hasattr(run, "to_dict") else dict(run) for run in (runs or [])
    ]

    rules: List[Dict[str, Any]] = []
    rule_counts: Dict[str, int] = {}
    for node_id, rows in (rule_results or {}).items():
        for row in rows:
            entry = dict(row)
            entry["node_id"] = node_id
            rules.append(entry)
            rule_counts[entry.get("status", "UNKNOWN")] = (
                rule_counts.get(entry.get("status", "UNKNOWN"), 0) + 1
            )

    quality_payload = None
    if quality is not None:
        quality_payload = quality.to_dict() if hasattr(quality, "to_dict") else dict(quality)

    deliverable_payload = None
    if deliverable is not None:
        deliverable_payload = (
            deliverable.to_dict() if hasattr(deliverable, "to_dict") else dict(deliverable)
        )

    review_payload = None
    if review is not None:
        review_payload = review.to_dict() if hasattr(review, "to_dict") else dict(review)

    return {
        "format": FORMAT,
        "version": VERSION,
        "generated_at": _now(),
        "task": task_payload,
        "task_section": _section_status(True),
        "workflow_runs": run_payloads,
        "workflow_section": _section_status(bool(run_payloads)),
        "rules": {
            "results": rules,
            "counts": rule_counts,
            **_section_status(bool(rules)),
        },
        "quality": {
            "report": quality_payload,
            **_section_status(quality_payload is not None),
        },
        "deliverable": {
            "record": deliverable_payload,
            **_section_status(deliverable_payload is not None),
        },
        "artifact_files": {
            "records": [dict(row) for row in (artifacts or [])],
            "count": len(artifacts or []),
            **_section_status(bool(artifacts)),
        },
        "review": {
            "record": review_payload,
            **_section_status(review_payload is not None),
        },
    }


def render_markdown(report: Dict[str, Any]) -> str:
    """Render the same records as a short, readable report."""
    if report.get("format") != FORMAT:
        raise ReportError("not a GeoOps report: format=%r" % report.get("format"))
    task = report["task"]
    lines = [
        "# 测绘作业报告 / Survey execution report",
        "",
        "- 任务 / Task: `%s` — %s" % (task.get("task_id"), task.get("name")),
        "- 项目 / Project: `%s`" % task.get("project_id"),
        "- 作业类型 / Task type: `%s`" % task.get("task_type"),
        "- 状态 / Status: **%s**" % task.get("status"),
        "- 生成时间 / Generated: %s" % report.get("generated_at"),
        "",
        "## 流程 / Workflow runs",
    ]
    if report["workflow_section"]["status"] != "RECORDED":
        lines.append("")
        lines.append("NOT_RECORDED — 本次未提供流程记录。")
    else:
        lines.append("")
        lines.append("| run | status | resumed_from | skipped |")
        lines.append("|---|---|---|---|")
        for run in report["workflow_runs"]:
            lines.append(
                "| %s | %s | %s | %s |"
                % (
                    run.get("run_id"),
                    run.get("status"),
                    run.get("resumed_from") or "—",
                    run.get("skipped", 0),
                )
            )

    lines += ["", "## 规则 / Rules"]
    if report["rules"]["status"] != "RECORDED":
        lines.append("")
        lines.append("NOT_RECORDED — 本次未提供规则判定结果。")
    else:
        lines.append("")
        for row in report["rules"]["results"]:
            lines.append(
                "- `%s` %s — %s" % (row.get("rule_id"), row.get("status"), row.get("detail"))
            )

    lines += ["", "## 质量检查 / Quality check"]
    quality = report["quality"]["report"]
    if report["quality"]["status"] != "RECORDED" or quality is None:
        lines.append("")
        lines.append("NOT_RECORDED — 本次未提供质量检查报告。")
    else:
        lines.append("")
        lines.append("- 结论 / Verdict: **%s**" % quality.get("status"))
        for check in quality.get("checks", []):
            lines.append(
                "  - %s: %s (%s)" % (check.get("name"), check.get("status"), check.get("detail"))
            )

    lines += ["", "## 成果 / Deliverable"]
    deliverable = report["deliverable"]["record"]
    if report["deliverable"]["status"] != "RECORDED" or deliverable is None:
        lines.append("")
        lines.append("NOT_RECORDED — 本次未提供成果登记。")
    else:
        lines.append("")
        lines.append("- `%s` %s" % (deliverable.get("object_id"), deliverable.get("status")))

    lines += ["", "## 成果物文件 / Deliverable files"]
    files = report["artifact_files"]["records"]
    if report["artifact_files"]["status"] != "RECORDED" or not files:
        lines.append("")
        lines.append("NOT_RECORDED — 本次未登记成果物文件。")
    else:
        lines.append("")
        lines.append("| artifact | path | size (B) | sha256 |")
        lines.append("|---|---|---|---|")
        for row in files:
            lines.append(
                "| %s | `%s` | %d | `%s` |"
                % (row.get("artifact_id"), row.get("path"), row.get("size", 0), row.get("sha256"))
            )

    lines += ["", "## 审核 / Review"]
    if report["review"]["status"] != "RECORDED":
        lines.append("")
        lines.append("NOT_RECORDED — 本次未提供人工审核记录。")
    lines.append("")
    return "\n".join(lines)


def write_report(report: Dict[str, Any], path: str, fmt: str = "json") -> str:
    """Write the report atomically and return the path that was written."""
    if report.get("format") != FORMAT:
        raise ReportError("not a GeoOps report: format=%r" % report.get("format"))
    fmt = str(fmt or "json").lower()
    if fmt not in ("json", "md"):
        raise ReportError("unsupported report format: %r" % fmt)
    path = str(path or "").strip()
    if not path:
        raise ReportError("report path must not be empty")
    path = os.path.abspath(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    if fmt == "json":
        text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    else:
        text = render_markdown(report)

    temp_path = path + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp_path, path)
    return path
