"""Structural smoke test for the GeoOps scaffold.

Run ``python -m geoops.smoke`` for the default no-data mode, or
``python -m geoops.smoke --data <path>`` to run the same pipeline against a
user-supplied dataset. No dataset is bundled and none is fabricated.

Every printed value comes from a live call. The final verdict is computed from
the observed results, not hardcoded.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

from geoops.core_adapter import CoreAdapter
from geoops.core_adapter import core as core_bridge
from geoops.domain import DomainRegistry, ObjectType
from geoops.domain import TaskEngine, TaskError, TaskStatus
from geoops.domain import datasets
from geoops.quality import QualityStatus, check_dataset
from geoops.quality import build_report, write_report
from geoops.survey import SurveyRuleEngine, rule_check_node
from geoops.survey.change import read_ascii_grid
from geoops.survey.change_node import change_detect_node
from geoops.store import SnapshotStore, StoreError
from geoops.workflow import (
    JournalError,
    Node,
    NodeResult,
    NodeStatus,
    RunJournal,
    WorkflowEngine,
    run as run_workflow,
)
from geoops.artifacts import ArtifactError, ArtifactStore
from geoops.delivery import artifact_register_node
from geoops.api import create_server, AuditLog, PermissionPolicy, AuditError, hash_token

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def section(title: str) -> None:
    print("")
    print("== %s ==" % title)


def dump(data) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def main() -> int:
    parser = argparse.ArgumentParser(description="GeoOps structural smoke test")
    parser.add_argument("--data", default=None, help="path to a real dataset")
    parser.add_argument(
        "--no-data",
        action="store_true",
        help="run without dataset data (default when --data is omitted)",
    )
    args = parser.parse_args()

    checks = []

    # 1. Core adapter: real kernel import and real interfaces.
    section("1. core adapter")
    adapter = CoreAdapter()
    print("kernel dir : %s" % core_bridge.core_dir())
    print("engine     : %s" % adapter.core.__file__)
    print("registry   : %s" % adapter.registry_module.__file__)
    print("templates  : %s" % adapter.templates.__file__)
    surface = adapter.surface()
    print("core surface: %s" % " ".join("%s=%s" % (k, v) for k, v in surface.items()))
    checks.append(("core surface complete", all(surface.values())))

    expected = adapter.wire()
    print("expected gates : %s" % sorted(expected))
    print("registered     : %s" % adapter.registered_gates())
    print("verify_registration -> %s" % adapter.verify())

    rows = adapter.run_gates()
    for gate_id, ok, detail in rows:
        print("  %s %-3s %s" % ("PASS" if ok else "FAIL", gate_id, detail))
    checks.append(("all host gates pass", all(ok for _, ok, _ in rows)))

    # 2. Domain registry.
    section("2. domain registry")
    registry = DomainRegistry()
    project = registry.register(
        ObjectType.PROJECT, "PRJ-SMOKE-001", {"name": "structural smoke project"}
    )
    task = registry.register(
        ObjectType.SURVEY_TASK, "TSK-SMOKE-001", {"project_id": project.object_id}
    )
    print("objects registered : %d" % len(registry))
    print("get %s -> %s" % (project.object_id, dump(project.to_dict())))
    print("get %s -> %s" % (task.object_id, dump(task.to_dict())))
    try:
        registry.register(ObjectType.PROJECT, "PRJ-SMOKE-001", {})
        duplicate_rejected = False
        duplicate_message = "duplicate was accepted"
    except ValueError as exc:
        duplicate_rejected = True
        duplicate_message = str(exc)
    print("duplicate id -> rejected=%s :: %s" % (duplicate_rejected, duplicate_message))
    checks.append(("duplicate id rejected", duplicate_rejected))

    # 2b. Survey task engine: explicit state machine, rejected edges leave the
    # task untouched, so a refusal is never recorded as progress.
    section("2b. survey task engine")
    tasks = TaskEngine(registry)
    smoke_task = tasks.create(project.object_id, "structural smoke task", actor="smoke")
    print("create -> %s" % dump(tasks.snapshot(smoke_task.task_id)))
    checks.append(
        ("task created in DRAFT", tasks.get(smoke_task.task_id).status is TaskStatus.DRAFT)
    )

    try:
        tasks.transition(smoke_task.task_id, TaskStatus.COMPLETED, reason="skip states")
        illegal_rejected = False
        illegal_message = "illegal transition was accepted"
    except TaskError as exc:
        illegal_rejected = True
        illegal_message = str(exc)
    print("DRAFT -> COMPLETED -> rejected=%s :: %s" % (illegal_rejected, illegal_message))
    checks.append(("illegal task transition rejected", illegal_rejected))

    for target, reason in (
        (TaskStatus.READY, "preconditions listed"),
        (TaskStatus.RUNNING, "workflow started"),
        (TaskStatus.PAUSED, "operator paused"),
        (TaskStatus.RUNNING, "operator resumed"),
        (TaskStatus.COMPLETED, "deliverable archived"),
    ):
        tasks.transition(smoke_task.task_id, target, reason=reason, actor="smoke")
    final_task = tasks.get(smoke_task.task_id)
    print(
        "final -> status=%s version=%d transitions=%d"
        % (
            final_task.status.value,
            final_task.version,
            tasks.transition_count(smoke_task.task_id),
        )
    )
    checks.append(
        (
            "legal task path recorded",
            final_task.status is TaskStatus.COMPLETED
            and tasks.transition_count(smoke_task.task_id) == 5
            and final_task.version == 6,
        )
    )

    try:
        tasks.transition(smoke_task.task_id, TaskStatus.RUNNING, reason="reopen")
        terminal_rejected = False
    except TaskError:
        terminal_rejected = True
    print("COMPLETED -> RUNNING -> rejected=%s" % terminal_rejected)
    checks.append(("terminal task rejects transitions", terminal_rejected))

    try:
        tasks.attach_run(smoke_task.task_id, "RUN-SMOKE-001")
        attach_refused = False
    except TaskError:
        attach_refused = True
    print("attach run on COMPLETED -> refused=%s" % attach_refused)
    checks.append(("run attaches only while running", attach_refused))

    try:
        tasks.transition("TSK-NOT-FOUND", TaskStatus.READY, reason="unknown")
        unknown_rejected = False
    except TaskError:
        unknown_rejected = True
    print("unknown task -> rejected=%s" % unknown_rejected)
    checks.append(("unknown task rejected", unknown_rejected))

    # 3. Dataset intake: explicit, non-crashing, no fabrication.
    section("3. dataset intake")
    record = datasets.register(args.data)
    print("register(%r) -> status=%s crs=%r reason=%s"
          % (args.data, record.status, record.crs, record.reason or "none"))
    missing = datasets.register(os.path.join(PROJECT_ROOT, "data", "absent.tif"))
    print("register(missing) -> status=%s relative_path=%s reason=%s"
          % (missing.status, os.path.relpath(missing.path, PROJECT_ROOT), missing.reason))
    checks.append(("missing dataset returns SKIP", missing.status == datasets.STATUS_SKIP))
    checks.append(("dataset intake did not crash", True))

    # 4. Workflow executor: three nodes, SKIP continues, FAIL stops.
    section("4. workflow (structural run)")

    def dataset_node(context):
        result = datasets.register(args.data)
        context["dataset"] = result
        if result.status == datasets.STATUS_SKIP:
            return NodeResult(NodeStatus.SKIP, result.reason)
        if result.status == datasets.STATUS_ERROR:
            return NodeResult(NodeStatus.ERROR, result.reason)
        registry.register(ObjectType.DATASET, result.dataset_id, result.to_dict())
        return NodeResult(NodeStatus.PASS, "%s (%s)" % (result.dataset_id, result.status))

    def quality_node(context):
        result = context.get("dataset")
        if result is None or result.status == datasets.STATUS_SKIP:
            return NodeResult(NodeStatus.SKIP, "no dataset registered")
        outcome = check_dataset(result.path, {"crs": result.crs})
        context["quality"] = outcome
        if outcome.status is QualityStatus.PASS:
            return NodeResult(NodeStatus.PASS, dump(outcome.to_dict()))
        if outcome.status is QualityStatus.FAIL:
            return NodeResult(NodeStatus.FAIL, dump(outcome.to_dict()))
        return NodeResult(NodeStatus.ERROR, dump(outcome.to_dict()))

    def report_node(context):
        outcome = context.get("quality")
        if outcome is not None:
            payload = outcome.to_dict()
        else:
            payload = {
                "status": "SKIPPED",
                "reason": context["dataset"].reason,
            }
        registry.register(ObjectType.QUALITY_REPORT, "QR-SMOKE-001", payload)
        return NodeResult(NodeStatus.PASS, "QR-SMOKE-001 recorded")

    structural = run_workflow(
        [
            Node("N1", "dataset intake", dataset_node),
            Node("N2", "quality check", quality_node),
            Node("N3", "quality report", report_node),
        ],
        run_id="RUN-SMOKE-001",
    )
    for node_run in structural.node_runs:
        print("  %-7s %-4s %s :: %s"
              % (node_run.node_id, node_run.status.value, node_run.name, node_run.detail))
    print("run %s -> status=%s skipped=%d"
          % (structural.run_id, structural.status.value, structural.skipped))
    if args.data is None:
        checks.append(("structural run completes with PASS", structural.status is NodeStatus.PASS))
    else:
        checks.append(("structural run completed", structural.status in (
            NodeStatus.PASS, NodeStatus.FAIL, NodeStatus.ERROR)))

    # The run id attached to a task is the one that just executed, not a
    # placeholder written in advance.
    section("4b. task / run linkage")
    link_task = tasks.create(project.object_id, "smoke run link task")
    tasks.transition(link_task.task_id, TaskStatus.READY, reason="preconditions listed")
    tasks.transition(link_task.task_id, TaskStatus.RUNNING, reason="workflow running")
    tasks.attach_run(link_task.task_id, structural.run_id)
    try:
        tasks.attach_run(link_task.task_id, structural.run_id)
        duplicate_run_rejected = False
    except TaskError:
        duplicate_run_rejected = True
    tasks.transition(link_task.task_id, TaskStatus.COMPLETED, reason="run recorded")
    linked = tasks.get(link_task.task_id)
    print(
        "task %s -> runs=%s duplicate_rejected=%s status=%s"
        % (
            linked.task_id,
            linked.workflow_run_ids,
            duplicate_run_rejected,
            linked.status.value,
        )
    )
    checks.append(
        (
            "run attached once to task",
            linked.workflow_run_ids == [structural.run_id] and duplicate_run_rejected,
        )
    )

    section("5. workflow (failure stop)")
    registry.register(ObjectType.PROJECT, "PRJ-SMOKE-002", {"name": "failure run project"})

    def fail_node(context):
        outcome = check_dataset(
            os.path.join(PROJECT_ROOT, "data", "absent.tif"), {"crs": ""}
        )
        return NodeResult(NodeStatus.FAIL, dump(outcome.to_dict()))

    def never_node(context):
        registry.register(ObjectType.DELIVERABLE, "DLV-SMOKE-001", {"stage": "unreachable"})
        return NodeResult(NodeStatus.PASS, "deliverable registered")

    failing = run_workflow(
        [
            Node("F1", "project registration", lambda ctx: NodeResult(NodeStatus.PASS, "project recorded")),
            Node("F2", "missing dataset check", fail_node),
            Node("F3", "deliverable", never_node),
        ],
        run_id="RUN-SMOKE-002",
    )
    for node_run in failing.node_runs:
        print("  %-7s %-4s %s :: %s"
              % (node_run.node_id, node_run.status.value, node_run.name, node_run.detail))
    print("run %s -> status=%s skipped=%d"
          % (failing.run_id, failing.status.value, failing.skipped))
    checks.append(("failed node stops later nodes",
                   failing.status is NodeStatus.FAIL
                   and failing.node_runs[-1].status is NodeStatus.SKIPPED))

    # 5b. Resume: passed nodes are carried forward, execution restarts at the
    # node that failed. F3 never ran before, so it runs for the first time here.
    section("5b. workflow resume")
    workflow = WorkflowEngine()
    resumed = workflow.resume(
        failing,
        [
            Node("F1", "project registration",
                 lambda ctx: NodeResult(NodeStatus.PASS, "project recorded")),
            Node("F2", "missing dataset check",
                 lambda ctx: NodeResult(NodeStatus.PASS, "dataset present after intake fix")),
            Node("F3", "deliverable", never_node),
        ],
        run_id="RUN-SMOKE-003",
    )
    for node_run in resumed.node_runs:
        print("  %-7s %-5s %s :: %s"
              % (node_run.node_id, node_run.status.value, node_run.name, node_run.detail))
    print("run %s -> status=%s resumed_from=%s"
          % (resumed.run_id, resumed.status.value, resumed.resumed_from))
    checks.append(
        ("resume reuses passed node and completes",
         resumed.status is NodeStatus.PASS
         and resumed.resumed_from == failing.run_id
         and resumed.node_runs[0].status is NodeStatus.REUSED
         and resumed.node_runs[1].status is NodeStatus.PASS)
    )

    refused = 0
    try:
        workflow.resume(resumed, [], run_id="RUN-SMOKE-004")
    except ValueError:
        refused += 1
    try:
        workflow.resume(
            failing,
            [Node("F1", "project registration",
                  lambda ctx: NodeResult(NodeStatus.PASS, "project recorded"))],
            run_id="RUN-SMOKE-005",
        )
    except ValueError:
        refused += 1
    print("resume refused (run already passed / shape changed) -> %d/2" % refused)
    checks.append(("resume rejects a passed run and a changed shape", refused == 2))

    # 5c. The task records both runs: the failed one and the retry.
    section("5c. task follows the retry")
    retry_task = tasks.create(project.object_id, "retry linkage task")
    tasks.transition(retry_task.task_id, TaskStatus.READY, reason="preconditions listed")
    tasks.transition(retry_task.task_id, TaskStatus.RUNNING, reason="first run started")
    tasks.attach_run(retry_task.task_id, failing.run_id)
    tasks.transition(retry_task.task_id, TaskStatus.FAILED, reason="node F2 failed")
    tasks.transition(retry_task.task_id, TaskStatus.RUNNING, reason="retry from failed node")
    tasks.attach_run(retry_task.task_id, resumed.run_id)
    tasks.transition(retry_task.task_id, TaskStatus.COMPLETED, reason="deliverable archived")
    retried = tasks.get(retry_task.task_id)
    print("task %s -> status=%s runs=%s"
          % (retried.task_id, retried.status.value, retried.workflow_run_ids))
    checks.append(
        ("task records the failed run and the retry",
         retried.workflow_run_ids == [failing.run_id, resumed.run_id]
         and retried.status is TaskStatus.COMPLETED)
    )

    # 6. Quality checker: PASS / FAIL / ERROR, never ERROR-as-PASS.
    section("6. quality checker")
    no_crs = check_dataset(os.path.join(PROJECT_ROOT, "README.md"), {})
    print("README without CRS -> %s" % dump(no_crs.to_dict()))
    checks.append(("missing CRS fails", no_crs.status is QualityStatus.FAIL))

    broken = check_dataset(None, {})
    print("path=None -> %s" % dump(broken.to_dict()))
    checks.append(("checker exception is ERROR", broken.status is QualityStatus.ERROR))

    if record.status in (datasets.STATUS_READY, datasets.STATUS_INCOMPLETE):
        actual = check_dataset(record.path, {"crs": record.crs})
        print("supplied dataset -> %s" % dump(actual.to_dict()))

    # 7. API: read endpoints, then the write endpoints behind a permission gate.
    section("7. api")
    policy = PermissionPolicy(
        {
            "admin-token": ["task:create", "task:transition", "audit:read"],
            "viewer-token": ["audit:read"],
        }
    )
    audit = AuditLog()
    server = create_server(
        registry,
        extra={"registered_gates": adapter.registered_gates()},
        tasks=tasks,
        policy=policy,
        audit=audit,
    )
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def fetch(path):
        url = "http://127.0.0.1:%d%s" % (port, path)
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                return response.status, response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8")

    for path in ("/api/v1/health", "/api/v1/objects/PRJ-SMOKE-001",
                 "/api/v1/objects/PRJ-NOT-FOUND"):
        code, body = fetch(path)
        print("GET %s -> %d %s" % (path, code, body))
        if path == "/api/v1/health":
            checks.append(("health endpoint returns 200", code == 200))
        elif path.endswith("PRJ-SMOKE-001"):
            checks.append(("object endpoint returns 200", code == 200))
        else:
            checks.append(("missing object returns 404", code == 404))

    task_code, task_body = fetch("/api/v1/objects/%s" % linked.task_id)
    print("GET /api/v1/objects/%s -> %d %s" % (linked.task_id, task_code, task_body))
    checks.append(
        (
            "task object served over api",
            task_code == 200 and '"status": "COMPLETED"' in task_body,
        )
    )

    tasks_code, tasks_body = fetch("/api/v1/tasks")
    tasks_payload = json.loads(tasks_body)
    print("GET /api/v1/tasks -> %d count=%s" % (tasks_code, tasks_payload.get("count")))
    checks.append(
        (
            "task list endpoint returns tasks",
            tasks_code == 200 and tasks_payload.get("count", 0) >= 2,
        )
    )

    # 7b. The write endpoints refuse before reading a body, and every refusal
    # is audited.
    section("7b. write api with permission gate")

    def post(path, token, payload):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            "http://127.0.0.1:%d%s" % (port, path), data=data, method="POST"
        )
        if token:
            request.add_header("X-GeoOps-Token", token)
        request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    denied_status, denied_body = post(
        "/api/v1/tasks", "", {"project_id": project.object_id, "name": "api task"}
    )
    print("POST task without token -> %d %s" % (denied_status, dump(denied_body)))
    checks.append(
        ("write without token is refused and audited",
         denied_status == 401 and audit.denied() == 1)
    )

    created_status, created_body = post(
        "/api/v1/tasks", "admin-token", {"project_id": project.object_id, "name": "api task"}
    )
    write_task_id = created_body["task"]["task_id"]
    print("POST task with admin token -> %d task=%s status=%s"
          % (created_status, write_task_id, created_body["task"]["status"]))
    checks.append(
        ("admin token creates a task",
         created_status == 201 and tasks.get(write_task_id) is not None)
    )

    for target, reason in (
        ("READY", "preconditions listed"),
        ("RUNNING", "started"),
        ("COMPLETED", "archived"),
    ):
        status, _ = post(
            "/api/v1/tasks/%s/transitions" % write_task_id,
            "admin-token",
            {"target": target, "reason": reason},
        )
        print("  transition -> %s : %d" % (target, status))
    print("task %s over http -> status=%s"
          % (write_task_id, tasks.get(write_task_id).status.value))
    checks.append(
        ("http transitions reach COMPLETED",
         tasks.get(write_task_id).status is TaskStatus.COMPLETED)
    )

    viewer_status, viewer_body = post(
        "/api/v1/tasks/%s/transitions" % write_task_id,
        "viewer-token",
        {"target": "RUNNING", "reason": "viewer attempt"},
    )
    print("viewer token transition -> %d %s" % (viewer_status, dump(viewer_body)))
    checks.append(("viewer token cannot transition", viewer_status == 403))

    audit_status, audit_body = fetch("/api/v1/audit")
    print("GET /api/v1/audit without token -> %d" % audit_status)
    checks.append(("audit endpoint needs its own token", audit_status == 401))

    server.shutdown()
    server.server_close()

    # 8. Survey rules: five states, exceptions and missing preconditions are
    # never reported as PASS.
    section("8. survey rules")
    rule_engine = SurveyRuleEngine()
    pack = rule_engine.load_pack(
        os.path.join(PROJECT_ROOT, "geoops", "survey", "packs", "p01_dataset.json")
    )
    print("pack p01_dataset -> %d rules %s"
          % (len(pack), [rule.rule_id for rule in pack]))
    checks.append(("rule pack loads four rules", len(pack) == 4))

    complete_context = {
        "path": os.path.join(PROJECT_ROOT, "README.md"),
        "crs": "EPSG:4490",
        "metadata_source": "sidecar:README.md.json",
        "project_id": project.object_id,
        "project_registered": True,
    }
    clean = rule_engine.evaluate("land_use_classification", complete_context)
    for result in clean:
        print("  %-10s %-7s %s :: %s"
              % (result.rule_id, result.status.value, result.rule_name, result.detail))
    clean_summary = rule_engine.summary(clean)
    print("summary -> %s" % dump(clean_summary))
    checks.append(("complete context passes all rules", clean_summary["total"] == 4
                   and clean_summary["FAIL"] == 0 and clean_summary["blocking"] == 0))

    # The real intake record has no CRS and no sidecar: that must fail and warn,
    # not pass quietly.
    intake_context = {
        "path": os.path.join(PROJECT_ROOT, "README.md"),
        "crs": record.crs,
        "metadata_source": record.metadata_source,
        "project_id": project.object_id,
        "project_registered": True,
    }
    intake_results = rule_engine.evaluate("land_use_classification", intake_context)
    for result in intake_results:
        print("  %-10s %-7s %s :: %s"
              % (result.rule_id, result.status.value, result.rule_name, result.detail))
    intake_summary = rule_engine.summary(intake_results)
    print("summary -> %s" % dump(intake_summary))
    checks.append(
        (
            "missing CRS fails and missing sidecar warns",
            intake_summary["FAIL"] >= 1
            and intake_summary["WARNING"] == 1
            and intake_summary["blocking"] >= 1,
        )
    )

    # A project that is not registered must block, and an unknown task type
    # evaluates no rule at all.
    unregistered = rule_engine.evaluate(
        "land_use_classification",
        {
            "path": os.path.join(PROJECT_ROOT, "README.md"),
            "crs": "EPSG:4490",
            "metadata_source": "sidecar",
            "project_id": "PRJ-TASK-NOT-REGISTERED",
            "project_registered": False,
        },
    )
    unregistered_summary = rule_engine.summary(unregistered)
    print("unregistered project -> %s" % dump(unregistered_summary))
    checks.append(("unregistered project blocks", unregistered_summary["blocking"] >= 1))

    other_task = rule_engine.evaluate("map_compilation", complete_context)
    print("task type without rules -> total=%d" % rule_engine.summary(other_task)["total"])
    checks.append(("rules are scoped by task type", len(other_task) == 0))

    # 8b. The rule engine as an explicit workflow node: blocking rules stop the
    # deliverable, warnings pass through but stay in the record.
    section("8b. rule gate node")
    gate = rule_check_node("R1", "rule gate", rule_engine, "land_use_classification")
    blocked_context = dict(intake_context)
    blocked_run = run_workflow(
        [
            gate,
            Node("R2", "deliverable", lambda ctx: NodeResult(NodeStatus.PASS, "deliverable written")),
        ],
        blocked_context,
        run_id="RUN-SMOKE-006",
    )
    for node_run in blocked_run.node_runs:
        print("  %-4s %-7s %s :: %s"
              % (node_run.node_id, node_run.status.value, node_run.name, node_run.detail))
    print("run %s -> status=%s" % (blocked_run.run_id, blocked_run.status.value))
    checks.append(
        (
            "blocking rule stops the deliverable",
            blocked_run.status is NodeStatus.FAIL
            and blocked_run.node_runs[1].status is NodeStatus.SKIPPED
            and blocked_context["rule_results"]["R1"][0]["status"] == "FAIL",
        )
    )

    fixed_context = dict(blocked_context)
    fixed_context["crs"] = "EPSG:4490"
    fixed_context["metadata_source"] = "sidecar:README.md.json"

    def deliverable_two(ctx):
        registry.register(ObjectType.DELIVERABLE, "DLV-SMOKE-002", {"stage": "after rule gate"})
        return NodeResult(NodeStatus.PASS, "deliverable registered")

    passed_run = run_workflow(
        [gate, Node("R2", "deliverable", deliverable_two)],
        fixed_context,
        run_id="RUN-SMOKE-007",
    )
    for node_run in passed_run.node_runs:
        print("  %-4s %-7s %s :: %s"
              % (node_run.node_id, node_run.status.value, node_run.name, node_run.detail))
    print("run %s -> status=%s" % (passed_run.run_id, passed_run.status.value))
    checks.append(
        (
            "fixed context passes the gate and reaches the deliverable",
            passed_run.status is NodeStatus.PASS
            and registry.get("DLV-SMOKE-002") is not None,
        )
    )

    warning_context = dict(fixed_context)
    warning_context["metadata_source"] = "none"
    warning_run = run_workflow([gate], warning_context, run_id="RUN-SMOKE-008")
    print("warning-only run %s -> status=%s stored=%s"
          % (warning_run.run_id, warning_run.status.value,
             [row["status"] for row in warning_context["rule_results"]["R1"]]))
    checks.append(
        (
            "warning-only gate passes with the warning recorded",
            warning_run.status is NodeStatus.PASS
            and any(row["status"] == "WARNING"
                    for row in warning_context["rule_results"]["R1"]),
        )
    )

    idle_context = {"crs": "EPSG:4490"}
    idle_gate = rule_check_node("R1", "rule gate", rule_engine, "map_compilation")
    idle_run = run_workflow([idle_gate], idle_context, run_id="RUN-SMOKE-009")
    print("no-rule task run %s -> node=%s detail=%s"
          % (idle_run.run_id, idle_run.node_runs[0].status.value,
             idle_run.node_runs[0].detail))
    checks.append(
        (
            "gate with no applicable rule records SKIP",
            idle_run.node_runs[0].status is NodeStatus.SKIP,
        )
    )

    # 9. Snapshot persistence: save, restore and reject a corrupt file.
    section("9. snapshot persistence")
    temp_dir = tempfile.mkdtemp(prefix="geoops-smoke-")
    store = SnapshotStore(os.path.join(temp_dir, "state.json"))
    snapshot = store.save(registry, tasks)
    print("saved -> objects=%d tasks=%d file=%s"
          % (len(snapshot["objects"]), len(snapshot["tasks"]), store.path))

    restored_registry = DomainRegistry()
    restored_tasks = TaskEngine(restored_registry)
    restored_summary = store.restore(restored_registry, restored_tasks)
    print("restored -> %s" % dump(restored_summary))
    checks.append(
        (
            "snapshot restores every object and task",
            restored_summary["objects"] == len(registry)
            and restored_summary["tasks"] == len(tasks.list())
            and len(restored_registry) == len(registry),
        )
    )

    restored_retry = restored_tasks.get(retried.task_id)
    print("restored task %s -> status=%s version=%d runs=%s"
          % (restored_retry.task_id, restored_retry.status.value,
             restored_retry.version, restored_retry.workflow_run_ids))
    checks.append(
        (
            "task status, version and runs survive a restart",
            restored_retry.status is TaskStatus.COMPLETED
            and restored_retry.version == retried.version
            and restored_retry.workflow_run_ids == retried.workflow_run_ids,
        )
    )

    corrupt_path = os.path.join(temp_dir, "corrupt.json")
    with open(corrupt_path, "w", encoding="utf-8") as handle:
        handle.write("{ this is not json")
    try:
        SnapshotStore(corrupt_path).load()
        corrupt_rejected = False
    except StoreError:
        corrupt_rejected = True
    print("corrupt snapshot -> rejected=%s" % corrupt_rejected)
    checks.append(("corrupt snapshot is rejected", corrupt_rejected))

    old_snapshot = os.path.join(temp_dir, "state_v0.json")
    with open(old_snapshot, "w", encoding="utf-8") as handle:
        json.dump(
            {"format": "geoops-snapshot", "version": 0, "saved_at": "2026-11-16T00:00:00Z",
             "objects": [], "tasks": []},
            handle,
        )
    try:
        SnapshotStore(old_snapshot).load()
        old_version_rejected = False
    except StoreError as exc:
        old_version_rejected = True
        print("older snapshot version -> refused :: %s" % exc)
    checks.append(("an older snapshot version is refused, not guessed", old_version_rejected))

    # 10. Execution report: copies recorded values only; gaps say NOT_RECORDED.
    section("10. execution report")
    deliverable_file = os.path.join(temp_dir, "ortho_result.tif")
    with open(deliverable_file, "wb") as handle:
        handle.write(b"GEOOPS smoke deliverable bytes, not a real ortho\n")
    artifacts = ArtifactStore(root=temp_dir, registry=registry)
    artifact_row = artifacts.register(
        deliverable_file, task_id=retried.task_id, kind="ortho", label="smoke ortho"
    )
    report = build_report(
        retried,
        [failing, resumed],
        warning_context["rule_results"],
        no_crs,
        registry.get("DLV-SMOKE-002"),
        artifacts=artifacts.for_task(retried.task_id),
    )
    print("report -> task=%s runs=%d rules=%s quality=%s review=%s artifacts=%d"
          % (report["task"]["task_id"], len(report["workflow_runs"]),
             report["rules"]["counts"], report["quality"]["report"]["status"],
             report["review"]["status"], report["artifact_files"]["count"]))
    json_path = write_report(report, os.path.join(temp_dir, "report.json"))
    md_path = write_report(report, os.path.join(temp_dir, "report.md"), fmt="md")
    print("report files -> %s | %s" % (json_path, md_path))
    with open(json_path, encoding="utf-8") as handle:
        parsed_report = json.load(handle)
    with open(md_path, encoding="utf-8") as handle:
        markdown_report = handle.read()
    checks.append(("report round-trips through json", parsed_report == report))
    checks.append(
        (
            "markdown report names the task and the unrecorded review",
            retried.task_id in markdown_report
            and "NOT_RECORDED" in markdown_report
            and "RUN-SMOKE-003" in markdown_report,
        )
    )

    # 11. Grants come from a file of hashes; the audit trail survives a reload.
    section("11. token file and audit file")
    token_file = os.path.join(temp_dir, "tokens.json")
    with open(token_file, "w", encoding="utf-8") as handle:
        json.dump(
            {
                "format": "geoops-tokens",
                "version": 1,
                "tokens": [
                    {
                        "sha256": hash_token("smoke-admin-token"),
                        "permissions": ["task:create", "task:transition", "audit:read"],
                    }
                ],
            },
            handle,
        )
    file_policy = PermissionPolicy.from_file(token_file)
    print("token file -> grants=%d admin_ok=%s unknown_ok=%s"
          % (len(file_policy), file_policy.known("smoke-admin-token"),
             file_policy.known("not-in-file")))
    checks.append(
        (
            "token file grants the real token and no other",
            file_policy.known("smoke-admin-token")
            and file_policy.permits("smoke-admin-token", "task:transition")
            and not file_policy.known("not-in-file"),
        )
    )

    audit_file = os.path.join(temp_dir, "audit.jsonl")
    file_audit = AuditLog(path=audit_file)
    file_audit.record("POST", "/api/v1/tasks", "smoke-admin-token", "deny", "missing permission", 403)
    file_audit.record("POST", "/api/v1/tasks", "smoke-admin-token", "allow", "created", 201)
    reloaded_audit = AuditLog(path=audit_file)
    print("audit file -> rows=%d denied=%d first_fp=%s"
          % (len(reloaded_audit.rows()), reloaded_audit.denied(),
             reloaded_audit.rows()[0]["token_fp"]))
    checks.append(
        (
            "audit rows survive a reload without the raw token",
            len(reloaded_audit.rows()) == 2
            and reloaded_audit.denied() == 1
            and reloaded_audit.rows()[0]["token_fp"] != "smoke-admin-token",
        )
    )

    with open(audit_file, "a", encoding="utf-8") as handle:
        handle.write("{ this is not json\n")
    try:
        AuditLog(path=audit_file)
        bad_audit_rejected = False
    except AuditError:
        bad_audit_rejected = True
    print("corrupt audit line -> rejected=%s" % bad_audit_rejected)
    checks.append(("corrupt audit file is refused, not trimmed", bad_audit_rejected))

    # 12. The registered deliverable is a real file, and its hash can be re-checked.
    section("12. deliverable registry")
    real_digest = hashlib.sha256(open(deliverable_file, "rb").read()).hexdigest()
    print("registered -> id=%s size=%d sha=%s"
          % (artifact_row["artifact_id"], artifact_row["size"], artifact_row["sha256"][:12]))
    checks.append(
        (
            "registered size and hash match the file",
            artifact_row["size"] == os.path.getsize(deliverable_file)
            and artifact_row["sha256"] == real_digest,
        )
    )

    again = artifacts.register(deliverable_file, task_id=retried.task_id, kind="ortho")
    checks.append(
        (
            "registering the same file twice returns the same row",
            again["artifact_id"] == artifact_row["artifact_id"] and len(artifacts) == 1,
        )
    )

    bound_file = os.path.join(temp_dir, "ortho_meta.json")
    with open(bound_file, "w", encoding="utf-8") as handle:
        handle.write('{"crs": "EPSG:4547"}\n')
    bound = artifacts.register(
        bound_file,
        task_id=retried.task_id,
        kind="metadata",
        deliverable_id="DLV-SMOKE-002",
    )
    print("bound artifact -> id=%s deliverable=%s files=%d"
          % (bound["artifact_id"], bound["deliverable_id"],
             len(artifacts.for_deliverable("DLV-SMOKE-002"))))
    checks.append(
        (
            "artifact binds to a registered deliverable",
            bound["deliverable_id"] == "DLV-SMOKE-002"
            and len(artifacts.for_deliverable("DLV-SMOKE-002")) == 1,
        )
    )

    copy_file = os.path.join(temp_dir, "ortho_meta_copy.json")
    with open(copy_file, "w", encoding="utf-8") as handle:
        handle.write('{"crs": "EPSG:4547"}\n')
    try:
        artifacts.register(copy_file, deliverable_id="DLV-NOT-REGISTERED")
        unbound_rejected = False
    except ArtifactError as exc:
        unbound_rejected = "not registered" in str(exc)
        print("unregistered deliverable -> refused :: %s" % exc)
    checks.append(("a file cannot bind to an unregistered deliverable", unbound_rejected))

    verify_ok = artifacts.verify_all()[0]["ok"]
    print("verify before edit -> ok=%s" % verify_ok)
    checks.append(("verify passes on an untouched file", verify_ok is True))

    with open(deliverable_file, "ab") as handle:
        handle.write(b"tampered\n")
    drift = artifacts.verify_all()[0]
    print("verify after edit -> ok=%s detail=%s" % (drift["ok"], drift["detail"]))
    checks.append(("an edited file no longer verifies", drift["ok"] is False))

    index_path = os.path.join(temp_dir, "artifacts.json")
    artifacts.save(index_path)
    reloaded = ArtifactStore(index_path=index_path)
    checks.append(
        (
            "artifact index reloads with the same count",
            len(reloaded) == len(artifacts) and reloaded.all()[0]["sha256"] == real_digest,
        )
    )
    checks.append(
        (
            "report carries the registered deliverable file",
            report["artifact_files"]["status"] == "RECORDED"
            and report["artifact_files"]["records"][0]["sha256"] == real_digest,
        )
    )

    # 13. A token can expire, and rotating one really replaces it.
    section("13. token expiry and rotation")
    stamps = {
        "past": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 3600)),
        "future": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 3600)),
    }
    expiring = PermissionPolicy()
    expiring.grant("will-expire-token", ["audit:read"], expires_at=stamps["past"])
    allowed, reason = expiring.check("will-expire-token", "audit:read")
    print("expired token -> known=%s allowed=%s reason=%s"
          % (expiring.known("will-expire-token"), allowed, reason))
    checks.append(
        (
            "an expired token is refused with its own reason",
            allowed is False and reason == "token expired",
        )
    )

    expiring.grant("rotating-token", ["task:create", "task:transition"],
                   issued_at=stamps["past"], expires_at=stamps["future"])
    expiring.rotate("rotating-token", "rotated-token")
    print("rotated token -> old_known=%s new_perms=%s"
          % (expiring.known("rotating-token"), expiring.permissions("rotated-token")))
    checks.append(
        (
            "rotation drops the old token and keeps its permissions",
            expiring.known("rotating-token") is False
            and expiring.permits("rotated-token", "task:transition")
            and expiring.permissions("rotated-token") == ["task:create", "task:transition"],
        )
    )

    expiring.grant("narrow-token", ["task:create", "task:transition"])
    expiring.rotate("narrow-token", "narrowed-token", permissions=["task:create"])
    checks.append(
        (
            "rotation can narrow the permissions",
            expiring.permissions("narrowed-token") == ["task:create"]
            and expiring.permits("narrowed-token", "task:transition") is False,
        )
    )

    # 14. Product rules for ortho and change detection, checked against real files.
    section("14. product rules (ortho / change detection)")
    product_engine = SurveyRuleEngine()
    product_engine.load_pack(
        os.path.join(PROJECT_ROOT, "geoops", "survey", "packs", "p02_products.json")
    )
    ortho_count = len(product_engine.enabled_rules("ortho_generation"))
    change_count = len(product_engine.enabled_rules("change_detection"))
    print("pack p02_products -> total=%d ortho=%d change=%d"
          % (len(product_engine.rules()), ortho_count, change_count))
    checks.append(
        (
            "product pack loads and is scoped 4 + 3",
            len(product_engine.rules()) == 7 and ortho_count == 4 and change_count == 3,
        )
    )

    ortho_context = {
        "crs": "EPSG:4547",
        "gsd_m": 0.2,
        "nodata": 0,
        "deliverable_path": deliverable_file,
    }
    ortho_results = product_engine.evaluate("ortho_generation", ortho_context)
    ortho_summary = product_engine.summary(ortho_results)
    print("ortho PASS context -> %s" % dump(ortho_summary))
    checks.append(
        (
            "a complete ortho context passes all four rules",
            ortho_summary["PASS"] == 4 and ortho_summary["blocking"] == 0,
        )
    )

    bad_crs = dict(ortho_context, crs="EPSG:4490")
    bad_results = product_engine.evaluate("ortho_generation", bad_crs)
    bad_ids = [row.rule_id for row in product_engine.blocking(bad_results)]
    print("ortho geographic CRS -> blocking=%s" % bad_ids)
    checks.append(
        (
            "a geographic CRS blocks the ortho product",
            bad_ids == ["R-OR-001"],
        )
    )

    baseline_file = os.path.join(temp_dir, "baseline.tif")
    comparison_file = os.path.join(temp_dir, "comparison.tif")
    for path in (baseline_file, comparison_file):
        with open(path, "wb") as handle:
            handle.write(b"temporal slice\n")
    change_context = {
        "baseline_path": baseline_file,
        "comparison_path": comparison_file,
        "crs_baseline": "EPSG:4547",
        "crs_comparison": "EPSG:4548",
        "min_area_m2": 5,
    }
    change_results = product_engine.evaluate("change_detection", change_context)
    change_ids = [row.rule_id for row in product_engine.blocking(change_results)]
    print("change detection CRS mismatch -> blocking=%s" % change_ids)
    checks.append(("mismatched CRSs block change detection", change_ids == ["R-CD-002"]))

    # 15. One run: rule gate, then registration. The product either earns its
    # hash or the run stops before it is registered.
    section("15. rule gate then registration, one run")
    delivery_file = os.path.join(temp_dir, "ortho_delivery.tif")
    with open(delivery_file, "wb") as handle:
        handle.write(b"GEOOPS clean product for the delivery run\n")
    delivery_digest = hashlib.sha256(open(delivery_file, "rb").read()).hexdigest()
    deliverable_store = ArtifactStore(root=temp_dir, registry=registry)
    gate = rule_check_node("O1", "ortho rules", product_engine, "ortho_generation")
    register = artifact_register_node(
        "O2",
        "register product",
        deliverable_store,
        deliverable_id="DLV-SMOKE-002",
        task_id=retried.task_id,
        kind="ortho",
    )
    good_context = {
        "task_id": retried.task_id,
        "crs": "EPSG:4547",
        "gsd_m": 0.2,
        "nodata": 0,
        "deliverable_path": delivery_file,
    }
    good_run = run_workflow([gate, register], good_context, run_id="RUN-SMOKE-010")
    for node_run in good_run.node_runs:
        print("  %-4s %-7s %s :: %s"
              % (node_run.node_id, node_run.status.value, node_run.name, node_run.detail))
    print("run %s -> status=%s artifacts=%d"
          % (good_run.run_id, good_run.status.value, len(good_context.get("artifacts", {}))))
    checks.append(
        (
            "one run passes the ortho rules and registers the hash",
            good_run.status is NodeStatus.PASS
            and good_context["artifacts"]["O2"]["sha256"] == delivery_digest,
        )
    )

    bad_context = {
        "task_id": retried.task_id,
        "crs": "EPSG:4490",
        "gsd_m": 0.2,
        "nodata": 0,
        "deliverable_path": delivery_file,
    }
    bad_run = run_workflow([gate, register], bad_context, run_id="RUN-SMOKE-011")
    print("bad CRS run -> status=%s register_node=%s artifacts=%d"
          % (bad_run.status.value, bad_run.node_runs[1].status.value,
             len(bad_context.get("artifacts", {}))))
    checks.append(
        (
            "a geographic CRS stops the run before registration",
            bad_run.status is NodeStatus.FAIL
            and bad_run.node_runs[1].status is NodeStatus.SKIPPED
            and not bad_context.get("artifacts"),
        )
    )

    run_report = build_report(
        {"task_id": retried.task_id, "name": "ortho run", "project_id": project.object_id,
         "task_type": "ortho_generation", "status": "COMPLETED"},
        [good_run],
        good_context["rule_results"],
        artifacts=list(good_context["artifacts"].values()),
    )
    print("run report -> rules=%s artifacts=%d"
          % (run_report["rules"]["counts"], run_report["artifact_files"]["count"]))
    checks.append(
        (
            "the report carries both the rule verdicts and the file hash",
            run_report["rules"]["counts"]["PASS"] == 4
            and run_report["artifact_files"]["records"][0]["sha256"] == delivery_digest,
        )
    )

    # 16. Change detection end to end: gate, compare two real grids, write the
    # mask, register the file that was written. Cells are hand-countable:
    # 5x4 at cellsize 10 (100 m2 per cell); a 2-cell patch (200 m2) and a 1-cell
    # patch (100 m2), one nodata cell, min_area 150 drops the small patch.
    section("16. change detection end to end")
    change_baseline = os.path.join(temp_dir, "change_baseline.asc")
    change_comparison = os.path.join(temp_dir, "change_comparison.asc")
    change_mask = os.path.join(temp_dir, "change_mask.asc")
    header = (
        "ncols 5\nnrows 4\nxllcorner 500000\nyllcorner 4500000\ncellsize 10\n"
        "NODATA_value -9999\n"
    )
    baseline_grid = header + "10 10 10 10 10\n10 10 10 10 10\n10 10 10 10 10\n10 10 10 10 -9999\n"
    comparison_grid = (
        header + "10 10 10 10 10\n10 20 20 10 10\n10 10 10 10 10\n10 10 30 10 -9999\n"
    )
    for path, text in ((change_baseline, baseline_grid), (change_comparison, comparison_grid)):
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)

    change_store = ArtifactStore(root=temp_dir, registry=registry)
    change_gate = rule_check_node("C1", "change rules", product_engine, "change_detection")
    detect_node = change_detect_node("C2", "change detect", threshold=1, min_area_m2=150)
    change_register = artifact_register_node(
        "C3",
        "register change mask",
        change_store,
        deliverable_id="DLV-SMOKE-002",
        task_id=retried.task_id,
        kind="change_mask",
        path_key="change_output_path",
    )
    change_context = {
        "task_id": retried.task_id,
        "baseline_path": change_baseline,
        "comparison_path": change_comparison,
        "crs_baseline": "EPSG:4547",
        "crs_comparison": "EPSG:4547",
        "min_area_m2": 150,
        "change_output_path": change_mask,
    }
    change_run = run_workflow(
        [change_gate, detect_node, change_register], change_context, run_id="RUN-SMOKE-012"
    )
    for node_run in change_run.node_runs:
        print("  %-4s %-7s %s :: %s"
              % (node_run.node_id, node_run.status.value, node_run.name, node_run.detail))
    change_stats = change_context.get("change_result", {})
    print("change run %s -> status=%s changed=%s kept=%s dropped=%s patches=%d area=%s artifacts=%d"
          % (change_run.run_id, change_run.status.value, change_stats.get("changed_cells"),
             change_stats.get("kept_cells"), change_stats.get("dropped_cells"),
             len(change_stats.get("patches", [])), change_stats.get("changed_area_m2"),
             len(change_context.get("artifacts", {}))))
    checks.append(
        (
            "one run gates, compares, writes and registers the change mask",
            change_run.status is NodeStatus.PASS
            and change_stats.get("changed_cells") == 3
            and change_stats.get("kept_cells") == 2
            and change_stats.get("dropped_cells") == 1
            and len(change_context.get("artifacts", {})) == 1,
        )
    )

    mask_grid = read_ascii_grid(change_mask)
    mask_ones = sum(1 for value in mask_grid["values"] if value == 1)
    mask_nodata = sum(
        1 for value in mask_grid["values"] if value == mask_grid["header"]["nodata_value"]
    )
    print("mask -> ones=%d nodata_cells=%d cellsize=%s"
          % (mask_ones, mask_nodata, mask_grid["cellsize"]))
    checks.append(
        (
            "the written mask carries exactly the kept cells and the nodata hole",
            mask_ones == 2 and mask_nodata == 1,
        )
    )

    with open(change_mask, "rb") as handle:
        mask_digest = hashlib.sha256(handle.read()).hexdigest()
    registered_mask = change_context["artifacts"]["C3"]
    print("registered mask -> %s sha_match=%s"
          % (registered_mask["sha256"][:8], registered_mask["sha256"] == mask_digest))
    checks.append(
        (
            "the registered hash is the hash of the file that was written",
            registered_mask["sha256"] == mask_digest and registered_mask["size"] > 0,
        )
    )

    shifted = os.path.join(temp_dir, "change_shifted.asc")
    with open(shifted, "w", encoding="utf-8") as handle:
        handle.write(comparison_grid.replace("xllcorner 500000", "xllcorner 500010"))
    refused_context = {
        "baseline_path": change_baseline,
        "comparison_path": shifted,
        "change_output_path": os.path.join(temp_dir, "never_written.asc"),
    }
    refused_run = run_workflow([detect_node], refused_context, run_id="RUN-SMOKE-013")
    print("unaligned grids -> status=%s :: %s"
          % (refused_run.status.value, refused_run.node_runs[0].detail))
    checks.append(
        (
            "unaligned grids fail before a mask is written",
            refused_run.status is NodeStatus.FAIL
            and not os.path.exists(refused_context["change_output_path"]),
        )
    )

    # 17. Console: the HTML shell is served by the same process, and its
    # overview numbers come from the same registry the smoke just filled.
    section("17. console shell")
    run_journal = RunJournal()
    run_journal.record(change_run, task_id=str(change_context.get("task_id") or ""),
                       project_id="PRJ-SMOKE-001", actor="smoke")
    console_server = create_server(
        registry,
        extra={"version": "0.1.0", "kernel": "v0.2.2", "tier": "core"},
        tasks=tasks,
        rules=product_engine,
        artifacts=artifacts,
        runs=run_journal,
    )
    console_port = console_server.server_address[1]
    console_thread = threading.Thread(target=console_server.serve_forever, daemon=True)
    console_thread.start()
    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:%d/ui/" % console_port, timeout=5
        ) as response:
            console_html = response.read().decode("utf-8")
            console_status = response.status
        with urllib.request.urlopen(
            "http://127.0.0.1:%d/api/v1/overview" % console_port, timeout=5
        ) as response:
            console_overview = json.loads(response.read().decode("utf-8"))
        with urllib.request.urlopen(
            "http://127.0.0.1:%d/api/v1/runs" % console_port, timeout=5
        ) as response:
            console_runs = json.loads(response.read().decode("utf-8"))
    finally:
        console_server.shutdown()
        console_server.server_close()
    nav_hits = [label for label in ("总览", "项目", "任务", "AI 资源", "数据", "流程", "规则", "质量", "成果", "审核", "追溯", "设置") if label in console_html]
    print("console -> status=%s nav=%d overview objects=%d tasks=%d rules=%d artifacts=%d runs=%d"
          % (console_status, len(nav_hits), console_overview["objects"],
             console_overview["tasks"]["total"], console_overview["rules"]["rules"],
             console_overview["artifacts"]["count"], console_runs["count"]))
    checks.append(
        (
            "the console shell is served with its twelve sections",
            console_status == 200 and "Bumao GeoOps" in console_html and len(nav_hits) == 12,
        )
    )
    checks.append(
        (
            "the console overview counts match the live registry",
            console_overview["objects"] == len(registry)
            and console_overview["tasks"]["total"] == len(tasks.list())
            and console_overview["rules"]["rules"] == len(product_engine.rules()),
        )
    )
    checks.append(
        (
            "the run journal serves the real change run",
            console_runs["count"] == 1
            and console_runs["runs"][0]["run_id"] == change_run.run_id
            and console_runs["runs"][0]["status"] == change_run.status.value
            and len(console_runs["runs"][0]["node_runs"]) == len(change_run.node_runs),
        )
    )
    try:
        run_journal.record(change_run, actor="smoke")
        duplicate_refused = False
    except JournalError:
        duplicate_refused = True
    checks.append(
        (
            "the journal refuses a duplicate run_id",
            duplicate_refused and console_runs["count"] == 1,
        )
    )

    # Verdict from observed results.
    print("")
    print("assertions:")
    for name, ok in checks:
        print("  %s %s" % ("PASS" if ok else "FAIL", name))
    failed = [name for name, ok in checks if not ok]
    print("")
    if failed:
        print("SMOKE FAIL: %d assertion(s) failed" % len(failed))
        return 1
    print("SMOKE PASS: %d assertions" % len(checks))
    return 0


if __name__ == "__main__":
    sys.exit(main())
