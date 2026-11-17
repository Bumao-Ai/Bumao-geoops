"""A workflow node that really calls the configured model.

If no model runtime is configured, the node raises ``ModelRuntimeError`` and
the executor records ``ERROR``. It never substitutes a canned answer, so a run
cannot look successful without a real provider behind it.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from geoops.ai.runtime import ModelRuntime
from geoops.workflow import Node, NodeResult, NodeStatus


def model_chat_node(
    node_id: str,
    name: str,
    runtime: ModelRuntime,
    model_id: str = "",
    prompt: str = "",
    prompt_key: str = "prompt",
    system: str = "",
    max_tokens: int = 512,
    context_key: str = "model_text",
) -> Node:
    """Build a node that calls an OpenAI-compatible model with a real prompt.

    ``prompt_key`` lets the caller put the prompt in the run context; the static
    ``prompt`` is the fallback. The returned text is stored under ``context_key``
    and also under ``context['node_outputs'][node_id]``.
    """

    def action(context: Dict[str, Any]) -> NodeResult:
        text_prompt = str(context.get(prompt_key) or prompt or "").strip()
        if not text_prompt:
            return NodeResult(
                NodeStatus.FAIL,
                "prompt is empty; set context[%r] or configure the node prompt" % prompt_key,
            )
        text_system = str(context.get("system_prompt") or system or "").strip()
        result = runtime.invoke(
            text_prompt,
            system=text_system,
            max_tokens=max_tokens,
            temperature=context.get("temperature"),
        )
        context[context_key] = result["text"]
        context.setdefault("node_outputs", {})[node_id] = result["text"]
        return NodeResult(
            NodeStatus.PASS,
            "model %s replied in %d ms (%d chars)"
            % (model_id or result["model"], result["elapsed_ms"], len(result["text"])),
            {
                "text": result["text"],
                "model": result["model"],
                "usage": result["usage"],
                "elapsed_ms": result["elapsed_ms"],
                "model_id": model_id,
            },
        )

    return Node(node_id, name, action)
