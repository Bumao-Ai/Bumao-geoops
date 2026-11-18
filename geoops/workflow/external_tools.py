"""Explicitly configured external GIS tools.

Nothing here guesses a GDAL/QGIS path. A tool exists only when the operator
lists it in a JSON file (``GEOOPS_EXTERNAL_TOOLS`` or
``var/external-tools.json``) with an absolute command and a fixed argument
template. The runner uses subprocess without a shell and surfaces stdout,
stderr and the exit code; a non-zero exit is an error, never a silent pass.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

PLACEHOLDER = re.compile(r"\{([A-Za-z0-9_.-]+)\}")


class ExternalToolError(ValueError):
    """The external tool is not configured, cannot run, or failed."""


def _default_path() -> str:
    if os.environ.get("GEOOPS_EXTERNAL_TOOLS"):
        return os.environ["GEOOPS_EXTERNAL_TOOLS"]
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(project_root, "var", "external-tools.json")


@dataclass
class ExternalTool:
    tool_id: str
    command: List[str]
    args: List[str] = field(default_factory=list)
    timeout: float = 60.0

    def run(self, params: Dict[str, Any]) -> Dict[str, Any]:
        missing = set()
        rendered = []
        for template in self.args:
            for key in PLACEHOLDER.findall(template):
                if key not in params:
                    missing.add(key)
            rendered.append(
                PLACEHOLDER.sub(
                    lambda match: str(params.get(match.group(1), "")), template
                )
            )
        if missing:
            raise ExternalToolError(
                "external tool %s is missing parameter(s): %s"
                % (self.tool_id, ", ".join(sorted(missing)))
            )
        if not self.command:
            raise ExternalToolError("external tool %s has an empty command" % self.tool_id)
        try:
            completed = subprocess.run(
                self.command + rendered,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                shell=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ExternalToolError(
                "external tool %s could not run: %s" % (self.tool_id, exc)
            ) from exc
        if completed.returncode != 0:
            raise ExternalToolError(
                "external tool %s exited %d: %s"
                % (
                    self.tool_id,
                    completed.returncode,
                    (completed.stderr or completed.stdout or "").strip()[:500],
                )
            )
        return {
            "tool_id": self.tool_id,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "command": self.command + rendered,
        }


class ExternalToolRegistry:
    def __init__(self, path: Optional[str] = None) -> None:
        self.path = os.path.abspath(path or _default_path())
        self.tools: Dict[str, ExternalTool] = {}
        self._load()

    def _load(self) -> None:
        if not os.path.isfile(self.path):
            return
        try:
            with open(self.path, encoding="utf-8-sig") as handle:
                payload = json.load(handle)
        except (OSError, ValueError) as exc:
            raise ExternalToolError("cannot read external tools %s: %s" % (self.path, exc)) from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("tools"), list):
            raise ExternalToolError("external tools file must contain a tools list")
        for index, row in enumerate(payload["tools"]):
            if not isinstance(row, dict):
                raise ExternalToolError("external tool %d must be an object" % index)
            tool_id = str(row.get("tool_id") or "").strip()
            command = row.get("command")
            args = row.get("args") or []
            if not tool_id or not isinstance(command, list) or not command:
                raise ExternalToolError("external tool %d needs tool_id and command" % index)
            if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
                raise ExternalToolError("external tool %s args must be strings" % tool_id)
            try:
                timeout = float(row.get("timeout") or 60)
            except (TypeError, ValueError):
                raise ExternalToolError("external tool %s timeout must be a number" % tool_id)
            if timeout <= 0:
                raise ExternalToolError("external tool %s timeout must be positive" % tool_id)
            self.tools[tool_id] = ExternalTool(
                tool_id=tool_id,
                command=[str(command[0])] + [str(part) for part in command[1:]],
                args=[str(part) for part in args],
                timeout=timeout,
            )

    def run(self, tool_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
        tool = self.tools.get(str(tool_id).strip())
        if tool is None:
            raise ExternalToolError(
                "external tool %r is not configured in %s"
                % (tool_id, self.path)
            )
        return tool.run(params)
