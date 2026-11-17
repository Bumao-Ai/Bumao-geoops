"""JSON snapshot store for the in-memory domain state.

The scaffold keeps projects, tasks and datasets in memory. This store writes
them to one JSON file and reads them back, so a run survives a restart without
inventing a database.

Two rules matter more than the format:

* a save is atomic — the file is written beside the target and moved into place
  only when complete, so a crash cannot leave a half-written snapshot;
* a restore validates the whole file first (on empty probe objects) and only
  then touches the live registry, so a bad row cannot leave the state half
  restored.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from typing import Any, Dict, Optional

from geoops.domain import DomainRegistry, TaskEngine


FORMAT = "geoops-snapshot"
VERSION = 1


class StoreError(ValueError):
    """Raised when a snapshot cannot be trusted; the live state is untouched."""


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _replace_when_free(temp_path: str, target: str, attempts: int = 60, delay: float = 0.05) -> None:
    """Move the temp file into place, waiting out an open reader.

    On Windows ``os.replace`` fails with WinError 5 while any other handle has
    the target open, so a reader that is mid-load blocks the swap for a moment.
    Retrying is the fix; a file that stays locked is reported, not skipped.
    """
    last_error = None
    for _ in range(max(1, attempts)):
        try:
            os.replace(temp_path, target)
            return
        except PermissionError as exc:  # target is open by a reader
            last_error = exc
            time.sleep(delay)
    raise StoreError("could not replace %s while it is open: %s" % (target, last_error))


def _open_for_read(path: str, attempts: int = 60, delay: float = 0.05):
    """Open the snapshot for reading, waiting out a save swapping the file.

    A reader that hits the swap exactly while ``os.replace`` runs sees WinError
    5 on Windows; the write is brief, so retrying is the fix and a file that
    stays locked is reported rather than guessed at.
    """
    last_error = None
    for _ in range(max(1, attempts)):
        try:
            return open(path, encoding="utf-8")
        except PermissionError as exc:
            last_error = exc
            time.sleep(delay)
    raise StoreError(
        "snapshot stayed locked for %.1fs: %s" % (attempts * delay, last_error)
    )


class SnapshotStore:
    def __init__(self, path: str) -> None:
        path = str(path or "").strip()
        if not path:
            raise StoreError("snapshot path must not be empty")
        self.path = os.path.abspath(path)
        # In-process serialisation: two threads saving at once must queue, not
        # fight over the same temp file (that produced WinError 5 on Windows).
        self._lock = threading.Lock()

    # -- write ------------------------------------------------------------
    def save(self, registry: DomainRegistry, tasks: Optional[TaskEngine] = None) -> Dict[str, Any]:
        payload = {
            "format": FORMAT,
            "version": VERSION,
            "saved_at": _now(),
            "objects": [obj.to_dict() for obj in registry.all()],
            "tasks": [task.to_dict() for task in tasks.list()] if tasks is not None else [],
        }
        directory = os.path.dirname(self.path) or "."
        os.makedirs(directory, exist_ok=True)
        with self._lock:
            handle, temp_path = tempfile.mkstemp(
                prefix=os.path.basename(self.path) + ".", suffix=".tmp", dir=directory
            )
            try:
                with os.fdopen(handle, "w", encoding="utf-8") as stream:
                    json.dump(payload, stream, ensure_ascii=False, indent=2)
                    stream.flush()
                    os.fsync(stream.fileno())
                _replace_when_free(temp_path, self.path)
            except BaseException:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                raise
        return payload

    # -- read -------------------------------------------------------------
    def load(self) -> Dict[str, Any]:
        if not os.path.exists(self.path):
            raise StoreError("snapshot not found: %s" % self.path)
        try:
            handle = _open_for_read(self.path)
            with handle:
                data = json.load(handle)
        except PermissionError as exc:  # kept for a lock that never cleared
            raise StoreError("snapshot is locked by another writer: %s" % exc)
        except json.JSONDecodeError as exc:
            raise StoreError("snapshot is not valid JSON: %s" % exc)
        if not isinstance(data, dict):
            raise StoreError("snapshot must be a JSON object")
        if data.get("format") != FORMAT:
            raise StoreError("not a GeoOps snapshot: format=%r" % data.get("format"))
        version = data.get("version")
        if not isinstance(version, int):
            raise StoreError("snapshot version must be an integer, got %r" % (version,))
        if version < VERSION:
            raise StoreError(
                "snapshot version %d is older than %d; no migration path is implemented"
                % (version, VERSION)
            )
        if version > VERSION:
            raise StoreError(
                "snapshot version %d is newer than %d; it was written by a build this one "
                "does not understand" % (version, VERSION)
            )
        if not isinstance(data.get("objects"), list):
            raise StoreError("snapshot has no objects list")
        if not isinstance(data.get("tasks", []), list):
            raise StoreError("snapshot tasks must be a list")
        return data

    # -- apply ------------------------------------------------------------
    def restore(
        self,
        registry: DomainRegistry,
        tasks: Optional[TaskEngine] = None,
    ) -> Dict[str, int]:
        data = self.load()

        # Probe on empty objects: any bad row aborts before the live state is
        # touched, so a corrupt snapshot cannot be half applied.
        probe_registry = DomainRegistry()
        probe_tasks = TaskEngine(probe_registry) if tasks is not None else None
        try:
            for row in data["objects"]:
                probe_registry.restore(row)
            if probe_tasks is not None:
                for row in data.get("tasks", []):
                    probe_tasks.restore(row)
        except (ValueError, TypeError) as exc:
            raise StoreError("snapshot rejected: %s" % exc)

        clashes = [
            row["object_id"]
            for row in data["objects"]
            if registry.get(row["object_id"]) is not None
        ]
        if clashes:
            raise StoreError("snapshot clashes with live objects: %s" % ", ".join(map(str, clashes)))
        clashing_tasks = [
            row["task_id"]
            for row in data.get("tasks", [])
            if tasks is not None and tasks.get(row["task_id"]) is not None
        ]
        if clashing_tasks:
            raise StoreError("snapshot clashes with live tasks: %s" % ", ".join(map(str, clashing_tasks)))

        for row in data["objects"]:
            registry.restore(row)
        if tasks is not None:
            for row in data.get("tasks", []):
                tasks.restore(row)
        return {"objects": len(data["objects"]), "tasks": len(data.get("tasks", []))}
