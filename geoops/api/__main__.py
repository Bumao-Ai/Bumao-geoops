"""Run the GeoOps console.

    python -m geoops.api

Starts the HTTP API plus the HTML console at http://127.0.0.1:<port>/ui/

Flags:
    --port 8787            listen port (0 picks a free one)
    --demo                 register one project and two tasks through the real
                           domain API, so the console has something to show
    --tokens <file>        load grants from a geoops-tokens JSON file
    --audit <file>         append audit rows to this JSONL file
    --artifacts <file>     keep the artifact index at this JSON path
    --runs <file>          keep the run journal at this JSONL path

Without --tokens the server is read-only: write endpoints answer 404 and
nothing can be created. Values shown in the console come from the endpoints;
there is no seeded dashboard.
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid

from geoops.api import AuditLog, PermissionPolicy, create_server
from geoops.artifacts import ArtifactStore
from geoops.catalog import Catalog
from geoops.domain import DeliverableRegistry, DomainRegistry, TaskEngine
from geoops.domain.datasets_store import DatasetRegistry
from geoops.domain.projects import ProjectRegistry
from geoops.quality.service import QualityService
from geoops.survey import SurveyRuleEngine, rule_check_node
from geoops.workflow import Node, RunJournal, WorkflowEngine

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load_rules() -> SurveyRuleEngine:
    engine = SurveyRuleEngine()
    folder = os.path.join(PROJECT_ROOT, "geoops", "survey", "packs")
    if os.path.isdir(folder):
        for name in sorted(os.listdir(folder)):
            if name.endswith(".json"):
                engine.load_pack(os.path.join(folder, name))
    return engine


def _seed(registry: DomainRegistry, tasks: TaskEngine, rules: SurveyRuleEngine,
          journal: RunJournal) -> None:
    """Create real records through the domain API, then run one real workflow.

    No numbers are fabricated: the tasks below are registered by the same calls
    the API uses, and the run is a real execution whose rule gate checks a task
    type that no pack covers, so the node reports SKIP instead of a verdict.
    """
    ProjectRegistry(registry).register(
        "PRJ-CONSOLE-001",
        "DEMO-001",
        "控制台演示项目",
        "survey",
        "演示测区",
        "EPSG:4547",
        "1985 国家高程基准",
    )
    first = tasks.create("PRJ-CONSOLE-001", "变化检测演示任务", "change_detection", actor="console")
    tasks.transition(first.task_id, "READY", reason="两期栅格已就位", actor="console")
    tasks.create("PRJ-CONSOLE-001", "正射成果演示任务", "ortho_generation", actor="console")

    compile_task = tasks.create(
        "PRJ-CONSOLE-001", "图件编制演示任务", "map_compilation", actor="console"
    )
    tasks.transition(compile_task.task_id, "READY", reason="图件模板已定", actor="console")
    tasks.transition(compile_task.task_id, "RUNNING", reason="规则门开始", actor="console")
    gate = rule_check_node("R1", "规则门（图件编制）", rules, "map_compilation")
    engine = WorkflowEngine()
    run = engine.start(
        [Node(gate.node_id, gate.name, gate.action)],
        {"task_id": compile_task.task_id, "project_id": "PRJ-CONSOLE-001"},
        run_id="RUN-CONSOLE-%s" % uuid.uuid4().hex[:8],
    )
    tasks.attach_run(compile_task.task_id, run.run_id)
    tasks.transition(compile_task.task_id, "COMPLETED", reason="运行记录已写入", actor="console")
    journal.record(run, task_id=compile_task.task_id, project_id="PRJ-CONSOLE-001",
                   actor="console")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="GeoOps console")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--tokens", default="")
    parser.add_argument("--audit", default="")
    parser.add_argument("--artifacts", default="")
    parser.add_argument("--runs", default="")
    args = parser.parse_args(argv)

    registry = DomainRegistry()
    tasks = TaskEngine(registry)
    projects = ProjectRegistry(registry)
    datasets = DatasetRegistry(registry, projects)
    catalog = Catalog(registry)
    deliverables = DeliverableRegistry(registry)
    quality = QualityService(
        registry,
        datasets,
        report_dir=os.path.join(PROJECT_ROOT, "var", "quality"),
    )
    rules = _load_rules()
    policy = None
    if args.tokens:
        policy = PermissionPolicy.from_file(args.tokens)
    audit = AuditLog(path=args.audit or None)
    artifacts = None
    if args.artifacts:
        artifacts = ArtifactStore(root=os.getcwd(), index_path=args.artifacts, registry=registry)
    journal = RunJournal(args.runs or None)
    if args.demo:
        _seed(registry, tasks, rules, journal)


    server = create_server(
        registry,
        extra={"version": "0.1.0", "kernel": "v0.2.2", "tier": "核心工程 · CORE"},
        tasks=tasks,
        policy=policy,
        audit=audit,
        rules=rules,
        artifacts=artifacts,
        runs=journal,
        projects=projects,
        datasets=datasets,
        catalog=catalog,
        deliverables=deliverables,
        quality=quality,
        host=args.host,
        port=args.port,
    )
    url = "http://%s:%d/ui/" % (args.host, server.server_address[1])
    print("GeoOps console: %s" % url, flush=True)
    print("writes: %s" % ("enabled" if policy is not None else "disabled (read-only)"), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped", flush=True)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
