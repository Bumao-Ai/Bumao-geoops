"""Change detection as a workflow node.

The node reads the two grid paths from the context, computes the mask, writes
it, and reports the statistics it actually observed. A refused input fails the
node, so the mask is never registered as a product of a comparison that did not
happen.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from geoops.survey.change import ChangeError, detect_changes, write_change_mask
from geoops.workflow import Node, NodeResult, NodeStatus


def change_detect_node(
    node_id: str,
    name: str,
    threshold: float = 1.0,
    baseline_key: str = "baseline_path",
    comparison_key: str = "comparison_path",
    output_key: str = "change_output_path",
    min_area_key: str = "min_area_m2",
    min_area_m2: Optional[float] = None,
) -> Node:
    """Build a node that compares two grids and writes the change mask."""

    def action(context: Dict[str, Any]) -> NodeResult:
        baseline = str(context.get(baseline_key) or "").strip()
        comparison = str(context.get(comparison_key) or "").strip()
        output = str(context.get(output_key) or "").strip()
        if not baseline or not comparison:
            return NodeResult(NodeStatus.FAIL, "both grid paths are required")
        if not output:
            return NodeResult(NodeStatus.FAIL, "%s is empty; nowhere to write the mask" % output_key)
        area = min_area_m2
        if area is None:
            raw_area = context.get(min_area_key)
            try:
                area = float(raw_area) if raw_area not in (None, "") else 0.0
            except (TypeError, ValueError):
                return NodeResult(NodeStatus.FAIL, "%s is not a number: %r" % (min_area_key, raw_area))
        try:
            result = detect_changes(baseline, comparison, threshold=threshold, min_area_m2=area)
            path = write_change_mask(result, output)
        except ChangeError as exc:
            return NodeResult(NodeStatus.FAIL, str(exc), {"baseline": baseline, "comparison": comparison})

        stats = {key: value for key, value in result.items() if key not in ("mask", "invalid_mask", "header")}
        stats["mask_path"] = path
        context["change_result"] = stats
        return NodeResult(
            NodeStatus.PASS,
            "changed=%d kept=%d dropped=%d patches=%d area=%.2f m2 nodata=%d mask=%s"
            % (
                result["changed_cells"],
                result["kept_cells"],
                result["dropped_cells"],
                len(result["patches"]),
                result["changed_area_m2"],
                result["nodata_cells"],
                os.path.basename(path),
            ),
            stats,
        )

    return Node(node_id, name, action)


__all__ = ["change_detect_node"]
