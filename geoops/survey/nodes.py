"""Rule check as an explicit workflow node.

The node keeps the rule engine out of the executor: the executor only sees a
node action that returns a node result. Blocking rules (``FAIL`` or ``ERROR``)
fail the node, so the executor stops later nodes without any special case.
``WARNING`` and ``SKIPPED`` results leave the node passing, but every result is
written to ``context["rule_results"][node_id]`` so a report can show what was
checked, what was skipped and what failed.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from geoops.survey.rules import RuleStatus, SurveyRuleEngine
from geoops.workflow import Node, NodeResult, NodeStatus


def rule_check_node(
    node_id: str,
    name: str,
    engine: SurveyRuleEngine,
    task_type: str,
    context_builder: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
) -> Node:
    """Build a node that evaluates ``engine`` for ``task_type``.

    ``context_builder`` receives the workflow context and returns the rule
    context. Without one the workflow context is used as-is; a builder that
    raises turns the node into ``ERROR`` through the executor, not into PASS.
    """

    def action(context: Dict[str, Any]) -> NodeResult:
        rule_context = context_builder(context) if context_builder else dict(context)
        results = engine.evaluate(task_type, rule_context)
        summary = engine.summary(results)
        context.setdefault("rule_results", {})[node_id] = [
            result.to_dict() for result in results
        ]

        if summary["total"] == 0:
            # Nothing was checked. Reporting PASS here would claim a verdict
            # that never happened, so the node is recorded as SKIP.
            return NodeResult(
                NodeStatus.SKIP,
                "no rule applies to task_type %r; nothing was checked" % task_type,
                summary,
            )

        blocking = [
            result
            for result in results
            if result.status in (RuleStatus.FAIL, RuleStatus.ERROR)
        ]
        if blocking:
            detail = "blocking rules: " + ", ".join(
                "%s(%s)" % (result.rule_id, result.status.value) for result in blocking
            )
            # A rule that could not be evaluated is an ERROR at node level too;
            # downgrading it to FAIL would blur "failed" and "never ran".
            status = (
                NodeStatus.ERROR
                if any(result.status is RuleStatus.ERROR for result in blocking)
                else NodeStatus.FAIL
            )
            return NodeResult(status, detail, summary)

        detail = "checked=%d pass=%d warning=%d skipped=%d error=%d" % (
            summary["total"],
            summary["PASS"],
            summary["WARNING"],
            summary["SKIPPED"],
            summary["ERROR"],
        )
        return NodeResult(NodeStatus.PASS, detail, summary)

    return Node(node_id, name, action)
