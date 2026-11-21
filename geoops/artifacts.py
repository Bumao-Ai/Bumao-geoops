"""Registered deliverables: a row per real file, with a hash that can be re-checked.

A registration is a claim that a specific file existed with specific content at a
specific time. The store never invents a row: a missing file, a symlink, or a
path whose content already changed is refused, and ``verify`` recomputes the
hash so a later edit cannot pass as the registered deliverable.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import time
from typing import Any, Dict, List, Optional

FORMAT = "geoops-artifacts"
VERSION = 1


class ArtifactError(ValueError):
    """Raised when a deliverable cannot be registered or no longer matches."""


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


def _replace_when_free(temp_path: str, target: str, attempts: int = 60, delay: float = 0.05) -> None:
    """Move the temp file into place, waiting out an open reader (Windows)."""
    last_error = None
    for _ in range(max(1, attempts)):
        try:
            os.replace(temp_path, target)
            return
        except PermissionError as exc:
            last_error = exc
            time.sleep(delay)
    raise ArtifactError("could not replace %s while it is open: %s" % (target, last_error))


class ArtifactStore:
    """Index of registered deliverables, optionally persisted as one JSON file."""

    def __init__(
        self,
        root: Optional[str] = None,
        index_path: Optional[str] = None,
        registry: Optional[Any] = None,
    ) -> None:
        self.root = os.path.abspath(root) if root else None
        self._rows: Dict[str, Dict[str, Any]] = {}
        self._by_path: Dict[str, str] = {}
        self._index_path = os.path.abspath(index_path) if index_path else None
        self.registry = registry
        self._lock = threading.RLock()
        if self._index_path and os.path.exists(self._index_path):
            self._load_index(self._index_path)

    # ------------------------------------------------------------------ paths
    def _absolute(self, path: str) -> str:
        path = str(path or "").strip()
        if not path:
            raise ArtifactError("artifact path must not be empty")
        if not os.path.isabs(path):
            if not self.root:
                raise ArtifactError("a relative path needs a store root: %s" % path)
            path = os.path.join(self.root, path)
        return os.path.abspath(path)

    def _stored(self, absolute: str) -> str:
        if self.root:
            try:
                common = os.path.commonpath([self.root, absolute])
            except ValueError:
                common = ""
            if common == self.root:
                return os.path.relpath(absolute, self.root).replace("\\", "/")
        return absolute.replace("\\", "/")

    # ------------------------------------------------------------- register
    def _check_deliverable(self, deliverable_id: str) -> str:
        """Refuse a binding to something that was never registered as a Deliverable."""
        from geoops.domain import ObjectType

        deliverable_id = str(deliverable_id or "").strip()
        if not deliverable_id:
            raise ArtifactError("deliverable_id must not be empty")
        if self.registry is None:
            raise ArtifactError(
                "a deliverable registry is required to bind a file to %s" % deliverable_id
            )
        found = self.registry.get(deliverable_id)
        if found is None:
            raise ArtifactError("deliverable not registered: %s" % deliverable_id)
        object_type = getattr(found, "object_type", None)
        if object_type != ObjectType.DELIVERABLE:
            raise ArtifactError(
                "%s is a %s, not a Deliverable" % (deliverable_id, getattr(object_type, "value", object_type))
            )
        return deliverable_id

    def register(
        self,
        path: str,
        task_id: Optional[str] = None,
        kind: Optional[str] = None,
        label: Optional[str] = None,
        deliverable_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            return self._register(path, task_id, kind, label, deliverable_id)

    def _register(
        self,
        path: str,
        task_id: Optional[str],
        kind: Optional[str],
        label: Optional[str],
        deliverable_id: Optional[str],
    ) -> Dict[str, Any]:
        absolute = self._absolute(path)
        if not os.path.exists(absolute):
            raise ArtifactError("artifact file not found: %s" % path)
        if os.path.islink(absolute):
            raise ArtifactError("refusing to register a symlink: %s" % path)
        if not os.path.isfile(absolute):
            raise ArtifactError("not a regular file: %s" % path)

        digest = _sha256(absolute)
        size = os.path.getsize(absolute)
        stored = self._stored(absolute)
        bound = self._check_deliverable(deliverable_id) if deliverable_id else None

        previous = self._by_path.get(stored)
        if previous is not None:
            row = self._rows[previous]
            if row["sha256"] == digest:
                if bound and row.get("deliverable_id") != bound:
                    raise ArtifactError(
                        "path already registered without binding to %s" % bound
                    )
                return dict(row)
            raise ArtifactError(
                "path already registered with different content: %s (registered %s, now %s)"
                % (stored, previous, digest[:12])
            )

        artifact_id = "ART-%s" % digest[:12]
        if artifact_id in self._rows:
            raise ArtifactError(
                "identical content already registered as %s" % artifact_id
            )
        row = {
            "artifact_id": artifact_id,
            "path": stored,
            "sha256": digest,
            "size": size,
            "registered_at": _now(),
            "task_id": str(task_id) if task_id else None,
            "deliverable_id": bound,
            "kind": str(kind) if kind else "unknown",
            "label": str(label) if label else os.path.basename(absolute),
        }
        self._rows[artifact_id] = row
        self._by_path[stored] = artifact_id
        if self._index_path:
            self.save(self._index_path)
        return dict(row)

    # --------------------------------------------------------------- queries
    def get(self, artifact_id: str) -> Dict[str, Any]:
        with self._lock:
            row = self._rows.get(str(artifact_id))
            if row is None:
                raise ArtifactError("unknown artifact: %s" % artifact_id)
            return dict(row)

    def all(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(row) for row in self._rows.values()]

    def for_task(self, task_id: str) -> List[Dict[str, Any]]:
        task_id = str(task_id or "")
        with self._lock:
            return [dict(row) for row in self._rows.values() if row["task_id"] == task_id]

    def for_deliverable(self, deliverable_id: str) -> List[Dict[str, Any]]:
        deliverable_id = str(deliverable_id or "")
        with self._lock:
            return [
                dict(row)
                for row in self._rows.values()
                if row.get("deliverable_id") == deliverable_id
            ]

    def __len__(self) -> int:
        with self._lock:
            return len(self._rows)

    # ---------------------------------------------------------------- verify
    def verify(self, artifact_id: str) -> Dict[str, Any]:
        with self._lock:
            row = self.get(artifact_id)
            absolute = self._absolute(row["path"])
            if not os.path.exists(absolute):
                raise ArtifactError("artifact file is gone: %s" % row["path"])
            if os.path.islink(absolute):
                raise ArtifactError("artifact is now a symlink: %s" % row["path"])
            if not os.path.isfile(absolute):
                raise ArtifactError("artifact is no longer a regular file: %s" % row["path"])
            if _sha256(absolute) != row["sha256"]:
                raise ArtifactError(
                    "artifact content changed since registration: %s" % row["path"]
                )
            if os.path.getsize(absolute) != row["size"]:
                raise ArtifactError("artifact size changed since registration: %s" % row["path"])
            return row

    def verify_all(self) -> List[Dict[str, Any]]:
        results = []
        for artifact_id in list(self._rows.keys()):
            try:
                self.verify(artifact_id)
                results.append({"artifact_id": artifact_id, "ok": True, "detail": "hash matches"})
            except ArtifactError as exc:
                results.append({"artifact_id": artifact_id, "ok": False, "detail": str(exc)})
        return results

    # ------------------------------------------------------------ persistence
    def save(self, path: Optional[str] = None) -> str:
        target = os.path.abspath(path or self._index_path or "")
        if not target:
            raise ArtifactError("no index path to save to")
        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
        with self._lock:
            payload = {
                "format": FORMAT,
                "version": VERSION,
                "root": self.root,
                "saved_at": _now(),
                "artifacts": self.all(),
            }
            handle, temp_path = tempfile.mkstemp(
                prefix=os.path.basename(target) + ".", suffix=".tmp", dir=os.path.dirname(target)
            )
            try:
                with os.fdopen(handle, "w", encoding="utf-8") as stream:
                    json.dump(payload, stream, ensure_ascii=False, indent=2)
                    stream.flush()
                    os.fsync(stream.fileno())
                _replace_when_free(temp_path, target)
            except BaseException:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                raise
        return target

    def _load_index(self, path: str) -> None:
        try:
            with open(path, encoding="utf-8") as handle:
                payload = json.load(handle)
        except json.JSONDecodeError as exc:
            raise ArtifactError("artifact index is not valid JSON: %s" % exc)
        if not isinstance(payload, dict):
            raise ArtifactError("artifact index must be a JSON object")
        if payload.get("format") != FORMAT:
            raise ArtifactError("not a GeoOps artifact index: format=%r" % payload.get("format"))
        if payload.get("version") != VERSION:
            raise ArtifactError("unsupported artifact index version: %r" % payload.get("version"))
        rows = payload.get("artifacts")
        if not isinstance(rows, list):
            raise ArtifactError("artifact index has no artifacts list")
        if not self.root and payload.get("root"):
            self.root = payload["root"]
        for row in rows:
            if not isinstance(row, dict) or not row.get("artifact_id"):
                raise ArtifactError("artifact entry has no artifact_id")
            for key in ("path", "sha256", "size"):
                if key not in row:
                    raise ArtifactError("artifact %s has no %s" % (row["artifact_id"], key))
            if row["artifact_id"] in self._rows:
                raise ArtifactError("duplicate artifact id: %s" % row["artifact_id"])
            self._rows[row["artifact_id"]] = row
            self._by_path[row["path"]] = row["artifact_id"]
