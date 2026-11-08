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

    def __len__(self) -> int:
        return len(self._objects)
