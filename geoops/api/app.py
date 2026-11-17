"""Minimal HTTP API over the domain registry.

Read endpoints:

    GET /api/v1/health
    GET /api/v1/overview           counts only; no records, no paths
    GET /api/v1/objects/<object_id>
    GET /api/v1/tasks              (when a task engine is supplied)
    GET /api/v1/runs               workflow runs from the journal (when supplied)
    GET /api/v1/projects           registered projects
    GET /api/v1/datasets           registered datasets (optional ?project_id=)
    GET /api/v1/datasets/<id>/validate
    GET /api/v1/catalog            models, agents and tools
    GET /api/v1/deliverables       registered deliverables (optional ?task_id=)
    GET /api/v1/quality-reports    quality reports (optional ?task_id=)
    GET /api/v1/settings           roles, permission matrix and caller grants
    GET /api/v1/deliverables       registered deliverables (optional ?task_id=)
    GET /api/v1/quality-reports    quality reports (optional ?task_id= / ?target_id=)
    GET /api/v1/settings           permission matrix, storage and kernel identity
    GET /api/v1/reviews            review records (optional ?task_id=)
    GET /api/v1/tasks/<id>/trace   structured trace from task to sources
    GET /api/v1/rules              rule pack metadata, from the pack files
    GET /api/v1/artifacts          (token with audit:read; when a store is supplied)
    GET /api/v1/audit              (when a permission policy is supplied)
    GET /ui/                       the HTML console (static files in geoops/web)

Write endpoints (only when a permission policy is supplied):

    POST /api/v1/tasks
    POST /api/v1/tasks/<task_id>/transitions
    POST /api/v1/projects          (project:write)
    POST /api/v1/datasets          (dataset:write)
    POST /api/v1/catalog           (catalog:write)
    POST /api/v1/deliverables      (deliverable:write)
    POST /api/v1/quality-reports   (quality:write)
    POST /api/v1/reviews           (review:write)
    POST /api/v1/deliverables/<id>/archive (deliverable:write, accepted only)

Writes are refused before the body is read when the caller is not authorised:
an unknown or missing token returns 401, a token without the required
permission returns 403, and both are written to the audit trail. The API has no
built-in accounts; the caller supplies the grants.
"""

from __future__ import annotations

import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, unquote, urlparse

from geoops.api.security import PERMISSIONS, AuditLog, PermissionPolicy
from geoops.catalog import Catalog, CatalogError
from geoops.domain.datasets_store import DatasetError, DatasetRegistry
from geoops.domain.deliverables import DeliverableError, DeliverableRegistry
from geoops.domain.projects import ProjectError, ProjectRegistry
from geoops.quality.service import QualityError, QualityService
from geoops.review import ReviewEngine, ReviewError
from geoops.trace import build_trace

MAX_BODY_BYTES = 64 * 1024
TRANSITION_PATH = re.compile(r"^/api/v1/tasks/([^/]+)/transitions$")
TRACE_PATH = re.compile(r"^/api/v1/tasks/([^/]+)/trace$")
DATASET_VALIDATE_PATH = re.compile(r"^/api/v1/datasets/([^/]+)/validate$")
DELIVERABLE_ARCHIVE_PATH = re.compile(r"^/api/v1/deliverables/([^/]+)/archive$")

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
PACK_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "survey", "packs")
UI_FILES = {
    "/ui/": "index.html",
    "/ui/index.html": "index.html",
    "/ui/ui.css": "ui.css",
    "/ui/ui.js": "ui.js",
}
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
}


def _pack_files() -> list:
    """Read the pack headers that are really on disk; a broken file is skipped."""
    packs = []
    if not os.path.isdir(PACK_DIR):
        return packs
    for name in sorted(os.listdir(PACK_DIR)):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(PACK_DIR, name), encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue
        rules = data.get("rules") if isinstance(data, dict) else None
        if not isinstance(rules, list):
            continue
        packs.append(
            {
                "pack_id": str(data.get("pack_id") or name[:-5]),
                "version": str(data.get("version") or ""),
                "rule_count": len(rules),
                "task_types": sorted(
                    {str(row.get("task_type")) for row in rules if isinstance(row, dict) and row.get("task_type")}
                ),
                "rules": [row for row in rules if isinstance(row, dict)],
            }
        )
    return packs



