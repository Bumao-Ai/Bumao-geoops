"""Structural smoke test for the GeoOps scaffold.

Run ``python -m geoops.smoke`` for the default no-data mode, or
``python -m geoops.smoke --data <path>`` to run the same pipeline against a
user-supplied dataset. No dataset is bundled and none is fabricated.

Every printed value comes from a live call. The final verdict is computed from
the observed results, not hardcoded.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import urllib.error
import urllib.request

from geoops.core_adapter import CoreAdapter
from geoops.core_adapter import core as core_bridge
from geoops.domain import DomainRegistry, ObjectType
from geoops.domain import datasets
from geoops.quality import QualityStatus, check_dataset
from geoops.workflow import Node, NodeResult, NodeStatus, run as run_workflow
from geoops.api import create_server

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

    section("5. workflow (failure stop)")
    registry.register(ObjectType.PROJECT, "PRJ-SMOKE-002", {"name": "failure run project"})

    def fail_node(context):
        outcome = check_dataset(
            os.path.join(PROJECT_ROOT, "data", "absent.tif"), {"crs": ""}
        )
        return NodeResult(NodeStatus.FAIL, dump(outcome.to_dict()))

    def never_node(context):
        registry.register(ObjectType.DELIVERABLE, "DLV-SMOKE-001", {"stage": "unreachable"})
        return NodeResult(NodeStatus.PASS, "should not run")

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

    # 7. API: two real endpoints over the registry built above.
    section("7. api")
    server = create_server(
        registry,
        extra={"registered_gates": adapter.registered_gates()},
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

    server.shutdown()
    server.server_close()

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
