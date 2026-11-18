"""Build and execute a workflow from a stored definition.

The definition is validated by ``WorkflowDefinitionRegistry``; this service
turns its declared nodes into the same real node implementations used by the
smoke tests. An unknown node type or an unavailable dependency is refused before
execution, never silently skipped.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from geoops.workflow.definitions import WorkflowDefinitionError, WorkflowDefinitionRegistry
from geoops.workflow.executor import (
    Node,
    NodeResult,
    NodeRun,
    NodeStatus,
    WorkflowEngine,
    WorkflowRun,
)


class WorkflowError(ValueError):
    """A definition cannot be executed or a run cannot be recorded."""


class WorkflowService:
    def __init__(
        self,
        definitions: WorkflowDefinitionRegistry,
        rules: Any,
        runtime: Any,
        artifacts: Any,
        engine: Optional[WorkflowEngine] = None,
        journal: Any = None,
        tasks: Any = None,
        datasets: Any = None,
        reviews: Any = None,
        catalog: Any = None,
    ) -> None:
        self.definitions = definitions
        self.rules = rules
        self.runtime = runtime
        self.artifacts = artifacts
        self.engine = engine if engine is not None else WorkflowEngine()
        self.journal = journal
        self.tasks = tasks
        self.datasets = datasets
        self.reviews = reviews
        self.catalog = catalog

    def build_nodes(self, definition: Any) -> list:
        nodes = []
        for spec in definition.payload.get("nodes") or []:
            node_id = spec["node_id"]
            node_name = spec["name"]
            node_type = spec["type"]
            if node_type == "data_input":
                if self.datasets is None:
                    raise WorkflowError("dataset registry is not configured")
                from geoops.workflow.data_nodes import data_input_node
                nodes.append(
                    data_input_node(
                        node_id,
                        node_name,
                        self.datasets,
                        spec.get("dataset_key", "dataset_id"),
                        spec.get("dataset_id", ""),
                    )
                )
            elif node_type == "data_check":
                if self.datasets is None:
                    raise WorkflowError("dataset registry is not configured")
                from geoops.workflow.data_nodes import data_check_node
                nodes.append(
                    data_check_node(
                        node_id,
                        node_name,
                        self.datasets,
                        spec.get("dataset_key", "dataset_id"),
                        spec.get("dataset_id", ""),
                    )
                )
            elif node_type == "review":
                if self.reviews is None:
                    raise WorkflowError("review engine is not configured")
                from geoops.workflow.data_nodes import review_gate_node
                nodes.append(
                    review_gate_node(
                        node_id,
                        node_name,
                        self.reviews,
                        spec.get("review_key", "review_id"),
                        spec.get("deliverable_key", "deliverable_id"),
                    )
                )
            elif node_type == "gis_tool_call":
                from geoops.workflow.gis_nodes import ascii_grid_profile_node
                nodes.append(
                    ascii_grid_profile_node(
                        node_id,
                        node_name,
                        tool_id=spec.get("tool_id") or "",
                        tool_key=spec.get("tool_key", "tool_id"),
                        path_key=spec.get("path_key", "raster_path"),
                    )
                )
            elif node_type == "rule_check":
                if self.rules is None:
                    raise WorkflowError("rule engine is not configured")
                from geoops.survey.nodes import rule_check_node
                nodes.append(
                    rule_check_node(node_id, node_name, self.rules, spec["task_type"])
                )
            elif node_type == "change_detection":
                from geoops.survey.change_node import change_detect_node
                nodes.append(
                    change_detect_node(
                        node_id,
                        node_name,
                        threshold=spec.get("threshold", 1.0),
                        baseline_key=spec.get("baseline_key", "baseline_path"),
                        comparison_key=spec.get("comparison_key", "comparison_path"),
                        output_key=spec.get("output_key", "change_output_path"),
                        min_area_m2=spec.get("min_area_m2", 0.0),
                    )
                )
            elif node_type in ("artifact_register", "output"):
                if self.artifacts is None:
                    raise WorkflowError("artifact store is not configured")
                from geoops.delivery.nodes import artifact_register_node
                nodes.append(
                    artifact_register_node(
                        node_id,
                        node_name,
                        self.artifacts,
                        deliverable_id=spec.get("deliverable_id") or None,
                        path_key=spec.get("path_key", "deliverable_path"),
                        kind=spec.get("kind") or None,
                        label=spec.get("label") or None,
                    )
                )
            elif node_type == "agent_execute":
                if self.runtime is None:
                    raise WorkflowError("model runtime is not configured")
                if self.catalog is None:
                    raise WorkflowError("agent catalog is not configured")
                from geoops.ai.agent_node import agent_execute_node
                nodes.append(
                    agent_execute_node(
                        node_id,
                        node_name,
                        self.runtime,
                        self.catalog,
                        agent_id=spec.get("agent_id") or "",
                        prompt=spec.get("prompt") or "",
                        prompt_key=spec.get("prompt_key") or "prompt",
                        system=spec.get("system") or "",
                        max_tokens=spec.get("max_tokens") or 512,
                    )
                )
            elif node_type in ("model_chat", "model_call"):
                if self.runtime is None:
                    raise WorkflowError("model runtime is not configured")
                from geoops.ai.nodes import model_chat_node
                nodes.append(
                    model_chat_node(
                        node_id,
                        node_name,
                        self.runtime,
                        model_id=spec.get("model_id") or "",
                        prompt=spec.get("prompt") or "",
                        prompt_key=spec.get("prompt_key") or "prompt",
                        system=spec.get("system") or "",
                        max_tokens=spec.get("max_tokens") or 512,
                    )
                )
            else:
                raise WorkflowError("unknown node type: %s" % node_type)
        return nodes

    def _previous_run(self, run_id: str) -> WorkflowRun:
        previous = self.engine.get(run_id)
        if previous is not None:
            return previous
        if self.journal is not None:
            for row in self.journal.rows():
                if row.get("run_id") != run_id:
                    continue
                try:
                    return WorkflowRun(
                        run_id=run_id,
                        status=NodeStatus(row.get("status")),
                        skipped=int(row.get("skipped") or 0),
                        resumed_from=str(row.get("resumed_from") or ""),
                        node_runs=[
                            NodeRun(
                                node_id=str(node.get("node_id") or ""),
                                name=str(node.get("name") or ""),
                                status=NodeStatus(node.get("status")),
                                detail=str(node.get("detail") or ""),
                                output=node.get("output"),
                            )
                            for node in (row.get("node_runs") or [])
                        ],
                    )
                except (TypeError, ValueError) as exc:
                    raise WorkflowError("journal row %s cannot be reconstructed: %s" % (run_id, exc)) from exc
        raise WorkflowError("unknown run_id: %s" % run_id)

    def resume(
        self,
        workflow_id: str,
        previous_run_id: str,
        context: Optional[Dict[str, Any]] = None,
        task_id: str = "",
        project_id: str = "",
        actor: str = "",
        run_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        definition = self.definitions.get(workflow_id)
        if definition is None:
            raise WorkflowError("unknown workflow_id: %s" % workflow_id)
        previous = self._previous_run(previous_run_id)
        context = dict(context or {})
        context.setdefault("workflow_id", workflow_id)
        if task_id:
            context.setdefault("task_id", task_id)
        if task_id:
            if self.tasks is None:
                raise WorkflowError("task engine is not configured")
            task = self.tasks.get(task_id)
            if task is None:
                raise WorkflowError("unknown task_id: %s" % task_id)
            if task.status.value != "RUNNING":
                raise WorkflowError("task %s must be RUNNING before a run is attached" % task_id)
            if not project_id:
                project_id = task.project_id
                context.setdefault("project_id", project_id)
        nodes = self.build_nodes(definition)
        try:
            run = self.engine.resume(
                previous, nodes, context, run_id=run_id or "RUN-" + uuid.uuid4().hex[:12]
            )
        except ValueError as exc:
            raise WorkflowError(str(exc)) from exc
        if task_id:
            try:
                self.tasks.attach_run(task_id, run.run_id)
            except Exception as exc:
                raise WorkflowError(
                    "run %s completed but could not attach to task %s: %s" % (run.run_id, task_id, exc)
                ) from exc
        if self.journal is not None:
            try:
                self.journal.record(run, task_id=task_id, project_id=project_id, actor=actor)
            except Exception as exc:
                raise WorkflowError("run %s completed but the journal refused it: %s" % (run.run_id, exc)) from exc
        return {
            "workflow": definition.to_dict(),
            "run": run.to_dict(),
            "task_id": task_id,
            "project_id": project_id,
            "status": run.status.value,
        }

    def execute(
        self,
        workflow_id: str,
        context: Optional[Dict[str, Any]] = None,
        task_id: str = "",
        project_id: str = "",
        actor: str = "",
        run_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        definition = self.definitions.get(workflow_id)
        if definition is None:
            raise WorkflowError("unknown workflow_id: %s" % workflow_id)
        context = dict(context or {})
        context.setdefault("workflow_id", workflow_id)
        if task_id:
            context.setdefault("task_id", task_id)
        if project_id:
            context.setdefault("project_id", project_id)
        if task_id:
            if self.tasks is None:
                raise WorkflowError("task engine is not configured")
            task = self.tasks.get(task_id)
            if task is None:
                raise WorkflowError("unknown task_id: %s" % task_id)
            if task.status.value != "RUNNING":
                raise WorkflowError("task %s must be RUNNING before a run is attached" % task_id)
            if not project_id:
                project_id = task.project_id
                context.setdefault("project_id", project_id)
        nodes = self.build_nodes(definition)
        try:
            run = self.engine.start(nodes, context, run_id=run_id or "RUN-" + uuid.uuid4().hex[:12])
        except ValueError as exc:
            raise WorkflowError(str(exc)) from exc
        if task_id:
            try:
                self.tasks.attach_run(task_id, run.run_id)
            except Exception as exc:
                raise WorkflowError("run %s completed but could not attach to task %s: %s" % (run.run_id, task_id, exc)) from exc
        if self.journal is not None:
            try:
                self.journal.record(run, task_id=task_id, project_id=project_id, actor=actor)
            except Exception as exc:
                raise WorkflowError("run %s completed but the journal refused it: %s" % (run.run_id, exc)) from exc
        return {
            "workflow": definition.to_dict(),
            "run": run.to_dict(),
            "task_id": task_id,
            "project_id": project_id,
            "status": run.status.value,
        }
