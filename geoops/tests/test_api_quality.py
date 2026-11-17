"""API tests for deliverable registration, quality reports, archive and settings."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from geoops.api import AuditLog, PermissionPolicy, create_server
from geoops.domain import DeliverableRegistry, DomainRegistry, TaskEngine
from geoops.domain.datasets_store import DatasetRegistry
from geoops.domain.projects import ProjectRegistry
from geoops.quality.service import QualityService


class QualityApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.mkdtemp(prefix="geoops-api-quality-")
        self.registry = DomainRegistry()
        ProjectRegistry(self.registry).register(
            "PRJ-API-QA", "QA-API", "接口质检项目", "survey", "哈尔滨", "EPSG:4547", "1985"
        )
        self.tasks = TaskEngine(self.registry)
        self.task = self.tasks.create("PRJ-API-QA", "接口质检任务", "change_detection", actor="test")
        self.datasets = DatasetRegistry(self.registry, ProjectRegistry(self.registry))
        self.quality = QualityService(self.registry, self.datasets)
        self.deliverables = DeliverableRegistry(self.registry)
        self.path = os.path.join(self.tempdir, "mask.asc")
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("ncols 2\nnrows 1\n0 1\n")
        self.policy = PermissionPolicy(
            {
                "admin": [
                    "task:create", "task:transition", "project:write", "dataset:write",
                    "catalog:write", "deliverable:write", "quality:write", "review:write",
                    "audit:read",
                ]
            }
        )
        self.server = create_server(
            self.registry,
            tasks=self.tasks,
            policy=self.policy,
            audit=AuditLog(limit=100),
            deliverables=self.deliverables,
            quality=self.quality,
            extra={"version": "0.1.0", "kernel": "v0.2.2", "tier": "核心工程"},
        )
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def call(self, method, path, body=None, token=None):
        url = "http://127.0.0.1:%d%s" % (self.port, path)
        data = None
        headers = {}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if token:
            headers["X-GeoOps-Token"] = token
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8") or "{}")

    def test_deliverable_and_quality_are_wired(self) -> None:
        status, payload = self.call(
            "POST", "/api/v1/deliverables",
            {"task_id": self.task.task_id, "name": "接口成果", "kind": "mask", "path": self.path},
            token="admin",
        )
        self.assertEqual(status, 201)
        deliverable_id = payload["deliverable"]["object_id"]
        self.assertEqual(len(payload["deliverable"]["payload"]["sha256"]), 64)

        status, payload = self.call(
            "POST", "/api/v1/quality-reports",
            {"target_type": "deliverable", "target_id": deliverable_id, "task_id": self.task.task_id},
            token="admin",
        )
        self.assertEqual(status, 201)
        report = payload["report"]
        self.assertEqual(report["payload"]["status"], "PARTIAL")
        self.assertEqual(report["payload"]["layers"]["professional"]["status"], "PARTIAL")

        status, payload = self.call("GET", "/api/v1/quality-reports?task_id=" + self.task.task_id)
        self.assertEqual(status, 200)
        self.assertEqual(payload["count"], 1)

    def test_archive_is_refused_until_accepted(self) -> None:
        status, payload = self.call(
            "POST", "/api/v1/deliverables",
            {"task_id": self.task.task_id, "name": "待审成果", "path": self.path},
            token="admin",
        )
        self.assertEqual(status, 201)
        deliverable_id = payload["deliverable"]["object_id"]
        status, payload = self.call(
            "POST", "/api/v1/deliverables/%s/archive" % deliverable_id,
            {"actor": "tester"}, token="admin",
        )
        self.assertEqual(status, 400)
        self.assertIn("accepted", payload["error"])

        status, payload = self.call(
            "POST", "/api/v1/reviews",
            {
                "task_id": self.task.task_id, "deliverable_id": deliverable_id,
                "reviewer": "reviewer", "decision": "APPROVE", "opinion": "通过",
            },
            token="admin",
        )
        self.assertEqual(status, 201)
        status, payload = self.call(
            "POST", "/api/v1/deliverables/%s/archive" % deliverable_id,
            {"actor": "tester"}, token="admin",
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["deliverable"]["status"], "archived")

    def test_settings_exposes_role_matrix_and_caller_grants(self) -> None:
        status, payload = self.call("GET", "/api/v1/settings", token="admin")
        self.assertEqual(status, 200)
        self.assertEqual(set(payload["caller"]["permissions"]), {
            "task:create", "task:transition", "project:write", "dataset:write",
            "catalog:write", "deliverable:write", "quality:write", "review:write",
            "audit:read",
        })
        self.assertTrue(payload["policy"]["configured"])
        self.assertIn("quality:write", payload["permissions"])


if __name__ == "__main__":
    unittest.main()
