"""A built-in GIS tool node for ESRI ASCII grids.

This is the one real geospatial processing adapter available without GDAL/QGIS:
it reads a grid, validates its header and cells, and computes statistics over
valid cells. Any other ``tool_id`` is refused as ERROR; the node never pretends
that an external GIS call happened.
"""

from __future__ import annotations

from typing import Any, Dict

from geoops.survey.change import ChangeError, read_ascii_grid
from geoops.workflow.executor import Node, NodeResult, NodeStatus

TOOL_ID = "builtin:ascii_grid_profile"
ALIASES = {TOOL_ID, "ascii_grid_profile"}


def ascii_grid_profile_node(
    node_id: str,
    name: str,
    tool_id: str = "",
    tool_key: str = "tool_id",
    path_key: str = "raster_path",
) -> Node:
    def action(context: Dict[str, Any]) -> NodeResult:
        resolved_tool = str(context.get(tool_key) or tool_id or "").strip()
        if resolved_tool not in ALIASES:
            return NodeResult(
                NodeStatus.ERROR,
                "no GIS adapter for tool %r; only %s is available" % (resolved_tool or "<empty>", TOOL_ID),
            )
        path = str(context.get(path_key) or context.get("baseline_path") or "").strip()
        if not path:
            return NodeResult(NodeStatus.FAIL, "%s is empty; no raster to profile" % path_key)
        try:
            grid = read_ascii_grid(path)
        except ChangeError as exc:
            return NodeResult(NodeStatus.ERROR, "ascii profile failed: %s" % exc, {"path": path})
        nodata = grid["header"].get("nodata_value")
        valid = [value for value in grid["values"] if nodata is None or value != nodata]
        if not valid:
            return NodeResult(NodeStatus.FAIL, "grid has no valid cells after NODATA removal", {"path": path})
        output = {
            "tool_id": TOOL_ID,
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
        context.setdefault("node_outputs", {})[node_id] = output
        return NodeResult(
            NodeStatus.PASS,
            "builtin ascii profile: valid=%d min=%s max=%s mean=%.4f"
            % (len(valid), output["min"], output["max"], output["mean"]),
            output,
        )

    return Node(node_id, name, action)
