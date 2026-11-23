"""Append-only journal of workflow runs.

The workflow engine keeps runs in memory for the life of the process. This
journal gives a console something real to read after the fact: each run is
written as one JSON line with its nodes, and the file is reloaded on start.

Discipline:

* a line is written only after the run finished, and it is ``fsync``-ed before
  the call returns;
* a duplicate ``run_id`` is refused instead of overwriting an earlier record;
* a corrupt or truncated line makes the whole file fail to load. Dropping the
  bad row would leave a history that silently disagrees with what happened.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


class JournalError(ValueError):
    """The journal refused to record or load a row."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class RunJournal:
    """In-memory run list, optionally backed by one JSONL file."""

    def __init__(self, path: Optional[str] = None) -> None:
        self._path = os.path.abspath(path) if path else None
        self._rows: List[Dict[str, Any]] = []
        self._lock = threading.RLock()
        if self._path and os.path.exists(self._path):
            self._load()

    # ---------------------------------------------------------------- write
    def record(
        self,
        run: Any,
        task_id: str = "",
        project_id: str = "",
        actor: str = "",
        workflow_id: str = "",
    ) -> Dict[str, Any]:
        """Append one finished run; returns the row that was written."""
        if not hasattr(run, "to_dict"):
            raise JournalError("only a workflow run can be recorded")
        row = dict(run.to_dict())
        run_id = str(row.get("run_id") or "").strip()
        if not run_id:
            raise JournalError("run_id must not be empty")
        if not isinstance(row.get("node_runs"), list):
            raise JournalError("run %s has no node_runs list" % run_id)
        row.update(
            {
                "task_id": str(task_id or ""),
                "project_id": str(project_id or ""),
                "actor": str(actor or ""),
                "workflow_id": str(workflow_id or ""),
                "recorded_at": _utc_now(),
            }
        )
        with self._lock:
            if any(existing.get("run_id") == run_id for existing in self._rows):
                raise JournalError("duplicate run_id: %s" % run_id)
            if self._path:
                self._append(row)
            self._rows.append(row)
        return row

    def _append(self, row: Dict[str, Any]) -> None:
        marker = (json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        directory = os.path.dirname(self._path) or "."
        if not os.path.isdir(directory):
            raise JournalError("journal directory does not exist: %s" % directory)
        handle = os.open(self._path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o644)
        try:
            os.write(handle, marker)
            os.fsync(handle)
        finally:
            os.close(handle)

    # ----------------------------------------------------------------- read
    def rows(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        with self._lock:
            rows = [dict(row) for row in self._rows]
        if limit is not None and limit > 0:
            rows = rows[-limit:]
        return rows

    def by_status(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for row in self.rows():
            key = str(row.get("status") or "")
            counts[key] = counts.get(key, 0) + 1
        return counts

    def __len__(self) -> int:
        with self._lock:
            return len(self._rows)

    def _load(self) -> None:
        try:
            with open(self._path, encoding="utf-8") as handle:
                text = handle.read()
        except OSError as exc:
            raise JournalError("cannot read journal %s: %s" % (self._path, exc)) from exc
        seen: List[str] = []
        for number, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise JournalError(
                    "journal line %d is not valid JSON; refusing to drop rows" % number
                ) from exc
            if not isinstance(row, dict) or not row.get("run_id"):
                raise JournalError("journal line %d has no run_id" % number)
            run_id = str(row["run_id"])
            if run_id in seen:
                raise JournalError("journal line %d repeats run_id %s" % (number, run_id))
            seen.append(run_id)
            self._rows.append(row)
