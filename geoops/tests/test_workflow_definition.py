"""Definitions are records; a run is built from the record, not a closure."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from geoops.api import AuditLog, PermissionPolicy, create_server
from geoops.catalog import Catalog, CatalogError
from geoops.domain import DomainRegistry, TaskEngine
from geoops.domain.datasets_store import DatasetRegistry
from geoops.domain.projects import ProjectRegistry
from geoops.domain.registry import ObjectType
from geoops.workflow import (
    Node,
    NodeResult,
    NodeStatus,
    RunJournal,
    WorkflowDefinitionError,
    WorkflowDefinitionRegistry,
    WorkflowEngine,
    WorkflowService,
    run,
    validate_definition,
)
from geoops.survey import SurveyRuleEngine


class DefinitionTests(unittest.TestCase):
    def setUp(self):
        self.registry = DomainRegistry()
        self.dir = tempfile.mkdtemp(prefix="geoops-workflow-")
        self.path = os.path.join(self.dir, "workflows.json")
        self.defs = WorkflowDefinitionRegistry(self.registry, path=self.path)

    def test_invalid_nodes_are_refused(self):
        with self.assertRaises(WorkflowDefinitionError):
            validate_definition("WF-1", "Bad", "x", [{"node_id": "N1", "name": "N1", "type": "fake"}])
        with self.assertRaises(WorkflowDefinitionError):
            validate_definition(
                "WF-1", "Bad", "x",
                [{"node_id": "N1", "name": "N1", "type": "rule_check"},
                 {"node_id": "N1", "name": "N2", "type": "rule_check"}],
            )

    def test_create_update_and_reload(self):
        widget = self.defs.create(
            "WF-A", "A", "change_detection",
            [{"node_id": "R1", "name": "门", "type": "rule_check", "task_type": "change_detection"}],
            description="first",
        )
        self.assertEqual(widget.version, 1)
        updated = self.defs.update("WF-A", nodes=[{"node_id": "C1", "name": "差分", "type": "change_detection"}])
        self.assertEqual(updated.version, 2)
        reloaded = WorkflowDefinitionRegistry(DomainRegistry(), path=self.path)
        self.assertIsNotNone(reloaded.get("WF-A"))
        self.assertEqual(reloaded.get("WF-A").payload["nodes"][0]["type"], "change_detection")

    def test_unknown_workflow_is_refused(self):
        with self.assertRaises(WorkflowDefinitionError):
            self.defs.update("WF-404", name="x")

    def test_spec_node_types_are_all_known(self):
        nodes = [
            {"node_id": "D1", "name": "数据输入", "type": "data_input"},
            {"node_id": "D2", "name": "数据检查", "type": "data_check"},
            {"node_id": "M1", "name": "模型", "type": "model_call", "prompt": "classify"},
            {"node_id": "A1", "name": "Agent", "type": "agent_execute", "prompt": "plan"},
            {"node_id": "G1", "name": "GIS", "type": "gis_tool_call", "tool_id": "gdal"},
            {"node_id": "R1", "name": "规则", "type": "rule_check"},
            {"node_id": "V1", "name": "审核", "type": "review"},
            {"node_id": "O1", "name": "输出", "type": "output"},
            {"node_id": "C1", "name": "差分", "type": "change_detection", "band": 2},
        ]
        result = validate_definition("WF-SPEC", "全类型", "change_detection", nodes)
        self.assertEqual(result["node_count"], 9)
        self.assertEqual(result["nodes"][-1]["band"], 2)


class NodeDataTests(unittest.TestCase):
    def test_downstream_node_reads_previous_output(self):
        def first(context):
            return NodeResult(NodeStatus.PASS, "wrote value", {"value": 7})

        def second(context):
            value = context["node_outputs"]["N1"]["value"]
            return NodeResult(NodeStatus.PASS if value == 7 else NodeStatus.FAIL, "read %s" % value)

        result = run([
            Node("N1", "first", first),
            Node("N2", "second", second),
        ])
        self.assertEqual(result.status, NodeStatus.PASS)
        self.assertEqual(result.node_runs[1].detail, "read 7")

    def test_data_input_and_check_use_real_record(self):
        registry = DomainRegistry()
        projects = ProjectRegistry(registry)
        projects.register("PRJ-D", "D-1", "数据项目", "survey", "哈尔滨", "EPSG:4547", "1985")
        datasets = DatasetRegistry(registry, projects)
        directory = tempfile.mkdtemp(prefix="geoops-data-node-")
        path = os.path.join(directory, "image.asc")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("ncols 2\nnrows 2\nxllcorner 0\nyllcorner 0\ncellsize 10\n")
        with open(path + ".json", "w", encoding="utf-8") as handle:
            json.dump({"crs": "EPSG:4547"}, handle)
        record = datasets.register("PRJ-D", path)

        from geoops.workflow.data_nodes import data_check_node, data_input_node

        context = {"dataset_id": record.object_id, "project_id": "PRJ-D"}
        self.assertEqual(data_input_node("D1", "input", datasets).action(context).status, NodeStatus.PASS)
        self.assertEqual(data_check_node("D2", "check", datasets).action(context).status, NodeStatus.PASS)

    def test_review_gate_never_fabricates_approval(self):
        registry = DomainRegistry()
        from geoops.review import ReviewEngine
        from geoops.workflow.data_nodes import review_gate_node

        reviews = ReviewEngine(registry)
        result = review_gate_node("V1", "review", reviews).action({})
        self.assertEqual(result.status, NodeStatus.FAIL)
        self.assertIn("cannot be fabricated", result.detail)

    def test_agent_node_resolves_registered_agent(self):
        registry = DomainRegistry()
        agent = registry.register(
            ObjectType.AGENT,
            "AGT-1",
            {"name": "变化调查 Agent", "version": "1.0", "strategy": "scripted",
             "model_ids": ["MOD-1"], "tool_ids": [], "available": True},
        )

        class Catalog:
            def get(self, kind, object_id):
                return agent if object_id == "AGT-1" else None

        class Runtime:
            def invoke(self, prompt, system="", max_tokens=512, temperature=None):
                return {"text": "ok", "model": "test-model", "usage": {}, "elapsed_ms": 1}

        from geoops.ai.agent_node import agent_execute_node
        result = agent_execute_node("A1", "Agent", Runtime(), Catalog(), agent_id="AGT-1", prompt="go").action({})
        self.assertEqual(result.status, NodeStatus.PASS)
        self.assertEqual(result.output["agent_id"], "AGT-1")
        self.assertEqual(result.output["text"], "ok")

    def test_agent_max_steps_is_bounded(self):
        catalog = Catalog(DomainRegistry())
        with self.assertRaises(CatalogError):
            catalog.register_agent("A-0", "零步", "1.0", "react", [], [], max_steps=0)
        with self.assertRaises(CatalogError):
            catalog.register_agent("A-17", "十七步", "1.0", "react", [], [], max_steps=17)
        agent = catalog.register_agent("A-3", "三步", "1.0", "react", [], [], max_steps=3)
        self.assertEqual(agent.payload["max_steps"], 3)

    def test_agent_executor_runs_a_declared_builtin_tool(self):
        directory = tempfile.mkdtemp(prefix="geoops-agent-tool-")
        path = os.path.join(directory, "grid.asc")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("ncols 2\nnrows 2\nxllcorner 0\nyllcorner 0\ncellsize 10\nNODATA_value -9999\n")
            handle.write("1 2\n3 -9999\n")
        registry = DomainRegistry()
        tool = registry.register(
            ObjectType.TOOL,
            "TOOL-PROFILE",
            {"tool_id": "TOOL-PROFILE", "name": "ASCII profile", "version": "1.0",
             "category": "raster", "adapter": "builtin:ascii_grid_profile", "available": True},
        )
        agent = registry.register(
            ObjectType.AGENT,
            "AGT-TOOL",
            {"name": "带工具的 Agent", "version": "1.0", "strategy": "react",
             "model_ids": [], "tool_ids": ["TOOL-PROFILE"], "available": True},
        )

        class Catalog:
            def get(self, kind, object_id):
                return {"TOOL-PROFILE": tool, "AGT-TOOL": agent}.get(object_id)

        class Runtime:
            def __init__(self):
                self.calls = 0

            def invoke(self, prompt, system="", max_tokens=512, temperature=None):
                self.calls += 1
                if self.calls == 1:
                    text = json.dumps({"tool": "TOOL-PROFILE", "args": {"path": path}})
                else:
                    text = json.dumps({"final": "profile complete"})
                return {"text": text, "model": "test-model", "usage": {}, "elapsed_ms": 1}

        from geoops.ai.agent_node import agent_execute_node
        result = agent_execute_node(
            "A1", "Agent", Runtime(), Catalog(), agent_id="AGT-TOOL", prompt="profile it"
        ).action({})
        self.assertEqual(result.status, NodeStatus.PASS)
        self.assertEqual(result.output["final"], "profile complete")
        self.assertEqual(len(result.output["tool_calls"]), 1)
        self.assertEqual(result.output["tool_calls"][0]["tool_id"], "TOOL-PROFILE")
        self.assertEqual(result.output["tool_calls"][0]["result"]["mean"], 2.0)


    def test_builtin_ascii_tool_computes_real_stats(self):
        directory = tempfile.mkdtemp(prefix="geoops-gis-node-")
        path = os.path.join(directory, "grid.asc")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("ncols 2\nnrows 2\nxllcorner 0\nyllcorner 0\ncellsize 10\nNODATA_value -9999\n")
            handle.write("1 2\n3 -9999\n")
        from geoops.workflow.gis_nodes import ascii_grid_profile_node
        result = ascii_grid_profile_node("G1", "profile", tool_id="builtin:ascii_grid_profile").action(
            {"raster_path": path}
        )
        self.assertEqual(result.status, NodeStatus.PASS)
        self.assertEqual(result.output["valid_cells"], 3)
        self.assertEqual(result.output["mean"], 2.0)
        unknown = ascii_grid_profile_node("G2", "profile", tool_id="gdal").action({"raster_path": path})
        self.assertEqual(unknown.status, NodeStatus.ERROR)

    def test_agent_executor_records_a_failed_external_tool_call(self):
        directory = tempfile.mkdtemp(prefix="geoops-agent-fail-")
        script = os.path.join(directory, "fail.py")
        with open(script, "w", encoding="utf-8") as handle:
            handle.write("import sys\nsys.exit(2)\n")
        config = os.path.join(directory, "tools.json")
        with open(config, "w", encoding="utf-8") as handle:
            json.dump({"tools": [{"tool_id": "external:fail", "command": [sys.executable, script], "args": [], "timeout": 10}]}, handle)
        old = os.environ.get("GEOOPS_EXTERNAL_TOOLS")
        os.environ["GEOOPS_EXTERNAL_TOOLS"] = config
        try:
            registry = DomainRegistry()
            tool = registry.register(
                ObjectType.TOOL,
                "TOOL-FAIL",
                {"tool_id": "TOOL-FAIL", "name": "failing tool", "version": "1.0",
                 "category": "gis", "adapter": "external:fail", "available": True},
            )
            agent = registry.register(
                ObjectType.AGENT,
                "AGT-FAIL",
                {"name": "failing agent", "version": "1.0", "strategy": "react",
                 "model_ids": [], "tool_ids": ["TOOL-FAIL"], "available": True},
            )

            class Catalog:
                def get(self, kind, object_id):
                    return {"TOOL-FAIL": tool, "AGT-FAIL": agent}.get(object_id)

            class Runtime:
                def invoke(self, prompt, system="", max_tokens=512, temperature=None):
                    return {"text": json.dumps({"tool": "TOOL-FAIL", "args": {}}),
                            "model": "test-model", "usage": {}, "elapsed_ms": 1}

            from geoops.ai.agent_node import agent_execute_node
            result = agent_execute_node(
                "A1", "Agent", Runtime(), Catalog(), agent_id="AGT-FAIL", prompt="fail"
            ).action({})
        finally:
            if old is None:
                os.environ.pop("GEOOPS_EXTERNAL_TOOLS", None)
            else:
                os.environ["GEOOPS_EXTERNAL_TOOLS"] = old
        self.assertEqual(result.status, NodeStatus.ERROR)
        self.assertEqual(len(result.output["steps"]), 1)
        self.assertEqual(result.output["tool_calls"], result.output["steps"])
        step = result.output["steps"][0]
        self.assertEqual(step["status"], "ERROR")
        self.assertEqual(step["failure"]["returncode"], 2)
        self.assertIn("ExternalToolError", step["error"])


class ResumeTests(unittest.TestCase):
    def test_service_resumes_at_failed_node_with_real_context(self):
        registry = DomainRegistry()
        projects = ProjectRegistry(registry)
        projects.register("PRJ-R", "R-1", "恢复项目", "survey", "哈尔滨", "EPSG:4547", "1985")
        datasets = DatasetRegistry(registry, projects)
        directory = tempfile.mkdtemp(prefix="geoops-resume-")
        baseline = os.path.join(directory, "a.asc")
        comparison = os.path.join(directory, "b.asc")
        output = os.path.join(directory, "mask.asc")
        for path, values in ((baseline, "1 1\n1 1\n"), (comparison, "1 2\n2 1\n")):
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("ncols 2\nnrows 2\nxllcorner 0\nyllcorner 0\ncellsize 10\n")
                handle.write(values)
        for path in (baseline, comparison):
            with open(path + ".json", "w", encoding="utf-8") as handle:
                json.dump({"crs": "EPSG:4547"}, handle)
        dataset = datasets.register("PRJ-R", baseline)

        defs = WorkflowDefinitionRegistry(registry)
        defs.create(
            "WF-RESUME", "恢复流程", "change_detection",
            [
                {"node_id": "D1", "name": "数据输入", "type": "data_input"},
                {"node_id": "C1", "name": "差分", "type": "change_detection"},
            ],
        )
        service = WorkflowService(defs, SurveyRuleEngine(), None, None, datasets=datasets)
        first = service.execute("WF-RESUME", {"dataset_id": dataset.object_id, "project_id": "PRJ-R"})
        self.assertEqual(first["status"], "FAIL")
        self.assertEqual(first["run"]["node_runs"][0]["status"], "PASS")
        resumed = service.resume(
            "WF-RESUME",
            first["run"]["run_id"],
            {
                "dataset_id": dataset.object_id,
                "project_id": "PRJ-R",
                "baseline_path": baseline,
                "comparison_path": comparison,
                "change_output_path": output,
            },
        )
        self.assertEqual(resumed["status"], "PASS")
        self.assertEqual(resumed["run"]["node_runs"][0]["status"], "REUSED")
        self.assertEqual(resumed["run"]["node_runs"][1]["status"], "PASS")
        self.assertTrue(os.path.exists(output))


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="geoops-workflow-run-")
        self.baseline = os.path.join(self.dir, "a.asc")
        self.comparison = os.path.join(self.dir, "b.asc")
        self.output = os.path.join(self.dir, "mask.asc")
        for path, values in (
            (self.baseline, "1 1 1\n1 1 1\n"),
            (self.comparison, "1 2 1\n1 1 2\n"),
        ):
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("ncols 3\nnrows 2\nxllcorner 0\nyllcorner 0\ncellsize 10\nNODATA_value -9999\n")
                handle.write(values)
        self.defs = WorkflowDefinitionRegistry(DomainRegistry())
        self.defs.create(
            "WF-CHANGE", "变化检测", "change_detection",
            [
                {"node_id": "C1", "name": "差分", "type": "change_detection", "threshold": 1, "min_area_m2": 150},
                {"node_id": "C2", "name": "差分二", "type": "change_detection", "threshold": 1, "min_area_m2": 0},
            ],
        )
        self.service = WorkflowService(
            self.defs,
            SurveyRuleEngine(),
            None,
            None,
            engine=WorkflowEngine(),
        )

    def test_change_definition_executes_real_nodes(self):
        result = self.service.execute(
            "WF-CHANGE",
            {"baseline_path": self.baseline, "comparison_path": self.comparison, "change_output_path": self.output},
        )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(len(result["run"]["node_runs"]), 2)
        self.assertTrue(os.path.exists(self.output))

    def test_missing_context_fails_not_passes(self):
        result = self.service.execute("WF-CHANGE", {})
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["run"]["node_runs"][0]["status"], "FAIL")

    def test_declared_input_aliases_feed_downstream_node(self):
        self.defs.create(
            "WF-ALIAS", "别名流程", "change_detection",
            [{
                "node_id": "C1", "name": "差分", "type": "change_detection",
                "baseline_key": "b", "comparison_key": "c", "output_key": "o",
                "inputs": {"b": "baseline_path", "c": "comparison_path", "o": "change_output_path"},
                "success_condition": "status == PASS", "failure_action": "stop",
            }],
        )
        result = self.service.execute(
            "WF-ALIAS",
            {"baseline_path": self.baseline, "comparison_path": self.comparison, "change_output_path": self.output},
        )
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(os.path.exists(self.output))

    def test_declared_retry_is_applied_by_the_service(self):
        self.defs.create(
            "WF-RETRY", "重试流程", "change_detection",
            [{
                "node_id": "G1", "name": "未实现工具", "type": "gis_tool_call",
                "tool_id": "builtin:not-implemented", "retry": 2,
                "failure_action": "stop",
            }],
        )
        result = self.service.execute("WF-RETRY", {})
        self.assertEqual(result["status"], "ERROR")
        self.assertEqual(result["run"]["node_runs"][0]["attempts"], 3)
        self.assertEqual(result["run"]["node_runs"][0]["status"], "ERROR")


class WorkflowApiTests(unittest.TestCase):
    def setUp(self):
        self.registry = DomainRegistry()
        ProjectRegistry(self.registry).register(
            "PRJ-WF", "WF-API", "流程接口项目", "survey", "哈尔滨", "EPSG:4547", "1985"
        )
        self.tasks = TaskEngine(self.registry)
        self.task = self.tasks.create("PRJ-WF", "流程任务", "change_detection", actor="test")
        self.tasks.transition(self.task.task_id, "READY", actor="test")
        self.tasks.transition(self.task.task_id, "RUNNING", actor="test")
        self.rules = SurveyRuleEngine()
        self.defs = WorkflowDefinitionRegistry(self.registry)
        self.service = WorkflowService(self.defs, self.rules, None, None, journal=RunJournal(), tasks=self.tasks)
        self.policy = PermissionPolicy({"admin": ["workflow:write", "workflow:execute"]})
        self.server = create_server(
            self.registry,
            tasks=self.tasks,
            policy=self.policy,
            audit=AuditLog(limit=100),
            rules=self.rules,
            workflows=self.defs,
            workflow_service=self.service,
        )
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def call(self, method, path, body=None, token=None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Content-Type": "application/json"} if body is not None else {}
        if token:
            headers["X-GeoOps-Token"] = token
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path), data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=5) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8") or "{}")

    def test_create_list_and_execute(self):
        status, payload = self.call(
            "POST", "/api/v1/workflows",
            {
                "workflow_id": "WF-API-1",
                "name": "接口流程",
                "task_type": "map_compilation",
                "nodes": [{"node_id": "R1", "name": "规则门", "type": "rule_check"}],
            },
            token="admin",
        )
        self.assertEqual(status, 201)
        self.assertEqual(self.call("GET", "/api/v1/workflows")[1]["count"], 1)
        status, payload = self.call(
            "POST", "/api/v1/workflows/WF-API-1/execute",
            {"task_id": self.task.task_id, "context": {"project_id": "PRJ-WF"}},
            token="admin",
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["run"]["node_runs"][0]["status"], "SKIP")
        self.assertIn(payload["run"]["run_id"], self.tasks.get(self.task.task_id).workflow_run_ids)

    def test_update_definition_in_place(self):
        created = self.call(
            "POST", "/api/v1/workflows",
            {
                "workflow_id": "WF-API-EDIT",
                "name": "接口流程",
                "task_type": "change_detection",
                "nodes": [{"node_id": "R1", "name": "规则门", "type": "rule_check"}],
            },
            token="admin",
        )
        self.assertEqual(created[0], 201)
        updated = self.call(
            "POST", "/api/v1/workflows/WF-API-EDIT",
            {
                "name": "接口流程 v2",
                "task_type": "change_detection",
                "description": "updated from the console",
                "nodes": [
                    {"node_id": "R1", "name": "规则门", "type": "rule_check"},
                    {"node_id": "C2", "name": "逐格差分", "type": "change_detection", "threshold": 1.0},
                ],
            },
            token="admin",
        )
        self.assertEqual(updated[0], 200)
        self.assertEqual(updated[1]["workflow"]["version"], 2)
        self.assertEqual(updated[1]["workflow"]["payload"]["name"], "接口流程 v2")
        self.assertEqual(updated[1]["workflow"]["payload"]["description"], "updated from the console")
        self.assertEqual(len(updated[1]["workflow"]["payload"]["nodes"]), 2)
        status, payload = self.call("GET", "/api/v1/workflows/WF-API-EDIT")
        self.assertEqual(status, 200)
        self.assertEqual(payload["workflow"]["version"], 2)
        self.assertEqual(payload["workflow"]["payload"]["node_count"], 2)
        self.assertEqual(
            self.call("POST", "/api/v1/workflows/WF-API-EDIT", {"name": "x"}, token=None)[0],
            401,
        )
        self.assertEqual(
            self.call("POST", "/api/v1/workflows/WF-MISSING", {"name": "x"}, token="admin")[0],
            404,
        )

    def test_resume_failed_run_over_http(self):
        directory = tempfile.mkdtemp(prefix="geoops-api-resume-")
        raster_path = os.path.join(directory, "grid.asc")
        with open(raster_path, "w", encoding="utf-8") as handle:
            handle.write("ncols 2\nnrows 2\nxllcorner 0\nyllcorner 0\ncellsize 10\n")
            handle.write("1 2\n3 4\n")
        status, payload = self.call(
            "POST", "/api/v1/workflows",
            {
                "workflow_id": "WF-API-RESUME",
                "name": "接口恢复流程",
                "task_type": "change_detection",
                "nodes": [
                    {
                        "node_id": "G1",
                        "name": "栅格统计",
                        "type": "gis_tool_call",
                        "tool_id": "builtin:ascii_grid_profile",
                        "path_key": "raster_path",
                    }
                ],
            },
            token="admin",
        )
        self.assertEqual(status, 201)
        status, first = self.call(
            "POST", "/api/v1/workflows/WF-API-RESUME/execute",
            {"context": {}},
            token="admin",
        )
        self.assertEqual(status, 200)
        self.assertEqual(first["status"], "FAIL")
        previous = first["run"]["run_id"]
        status, resumed = self.call(
            "POST", "/api/v1/workflow-runs/%s/resume" % previous,
            {"workflow_id": "WF-API-RESUME", "context": {"raster_path": raster_path}},
            token="admin",
        )
        self.assertEqual(status, 200)
        self.assertEqual(resumed["status"], "PASS")
        self.assertEqual(resumed["run"]["resumed_from"], previous)
        self.assertEqual(resumed["run"]["node_runs"][0]["status"], "PASS")
        rows = self.service.journal.rows()
        self.assertEqual(rows[-1]["workflow_id"], "WF-API-RESUME")
        self.assertEqual(
            self.call("POST", "/api/v1/workflow-runs/%s/resume" % previous, {"context": {}}, token="admin")[0],
            400,
        )

    def test_create_needs_permission_and_context_is_checked(self):
        self.assertEqual(
            self.call("POST", "/api/v1/workflows", {"workflow_id": "WF-2", "name": "x", "task_type": "x", "nodes": []})[0],
            401,
        )
        status, payload = self.call(
            "POST", "/api/v1/workflows",
            {"workflow_id": "WF-API-2", "name": "接口流程", "task_type": "map_compilation",
             "nodes": [{"node_id": "R1", "name": "规则门", "type": "rule_check"}]},
            token="admin",
        )
        self.assertEqual(status, 201)
        self.assertEqual(
            self.call("POST", "/api/v1/workflows/WF-API-2/execute", {"context": []}, token="admin")[0],
            400,
        )


if __name__ == "__main__":
    unittest.main()
