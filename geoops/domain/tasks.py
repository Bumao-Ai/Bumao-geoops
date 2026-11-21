"""Survey task engine: the task lifecycle, kept apart from workflow execution.

A task is the business goal; a workflow is one way to carry it out. The same
task may be run by different workflow versions, so this engine owns only the
task state machine and its history. It does not execute nodes and it does not
judge quality.

Transitions are explicit: every state change must be listed in ``ALLOWED``,
otherwise it is rejected with a readable reason instead of being applied. A
rejected transition leaves the task untouched, so a failure cannot look like a
success in the record.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from geoops.domain.registry import DomainRegistry, ObjectType


class TaskStatus(str, Enum):
    DRAFT = "DRAFT"
    READY = "READY"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


# Allowed target states from each state. Terminal states have no outgoing edge.
ALLOWED: Dict[TaskStatus, frozenset] = {
    TaskStatus.DRAFT: frozenset({TaskStatus.READY, TaskStatus.CANCELLED}),
    TaskStatus.READY: frozenset({TaskStatus.RUNNING, TaskStatus.DRAFT, TaskStatus.CANCELLED}),
    TaskStatus.RUNNING: frozenset(
        {
            TaskStatus.PAUSED,
            TaskStatus.FAILED,
            TaskStatus.COMPLETED,
            TaskStatus.CANCELLED,
        }
    ),
    # A paused task resumes; a failed task may be retried from the failed node.
    TaskStatus.PAUSED: frozenset({TaskStatus.RUNNING, TaskStatus.CANCELLED}),
    TaskStatus.FAILED: frozenset({TaskStatus.RUNNING, TaskStatus.CANCELLED}),
    TaskStatus.COMPLETED: frozenset(),
    TaskStatus.CANCELLED: frozenset(),
}


class TaskError(ValueError):
    """Raised when a task operation cannot be applied. The task is unchanged."""


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@dataclass
class SurveyTask:
    task_id: str
    project_id: str
    name: str
    task_type: str
    status: TaskStatus
    created_at: str
    updated_at: str
    version: int = 1
    workflow_run_ids: List[str] = field(default_factory=list)
    history: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "project_id": self.project_id,
            "name": self.name,
            "task_type": self.task_type,
            "status": self.status.value,
            "version": self.version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "workflow_run_ids": list(self.workflow_run_ids),
            "history": [dict(entry) for entry in self.history],
        }


def _locked(method):
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    wrapper.__name__ = method.__name__
    return wrapper


class TaskEngine:
    """Create survey tasks and drive their state machine.

    The registry holds a mirror of each task so the HTTP API can serve it by
    object id. This engine keeps the authoritative copy; every mutation is
    written back to the registry in the same call.
    """

    def __init__(self, registry: DomainRegistry) -> None:
        self.registry = registry
        self._tasks: Dict[str, SurveyTask] = {}
        self._lock = threading.RLock()

    @_locked
    def create(
        self,
        project_id: str,
        name: str,
        task_type: str = "land_use_classification",
        actor: str = "",
    ) -> SurveyTask:
        project = self.registry.get(project_id)
        if project is None:
            raise TaskError("unknown project_id: %s" % project_id)
        if project.object_type is not ObjectType.PROJECT:
            raise TaskError("object %s is not a Project" % project_id)
        task_name = str(name or "").strip()
        if not task_name:
            raise TaskError("task name must not be empty")
        task_type = str(task_type or "").strip()
        if not task_type:
            raise TaskError("task_type must not be empty")

        task_id = "TSK-" + uuid.uuid4().hex[:10]
        now = _now()
        task = SurveyTask(
            task_id=task_id,
            project_id=project.object_id,
            name=task_name,
            task_type=task_type,
            status=TaskStatus.DRAFT,
            created_at=now,
            updated_at=now,
            history=[
                {
                    "event": "created",
                    "from": "",
                    "to": TaskStatus.DRAFT.value,
                    "at": now,
                    "reason": "task created",
                    "actor": str(actor or ""),
                }
            ],
        )
        self._tasks[task_id] = task
        self.registry.register(
            ObjectType.SURVEY_TASK, task_id, task.to_dict(), status=task.status.value
        )
        return task

    def get(self, task_id: str) -> Optional[SurveyTask]:
        return self._tasks.get(str(task_id or ""))

    @_locked
    def restore(self, row: Dict[str, Any]) -> SurveyTask:
        """Rebuild a task from a snapshot, keeping status, version and history."""
        if not isinstance(row, dict):
            raise TaskError("task row must be an object, got %r" % (row,))
        task_id = str(row.get("task_id") or "").strip()
        if not task_id:
            raise TaskError("restored task_id must not be empty")
        if task_id in self._tasks:
            raise TaskError("duplicate task_id: %s" % task_id)
        try:
            status = TaskStatus(row.get("status"))
        except ValueError:
            raise TaskError("unknown task status for %s: %r" % (task_id, row.get("status")))
        runs = row.get("workflow_run_ids") or []
        if not isinstance(runs, list):
            raise TaskError("workflow_run_ids for %s must be a list" % task_id)
        history = row.get("history") or []
        if not isinstance(history, list):
            raise TaskError("history for %s must be a list" % task_id)
        try:
            version = int(row.get("version") or 1)
        except (TypeError, ValueError):
            raise TaskError("version for %s must be an integer" % task_id)
        now = _now()
        task = SurveyTask(
            task_id=task_id,
            project_id=str(row.get("project_id") or ""),
            name=str(row.get("name") or ""),
            task_type=str(row.get("task_type") or ""),
            status=status,
            created_at=str(row.get("created_at") or now),
            updated_at=str(row.get("updated_at") or now),
            version=version,
            workflow_run_ids=[str(run) for run in runs],
            history=[dict(entry) for entry in history],
        )
        self._tasks[task_id] = task
        # The snapshot also holds the registry mirror; refresh it instead of
        # registering twice, so the two records cannot diverge.
        mirror = self.registry.get(task_id)
        if mirror is None:
            self.registry.register(
                ObjectType.SURVEY_TASK, task_id, task.to_dict(), status=task.status.value
            )
        else:
            mirror.status = task.status.value
            mirror.version = task.version
            mirror.payload = task.to_dict()
        return task

    def list(self) -> List[SurveyTask]:
        return list(self._tasks.values())

    def snapshot(self, task_id: str) -> Dict[str, Any]:
        task = self.get(task_id)
        if task is None:
            raise TaskError("unknown task_id: %s" % task_id)
        return task.to_dict()

    def allowed_targets(self, task_id: str) -> List[str]:
        task = self.get(task_id)
        if task is None:
            raise TaskError("unknown task_id: %s" % task_id)
        return sorted(status.value for status in ALLOWED[task.status])

    @_locked
    def transition(
        self,
        task_id: str,
        target: Any,
        reason: str = "",
        actor: str = "",
    ) -> SurveyTask:
        """Move a task to ``target`` if the edge is allowed, else reject."""
        task = self.get(task_id)
        if task is None:
            raise TaskError("unknown task_id: %s" % task_id)
        try:
            wanted = TaskStatus(target)
        except ValueError:
            raise TaskError("unknown target status: %r" % (target,))
        if wanted is task.status:
            raise TaskError("task %s is already %s" % (task.task_id, task.status.value))
        if wanted not in ALLOWED[task.status]:
            allowed = ", ".join(sorted(status.value for status in ALLOWED[task.status]))
            raise TaskError(
                "transition %s -> %s is not allowed; allowed from %s: %s"
                % (task.status.value, wanted.value, task.status.value, allowed or "none")
            )
        if wanted in (TaskStatus.COMPLETED, TaskStatus.CANCELLED) and not str(reason or "").strip():
            raise TaskError("a reason is required to move a task to %s" % wanted.value)

        now = _now()
        task.history.append(
            {
                "event": "transition",
                "from": task.status.value,
                "to": wanted.value,
                "at": now,
                "reason": str(reason or "").strip(),
                "actor": str(actor or ""),
            }
        )
        task.status = wanted
        task.updated_at = now
        task.version += 1
        self._sync(task)
        return task

    @_locked
    def attach_run(self, task_id: str, run_id: str) -> SurveyTask:
        """Record a workflow run against a task. Runs attach while running."""
        task = self.get(task_id)
        if task is None:
            raise TaskError("unknown task_id: %s" % task_id)
        run_id = str(run_id or "").strip()
        if not run_id:
            raise TaskError("run_id must not be empty")
        if task.status is not TaskStatus.RUNNING:
            raise TaskError(
                "a run can only be attached while RUNNING; task is %s" % task.status.value
            )
        if run_id in task.workflow_run_ids:
            # Attaching the same run twice would make the record lie about
            # how many runs a task actually had.
            raise TaskError("run already attached: %s" % run_id)

        now = _now()
        task.workflow_run_ids.append(run_id)
        task.history.append(
            {
                "event": "run_attached",
                "from": task.status.value,
                "to": task.status.value,
                "at": now,
                "reason": "workflow run attached",
                "actor": "",
            }
        )
        task.updated_at = now
        task.version += 1
        self._sync(task)
        return task

    def transition_count(self, task_id: str) -> int:
        task = self.get(task_id)
        if task is None:
            raise TaskError("unknown task_id: %s" % task_id)
        return sum(1 for entry in task.history if entry.get("event") == "transition")

    def _sync(self, task: SurveyTask) -> None:
        obj = self.registry.get(task.task_id)
        if obj is None:
            raise TaskError("task mirror missing from registry: %s" % task.task_id)
        obj.status = task.status.value
        obj.version = task.version
        obj.payload = task.to_dict()
