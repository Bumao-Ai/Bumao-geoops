"""Deliverable registration and archival.

A deliverable is a real file that a task produced. Registration reads the file
and records its sha256 and size, so a later edit is detectable. Final
acceptance is not decided here: ``ReviewEngine`` flips a deliverable to
``accepted`` only on an approving review. Archival is a separate, explicit step
that is allowed only after acceptance.
"""

from __future__ import annotations

import hashlib
import os
import time
import uuid
from typing import Any, Dict, List, Optional

from geoops.domain.registry import DomainObject, DomainRegistry, ObjectType


class DeliverableError(ValueError):
    """A deliverable record was refused; nothing was written."""


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


class DeliverableRegistry:
    def __init__(self, registry: DomainRegistry) -> None:
        self.registry = registry

    def register(
        self,
        task_id: str,
        name: str,
        path: str,
        kind: str = "",
        notes: str = "",
        deliverable_id: str = "",
        version: int = 1,
        synthetic: bool = False,
    ) -> DomainObject:
        task_id = str(task_id or "").strip()
        name = str(name or "").strip()
        path = str(path or "").strip()
        if not task_id:
            raise DeliverableError("task_id is required")
        if not name:
            raise DeliverableError("deliverable name is required")
        if not path:
            raise DeliverableError("deliverable path is required")
        task = self.registry.get(task_id)
        if task is None or task.object_type is not ObjectType.SURVEY_TASK:
            raise DeliverableError("unknown task_id: %s" % task_id)
        absolute = os.path.abspath(path)
        if not os.path.exists(absolute):
            raise DeliverableError("deliverable file not found: %s" % path)
        if os.path.islink(absolute):
            raise DeliverableError("refusing to register a symlink: %s" % path)
        if not os.path.isfile(absolute):
            raise DeliverableError("not a regular file: %s" % path)
        try:
            version = int(version)
        except (TypeError, ValueError):
            raise DeliverableError("version must be an integer")
        if version < 1:
            raise DeliverableError("version must be >= 1")
        digest = _sha256(absolute)
        size = os.path.getsize(absolute)
        deliverable_id = str(deliverable_id or "").strip()
        if not deliverable_id:
            deliverable_id = "DLV-%s" % uuid.uuid4().hex[:10]
        if self.registry.get(deliverable_id) is not None:
            raise DeliverableError("duplicate deliverable_id: %s" % deliverable_id)
        task_payload = task.payload
        payload: Dict[str, Any] = {
            "deliverable_id": deliverable_id,
            "task_id": task_id,
            "project_id": task_payload.get("project_id"),
            "synthetic": bool(synthetic),
            "name": name,
            "kind": str(kind or "").strip(),
            "path": absolute.replace("\\", "/"),
            "sha256": digest,
            "size_bytes": size,
            "deliverable_version": version,
            "notes": str(notes or "").strip(),
            "registered_at": _now(),
        }
        try:
            return self.registry.register(ObjectType.DELIVERABLE, deliverable_id, payload)
        except ValueError as exc:
            raise DeliverableError(str(exc)) from exc

    def get(self, deliverable_id: str) -> Optional[DomainObject]:
        obj = self.registry.get(deliverable_id)
        if obj is None or obj.object_type is not ObjectType.DELIVERABLE:
            return None
        return obj

    def list(self, task_id: str = "") -> List[DomainObject]:
        rows = self.registry.list_by_type(ObjectType.DELIVERABLE)
        if task_id:
            rows = [row for row in rows if row.payload.get("task_id") == task_id]
        return rows

    def archive(self, deliverable_id: str, actor: str = "", note: str = "") -> DomainObject:
        deliverable = self.get(deliverable_id)
        if deliverable is None:
            raise DeliverableError("unknown deliverable_id: %s" % deliverable_id)
        if deliverable.status != "accepted":
            raise DeliverableError(
                "only an accepted deliverable can be archived; %s is %s"
                % (deliverable_id, deliverable.status)
            )
        if deliverable.payload.get("archived_at"):
            raise DeliverableError("deliverable is already archived: %s" % deliverable_id)
        return self.registry.update(
            deliverable_id,
            payload={
                "archived_at": _now(),
                "archived_by": str(actor or "").strip(),
                "archive_note": str(note or "").strip(),
            },
            status="archived",
        )
