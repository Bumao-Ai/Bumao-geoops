"""Execute a registered Agent against its declared tools.

An Agent is not a prompt prefix. This executor asks the configured model for a
JSON plan, checks that the requested tool is actually declared by the Agent and
present in the catalog, runs only a real builtin adapter, records every call,
and loops until the model returns a final answer or the step budget is spent.
There is no fallback to a scripted answer when the model is unavailable.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional, Tuple

from geoops.domain.registry import ObjectType
from geoops.survey.change import ChangeError, detect_changes, read_raster_grid, write_change_mask
from geoops.workflow.external_tools import ExternalToolError, ExternalToolRegistry
from geoops.workflow import Node, NodeResult, NodeStatus

AGENT_SYSTEM = """You are an Agent inside Bumao GeoOps.
Return exactly one JSON object, without prose outside it.
To call a declared tool: {"tool": "<tool id>", "args": {...}}
When finished: {"final": "<answer>"}
Never invent a tool or claim an unlisted capability.
"""


class AgentExecutionError(RuntimeError):
    """An Agent step failed; no output is fabricated."""


def _usage_add(total: Dict[str, Any], usage: Dict[str, Any]) -> None:
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = usage.get(key) if isinstance(usage, dict) else None
        if isinstance(value, int):
            total[key] = int(total.get(key) or 0) + value


def _parse_plan(text: str) -> Tuple[Optional[str], Optional[Dict[str, Any]], Optional[str]]:
    """Return (tool_id, args, final_text) or raise AgentExecutionError."""
    text = str(text or "").strip()
    if not text:
        raise AgentExecutionError("model returned an empty plan")
    cleaned = text
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        # A plain answer is accepted only as a final answer; it never triggers
        # an invented tool call.
        return None, None, text
    if not isinstance(payload, dict):
        return None, None, text
    if isinstance(payload.get("final"), str):
        return None, None, payload["final"].strip()
    tool = payload.get("tool")
    args = payload.get("args")
    if not isinstance(tool, str) or not tool.strip():
        raise AgentExecutionError("plan has neither a final answer nor a tool id")
    if args is None:
        args = {}
    if not isinstance(args, dict):
        raise AgentExecutionError("tool args must be a JSON object")
    return tool.strip(), args, None


def _profile(args: Dict[str, Any]) -> Dict[str, Any]:
    path = str(args.get("path") or args.get("raster_path") or "").strip()
    if not path:
        raise AgentExecutionError("ascii_grid_profile needs path")
    grid = read_raster_grid(path)
    nodata = grid["header"].get("nodata_value")
    valid = [value for value in grid["values"] if nodata is None or value != nodata]
    if not valid:
        raise AgentExecutionError("grid has no valid cells after NODATA removal")
    return {
        "path": path,
        "ncols": grid["ncols"],
        "nrows": grid["nrows"],
        "cellsize": grid["cellsize"],
        "valid_cells": len(valid),
        "nodata_cells": len(grid["values"]) - len(valid),
        "min": min(valid),
        "max": max(valid),
        "mean": sum(valid) / len(valid),
    }


def _change(args: Dict[str, Any]) -> Dict[str, Any]:
    baseline = str(args.get("baseline") or args.get("baseline_path") or "").strip()
    comparison = str(args.get("comparison") or args.get("comparison_path") or "").strip()
    if not baseline or not comparison:
        raise AgentExecutionError("change detection needs baseline and comparison paths")
    try:
        threshold = float(args.get("threshold", 1.0))
        min_area = float(args.get("min_area_m2", 0.0))
    except (TypeError, ValueError) as exc:
        raise AgentExecutionError("threshold/min_area_m2 must be numbers") from exc
    result = detect_changes(
        baseline, comparison, threshold=threshold, min_area_m2=min_area
    )
    output = str(args.get("output") or args.get("change_output_path") or "").strip()
    mask_path = write_change_mask(result, output) if output else None
    stats = {
        key: value for key, value in result.items()
        if key not in ("mask", "invalid_mask", "header")
    }
    stats["mask_path"] = mask_path
    return stats


def _rules(args: Dict[str, Any], rules: Any) -> Dict[str, Any]:
    if rules is None:
        raise AgentExecutionError("rule engine is not available")
    task_type = str(args.get("task_type") or "").strip()
    if not task_type:
        raise AgentExecutionError("survey_rule_engine needs task_type")
    context = args.get("context") if isinstance(args.get("context"), dict) else {}
    rows = rules.evaluate(task_type, context)
    return {
        "task_type": task_type,
        "results": [
            {
                "rule_id": getattr(row, "rule_id", ""),
                "status": getattr(getattr(row, "status", None), "value", str(getattr(row, "status", ""))),
                "detail": getattr(row, "detail", ""),
            }
            for row in rows
        ],
    }


def execute_tool(
    tool_id: str,
    tool_payload: Dict[str, Any],
    args: Dict[str, Any],
    rules: Any = None,
) -> Dict[str, Any]:
    """Run one declared tool; unknown adapters are refused, never simulated."""
    adapter = str((tool_payload or {}).get("adapter") or tool_id).strip()
    if adapter in ("builtin:ascii_grid_profile", "ascii_grid_profile"):
        return _profile(args)
    if adapter in ("builtin:change_detection", "builtin:ascii_raster_diff",
                   "change_detection", "ascii_raster_diff"):
        return _change(args)
    if adapter in ("builtin:survey_rule_engine", "survey_rule_engine"):
        return _rules(args, rules)
    if adapter.startswith("external:"):
        try:
            result = ExternalToolRegistry().run(adapter, dict(args or {}))
        except ExternalToolError as exc:
            raise AgentExecutionError(str(exc)) from exc
        return result
    raise AgentExecutionError("no executable adapter for tool %s" % adapter)


def agent_execute_node(
    node_id: str,
    name: str,
    runtime: Any,
    catalog: Any,
    agent_id: str = "",
    prompt: str = "",
    prompt_key: str = "prompt",
    system: str = "",
    max_tokens: int = 512,
    max_steps: int = 8,
    rules: Any = None,
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
                "agent %s is unavailable: %s"
                % (resolved_id, payload.get("reason") or "dependency unavailable"),
            )
        text_prompt = str(context.get(prompt_key) or prompt or "").strip()
        if not text_prompt:
            return NodeResult(
                NodeStatus.FAIL,
                "prompt is empty; set context[%r] or configure the Agent node prompt" % prompt_key,
            )

        tool_ids = [str(item) for item in (payload.get("tool_ids") or []) if str(item).strip()]
        base_system = "\n".join(
            part for part in (
                str(system or "").strip(),
                AGENT_SYSTEM,
                "Agent: %s v%s" % (payload.get("name"), payload.get("version")),
                "Strategy: %s" % (payload.get("strategy") or ""),
                "Declared tools: %s" % (", ".join(tool_ids) if tool_ids else "none"),
            ) if part
        )
        steps: List[Dict[str, Any]] = []
        usage: Dict[str, Any] = {}
        elapsed_ms = 0
        last_model = ""
        history: List[str] = []
        started = time.monotonic()

        try:
            for step in range(1, max(1, min(16, int(max_steps))) + 1):
                plan_prompt = (
                    "Request:\n%s\n\nAvailable tools:\n%s\n\nPrevious steps:\n%s\n\n"
                    "Return one JSON plan now."
                    % (
                        text_prompt,
                        "\n".join("- %s" % item for item in tool_ids) or "(none)",
                        "\n".join(history) if history else "(none)",
                    )
                )
                call = runtime.invoke(
                    plan_prompt,
                    system=base_system,
                    max_tokens=max_tokens,
                    temperature=context.get("temperature"),
                )
                text = str(call.get("text") or "")
                last_model = str(call.get("model") or last_model)
                _usage_add(usage, call.get("usage") or {})
                elapsed_ms += int(call.get("elapsed_ms") or 0)
                tool, args, final = _parse_plan(text)
                if final is not None:
                    output = {
                        "agent_id": resolved_id,
                        "agent_version": payload.get("version"),
                        "text": final,
                        "final": final,
                        "steps": len(steps) + 1,
                        "tool_calls": steps,
                        "model": last_model,
                        "usage": usage,
                        "elapsed_ms": elapsed_ms,
                        "tool_execution": "executed by agent executor",
                    }
                    context[context_key] = final
                    context.setdefault("node_outputs", {})[node_id] = output
                    return NodeResult(
                        NodeStatus.PASS,
                        "agent %s finished after %d tool step(s)" % (resolved_id, len(steps)),
                        output,
                    )

                if not tool or tool not in tool_ids:
                    raise AgentExecutionError(
                        "model requested undeclared tool %r" % (tool or "<empty>")
                    )
                tool_obj = catalog.get(ObjectType.TOOL, tool)
                if tool_obj is None:
                    raise AgentExecutionError("tool is not registered: %s" % tool)
                if not tool_obj.payload.get("available"):
                    raise AgentExecutionError(
                        "tool %s is unavailable: %s" % (tool, tool_obj.payload.get("reason") or "not runnable")
                    )
                try:
                    result = execute_tool(tool, tool_obj.payload, args, rules=rules)
                    tool_status = "PASS"
                    detail = "tool executed"
                except Exception as exc:
                    raise AgentExecutionError(
                        "tool %s failed: %s: %s" % (tool, type(exc).__name__, exc)
                    ) from exc
                steps.append(
                    {
                        "step": step,
                        "tool_id": tool,
                        "args": args,
                        "status": tool_status,
                        "detail": detail,
                        "result": result,
                    }
                )
                history.append(
                    "step %d: %s -> %s"
                    % (step, tool, json.dumps(result, ensure_ascii=False)[:4000])
                )
                context.setdefault("agent_tool_calls", []).append(steps[-1])
        except Exception as exc:
            return NodeResult(
                NodeStatus.ERROR,
                "agent %s failed: %s: %s" % (resolved_id, type(exc).__name__, exc),
                {"agent_id": resolved_id, "steps": steps},
            )

        return NodeResult(
            NodeStatus.ERROR,
            "agent %s reached the step budget without a final answer" % resolved_id,
            {"agent_id": resolved_id, "steps": steps, "elapsed_ms": int((time.monotonic() - started) * 1000)},
        )

    return Node(node_id, name, action)


__all__ = ["AgentExecutionError", "agent_execute_node", "execute_tool"]
