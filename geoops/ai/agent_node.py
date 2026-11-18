"""An Agent node that resolves the declared Agent before calling a model.

An Agent is a registered orchestration resource, not another name for a model.
This node checks that the Agent exists in the catalog and that its declared
dependencies are available; it then uses the configured language model for the
agent's language step. It does not pretend to execute the Agent's GIS tools:
tool calls remain a separate node type and are refused when no adapter exists.
"""

from __future__ import annotations

from typing import Any, Dict

from geoops.ai.runtime import ModelRuntime
from geoops.domain.registry import ObjectType
from geoops.workflow import Node, NodeResult, NodeStatus


def agent_execute_node(
    node_id: str,
    name: str,
    runtime: ModelRuntime,
    catalog: Any,
    agent_id: str = "",
    prompt: str = "",
    prompt_key: str = "prompt",
    system: str = "",
    max_tokens: int = 512,
    context_key: str = "agent_text",
) -> Node:
    def action(context: Dict[str, Any]) -> NodeResult:
        resolved_id = str(context.get("agent_id") or agent_id or "").strip()
        if not resolved_id:
            return NodeResult(
                NodeStatus.FAIL,
                "agent_id is empty; an Agent node must name a registered Agent",
            )
        if catalog is None:
            return NodeResult(NodeStatus.FAIL, "agent catalog is not configured")
        agent = catalog.get(ObjectType.AGENT, resolved_id)
        if agent is None:
            return NodeResult(NodeStatus.FAIL, "unknown agent_id: %s" % resolved_id)
        payload = agent.payload
        if not payload.get("available"):
            return NodeResult(
                NodeStatus.ERROR,
                "agent %s is unavailable: %s" % (resolved_id, payload.get("reason") or "dependency unavailable"),
            )
        text_prompt = str(context.get(prompt_key) or prompt or "").strip()
        if not text_prompt:
            return NodeResult(
                NodeStatus.FAIL,
                "prompt is empty; set context[%r] or configure the Agent node prompt" % prompt_key,
            )
        text_system = "\n".join(
            part for part in (
                str(system or "").strip(),
                "Agent: %s v%s" % (payload.get("name"), payload.get("version")),
                "Strategy: %s" % (payload.get("strategy") or ""),
                "Declared model ids: %s" % ", ".join(payload.get("model_ids") or []),
                "Declared tool ids: %s" % ", ".join(payload.get("tool_ids") or []),
            ) if part
        )
        result = runtime.invoke(
            text_prompt,
            system=text_system,
            max_tokens=max_tokens,
            temperature=context.get("temperature"),
        )
        context[context_key] = result["text"]
        output = {
            "agent_id": resolved_id,
            "agent_version": payload.get("version"),
            "text": result["text"],
            "model": result["model"],
            "usage": result["usage"],
            "elapsed_ms": result["elapsed_ms"],
            "tool_execution": "not executed by this language adapter",
        }
        context.setdefault("node_outputs", {})[node_id] = output
        return NodeResult(
            NodeStatus.PASS,
            "agent %s replied via %s in %d ms" % (resolved_id, result["model"], result["elapsed_ms"]),
            output,
        )

    return Node(node_id, name, action)
