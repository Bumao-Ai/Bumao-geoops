"""Tests for explicitly configured external tool execution."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

from geoops.workflow.external_tools import ExternalToolError, ExternalToolRegistry
from geoops.workflow.gis_nodes import ascii_grid_profile_node


class ExternalToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.script = os.path.join(self.tmp.name, "echo_tool.py")
        with open(self.script, "w", encoding="utf-8") as handle:
            handle.write("import sys\nprint('GOT ' + sys.argv[1])\n")
        self.config = os.path.join(self.tmp.name, "tools.json")
        with open(self.config, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "tools": [
                        {
                            "tool_id": "external:echo",
                            "command": [sys.executable, self.script],
                            "args": ["{path}"],
                            "timeout": 10,
                        }
                    ]
                },
                handle,
            )
        os.environ["GEOOPS_EXTERNAL_TOOLS"] = self.config

    def tearDown(self) -> None:
        os.environ.pop("GEOOPS_EXTERNAL_TOOLS", None)
        self.tmp.cleanup()

    def test_configured_command_runs_for_real(self) -> None:
        registry = ExternalToolRegistry(self.config)
        result = registry.run("external:echo", {"path": "D:/data/a.tif"})
        self.assertEqual(result["returncode"], 0)
        self.assertIn("GOT D:/data/a.tif", result["stdout"])
        self.assertGreaterEqual(result["elapsed_ms"], 0)
        self.assertFalse(result["shell"])
        self.assertEqual(result["command"][-1], "D:/data/a.tif")

    def test_unconfigured_tool_is_refused(self) -> None:
        registry = ExternalToolRegistry(self.config)
        with self.assertRaises(ExternalToolError):
            registry.run("external:gdalinfo", {"path": "D:/data/a.tif"})

    def test_missing_placeholder_parameter_is_refused(self) -> None:
        registry = ExternalToolRegistry(self.config)
        with self.assertRaises(ExternalToolError):
            registry.run("external:echo", {})

    def test_gis_node_runs_configured_external_tool(self) -> None:
        node = ascii_grid_profile_node(
            "g1", "external", tool_id="external:echo", path_key="raster_path"
        )
        result = node.action({"raster_path": "D:/data/a.tif"})
        self.assertEqual(result.status.value, "PASS")
        self.assertIn("GOT D:/data/a.tif", result.output["stdout"])

    def test_gis_node_refuses_unconfigured_external_tool(self) -> None:
        node = ascii_grid_profile_node(
            "g1", "external", tool_id="external:gdalinfo", path_key="raster_path"
        )
        result = node.action({"raster_path": "D:/data/a.tif"})
        self.assertEqual(result.status.value, "ERROR")

    def test_nonzero_exit_is_an_error(self) -> None:
        bad = os.path.join(self.tmp.name, "bad.py")
        with open(bad, "w", encoding="utf-8") as handle:
            handle.write("import sys\nsys.exit(3)\n")
        with open(self.config, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "tools": [
                        {
                            "tool_id": "external:bad",
                            "command": [sys.executable, bad],
                            "args": [],
                            "timeout": 10,
                        }
                    ]
                },
                handle,
            )
        registry = ExternalToolRegistry(self.config)
        with self.assertRaises(ExternalToolError) as caught:
            registry.run("external:bad", {})
        self.assertIn("exited 3", str(caught.exception))
        details = caught.exception.details
        self.assertEqual(details["returncode"], 3)
        self.assertFalse(details["shell"])
        self.assertEqual(details["command"][-1], bad)
        self.assertGreaterEqual(details["elapsed_ms"], 0)

    def test_gis_node_records_a_failed_command(self) -> None:
        bad = os.path.join(self.tmp.name, "bad-node.py")
        with open(bad, "w", encoding="utf-8") as handle:
            handle.write("import sys\nprint('no', file=sys.stderr)\nsys.exit(4)\n")
        with open(self.config, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "tools": [
                        {
                            "tool_id": "external:bad",
                            "command": [sys.executable, bad],
                            "args": [],
                            "timeout": 10,
                        }
                    ]
                },
                handle,
            )
        node = ascii_grid_profile_node(
            "g1", "external", tool_id="external:bad", path_key="raster_path"
        )
        result = node.action({"raster_path": "D:/data/a.tif"})
        self.assertEqual(result.status.value, "ERROR")
        self.assertEqual(result.output["returncode"], 4)
        self.assertIn("no", result.output["stderr"])
        self.assertFalse(result.output["shell"])


if __name__ == "__main__":
    unittest.main()
