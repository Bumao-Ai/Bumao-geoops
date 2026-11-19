"""Tests for the 0.1 write endpoints: project, dataset, catalog, review, trace."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from geoops.api import AuditLog, PermissionPolicy, create_server
from geoops.artifacts import ArtifactStore
from geoops.domain import DomainRegistry, ObjectType, TaskEngine
from geoops.domain.projects import ProjectRegistry
from geoops.workflow import RunJournal


class ReleaseApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.mkdtemp(prefix="geoops-api-release-")
        self.registry = DomainRegistry()
        ProjectRegistry(self.registry).register(
            "PRJ-API-1", "API-1", "接口项目", "survey", "哈尔滨", "EPSG:4547", "1985"
        )
        self.tasks = TaskEngine(self.registry)
        self.task = self.tasks.create("PRJ-API-1", "接口任务", "change_detection", actor="test")
        self.registry.register(ObjectType.DELIVERABLE, "DLV-API-1", {"task_id": self.task.task_id})
        self.artifacts = ArtifactStore(
            root=self.tempdir,
            index_path=os.path.join(self.tempdir, "artifacts.json"),
            registry=self.registry,
        )
        self.policy = PermissionPolicy(
            {
                "admin": ["project:write", "dataset:write", "catalog:write", "review:write",
                          "deliverable:write", "audit:read"],
                "reader": ["audit:read"],
            }
        )
        self.audit = AuditLog(limit=100)
        self.runs = RunJournal()
        self.server = create_server(
            self.registry,
            tasks=self.tasks,
            policy=self.policy,
            audit=self.audit,
            artifacts=self.artifacts,
            runs=self.runs,
            extra={"version": "0.1.0"},
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

    def test_project_write_requires_the_permission(self) -> None:
        body = {
            "project_id": "PRJ-API-2", "project_code": "API-2", "name": "接口项目二",
            "project_type": "survey", "area": "哈尔滨", "crs": "EPSG:4547",
            "vertical_datum": "1985",
        }
        status, _ = self.call("POST", "/api/v1/projects", body)
        self.assertEqual(status, 401)
        status, _ = self.call("POST", "/api/v1/projects", body, token="reader")
        self.assertEqual(status, 403)
        status, payload = self.call("POST", "/api/v1/projects", body, token="admin")
        self.assertEqual(status, 201)
        self.assertEqual(payload["project"]["payload"]["crs"], "EPSG:4547")

    def test_dataset_is_registered_with_a_real_file(self) -> None:
        path = os.path.join(self.tempdir, "grid.asc")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("ncols 2\nnrows 1\nxllcorner 0\nyllcorner 0\ncellsize 1\n1 0\n")
        with open(path + ".json", "w", encoding="utf-8") as handle:
            json.dump({"crs": "EPSG:4547"}, handle)
        status, payload = self.call(
            "POST", "/api/v1/datasets",
            {"project_id": "PRJ-API-1", "path": path, "label": "一期"}, token="admin",
        )
        self.assertEqual(status, 201)
        dataset = payload["dataset"]
        self.assertEqual(len(payload["dataset"]["payload"]["sha256"]), 64)
        status, validation = self.call("GET", "/api/v1/datasets/%s/validate" % dataset["object_id"])
        self.assertEqual(status, 200)
        self.assertEqual(validation["status"], "PASS")
        status, profile = self.call("GET", "/api/v1/datasets/%s/profile" % dataset["object_id"])
        self.assertEqual(status, 200)
        self.assertEqual(profile["format"], "ascii")
        self.assertEqual(profile["bands"], 1)
        self.assertEqual(profile["band"], 1)
        self.assertEqual(profile["ncols"], 2)
        self.assertEqual(profile["nrows"], 1)
        self.assertEqual(profile["valid_cells"], 2)
        self.assertEqual(profile["min"], 0.0)
        self.assertEqual(profile["max"], 1.0)
        self.assertEqual(profile["mean"], 0.5)

    def test_dataset_without_a_project_is_refused(self) -> None:
        status, payload = self.call(
            "POST", "/api/v1/datasets",
            {"project_id": "PRJ-NOPE", "path": os.path.join(self.tempdir, "none.asc")},
            token="admin",
        )
        self.assertEqual(status, 400)
        self.assertIn("project", payload["error"])

    def test_survey_area_is_registered_against_a_real_project(self) -> None:
        status, payload = self.call(
            "POST", "/api/v1/survey-areas",
            {"area_id": "AREA-API-1", "project_id": "PRJ-API-1", "name": "测区",
             "area_type": "project", "crs": "EPSG:4547", "bounds": [0, 0, 10, 10]},
            token="admin",
        )
        self.assertEqual(status, 201)
        self.assertEqual(payload["survey_area"]["payload"]["bounds"], [0.0, 0.0, 10.0, 10.0])
        status, listing = self.call("GET", "/api/v1/survey-areas?project_id=PRJ-API-1")
        self.assertEqual(status, 200)
        self.assertEqual(listing["count"], 1)

    def test_catalog_slices_are_readable_by_kind(self) -> None:
        for path, kind in (("/api/v1/models", "Model"), ("/api/v1/agents", "Agent"), ("/api/v1/tools", "Tool")):
            status, payload = self.call("GET", path)
            self.assertEqual(status, 200)
            self.assertEqual(payload["kind"], kind)
            self.assertEqual(payload["count"], 0)

    def test_execution_events_flattens_a_real_journal_row(self) -> None:
        class FakeRun:
            def to_dict(self):
                return {
                    "run_id": "RUN-API-1",
                    "workflow_id": "WF-API-1",
                    "status": "SUCCEEDED",
                    "started_at": "2026-11-18T00:00:00Z",
                    "finished_at": "2026-11-18T00:00:01Z",
                    "node_runs": [
                        {"node_id": "N1", "node_type": "data_input", "status": "SUCCEEDED",
                         "attempts": 1, "started_at": "2026-11-18T00:00:00Z",
                         "finished_at": "2026-11-18T00:00:01Z", "error": ""}
                    ],
                }
        self.runs.record(FakeRun(), task_id=self.task.task_id, project_id="PRJ-API-1")
        status, payload = self.call(
            "GET", "/api/v1/execution-events?task_id=%s" % self.task.task_id
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["count"], 2)
        self.assertEqual(payload["events"][0]["kind"], "run")
        self.assertEqual(payload["events"][1]["kind"], "node")
        self.assertEqual(payload["events"][1]["node_id"], "N1")

    def test_catalog_rejects_an_agent_with_unknown_models(self) -> None:
        status, payload = self.call(
            "POST", "/api/v1/catalog",
            {"kind": "Agent", "id": "AG-API-1", "name": "Agent", "version": "1.0",
             "strategy": "sequential", "model_ids": ["MDL-NOPE"], "tool_ids": []},
            token="admin",
        )
        self.assertEqual(status, 400)
        self.assertIn("unknown ids", payload["error"])

    def test_catalog_registers_a_builtin_algorithm(self) -> None:
        status, payload = self.call(
            "POST", "/api/v1/catalog",
            {"kind": "Model", "id": "MDL-API-1", "name": "像元差分", "version": "1.0",
             "model_kind": "algorithm", "capability": "change_detection",
             "adapter": "builtin:change_detection", "available": True},
            token="admin",
        )
        self.assertEqual(status, 201)
        self.assertTrue(payload["object"]["payload"]["available"])
        status, listing = self.call("GET", "/api/v1/catalog")
        self.assertEqual(status, 200)
        self.assertEqual(len(listing["models"]), 1)

    def test_artifact_binding_requires_permission_and_a_real_file(self) -> None:
        path = os.path.join(self.tempdir, "bound.asc")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("ncols 2\nnrows 1\n0 1\n")
        status, _ = self.call(
            "POST", "/api/v1/deliverables/DLV-API-1/artifacts",
            {"path": path, "kind": "mask"}, token="reader",
        )
        self.assertEqual(status, 403)
        status, payload = self.call(
            "POST", "/api/v1/deliverables/DLV-API-1/artifacts",
            {"path": path, "kind": "mask", "label": "SYNTHETIC API artifact"}, token="admin",
        )
        self.assertEqual(status, 201)
        self.assertEqual(payload["artifact"]["deliverable_id"], "DLV-API-1")
        self.assertEqual(len(payload["artifact"]["sha256"]), 64)

    def test_review_approves_and_marks_the_deliverable(self) -> None:
        status, payload = self.call(
            "POST", "/api/v1/reviews",
            {"task_id": self.task.task_id, "deliverable_id": "DLV-API-1",
             "reviewer": "审核员", "decision": "APPROVE", "opinion": "通过"},
            token="admin",
        )
        self.assertEqual(status, 201)
        self.assertEqual(payload["review"]["payload"]["decision"], "APPROVE")
        self.assertEqual(self.registry.get("DLV-API-1").status, "accepted")
        status, _ = self.call(
            "POST", "/api/v1/reviews",
            {"task_id": self.task.task_id, "deliverable_id": "DLV-API-1",
             "reviewer": "另一位", "decision": "REJECT", "opinion": "重做"},
            token="admin",
        )
        self.assertEqual(status, 400)

    def test_trace_reports_missing_links(self) -> None:
        status, trace = self.call("GET", "/api/v1/tasks/%s/trace" % self.task.task_id)
        self.assertEqual(status, 200)
        self.assertFalse(trace["complete"])
        names = {entry["name"] for entry in trace["missing"]}
        self.assertIn("datasets", names)
        status, missing = self.call("GET", "/api/v1/tasks/TSK-NOPE/trace")
        self.assertEqual(status, 404)

    def test_overview_counts_the_new_layers(self) -> None:
        status, overview = self.call("GET", "/api/v1/overview")
        self.assertEqual(status, 200)
        for key in ("projects", "survey_areas", "datasets", "reviews"):
            self.assertIn(key, overview)


if __name__ == "__main__":
    unittest.main()
