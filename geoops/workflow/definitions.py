"""Workflow definitions: validated records that a run can be built from.

A definition is data, not a Python closure. It is validated (node ids unique,
node types known, required fields present), stored as a `Workflow` domain
object and optionally persisted to one atomic JSON file. A run is built from
that record, so the console cannot execute a different node graph than the one
it displays.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from typing import Any, Dict, List, Optional

from geoops.domain.registry import DomainRegistry, ObjectType

FORMAT = "geoops-workflows"
FILE_VERSION = 1
NODE_TYPES = {
    "data_input",
    "data_check",
    "model_call",
    "agent_execute",
    "gis_tool_call",
    "rule_check",
    "change_detection",
    "artifact_register",
    "review",
    "output",
    "model_chat",
}
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{1,63}$")


class WorkflowDefinitionError(ValueError):
    """The definition was refused; nothing was written."""


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _text(value: Any, field: str, required: bool = True) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise WorkflowDefinitionError("%s must not be empty" % field)
    return text


def _number(value: Any, field: str, minimum: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise WorkflowDefinitionError("%s must be a number" % field)
    if number < minimum:
        raise WorkflowDefinitionError("%s must be >= %s" % (field, minimum))
    return number


def validate_definition(
    workflow_id: str,
    name: str,
    task_type: str,
    nodes: Any,
    description: str = "",
) -> Dict[str, Any]:
    workflow_id = _text(workflow_id, "workflow_id")
    if not _ID.match(workflow_id):
        raise WorkflowDefinitionError(
            "workflow_id must be 2-64 chars of letters, digits, dot, dash or underscore"
        )
    name = _text(name, "name")
    task_type = _text(task_type, "task_type")
    description = str(description or "").strip()
    if not isinstance(nodes, list) or not nodes:
        raise WorkflowDefinitionError("nodes must be a non-empty list")
    if len(nodes) > 50:
        raise WorkflowDefinitionError("a definition may have at most 50 nodes")
    normalized: List[Dict[str, Any]] = []
    seen_ids = []
    seen_names = []
    for index, raw in enumerate(nodes):
        if not isinstance(raw, dict):
            raise WorkflowDefinitionError("node %d must be an object" % index)
        node_id = _text(raw.get("node_id"), "node[%d].node_id" % index)
        node_name = _text(raw.get("name"), "node[%d].name" % index)
        node_type = _text(raw.get("type"), "node[%d].type" % index)
        if node_type not in NODE_TYPES:
            raise WorkflowDefinitionError(
                "node[%d].type must be one of %s" % (index, ", ".join(sorted(NODE_TYPES)))
            )
        if node_id in seen_ids:
            raise WorkflowDefinitionError("duplicate node_id: %s" % node_id)
        if node_name in seen_names:
            raise WorkflowDefinitionError("duplicate node name: %s" % node_name)
        seen_ids.append(node_id)
        seen_names.append(node_name)
        item: Dict[str, Any] = {"node_id": node_id, "name": node_name, "type": node_type}

        if node_type == "rule_check":
            item["task_type"] = _text(raw.get("task_type") or task_type, "node[%d].task_type" % index)
        elif node_type == "change_detection":
            item["threshold"] = _number(raw.get("threshold", 1.0), "node[%d].threshold" % index)
            item["min_area_m2"] = _number(raw.get("min_area_m2", 0.0), "node[%d].min_area_m2" % index)
            for key in ("baseline_key", "comparison_key", "output_key"):
                if raw.get(key) is not None:
                    item[key] = _text(raw.get(key), "node[%d].%s" % (index, key))
        elif node_type in ("artifact_register", "output"):
            item["path_key"] = _text(raw.get("path_key") or "deliverable_path", "node[%d].path_key" % index)
            for key in ("deliverable_id", "kind", "label"):
                if raw.get(key) is not None:
                    item[key] = str(raw.get(key)).strip()
        elif node_type in ("model_chat", "model_call", "agent_execute"):
            if not (raw.get("prompt") or raw.get("prompt_key")):
                raise WorkflowDefinitionError("node[%d].%s needs prompt or prompt_key" % (index, node_type))
            item["prompt"] = str(raw.get("prompt") or "")
            item["prompt_key"] = str(raw.get("prompt_key") or "prompt")
            item["system"] = str(raw.get("system") or "")
            item["max_tokens"] = int(_number(raw.get("max_tokens", 512), "node[%d].max_tokens" % index, 1))
            if raw.get("model_id") is not None:
                item["model_id"] = str(raw["model_id"]).strip()
            if raw.get("agent_id") is not None:
                item["agent_id"] = str(raw["agent_id"]).strip()
        elif node_type in ("data_input", "data_check"):
            item["dataset_key"] = _text(raw.get("dataset_key") or "dataset_id", "node[%d].dataset_key" % index)
            if raw.get("dataset_id") is not None:
                item["dataset_id"] = str(raw["dataset_id"]).strip()
        elif node_type == "review":
            item["review_key"] = _text(raw.get("review_key") or "review_id", "node[%d].review_key" % index)
            item["deliverable_key"] = _text(
                raw.get("deliverable_key") or "deliverable_id", "node[%d].deliverable_key" % index
            )
        elif node_type == "gis_tool_call":
            item["tool_key"] = _text(raw.get("tool_key") or "tool_id", "node[%d].tool_key" % index)
            item["path_key"] = _text(raw.get("path_key") or "raster_path", "node[%d].path_key" % index)
            if raw.get("tool_id") is not None:
                item["tool_id"] = str(raw["tool_id"]).strip()
        normalized.append(item)
    return {
        "workflow_id": workflow_id,
        "name": name,
        "task_type": task_type,
        "description": description,
        "nodes": normalized,
        "node_count": len(normalized),
        "updated_at": _now(),
    }


class WorkflowDefinitionRegistry:
    """Store definitions as Workflow domain objects, optionally in one file."""

    def __init__(self, registry: DomainRegistry, path: Optional[str] = None) -> None:
        self.registry = registry
        self.path = os.path.abspath(path) if path else None
        if self.path and os.path.exists(self.path):
            self._load()

    def create(
        self,
        workflow_id: str,
        name: str,
        task_type: str,
        nodes: Any,
        description: str = "",
    ):
        payload = validate_definition(workflow_id, name, task_type, nodes, description)
        if self.registry.get(payload["workflow_id"]) is not None:
            raise WorkflowDefinitionError("duplicate workflow_id: %s" % payload["workflow_id"])
        try:
            obj = self.registry.register(ObjectType.WORKFLOW, payload["workflow_id"], payload)
        except ValueError as exc:
            raise WorkflowDefinitionError(str(exc)) from exc
        self._save()
        return obj

    def update(
        self,
        workflow_id: str,
        name: Optional[str] = None,
        task_type: Optional[str] = None,
        nodes: Optional[Any] = None,
        description: Optional[str] = None,
    ):
        existing = self.get(workflow_id)
        if existing is None:
            raise WorkflowDefinitionError("unknown workflow_id: %s" % workflow_id)
        payload = validate_definition(
            workflow_id,
            name if name is not None else existing.payload.get("name"),
            task_type if task_type is not None else existing.payload.get("task_type"),
            nodes if nodes is not None else existing.payload.get("nodes"),
            description if description is not None else existing.payload.get("description", ""),
        )
        payload["created_at"] = existing.created_at
        try:
            obj = self.registry.update(workflow_id, payload)
        except ValueError as exc:
            raise WorkflowDefinitionError(str(exc)) from exc
        self._save()
        return obj

    def get(self, workflow_id: str):
        obj = self.registry.get(str(workflow_id or "").strip())
        if obj is None or obj.object_type is not ObjectType.WORKFLOW:
            return None
        return obj

    def list(self):
        return self.registry.list_by_type(ObjectType.WORKFLOW)

    def _save(self) -> None:
        if not self.path:
            return
        rows = [obj.to_dict() for obj in self.list()]
        data = {"format": FORMAT, "version": FILE_VERSION, "workflows": rows}
        directory = os.path.dirname(self.path) or "."
        os.makedirs(directory, exist_ok=True)
        marker = (json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        handle, temp_path = tempfile.mkstemp(prefix=".workflows-", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(handle, "wb") as stream:
                stream.write(marker)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_path, self.path)
        finally:
            if os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass

    def _load(self) -> None:
        try:
            with open(self.path, encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise WorkflowDefinitionError("cannot read workflow file %s: %s" % (self.path, exc)) from exc
        if not isinstance(data, dict) or data.get("format") != FORMAT:
            raise WorkflowDefinitionError("not a GeoOps workflow file")
        if data.get("version") != FILE_VERSION:
            raise WorkflowDefinitionError("unsupported workflow file version: %r" % data.get("version"))
        rows = data.get("workflows")
        if not isinstance(rows, list):
            raise WorkflowDefinitionError("workflow file has no workflows list")
        for row in rows:
            if not isinstance(row, dict):
                raise WorkflowDefinitionError("workflow row must be an object")
            payload = row.get("payload")
            if not isinstance(payload, dict):
                raise WorkflowDefinitionError("workflow row has no payload")
            workflow_id = str(row.get("object_id") or payload.get("workflow_id") or "")
            if not workflow_id:
                raise WorkflowDefinitionError("workflow row has no workflow_id")
            validated = validate_definition(
                workflow_id,
                payload.get("name"),
                payload.get("task_type"),
                payload.get("nodes"),
                payload.get("description", ""),
            )
            # A reload must not rewrite the record's timestamps.
            validated["updated_at"] = str(payload.get("updated_at") or validated["updated_at"])
            if self.registry.get(workflow_id) is not None:
                raise WorkflowDefinitionError("duplicate workflow_id in file: %s" % workflow_id)
            obj = self.registry.register(ObjectType.WORKFLOW, workflow_id, validated)
            obj.created_at = str(row.get("created_at") or obj.created_at)
