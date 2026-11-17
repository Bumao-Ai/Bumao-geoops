"""Unit tests for the write endpoints and the permission gate.

Standard library only: run with

    python -m unittest geoops.tests.test_api_write -v
"""

from __future__ import annotations

import json
import threading
import time
import unittest
import urllib.error
import urllib.request

from geoops.api import AuditLog, PermissionPolicy, create_server
from geoops.domain import DomainRegistry, ObjectType, TaskEngine, TaskStatus


class ApiWriteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = DomainRegistry()
        self.registry.register(ObjectType.PROJECT, "PRJ-W-001", {"name": "api test project"})
        self.tasks = TaskEngine(self.registry)
        self.audit = AuditLog(limit=50)
        self.policy = PermissionPolicy(
            {
                "admin-token": ["task:create", "task:transition", "audit:read"],
                "creator-token": ["task:create"],
                "viewer-token": ["audit:read"],
            }
        )
        self.policy.grant(
            "stale-token",
            ["task:create"],
            expires_at=time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 60)
            ),
        )
        self.server = create_server(
            self.registry, tasks=self.tasks, policy=self.policy, audit=self.audit
        )
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def call(self, path, method="GET", token=None, payload=None, raw_body=None):
        url = "http://127.0.0.1:%d%s" % (self.port, path)
        data = None
        if raw_body is not None:
            data = raw_body
        elif payload is not None:
            data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(url, data=data, method=method)
        if token:
            request.add_header("X-GeoOps-Token", token)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def create_task(self, token="admin-token", payload=None):
        body = {"project_id": "PRJ-W-001", "name": "api write task"}
        if payload:
            body.update(payload)
        return self.call("/api/v1/tasks", "POST", token, body)

    def test_missing_token_is_401_and_audited(self) -> None:
        status, body = self.create_task(token=None)
        self.assertEqual(status, 401)
        self.assertIn("token", body["error"])
        self.assertEqual(len(self.tasks.list()), 0)
        self.assertEqual(self.audit.denied(), 1)
        row = self.audit.rows()[0]
        self.assertEqual(row["decision"], "deny")
        self.assertEqual(row["token_fp"], "")

    def test_unknown_token_is_401(self) -> None:
        status, _ = self.create_task(token="not-a-token")
        self.assertEqual(status, 401)
        self.assertEqual(len(self.tasks.list()), 0)

    def test_token_without_permission_is_403(self) -> None:
        status, body = self.create_task(token="creator-token")
        self.assertEqual(status, 201)
        task_id = body["task"]["task_id"]
        status, body = self.call(
            "/api/v1/tasks/%s/transitions" % task_id,
            "POST",
            "creator-token",
            {"target": "READY", "reason": "preconditions listed"},
        )
        self.assertEqual(status, 403)
        self.assertIs(self.tasks.get(task_id).status, TaskStatus.DRAFT)
        self.assertEqual(self.audit.denied(), 1)

    def test_create_with_permission_returns_201(self) -> None:
        status, body = self.create_task()
        self.assertEqual(status, 201)
        task_id = body["task"]["task_id"]
        self.assertIs(self.tasks.get(task_id).status, TaskStatus.DRAFT)
        self.assertEqual(body["task"]["project_id"], "PRJ-W-001")

    def test_illegal_transition_is_400_and_leaves_task_untouched(self) -> None:
        _, created = self.create_task()
        task_id = created["task"]["task_id"]
        status, _ = self.call(
            "/api/v1/tasks/%s/transitions" % task_id,
            "POST",
            "admin-token",
            {"target": "COMPLETED", "reason": "skip"},
        )
        self.assertEqual(status, 400)
        self.assertIs(self.tasks.get(task_id).status, TaskStatus.DRAFT)

    def test_completion_without_reason_is_400(self) -> None:
        _, created = self.create_task()
        task_id = created["task"]["task_id"]
        for target in ("READY", "RUNNING"):
            status, _ = self.call(
                "/api/v1/tasks/%s/transitions" % task_id,
                "POST",
                "admin-token",
                {"target": target, "reason": "step"},
            )
            self.assertEqual(status, 200)
        status, _ = self.call(
            "/api/v1/tasks/%s/transitions" % task_id,
            "POST",
            "admin-token",
            {"target": "COMPLETED", "reason": ""},
        )
        self.assertEqual(status, 400)
        self.assertIs(self.tasks.get(task_id).status, TaskStatus.RUNNING)

    def test_full_path_over_http(self) -> None:
        _, created = self.create_task()
        task_id = created["task"]["task_id"]
        for target, reason in (
            ("READY", "preconditions listed"),
            ("RUNNING", "started"),
            ("COMPLETED", "archived"),
        ):
            status, body = self.call(
                "/api/v1/tasks/%s/transitions" % task_id,
                "POST",
                "admin-token",
                {"target": target, "reason": reason},
            )
            self.assertEqual(status, 200)
        self.assertIs(self.tasks.get(task_id).status, TaskStatus.COMPLETED)
        self.assertEqual(self.tasks.transition_count(task_id), 3)

    def test_invalid_json_and_oversized_body(self) -> None:
        status, _ = self.call("/api/v1/tasks", "POST", "admin-token", raw_body=b"{nope")
        self.assertEqual(status, 400)
        big = json.dumps({"project_id": "PRJ-W-001", "name": "x" * (70 * 1024)}).encode("utf-8")
        status, _ = self.call("/api/v1/tasks", "POST", "admin-token", raw_body=big)
        self.assertEqual(status, 413)

    def test_audit_endpoint_requires_permission(self) -> None:
        status, _ = self.call("/api/v1/audit")
        self.assertEqual(status, 401)
        status, body = self.call("/api/v1/audit", token="viewer-token")
        self.assertEqual(status, 200)
        self.assertEqual(body["count"], len(body["rows"]))

    def test_expired_token_is_401_and_audited(self) -> None:
        status, body = self.call(
            "/api/v1/tasks", method="POST", token="stale-token",
            payload={"project_id": "PRJ-W-001", "name": "stale"},
        )
        self.assertEqual(status, 401)
        self.assertEqual(body["error"], "token expired")
        last = self.audit.rows()[-1]
        self.assertEqual(last["decision"], "deny")
        self.assertEqual(last["reason"], "token expired")

    def test_unknown_write_path_is_404(self) -> None:
        status, _ = self.call("/api/v1/nothing", "POST", "admin-token", {"x": 1})
        self.assertEqual(status, 404)

    def test_unknown_write_path_answers_every_time(self) -> None:
        # A 404 that only arrives sometimes means the server closed with the
        # request body still queued; the client then sees a reset, not the code.
        for _ in range(20):
            status, _ = self.call("/api/v1/nothing", "POST", "admin-token", {"x": 1})
            self.assertEqual(status, 404)

    def test_write_disabled_server_refuses_post(self) -> None:
        bare = create_server(DomainRegistry(), tasks=TaskEngine(DomainRegistry()))
        port = bare.server_address[1]
        thread = threading.Thread(target=bare.serve_forever, daemon=True)
        thread.start()
        try:
            url = "http://127.0.0.1:%d/api/v1/tasks" % port
            request = urllib.request.Request(
                url, data=json.dumps({"project_id": "x", "name": "y"}).encode(), method="POST"
            )
            request.add_header("Content-Type", "application/json")
            try:
                with urllib.request.urlopen(request, timeout=5) as response:
                    status = response.status
            except urllib.error.HTTPError as exc:
                status = exc.code
            self.assertEqual(status, 404)
        finally:
            bare.shutdown()
            bare.server_close()


if __name__ == "__main__":
    unittest.main()
