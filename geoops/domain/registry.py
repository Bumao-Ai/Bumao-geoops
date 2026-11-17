"""Minimal in-memory domain registry.

Object types follow the product specification's Domain Registry list. This
implementation stores objects in process memory; persistence is not part of
the current scaffold.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class ObjectType(str, Enum):
    PROJECT = "Project"
    SURVEY_TASK = "SurveyTask"
    SURVEY_AREA = "SurveyArea"
    DATASET = "Dataset"
    MODEL = "Model"
    AGENT = "Agent"
    TOOL = "Tool"
    WORKFLOW = "Workflow"
    WORKFLOW_NODE = "WorkflowNode"
    SURVEY_RULE = "SurveyRule"
    QUALITY_REPORT = "QualityReport"
    DELIVERABLE = "Deliverable"
    REVIEW_RECORD = "ReviewRecord"


@dataclass
class DomainObject:
    object_id: str
    object_type: ObjectType
    version: int
    status: str
    created_at: str
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "object_id": self.object_id,
            "object_type": self.object_type.value,
            "version": self.version,
            "status": self.status,
            "created_at": self.created_at,
            "payload": self.payload,
        }


class DomainRegistry:
    """Register typed domain objects and fetch them by id."""

    def __init__(self) -> None:
        self._objects: Dict[str, DomainObject] = {}

    def register(
        self,
        object_type: Any,
        object_id: str,
        payload: Optional[Dict[str, Any]] = None,
        status: str = "registered",
    ) -> DomainObject:
        object_type = ObjectType(object_type)
        object_id = str(object_id or "").strip()
        if not object_id:
            raise ValueError("object_id must not be empty")
        if object_id in self._objects:
            raise ValueError("duplicate object_id: %s" % object_id)
        obj = DomainObject(
            object_id=object_id,
            object_type=object_type,
            version=1,
            status=str(status),
            created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            payload=dict(payload or {}),
        )
        self._objects[object_id] = obj
        return obj

    def get(self, object_id: str) -> Optional[DomainObject]:
        return self._objects.get(str(object_id or ""))

    def list_by_type(self, object_type: Any) -> List[DomainObject]:
        object_type = ObjectType(object_type)
        return [obj for obj in self._objects.values() if obj.object_type is object_type]

    def update(
        self,
        object_id: str,
        payload: Optional[Dict[str, Any]] = None,
        status: Optional[str] = None,
    ) -> DomainObject:
        """Change a recorded object in place, keeping its identity and history.

        Every update bumps ``version``; the caller cannot silently rewrite an
        object at the same version. A missing id is refused, not created.
        """
        obj = self.get(object_id)
        if obj is None:
            raise ValueError("unknown object_id: %s" % object_id)
        if payload:
            if not isinstance(payload, dict):
                raise ValueError("payload patch must be an object")
            obj.payload.update(payload)
        if status is not None:
            obj.status = str(status)
        obj.version += 1
        return obj

    def all(self) -> List[DomainObject]:
        return list(self._objects.values())

    def restore(self, row: Dict[str, Any]) -> DomainObject:
        """Re-create an object exactly as recorded, keeping version and time.

        Used by the snapshot store; ``register`` always starts at version 1, so
        a restored object must not go through it or the version would lie.
        """
        if not isinstance(row, dict):
            raise ValueError("object row must be an object, got %r" % (row,))
        object_id = str(row.get("object_id") or "").strip()
        if not object_id:
            raise ValueError("restored object_id must not be empty")
        if object_id in self._objects:
            raise ValueError("duplicate object_id: %s" % object_id)
        try:
            object_type = ObjectType(row.get("object_type"))
        except ValueError:
            raise ValueError(
                "unknown object_type for %s: %r" % (object_id, row.get("object_type"))
            )
        try:
            version = int(row.get("version") or 1)
        except (TypeError, ValueError):
            raise ValueError("version for %s must be an integer" % object_id)
        if version < 1:
            raise ValueError("version for %s must be >= 1" % object_id)
        payload = row.get("payload") or {}
        if not isinstance(payload, dict):
            raise ValueError("payload for %s must be an object" % object_id)
        obj = DomainObject(
            object_id=object_id,
            object_type=object_type,
            version=version,
            status=str(row.get("status") or "registered"),
            created_at=str(row.get("created_at") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
            payload=dict(payload),
        )
        self._objects[object_id] = obj
        return obj

    def __len__(self) -> int:
        return len(self._objects)