def create_server(
    registry: Any,
    extra: Optional[Dict[str, Any]] = None,
    tasks: Optional[Any] = None,
    policy: Optional[PermissionPolicy] = None,
    audit: Optional[AuditLog] = None,
    rules: Optional[Any] = None,
    artifacts: Optional[Any] = None,
    runs: Optional[Any] = None,
    projects: Optional[Any] = None,
    datasets: Optional[Any] = None,
    catalog: Optional[Any] = None,
    deliverables: Optional[Any] = None,
    quality: Optional[Any] = None,
    reviews: Optional[Any] = None,
    host: str = "127.0.0.1",
    port: int = 0,
) -> ThreadingHTTPServer:
    extra_data = dict(extra or {})
    audit_log = audit if audit is not None else AuditLog()
    writes_enabled = policy is not None and tasks is not None
    project_registry = projects if projects is not None else ProjectRegistry(registry)
    dataset_registry = (
        datasets if datasets is not None else DatasetRegistry(registry, project_registry)
    )
    catalog_registry = catalog if catalog is not None else Catalog(registry)
    deliverable_registry = (
        deliverables if deliverables is not None else DeliverableRegistry(registry)
    )
    quality_service = (
        quality if quality is not None else QualityService(registry, dataset_registry)
    )
    review_engine = reviews if reviews is not None else ReviewEngine(registry)

    class Handler(BaseHTTPRequestHandler):
        # -- read ---------------------------------------------------------
        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/api/v1/health":
                self._json(
                    200,
                    {
                        "status": "ok",
                        "objects": len(registry),
                        "writes": "enabled" if writes_enabled else "disabled",
                        "context": extra_data,
                    },
                )
                return
            if path == "/api/v1/tasks":
                if tasks is None:
                    self._json(404, {"error": "task endpoint not configured"})
                    return
                rows = []
                for task in tasks.list():
                    row = task.to_dict()
                    try:
                        row["allowed_targets"] = tasks.allowed_targets(task.task_id)
                    except ValueError:
                        row["allowed_targets"] = []
                    rows.append(row)
                self._json(200, {"count": len(rows), "tasks": rows})
                return
            if path == "/api/v1/overview":
                task_rows = [task.to_dict() for task in tasks.list()] if tasks is not None else []
                by_status: Dict[str, int] = {}
                for row in task_rows:
                    key = str(row.get("status") or "")
                    by_status[key] = by_status.get(key, 0) + 1
                packs = _pack_files()
                engine_rows = [rule.to_dict() for rule in rules.rules()] if rules is not None else []
                rule_count = len(engine_rows) if engine_rows else sum(pack["rule_count"] for pack in packs)
                self._json(
                    200,
                    {
                        "objects": len(registry),
                        "tasks": {"total": len(task_rows), "by_status": by_status},
                        "projects": len(project_registry.list()),
                        "datasets": len(dataset_registry.list()),
                        "deliverables": len(deliverable_registry.list()),
                        "quality_reports": len(quality_service.list()),
                        "reviews": len(review_engine.list()),
                        "rules": {"packs": len(packs), "rules": rule_count},
                        "artifacts": {
                            "configured": artifacts is not None,
                            "count": len(artifacts) if artifacts is not None else 0,
                        },
                        "context": extra_data,
                    },
                )
                return
            if path == "/api/v1/rules":
                packs = _pack_files()
                engine_rows = [rule.to_dict() for rule in rules.rules()] if rules is not None else []
                if not engine_rows:
                    engine_rows = [row for pack in packs for row in pack["rules"]]
                self._json(
                    200,
                    {
                        "count": len(engine_rows),
                        "packs": [{key: pack[key] for key in ("pack_id", "version", "rule_count", "task_types")} for pack in packs],
                        "rules": engine_rows,
                    },
                )
                return
            if path == "/api/v1/runs":
                if runs is None:
                    self._json(404, {"error": "run journal not configured"})
                    return
                rows = runs.rows()
                self._json(
                    200,
                    {
                        "count": len(rows),
                        "by_status": runs.by_status(),
                        "runs": rows,
                    },
                )
                return
            if path == "/api/v1/projects":
                rows = [row.to_dict() for row in project_registry.list()]
                self._json(200, {"count": len(rows), "projects": rows})
                return
            if path == "/api/v1/datasets":
                project_id = parse_qs(urlparse(self.path).query).get("project_id", [""])[0]
                rows = [row.to_dict() for row in dataset_registry.list(project_id)]
                self._json(200, {"count": len(rows), "datasets": rows})
                return
            match = DATASET_VALIDATE_PATH.match(path)
            if match:
                dataset_id = unquote(match.group(1))
                try:
                    result = dataset_registry.validate(dataset_id)
                except DatasetError as exc:
                    self._json(404, {"error": str(exc)})
                    return
                self._json(200, result)
                return
            if path == "/api/v1/catalog":
                self._json(
                    200,
                    {
                        "models": [row.to_dict() for row in catalog_registry.list("Model")],
                        "tools": [row.to_dict() for row in catalog_registry.list("Tool")],
                        "agents": [row.to_dict() for row in catalog_registry.list("Agent")],
                    },
                )
                return
            if path == "/api/v1/deliverables":
                task_id = parse_qs(urlparse(self.path).query).get("task_id", [""])[0]
                rows = [row.to_dict() for row in deliverable_registry.list(task_id)]
                self._json(200, {"count": len(rows), "deliverables": rows})
                return
            if path == "/api/v1/quality-reports":
                task_id = parse_qs(urlparse(self.path).query).get("task_id", [""])[0]
                rows = [row.to_dict() for row in quality_service.list(task_id)]
                self._json(200, {"count": len(rows), "reports": rows})
                return
            if path == "/api/v1/settings":
                token_perms = policy.permissions(self._token()) if policy is not None else []
                self._json(
                    200,
                    {
                        "context": extra_data,
                        "roles": [
                            {"role": "系统管理员", "permissions": list(PERMISSIONS)},
                            {"role": "项目负责人", "permissions": ["project:write", "task:create", "task:transition", "dataset:write", "catalog:write", "deliverable:write", "quality:write", "review:write", "audit:read"]},
                            {"role": "作业人员", "permissions": ["task:create", "task:transition", "dataset:write", "deliverable:write", "quality:write"]},
                            {"role": "审核人员", "permissions": ["review:write", "quality:write", "audit:read"]},
                            {"role": "只读", "permissions": []},
                        ],
                        "permissions": list(PERMISSIONS),
                        "policy": {
                            "configured": policy is not None,
                            "grants": len(policy) if policy is not None else 0,
                        },
                        "caller": {
                            "token_present": bool(self._token()),
                            "permissions": token_perms,
                        },
                        "storage": {
                            "registry": "process-memory (snapshot optional)",
                            "runs": "configured" if runs is not None else "not configured",
                            "artifacts": "configured" if artifacts is not None else "not configured",
                            "quality_reports": "configured" if quality_service.report_dir else "object-only",
                        },
                    },
                )
                return
            if path == "/api/v1/reviews":
                task_id = parse_qs(urlparse(self.path).query).get("task_id", [""])[0]
                rows = [row.to_dict() for row in review_engine.list(task_id=task_id)]
                self._json(200, {"count": len(rows), "reviews": rows})
                return
            match = TRACE_PATH.match(path)
            if match:
                task_id = unquote(match.group(1))
                try:
                    trace = build_trace(
                        registry, task_id, journal=runs, artifacts=artifacts, reviews=review_engine
                    )
                except ValueError as exc:
                    self._json(404, {"error": str(exc)})
                    return
                self._json(200, trace)
                return
            if path == "/api/v1/artifacts":
                if artifacts is None or policy is None:
                    self._json(404, {"error": "artifact endpoint not configured"})
                    return
                if not self._authorize("audit:read", path):
                    return
                rows = artifacts.all()
                self._json(200, {"count": len(rows), "artifacts": rows})
                return
            if path in UI_FILES:
                self._serve_ui(UI_FILES[path])
                return
            if path == "/api/v1/audit":
                if policy is None:
                    self._json(404, {"error": "audit endpoint not configured"})
                    return
                if not self._authorize("audit:read", path):
                    return
                self._json(200, {"count": len(audit_log.rows()), "rows": audit_log.rows()})
                return
            prefix = "/api/v1/objects/"
            if path.startswith(prefix):
                object_id = unquote(path[len(prefix):])
                obj = registry.get(object_id)
                if obj is None:
                    self._json(404, {"error": "object not found", "object_id": object_id})
                else:
                    self._json(200, obj.to_dict())
                return
            self._json(404, {"error": "unknown endpoint", "path": path})

        # -- write --------------------------------------------------------
        def do_POST(self):
            path = urlparse(self.path).path
            if not writes_enabled:
                self._json(404, {"error": "write endpoints not configured"})
                self._drain_body()
                return
            if path == "/api/v1/tasks":
                if not self._authorize("task:create", path):
                    return
                payload = self._read_json()
                if payload is None:
                    return
                project_id = str(payload.get("project_id") or "").strip()
                name = str(payload.get("name") or "").strip()
                task_type = str(payload.get("task_type") or "land_use_classification")
                try:
                    task = tasks.create(
                        project_id, name, task_type, actor=str(payload.get("actor") or "")
                    )
                except ValueError as exc:
                    self._deny(400, str(exc), path)
                    return
                audit_log.record("POST", path, self._token(), "allow", "task created", 201)
                self._json(201, {"task": task.to_dict()})
                return

            if path == "/api/v1/projects":
                if not self._authorize("project:write", path):
                    return
                payload = self._read_json()
                if payload is None:
                    return
                try:
                    project = project_registry.register(
                        project_id=str(payload.get("project_id") or ""),
                        project_code=str(payload.get("project_code") or ""),
                        name=str(payload.get("name") or ""),
                        project_type=str(payload.get("project_type") or ""),
                        area=str(payload.get("area") or ""),
                        crs=str(payload.get("crs") or ""),
                        vertical_datum=str(payload.get("vertical_datum") or ""),
                        description=payload.get("description"),
                        client=payload.get("client"),
                        contact=payload.get("contact"),
                        created_by=payload.get("created_by"),
                    )
                except (ProjectError, ValueError) as exc:
                    self._deny(400, str(exc), path)
                    return
                audit_log.record("POST", path, self._token(), "allow", "project registered", 201)
                self._json(201, {"project": project.to_dict()})
                return

            if path == "/api/v1/datasets":
                if not self._authorize("dataset:write", path):
                    return
                payload = self._read_json()
                if payload is None:
                    return
                try:
                    dataset = dataset_registry.register(
                        project_id=str(payload.get("project_id") or ""),
                        path=str(payload.get("path") or ""),
                        label=str(payload.get("label") or ""),
                        task_id=str(payload.get("task_id") or ""),
                    )
                except (DatasetError, ValueError) as exc:
                    self._deny(400, str(exc), path)
                    return
                audit_log.record("POST", path, self._token(), "allow", "dataset registered", 201)
                self._json(201, {"dataset": dataset.to_dict()})
                return

            if path == "/api/v1/catalog":
                if not self._authorize("catalog:write", path):
                    return
                payload = self._read_json()
                if payload is None:
                    return
                kind = str(payload.get("kind") or "").strip()
                try:
                    if kind == "Model":
                        obj = catalog_registry.register_model(
                            model_id=str(payload.get("id") or ""),
                            name=str(payload.get("name") or ""),
                            version=str(payload.get("version") or ""),
                            kind=str(payload.get("model_kind") or ""),
                            capability=str(payload.get("capability") or ""),
                            adapter=str(payload.get("adapter") or ""),
                            available=bool(payload.get("available")),
                        )
                    elif kind == "Tool":
                        obj = catalog_registry.register_tool(
                            tool_id=str(payload.get("id") or ""),
                            name=str(payload.get("name") or ""),
                            version=str(payload.get("version") or ""),
                            category=str(payload.get("category") or ""),
                            adapter=str(payload.get("adapter") or ""),
                            available=bool(payload.get("available")),
                            timeout_s=payload.get("timeout_s"),
                            error_handling=str(payload.get("error_handling") or ""),
                        )
                    elif kind == "Agent":
                        obj = catalog_registry.register_agent(
                            agent_id=str(payload.get("id") or ""),
                            name=str(payload.get("name") or ""),
                            version=str(payload.get("version") or ""),
                            strategy=str(payload.get("strategy") or ""),
                            model_ids=[str(x) for x in (payload.get("model_ids") or [])],
                            tool_ids=[str(x) for x in (payload.get("tool_ids") or [])],
                            description=str(payload.get("description") or ""),
                        )
                    else:
                        raise CatalogError("kind must be Model, Tool or Agent")
                except (CatalogError, ValueError, TypeError) as exc:
                    self._deny(400, str(exc), path)
                    return
                audit_log.record("POST", path, self._token(), "allow", "catalog registered", 201)
                self._json(201, {"object": obj.to_dict()})
                return

            if path == "/api/v1/deliverables":
                if not self._authorize("deliverable:write", path):
                    return
                payload = self._read_json()
                if payload is None:
                    return
                try:
                    deliverable = deliverable_registry.register(
                        task_id=str(payload.get("task_id") or ""),
                        name=str(payload.get("name") or ""),
                        path=str(payload.get("path") or ""),
                        kind=str(payload.get("kind") or ""),
                        notes=str(payload.get("notes") or ""),
                        deliverable_id=str(payload.get("deliverable_id") or ""),
                        version=payload.get("version") or 1,
                    )
                except (DeliverableError, ValueError, TypeError) as exc:
                    self._deny(400, str(exc), path)
                    return
                audit_log.record("POST", path, self._token(), "allow", "deliverable registered", 201)
                self._json(201, {"deliverable": deliverable.to_dict()})
                return

            if path == "/api/v1/quality-reports":
                if not self._authorize("quality:write", path):
                    return
                payload = self._read_json()
                if payload is None:
                    return
                try:
                    report = quality_service.evaluate(
                        target_type=str(payload.get("target_type") or ""),
                        target_id=str(payload.get("target_id") or ""),
                        task_id=str(payload.get("task_id") or ""),
                        professional_sample=bool(payload.get("professional_sample")),
                        sample_note=str(payload.get("sample_note") or ""),
                        actor=str(payload.get("actor") or ""),
                    )
                except (QualityError, ValueError) as exc:
                    self._deny(400, str(exc), path)
                    return
                audit_log.record("POST", path, self._token(), "allow", "quality report generated", 201)
                self._json(201, {"report": report.to_dict()})
                return

            match = DELIVERABLE_ARCHIVE_PATH.match(path)
            if match:
                if not self._authorize("deliverable:write", path):
                    return
                deliverable_id = unquote(match.group(1))
                payload = self._read_json()
                if payload is None:
                    return
                try:
                    deliverable = deliverable_registry.archive(
                        deliverable_id,
                        actor=str(payload.get("actor") or ""),
                        note=str(payload.get("note") or ""),
                    )
                except (DeliverableError, ValueError) as exc:
                    self._deny(400, str(exc), path)
                    return
                audit_log.record("POST", path, self._token(), "allow", "deliverable archived", 200)
                self._json(200, {"deliverable": deliverable.to_dict()})
                return

            if path == "/api/v1/reviews":
                if not self._authorize("review:write", path):
                    return
                payload = self._read_json()
                if payload is None:
                    return
                try:
                    review = review_engine.submit(
                        task_id=str(payload.get("task_id") or ""),
                        deliverable_id=str(payload.get("deliverable_id") or ""),
                        reviewer=str(payload.get("reviewer") or ""),
                        decision=str(payload.get("decision") or ""),
                        opinion=str(payload.get("opinion") or ""),
                    )
                except (ReviewError, ValueError) as exc:
                    self._deny(400, str(exc), path)
                    return
                audit_log.record("POST", path, self._token(), "allow", "review recorded", 201)
                self._json(201, {"review": review.to_dict()})
                return

            match = TRANSITION_PATH.match(path)
            if match:
                if not self._authorize("task:transition", path):
                    return
                task_id = unquote(match.group(1))
                payload = self._read_json()
                if payload is None:
                    return
                target = str(payload.get("target") or "").strip()
                if not target:
                    self._deny(400, "target is required", path)
                    return
                try:
                    task = tasks.transition(
                        task_id,
                        target,
                        reason=str(payload.get("reason") or ""),
                        actor=str(payload.get("actor") or ""),
                    )
                except ValueError as exc:
                    self._deny(400, str(exc), path)
                    return
                audit_log.record(
                    "POST", path, self._token(), "allow", "task transitioned", 200
                )
                self._json(200, {"task": task.to_dict()})
                return

            self._json(404, {"error": "unknown endpoint", "path": path})
            # A POST to an unknown path still has a body queued; closing it
            # unread makes the kernel send RST and the client loses the 404.
            self._drain_body()

        # -- helpers ------------------------------------------------------
        def _token(self) -> str:
            header = self.headers.get("X-GeoOps-Token") or ""
            if header.strip():
                return header.strip()
            auth = self.headers.get("Authorization") or ""
            if auth.lower().startswith("bearer "):
                return auth[7:].strip()
            return ""

        def _authorize(self, permission: str, path: str) -> bool:
            token = self._token()
            if not token:
                self._deny(401, "missing token", path)
                return False
            allowed, reason = policy.check(token, permission)
            if allowed:
                return True
            status = 401 if reason in ("unknown token", "token expired") else 403
            self._deny(status, reason, path)
            return False

        def _deny(self, status: int, reason: str, path: str):
            audit_log.record("POST" if self.command == "POST" else "GET", path,
                             self._token(), "deny", reason, status)
            self._json(status, {"error": reason})
            self._drain_body()

        def _drain_body(self, cap: int = 1 << 20):
            """Consume a refused request body before closing.

            A refusal can be decided without reading the body. Closing with bytes
            still queued makes the kernel send RST, and on Windows the client then
            loses the 401/403/413 it was owed. Draining a bounded amount keeps the
            response readable; an oversized remainder is simply closed.
            """
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except (TypeError, ValueError):
                return
            remaining = min(max(length, 0), cap)
            while remaining > 0:
                chunk = self.rfile.read(min(remaining, 8192))
                if not chunk:
                    break
                remaining -= len(chunk)

        def _read_json(self) -> Optional[Dict[str, Any]]:
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except (TypeError, ValueError):
                self._deny(400, "invalid Content-Length", urlparse(self.path).path)
                return None
            if length <= 0:
                self._deny(400, "empty body", urlparse(self.path).path)
                return None
            if length > MAX_BODY_BYTES:
                self._deny(413, "body larger than %d bytes" % MAX_BODY_BYTES,
                           urlparse(self.path).path)
                return None
            raw = self.rfile.read(length)
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._deny(400, "body is not valid JSON", urlparse(self.path).path)
                return None
            if not isinstance(payload, dict):
                self._deny(400, "body must be a JSON object", urlparse(self.path).path)
                return None
            return payload

        def _json(self, code: int, payload: Dict[str, Any]):
            body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _serve_ui(self, name: str):
            """Serve one of the whitelisted console files; nothing else."""
            path = os.path.join(WEB_DIR, name)
            if not os.path.isfile(path):
                self._json(404, {"error": "ui file not found", "file": name})
                return
            with open(path, "rb") as handle:
                body = handle.read()
            self.send_response(200)
            self.send_header("Content-Type", CONTENT_TYPES.get(os.path.splitext(name)[1], "text/plain"))
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            return

    return ThreadingHTTPServer((host, port), Handler)
