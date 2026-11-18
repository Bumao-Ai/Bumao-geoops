"""Human review records and the final-acceptance gate.

A deliverable becomes ``accepted`` only through an approving review record. The
review records who reviewed it, when, with what opinion and at which object
version; a rejection or rerun request leaves the deliverable unaccepted, and an
already accepted deliverable refuses further review so a signature cannot be
quietly replaced.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional

from geoops.domain.registry import DomainObject, DomainRegistry, ObjectType

DECISIONS = {"APPROVE", "REJECT", "RERUN"}


class ReviewError(ValueError):
    """A review was refused; nothing was written."""


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class ReviewEngine:
    def __init__(self, registry: DomainRegistry) -> None:
        self.registry = registry

    def submit(
        self,
        task_id: str,
        deliverable_id: str,
        reviewer: str,
        decision: str,
        opinion: str = "",
        review_id: str = "",
        quality_report_id: str = "",
    ) -> DomainObject:
        reviewer = str(reviewer or "").strip()
        task_id = str(task_id or "").strip()
        deliverable_id = str(deliverable_id or "").strip()
        decision = str(decision or "").strip().upper()
        if not reviewer:
            raise ReviewError("reviewer is required")
        if decision not in DECISIONS:
            raise ReviewError("decision must be one of %s" % ", ".join(sorted(DECISIONS)))
        if decision in ("REJECT", "RERUN") and not str(opinion or "").strip():
            raise ReviewError("a %s review requires an opinion" % decision.lower())
        task = self.registry.get(task_id)
        if task is None or task.object_type is not ObjectType.SURVEY_TASK:
            raise ReviewError("unknown task_id: %s" % task_id)
        deliverable = self.registry.get(deliverable_id)
        if deliverable is None or deliverable.object_type is not ObjectType.DELIVERABLE:
            raise ReviewError("unknown deliverable_id: %s" % deliverable_id)
        if deliverable.status == "accepted":
            raise ReviewError("deliverable is already finally accepted: %s" % deliverable_id)
        if decision == "APPROVE" and bool(deliverable.payload.get("synthetic")):
            raise ReviewError(
                "synthetic deliverable %s cannot be finally accepted" % deliverable_id
            )
        quality_report_id = str(quality_report_id or "").strip()
        if quality_report_id:
            report = self.registry.get(quality_report_id)
            if report is None or report.object_type is not ObjectType.QUALITY_REPORT:
                raise ReviewError("unknown quality_report_id: %s" % quality_report_id)
            target = report.payload.get("target") or {}
            if report.payload.get("target_type") != "deliverable" or target.get("deliverable_id") != deliverable_id:
                raise ReviewError(
                    "quality report %s does not inspect deliverable %s"
                    % (quality_report_id, deliverable_id)
                )
            if decision == "APPROVE" and report.payload.get("status") != "PASS":
                raise ReviewError(
                    "cannot approve %s with quality report %s in state %s"
                    % (deliverable_id, quality_report_id, report.payload.get("status"))
                )
        review_id = str(review_id or "RV-%s" % uuid.uuid4().hex[:10]).strip()
        if self.registry.get(review_id) is not None:
            raise ReviewError("duplicate review_id: %s" % review_id)
        payload: Dict[str, Any] = {
            "review_id": review_id,
            "task_id": task_id,
            "deliverable_id": deliverable_id,
            "reviewer": reviewer,
            "decision": decision,
            "opinion": str(opinion or "").strip(),
            "quality_report_id": quality_report_id or None,
            "reviewed_at": _now(),
            "deliverable_version_at_review": deliverable.version,
        }
        try:
            record = self.registry.register(
                ObjectType.REVIEW_RECORD,
                review_id,
                payload,
                status="final" if decision == "APPROVE" else "open",
            )
        except ValueError as exc:
            raise ReviewError(str(exc)) from exc
        if decision == "APPROVE":
            self.registry.update(
                deliverable_id,
                payload={"review_id": review_id, "reviewed_by": reviewer},
                status="accepted",
            )
        elif decision == "REJECT":
            self.registry.update(deliverable_id, status="rejected")
        else:
            self.registry.update(deliverable_id, status="rerun_requested")
        return record

    def get(self, review_id: str) -> Optional[DomainObject]:
        obj = self.registry.get(review_id)
        if obj is None or obj.object_type is not ObjectType.REVIEW_RECORD:
            return None
        return obj

    def list(self, task_id: str = "", deliverable_id: str = "") -> List[DomainObject]:
        rows = self.registry.list_by_type(ObjectType.REVIEW_RECORD)
        if task_id:
            rows = [row for row in rows if row.payload.get("task_id") == task_id]
        if deliverable_id:
            rows = [row for row in rows if row.payload.get("deliverable_id") == deliverable_id]
        return rows

    def is_finally_accepted(self, deliverable_id: str) -> bool:
        obj = self.registry.get(deliverable_id)
        return bool(obj is not None and obj.status == "accepted")
