"""Catalog of models, agents and tools, with availability that cannot be faked.

A model is not an agent and an agent is not a tool. The catalog keeps them
apart, records which ones are actually runnable, and refuses an agent that
points at a model or tool which is not registered.

Availability is checked, not taken on trust. A builtin adapter must be one this
repository really implements; an external adapter must point at a path that
exists, otherwise the record is stored as unavailable with the reason.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from geoops.domain.registry import DomainObject, DomainRegistry, ObjectType

BUILTIN_ADAPTERS = {"change_detection", "ascii_raster_diff", "survey_rule_engine"}
MODEL_KINDS = {"algorithm", "ai-model"}
TOOL_CATEGORIES = {"gis", "raster", "vector", "conversion"}


class CatalogError(ValueError):
    """A catalog record was refused; nothing was written."""


def _required(values: Dict[str, Any], label: str) -> None:
    missing = [key for key, value in values.items() if not str(value or "").strip()]
    if missing:
        raise CatalogError("%s is missing: %s" % (label, ", ".join(missing)))


class Catalog:
    def __init__(self, registry: DomainRegistry) -> None:
        self.registry = registry

    # ------------------------------------------------------------- models
    def register_model(
        self,
        model_id: str,
        name: str,
        version: str,
        kind: str,
        capability: str,
        adapter: str,
        available: bool = False,
    ) -> DomainObject:
        _required(
            {"model_id": model_id, "name": name, "version": version,
             "kind": kind, "capability": capability, "adapter": adapter},
            "model",
        )
        if kind not in MODEL_KINDS:
            raise CatalogError("model kind must be one of %s" % ", ".join(sorted(MODEL_KINDS)))
        available, reason = self._availability(adapter, available)
        payload = {
            "model_id": model_id,
            "name": name,
            "version": version,
            "kind": kind,
            "capability": capability,
            "adapter": adapter,
            "available": available,
            "reason": reason,
        }
        return self._register(ObjectType.MODEL, model_id, payload)

    # -------------------------------------------------------------- tools
    def register_tool(
        self,
        tool_id: str,
        name: str,
        version: str,
        category: str,
        adapter: str,
        available: bool = False,
        timeout_s: Optional[int] = None,
        error_handling: str = "",
    ) -> DomainObject:
        _required(
            {"tool_id": tool_id, "name": name, "version": version,
             "category": category, "adapter": adapter},
            "tool",
        )
        if category not in TOOL_CATEGORIES:
            raise CatalogError("tool category must be one of %s" % ", ".join(sorted(TOOL_CATEGORIES)))
        available, reason = self._availability(adapter, available)
        payload = {
            "tool_id": tool_id,
            "name": name,
            "version": version,
            "category": category,
            "adapter": adapter,
            "available": available,
            "reason": reason,
            "timeout_s": timeout_s,
            "error_handling": error_handling,
        }
        return self._register(ObjectType.TOOL, tool_id, payload)

    # ------------------------------------------------------------- agents
    def register_agent(
        self,
        agent_id: str,
        name: str,
        version: str,
        strategy: str,
        model_ids: List[str],
        tool_ids: List[str],
        description: str = "",
    ) -> DomainObject:
        _required(
            {"agent_id": agent_id, "name": name, "version": version, "strategy": strategy},
            "agent",
        )
        models = [self.get(ObjectType.MODEL, model_id) for model_id in model_ids]
        tools = [self.get(ObjectType.TOOL, tool_id) for tool_id in tool_ids]
        missing = [model_id for model_id, obj in zip(model_ids, models) if obj is None]
        missing += [tool_id for tool_id, obj in zip(tool_ids, tools) if obj is None]
        if missing:
            raise CatalogError("agent references unknown ids: %s" % ", ".join(missing))
        unavailable = [
            obj.object_id for obj in models + tools if not obj.payload.get("available")
        ]
        payload = {
            "agent_id": agent_id,
            "name": name,
            "version": version,
            "strategy": strategy,
            "model_ids": list(model_ids),
            "tool_ids": list(tool_ids),
            "description": description,
            "available": not unavailable,
            "reason": "" if not unavailable else "unavailable dependencies: %s" % ", ".join(unavailable),
        }
        return self._register(ObjectType.AGENT, agent_id, payload)

    # ------------------------------------------------------------- lookup
    def get(self, kind: Any, object_id: str) -> Optional[DomainObject]:
        obj = self.registry.get(object_id)
        if obj is None or obj.object_type is not ObjectType(kind):
            return None
        return obj

    def list(self, kind: Any) -> List[DomainObject]:
        return self.registry.list_by_type(ObjectType(kind))

    # ------------------------------------------------------------- helpers
    def _availability(self, adapter: str, available: bool):
        adapter = str(adapter)
        if adapter.startswith("builtin:"):
            name = adapter.split(":", 1)[1]
            if name not in BUILTIN_ADAPTERS:
                return False, "builtin adapter is not implemented: %s" % name
            return True, ""
        if adapter.startswith("external:"):
            path = adapter.split(":", 1)[1]
            if not available:
                return False, "adapter declared unavailable"
            if not os.path.exists(path):
                return False, "external adapter path does not exist: %s" % path
            return True, ""
        return False, "adapter must start with builtin: or external:"

    def _register(self, object_type: ObjectType, object_id: str, payload: Dict[str, Any]):
        object_id = str(object_id or "").strip()
        if self.registry.get(object_id) is not None:
            raise CatalogError("duplicate id: %s" % object_id)
        try:
            return self.registry.register(object_type, object_id, payload)
        except ValueError as exc:
            raise CatalogError(str(exc)) from exc
