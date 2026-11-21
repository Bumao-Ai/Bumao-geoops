"""Deliverable registration and archival.

A deliverable is a real file that a task produced. Registration reads the file
and records its sha256 and size, so a later edit is detectable. Final
acceptance is not decided here: ``ReviewEngine`` flips a deliverable to
``accepted`` only on an approving review. Archival is a separate, explicit step
that is allowed only after acceptance.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
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
    def __init__(self, registry: DomainRegistry, archive_dir: str = "") -> None:
        self.registry = registry
        self.archive_dir = os.path.abspath(archive_dir) if str(archive_dir or "").strip() else ""

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

    def _copy_to_archive(
        self, deliverable: DomainObject, source: str, actor: str, note: str
    ) -> Dict[str, Any]:
        """Copy the verified source into an immutable per-deliverable folder."""
        root = self.archive_dir
        target = os.path.join(root, deliverable.object_id)
        if os.path.exists(target):
            raise DeliverableError("archive target already exists: %s" % target)
        try:
            os.makedirs(root, exist_ok=True)
            temp = tempfile.mkdtemp(prefix=deliverable.object_id + "-", dir=root)
        except OSError as exc:
            raise DeliverableError("cannot create archive folder: %s" % exc) from exc
        try:
            files_dir = os.path.join(temp, "files")
            os.makedirs(files_dir)
            name = os.path.basename(source)
            copied = os.path.join(files_dir, name)
            shutil.copyfile(source, copied)
            copied_sha = _sha256(copied)
            registered_sha = str(deliverable.payload.get("sha256") or "")
            if copied_sha != registered_sha:
                raise DeliverableError("archive copy does not match the registered sha256")
            archived_at = _now()
            manifest = {
                "deliverable_id": deliverable.object_id,
                "task_id": deliverable.payload.get("task_id"),
                "project_id": deliverable.payload.get("project_id"),
                "source_path": source.replace("\\", "/"),
                "source_sha256": registered_sha,
                "copied_sha256": copied_sha,
                "size_bytes": os.path.getsize(copied),
                "files": [
                    {
                        "name": name,
                        "path": "files/" + name,
                        "sha256": copied_sha,
                        "size_bytes": os.path.getsize(copied),
                    }
                ],
                "archived_at": archived_at,
                "archived_by": str(actor or "").strip(),
                "archive_note": str(note or "").strip(),
            }
            manifest_path = os.path.join(temp, "manifest.json")
            with open(manifest_path, "w", encoding="utf-8") as handle:
                json.dump(manifest, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, target)
        except Exception:
            shutil.rmtree(temp, ignore_errors=True)
            raise
        return {
            "archive_path": target.replace("\\", "/"),
            "archive_file": os.path.join(target, "files", name).replace("\\", "/"),
            "archive_manifest": os.path.join(target, "manifest.json").replace("\\", "/"),
            "archive_sha256": copied_sha,
            "archive_size_bytes": os.path.getsize(os.path.join(target, "files", name)),
            "archived_at": manifest["archived_at"],
        }

    def verify_archive(self, deliverable_id: str) -> Dict[str, Any]:
        """Re-hash an archived copy and compare it with its manifest."""
        deliverable = self.get(deliverable_id)
        if deliverable is None:
            raise DeliverableError("unknown deliverable_id: %s" % deliverable_id)
        payload = deliverable.payload
        problems: List[str] = []
        files: List[Dict[str, Any]] = []
        manifest_path = str(payload.get("archive_manifest") or "")
        manifest: Dict[str, Any] = {}
        if not manifest_path:
            problems.append("deliverable has no archive manifest")
        elif not os.path.isfile(manifest_path):
            problems.append("archive manifest is missing: %s" % manifest_path)
        else:
            manifest_real = os.path.realpath(manifest_path)
            if self.archive_dir:
                root_real = os.path.realpath(self.archive_dir)
                try:
                    inside = os.path.commonpath([root_real, manifest_real]) == root_real
                except ValueError:
                    inside = False
                if not inside:
                    problems.append("archive manifest is outside the archive directory")
            try:
                with open(manifest_path, encoding="utf-8-sig") as handle:
                    manifest = json.load(handle)
            except (OSError, ValueError) as exc:
                problems.append("cannot read archive manifest: %s" % exc)
            if not isinstance(manifest, dict):
                manifest = {}
                problems.append("archive manifest is not an object")
        if manifest:
            if manifest.get("deliverable_id") != deliverable_id:
                problems.append("manifest deliverable_id does not match")
            registered_sha = str(payload.get("sha256") or "")
            if manifest.get("source_sha256") != registered_sha:
                problems.append("manifest source_sha256 does not match the registry")
            if manifest.get("copied_sha256") != registered_sha:
                problems.append("manifest copied_sha256 does not match the registry")
            for entry in manifest.get("files") or []:
                if not isinstance(entry, dict):
                    problems.append("manifest file entry is not an object")
                    continue
                relative = str(entry.get("path") or "")
                if (
                    not relative
                    or os.path.isabs(relative)
                    or ".." in relative.replace("\\", "/").split("/")
                ):
                    problems.append("unsafe archive file path: %r" % relative)
                    files.append({"path": relative, "ok": False})
                    continue
                target = os.path.join(os.path.dirname(manifest_path), relative)
                if self.archive_dir:
                    root_real = os.path.realpath(self.archive_dir)
                    target_real = os.path.realpath(target)
                    try:
                        inside = os.path.commonpath([root_real, target_real]) == root_real
                    except ValueError:
                        inside = False
                    if not inside:
                        problems.append("archive file resolves outside the archive directory: %s" % relative)
                        files.append({"path": relative, "ok": False})
                        continue
                exists = os.path.isfile(target)
                actual_sha = _sha256(target) if exists else ""
                actual_size = os.path.getsize(target) if exists else 0
                matches = (
                    exists
                    and actual_sha == str(entry.get("sha256") or "")
                    and actual_size == int(entry.get("size_bytes") or -1)
                )
                if not exists:
                    problems.append("archived file is missing: %s" % relative)
                elif not matches:
                    problems.append("archived file does not match the manifest: %s" % relative)
                files.append({
                    "path": relative,
                    "exists": exists,
                    "sha256": actual_sha,
                    "size_bytes": actual_size,
                    "ok": matches,
                })
            if not manifest.get("files"):
                problems.append("manifest lists no archived files")
        return {
            "deliverable_id": deliverable_id,
            "status": deliverable.status,
            "ok": not problems,
            "checked_at": _now(),
            "archive_path": str(payload.get("archive_path") or ""),
            "manifest": manifest_path.replace("\\", "/"),
            "files": files,
            "problems": problems,
        }

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
        source = str(deliverable.payload.get("path") or "").strip()
        if not source or not os.path.isfile(source):
            raise DeliverableError(
                "deliverable file is missing; cannot archive: %s" % (source or deliverable_id)
            )
        if _sha256(source) != str(deliverable.payload.get("sha256") or ""):
            raise DeliverableError(
                "deliverable file changed since registration; re-register before archiving"
            )
        payload = {
            "archived_at": _now(),
            "archived_by": str(actor or "").strip(),
            "archive_note": str(note or "").strip(),
        }
        if self.archive_dir:
            payload.update(self._copy_to_archive(deliverable, source, actor, note))
        return self.registry.update(
            deliverable_id,
            payload=payload,
            status="archived",
        )
