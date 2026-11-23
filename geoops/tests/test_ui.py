"""Tests for the HTML console and the read endpoints it uses.

Standard library only: run with

    python -m unittest geoops.tests.test_ui -v
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from geoops.api import AuditLog, PermissionPolicy, create_server
from geoops.artifacts import ArtifactStore
from geoops.domain import DomainRegistry, ObjectType, TaskEngine
from geoops.survey import SurveyRuleEngine
from geoops.workflow import Node, NodeResult, NodeStatus, RunJournal, WorkflowEngine

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PACK_DIR = os.path.join(PROJECT_ROOT, "geoops", "survey", "packs")
WEB_DIR = os.path.join(PROJECT_ROOT, "geoops", "web")


class ConsoleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rules = SurveyRuleEngine()
        for name in sorted(os.listdir(PACK_DIR)):
            if name.endswith(".json"):
                cls.rules.load_pack(os.path.join(PACK_DIR, name))

    def setUp(self) -> None:
        self.tempdir = tempfile.mkdtemp(prefix="geoops-ui-")
        self.registry = DomainRegistry()
        self.registry.register(ObjectType.PROJECT, "PRJ-UI-001", {"name": "控制台项目"})
        self.tasks = TaskEngine(self.registry)
        first = self.tasks.create("PRJ-UI-001", "变化检测任务", "change_detection", actor="ui")
        self.task_id = first.task_id
        self.tasks.transition(first.task_id, "READY", reason="两期就位", actor="ui")
        self.artifacts = ArtifactStore(root=self.tempdir, registry=self.registry)
        self.deliverable = self.registry.register(
            ObjectType.DELIVERABLE, "DLV-UI-001", {"name": "控制台成果"}
        )
        self.file_path = os.path.join(self.tempdir, "mask.asc")
        with open(self.file_path, "w", encoding="utf-8") as handle:
            handle.write("ncols 2\nnrows 1\nxllcorner 0\nyllcorner 0\ncellsize 1\n1 0\n")
        self.row = self.artifacts.register(
            self.file_path, task_id=first.task_id, kind="change_mask", deliverable_id="DLV-UI-001"
        )
        self.audit = AuditLog(limit=100)
        self.policy = PermissionPolicy({"admin-token": ["audit:read", "task:create"]})
        self.runs = RunJournal()
        engine = WorkflowEngine()
        self.run = engine.start(
            [Node("R1", "规则门", lambda ctx: NodeResult(NodeStatus.PASS, "checked=1"))],
            {},
            run_id="RUN-UI-001",
        )
        self.runs.record(self.run, task_id=self.task_id, project_id="PRJ-UI-001")
        self.server = create_server(
            self.registry,
            extra={"version": "0.1.0", "kernel": "v0.2.2", "tier": "core"},
            tasks=self.tasks,
            policy=self.policy,
            audit=self.audit,
            rules=self.rules,
            artifacts=self.artifacts,
            runs=self.runs,
        )
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def get(self, path, token=None, raw=False):
        url = "http://127.0.0.1:%d%s" % (self.port, path)
        request = urllib.request.Request(url, method="GET")
        if token:
            request.add_header("X-GeoOps-Token", token)
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                body = response.read()
                if raw:
                    return response.status, response.headers.get("Content-Type", ""), body
                return response.status, json.loads(body.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read()
            if raw:
                return exc.code, exc.headers.get("Content-Type", ""), body
            return exc.code, json.loads(body.decode("utf-8") or "{}")

    # ---------------------------------------------------------------- console
    def test_console_page_is_served_with_its_own_markup(self) -> None:
        status, ctype, body = self.get("/ui/", raw=True)
        text = body.decode("utf-8")
        self.assertEqual(status, 200)
        self.assertTrue(ctype.startswith("text/html"))
        self.assertIn("Bumao GeoOps", text)
        self.assertIn("overview", text)
        self.assertNotIn("http://", text, "the page must not pull anything from the network")

    def test_console_exposes_functional_controls(self) -> None:
        status, _, body = self.get("/ui/", raw=True)
        text = body.decode("utf-8")
        self.assertEqual(status, 200)
        for marker in (
            'id="datasetQuery"',
            'id="datasetProfileCard"',
            'id="qualityTargetList"',
            'id="qualityAccuracyPanel"',
            'name="reference_path"',
            'name="threshold_pixel_accuracy"',
            'data-goto="projects"',
            'id="workflowIdInput"',
            'id="workflowSubmitBtn"',
            'id="workflowCancelBtn"',
            'id="workflowEditNote"',
            'id="resumeRunSelect"',
            'id="resumeHint"',
            'id="workflowExecuteBtn"',
            'id="runQuery"',
            'data-node-template="rule_check"',
        ):
            self.assertIn(marker, text)

    def test_stylesheet_and_script_are_served_with_their_types(self) -> None:
        _, css_type, css = self.get("/ui/ui.css", raw=True)
        self.assertTrue(css_type.startswith("text/css"))
        self.assertIn(b"--paper", css)
        _, js_type, js = self.get("/ui/ui.js", raw=True)
        self.assertIn("application/javascript", js_type)
        self.assertIn(b"/api/v1/overview", js)
        self.assertIn(b"data-workflow-edit", js)
        self.assertIn(b"/api/v1/workflows/", js)
        self.assertIn(b"data-node-template", js)
        self.assertIn(b"data-run-resume", js)
        self.assertIn(b"/api/v1/workflow-runs/", js)
        self.assertIn(b"pill editing", js)
        self.assertIn(b"is-editing", js)
        self.assertIn(b"filteredRuns", js)

    def test_unknown_ui_path_is_404(self) -> None:
        status, _ = self.get("/ui/../../app.py")
        self.assertEqual(status, 404)

    def test_console_script_parses(self) -> None:
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not on PATH; the syntax check needs it")
        result = subprocess.run(
            [node, "--check", os.path.join(WEB_DIR, "ui.js")],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    # ------------------------------------------------------------- endpoints
    def test_overview_reports_real_counts(self) -> None:
        status, body = self.get("/api/v1/overview")
        self.assertEqual(status, 200)
        self.assertEqual(body["objects"], len(self.registry))
        self.assertEqual(body["tasks"]["total"], len(self.tasks.list()))
        self.assertEqual(body["tasks"]["by_status"].get("READY"), 1)
        self.assertEqual(body["rules"]["packs"], 2)
        self.assertEqual(body["rules"]["rules"], len(self.rules.rules()))
        self.assertEqual(body["artifacts"]["count"], 1)

    def test_rules_endpoint_lists_the_packs_on_disk(self) -> None:
        status, body = self.get("/api/v1/rules")
        self.assertEqual(status, 200)
        pack_ids = {pack["pack_id"] for pack in body["packs"]}
        self.assertIn("p01_dataset", pack_ids)
        self.assertIn("p02_products", pack_ids)
        disk_rules = 0
        for name in os.listdir(PACK_DIR):
            if not name.endswith(".json"):
                continue
            with open(os.path.join(PACK_DIR, name), encoding="utf-8") as handle:
                disk_rules += len(json.load(handle).get("rules") or [])
        self.assertEqual(body["count"], disk_rules)
        self.assertEqual(len(body["rules"]), disk_rules)

    def test_artifacts_need_a_token_and_return_the_registered_row(self) -> None:
        status, _ = self.get("/api/v1/artifacts")
        self.assertEqual(status, 401)
        status, body = self.get("/api/v1/artifacts", token="admin-token")
        self.assertEqual(status, 200)
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["artifacts"][0]["sha256"], self.row["sha256"])
        self.assertEqual(body["artifacts"][0]["deliverable_id"], "DLV-UI-001")

    def test_tasks_endpoint_lists_allowed_targets(self) -> None:
        status, body = self.get("/api/v1/tasks")
        self.assertEqual(status, 200)
        self.assertEqual(body["count"], 1)
        row = body["tasks"][0]
        self.assertEqual(row["allowed_targets"], ["CANCELLED", "DRAFT", "RUNNING"])

    def test_runs_endpoint_serves_the_journal(self) -> None:
        status, body = self.get("/api/v1/runs")
        self.assertEqual(status, 200)
        self.assertEqual(body["count"], 1)
        row = body["runs"][0]
        self.assertEqual(row["run_id"], "RUN-UI-001")
        self.assertEqual(row["task_id"], self.task_id)
        self.assertEqual(body["by_status"], {"PASS": 1})
        self.assertEqual([node["status"] for node in row["node_runs"]], ["PASS"])

    def test_runs_endpoint_is_404_without_a_journal(self) -> None:
        server = create_server(self.registry, tasks=self.tasks)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with urllib.request.urlopen(
                "http://127.0.0.1:%d/api/v1/runs" % port, timeout=5
            ) as response:
                status = response.status
        except urllib.error.HTTPError as exc:
            status = exc.code
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
