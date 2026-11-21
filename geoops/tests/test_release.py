"""Tests for the 0.1 domain layer: projects, datasets, catalog, review, trace."""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from geoops.artifacts import ArtifactStore
from geoops.catalog import Catalog, CatalogError
from geoops.domain import DomainRegistry, ObjectType, TaskEngine
from geoops.domain.datasets_store import DatasetError, DatasetRegistry
from geoops.domain.survey_areas import SurveyAreaError, SurveyAreaRegistry
from geoops.geotiff import write_geotiff_mask
from geoops.tests.test_geotiff_pixels import (
    _bigtiff,
    _georeferenced_multiband_tiff,
    _georeferenced_tiff,
)
from geoops.domain.projects import ProjectError, ProjectRegistry
from geoops.review import ReviewEngine, ReviewError
from geoops.trace import build_trace
from geoops.workflow import Node, NodeResult, NodeStatus, RunJournal, WorkflowEngine


def _grid(path: str, rows: str = "1 0\n0 1\n") -> str:
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("ncols 2\nnrows 2\nxllcorner 0\nyllcorner 0\ncellsize 1\n" + rows)
    return path


class ProjectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = DomainRegistry()
        self.projects = ProjectRegistry(self.registry)

    def test_all_required_fields_are_enforced(self) -> None:
        with self.assertRaises(ProjectError):
            self.projects.register("PRJ-1", "P-1", "项目", "survey", "", "EPSG:4547", "1985")
        self.assertEqual(len(self.projects.list()), 0)

    def test_a_valid_project_is_registered(self) -> None:
        project = self.projects.register(
            "PRJ-1", "P-1", "项目一", "survey", "哈尔滨", "EPSG:4547", "1985 国家高程基准"
        )
        self.assertEqual(project.payload["project_code"], "P-1")
        self.assertEqual(project.payload["vertical_datum"], "1985 国家高程基准")
        self.assertEqual(len(self.projects.list()), 1)

    def test_duplicate_project_code_is_refused(self) -> None:
        self.projects.register("PRJ-1", "P-1", "项目一", "survey", "哈尔滨", "EPSG:4547", "1985")
        with self.assertRaises(ProjectError):
            self.projects.register("PRJ-2", "P-1", "项目二", "survey", "哈尔滨", "EPSG:4547", "1985")


class DatasetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.mkdtemp(prefix="geoops-release-")
        self.registry = DomainRegistry()
        self.projects = ProjectRegistry(self.registry)
        self.projects.register("PRJ-1", "P-1", "项目", "survey", "哈尔滨", "EPSG:4547", "1985")
        self.datasets = DatasetRegistry(self.registry, self.projects)
        self.path = _grid(os.path.join(self.tempdir, "a.asc"))

    def _write_sidecar(self, crs: str = "EPSG:4547") -> None:
        with open(self.path + ".json", "w", encoding="utf-8") as handle:
            json.dump({"crs": crs, "crs_model": "projected"}, handle)

    def test_a_dataset_without_crs_is_refused(self) -> None:
        with self.assertRaises(DatasetError):
            self.datasets.register("PRJ-1", self.path)
        self.assertEqual(len(self.datasets.list()), 0)

    def test_a_dataset_with_crs_is_registered_with_its_hash(self) -> None:
        self._write_sidecar()
        dataset = self.datasets.register("PRJ-1", self.path, label="一期")
        self.assertEqual(dataset.payload["crs"], "EPSG:4547")
        self.assertEqual(dataset.payload["crs_model"], "projected")
        self.assertEqual(len(dataset.payload["sha256"]), 64)
        self.assertEqual(len(self.datasets.list("PRJ-1")), 1)
        self.assertEqual(self.datasets.list("PRJ-OTHER"), [])

    def test_validate_detects_a_changed_crs_model(self) -> None:
        self._write_sidecar()
        dataset = self.datasets.register("PRJ-1", self.path)
        with open(self.path + ".json", "w", encoding="utf-8") as handle:
            json.dump({"crs": "EPSG:4547", "crs_model": "geographic"}, handle)
        result = self.datasets.validate(dataset.object_id)
        self.assertEqual(result["status"], "FAIL")
        check = [row for row in result["checks"] if row["name"] == "crs_model"][0]
        self.assertEqual(check["status"], "FAIL")

    def test_validate_detects_changed_content(self) -> None:
        self._write_sidecar()
        dataset = self.datasets.register("PRJ-1", self.path)
        self.assertEqual(self.datasets.validate(dataset.object_id)["status"], "PASS")
        _grid(self.path, "2 0\n0 1\n")
        result = self.datasets.validate(dataset.object_id)
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("sha256", [check["name"] for check in result["checks"] if check["status"] == "FAIL"])

    def test_validate_detects_a_changed_sidecar_crs(self) -> None:
        self._write_sidecar()
        dataset = self.datasets.register("PRJ-1", self.path)
        self._write_sidecar("EPSG:3857")
        result = self.datasets.validate(dataset.object_id)
        self.assertEqual(result["status"], "FAIL")
        crs_check = [check for check in result["checks"] if check["name"] == "crs"][0]
        self.assertEqual(crs_check["status"], "FAIL")
        self.assertIn("EPSG:4547", crs_check["detail"])
        self.assertIn("EPSG:3857", crs_check["detail"])

    def test_an_unknown_project_is_refused(self) -> None:
        self._write_sidecar()
        with self.assertRaises(DatasetError):
            self.datasets.register("PRJ-NOPE", self.path)

    def test_profile_excludes_nodata_and_does_not_invent_statistics(self) -> None:
        path = os.path.join(self.tempdir, "nodata.asc")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(
                "ncols 2\nnrows 2\nxllcorner 0\nyllcorner 0\ncellsize 1\n"
                "NODATA_value -9999\n1 -9999\n-9999 -9999\n"
            )
        with open(path + ".json", "w", encoding="utf-8") as handle:
            json.dump({"crs": "EPSG:4547"}, handle)
        dataset = self.datasets.register("PRJ-1", path)
        profile = self.datasets.profile(dataset.object_id)
        self.assertEqual(profile["read_mode"], "whole_file")
        self.assertEqual(profile["valid_cells"], 1)
        self.assertEqual(profile["nodata_cells"], 3)
        self.assertEqual(profile["non_finite_cells"], 0)
        self.assertEqual(profile["min"], 1.0)
        self.assertEqual(profile["max"], 1.0)
        self.assertEqual(profile["mean"], 1.0)
        self.assertEqual(profile["bounds"], [0.0, 0.0, 2.0, 2.0])
        self.assertEqual(profile["crs"], "EPSG:4547")

    def test_profile_excludes_non_finite_cells(self) -> None:
        path = os.path.join(self.tempdir, "infinite.asc")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(
                "ncols 2\nnrows 2\nxllcorner 0\nyllcorner 0\ncellsize 1\n"
                "NODATA_value -9999\n1 1e999\n2 -9999\n"
            )
        with open(path + ".json", "w", encoding="utf-8") as handle:
            json.dump({"crs": "EPSG:4547", "crs_model": "projected"}, handle)
        dataset = self.datasets.register("PRJ-1", path)
        profile = self.datasets.profile(dataset.object_id)
        self.assertEqual(profile["valid_cells"], 2)
        self.assertEqual(profile["nodata_cells"], 1)
        self.assertEqual(profile["non_finite_cells"], 1)
        self.assertEqual(profile["min"], 1.0)
        self.assertEqual(profile["max"], 2.0)
        self.assertEqual(profile["mean"], 1.5)

    def test_a_sidecar_crs_conflict_is_refused_at_registration(self) -> None:
        path = os.path.join(self.tempdir, "conflict.tif")
        write_geotiff_mask(
            path, width=2, height=2, cellsize=10.0, cellsize_y=10.0,
            xllcorner=0.0, yllcorner=0.0, crs="EPSG:4547",
            crs_model="projected", values=[1.0, 2.0, 3.0, 4.0],
        )
        with open(path + ".json", "w", encoding="utf-8") as handle:
            json.dump({"crs": "EPSG:4326", "crs_model": "geographic"}, handle)
        with self.assertRaises(DatasetError) as caught:
            self.datasets.register("PRJ-1", path)
        self.assertIn("metadata conflict", str(caught.exception))

    def test_an_invalid_sidecar_crs_model_is_not_ignored(self) -> None:
        path = os.path.join(self.tempdir, "bad-model.tif")
        write_geotiff_mask(
            path, width=2, height=2, cellsize=10.0, cellsize_y=10.0,
            xllcorner=0.0, yllcorner=0.0, crs="EPSG:4547",
            crs_model="projected", values=[1.0, 2.0, 3.0, 4.0],
        )
        with open(path + ".json", "w", encoding="utf-8") as handle:
            json.dump({"crs": "EPSG:4547", "crs_model": "banana"}, handle)
        with self.assertRaises(DatasetError) as caught:
            self.datasets.register("PRJ-1", path)
        self.assertIn("crs_model", str(caught.exception))

    def test_profile_reads_real_geotiff_pixels(self) -> None:
        path = os.path.join(self.tempdir, "tile.tif")
        _georeferenced_tiff(path, [1, 2, 3, 4])
        with open(path + ".json", "w", encoding="utf-8") as handle:
            json.dump({"crs": "EPSG:4547", "crs_model": "projected"}, handle)
        dataset = self.datasets.register("PRJ-1", path)
        self.assertEqual(dataset.payload["crs_model"], "projected")
        self.assertEqual(dataset.payload["raster_type"], 1)
        self.assertEqual(dataset.payload["linear_unit_m"], 1.0)
        profile = self.datasets.profile(dataset.object_id)
        self.assertEqual(profile["format"], "geotiff")
        self.assertEqual(profile["read_mode"], "streamed_blocks")
        self.assertEqual(profile["ncols"], 2)
        self.assertEqual(profile["nrows"], 2)
        self.assertEqual(profile["valid_cells"], 4)
        self.assertEqual(profile["mean"], 2.5)
        self.assertEqual(profile["cell_area_m2"], 100.0)
        self.assertEqual(profile["footprint_area_m2"], 400.0)
        self.assertEqual(profile["bounds"], [0.0, -20.0, 20.0, 0.0])
        self.assertEqual(profile["crs"], "EPSG:4547")

    def test_profile_selects_a_real_geotiff_band(self) -> None:
        path = os.path.join(self.tempdir, "multi.tif")
        _georeferenced_multiband_tiff(path, [1, 5, 2, 6, 3, 7, 4, 8])
        with open(path + ".json", "w", encoding="utf-8") as handle:
            json.dump({"crs": "EPSG:4547"}, handle)
        dataset = self.datasets.register("PRJ-1", path)
        profile = self.datasets.profile(dataset.object_id, band=2)
        self.assertEqual(profile["bands"], 2)
        self.assertEqual(profile["band"], 2)
        self.assertEqual(profile["valid_cells"], 4)
        self.assertEqual(profile["mean"], 6.5)
        self.assertEqual(profile["min"], 5.0)
        self.assertEqual(profile["max"], 8.0)
        with self.assertRaises(DatasetError):
            self.datasets.profile(dataset.object_id, band=3)

    def test_bigtiff_dataset_keeps_dimensions_and_profile(self) -> None:
        path = os.path.join(self.tempdir, "big.tif")
        _bigtiff(path, [1, 2, 3, 4])
        with open(path + ".json", "w", encoding="utf-8") as handle:
            json.dump({"crs": "EPSG:4547"}, handle)
        dataset = self.datasets.register("PRJ-1", path)
        self.assertEqual(dataset.payload["width"], 2)
        self.assertEqual(dataset.payload["height"], 2)
        self.assertEqual(dataset.payload["pixel_size"], [10.0, 10.0])
        self.assertEqual(dataset.payload["bounds"], [0.0, -20.0, 20.0, 0.0])
        profile = self.datasets.profile(dataset.object_id)
        self.assertEqual(profile["format"], "geotiff")
        self.assertEqual(profile["valid_cells"], 4)
        self.assertEqual(profile["mean"], 2.5)


class SurveyAreaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = DomainRegistry()
        self.projects = ProjectRegistry(self.registry)
        self.projects.register("PRJ-1", "P-1", "项目", "survey", "哈尔滨", "EPSG:4547", "1985")
        self.areas = SurveyAreaRegistry(self.registry, self.projects)

    def test_a_real_area_is_registered_with_its_bounds(self) -> None:
        area = self.areas.register(
            "AREA-1", "PRJ-1", "测区一", "project", "EPSG:4547",
            bounds=[0, 0, 10, 10],
        )
        self.assertEqual(area.payload["bounds"], [0.0, 0.0, 10.0, 10.0])
        self.assertEqual(len(self.areas.list("PRJ-1")), 1)
        self.assertEqual(self.areas.list("PRJ-OTHER"), [])

    def test_malformed_bounds_are_refused(self) -> None:
        for bounds in ([0, 0, 0, 1], [0, 1], "0 0 1 1", [0, 0, float("nan"), 1]):
            with self.assertRaises(SurveyAreaError):
                self.areas.register(
                    "AREA-X", "PRJ-1", "坏边界", "project", "EPSG:4547", bounds=bounds,
                )
        self.assertEqual(len(self.areas.list()), 0)

    def test_an_unknown_project_is_refused(self) -> None:
        with self.assertRaises(SurveyAreaError):
            self.areas.register("AREA-2", "PRJ-NOPE", "测区", "project", "EPSG:4547")


class CatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = DomainRegistry()
        self.catalog = Catalog(self.registry)

    def test_a_builtin_algorithm_is_available(self) -> None:
        model = self.catalog.register_model(
            "MDL-1", "像元差分", "1.0", "algorithm", "change_detection",
            "builtin:change_detection", True,
            provider="builtin", endpoint="builtin://change",
            model_name="ascii-raster-diff", api_key_env="", timeout_s=30,
        )
        self.assertTrue(model.payload["available"])
        self.assertEqual(model.payload["endpoint"], "builtin://change")
        self.assertEqual(model.payload["model_name"], "ascii-raster-diff")

    def test_tool_records_its_interface_fields(self) -> None:
        tool = self.catalog.register_tool(
            "TL-2", "ASCII 差分", "1.0", "raster", "builtin:ascii_raster_diff", True,
            input_format="ESRI ASCII grid", output_format="ASCII mask",
            invocation="builtin", permission="workflow:execute", timeout_s=30,
        )
        self.assertEqual(tool.payload["status"], "READY")
        self.assertEqual(tool.payload["permission"], "workflow:execute")
        self.assertEqual(tool.payload["input_format"], "ESRI ASCII grid")

    def test_an_unimplemented_builtin_is_marked_unavailable(self) -> None:
        model = self.catalog.register_model(
            "MDL-2", "未实现", "1.0", "algorithm", "x", "builtin:not_there", True
        )
        self.assertFalse(model.payload["available"])
        self.assertIn("not implemented", model.payload["reason"])

    def test_a_missing_external_path_is_unavailable(self) -> None:
        tool = self.catalog.register_tool(
            "TL-1", "GDAL", "3.8", "gis", "external:D:/nope/gdal.exe", True
        )
        self.assertFalse(tool.payload["available"])

    def test_an_agent_needs_registered_dependencies(self) -> None:
        with self.assertRaises(CatalogError):
            self.catalog.register_agent("AG-1", "变化检测 Agent", "1.0", "sequential", ["MDL-X"], [])

    def test_an_agent_inherits_dependency_availability(self) -> None:
        self.catalog.register_model(
            "MDL-1", "像元差分", "1.0", "algorithm", "change_detection", "builtin:change_detection", True
        )
        self.catalog.register_tool(
            "TL-1", "ASCII 差分", "1.0", "raster", "builtin:ascii_raster_diff", True
        )
        agent = self.catalog.register_agent("AG-1", "变化检测 Agent", "1.0", "sequential", ["MDL-1"], ["TL-1"])
        self.assertTrue(agent.payload["available"])


class ReviewAndTraceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.mkdtemp(prefix="geoops-hit-")
        self.registry = DomainRegistry()
        self.projects = ProjectRegistry(self.registry)
        self.projects.register("PRJ-1", "P-1", "项目", "survey", "哈尔滨", "EPSG:4547", "1985")
        self.tasks = TaskEngine(self.registry)
        self.task = self.tasks.create("PRJ-1", "变化检测任务", "change_detection", actor="test")
        self.tasks.transition(self.task.task_id, "READY", reason="资料齐", actor="test")
        self.tasks.transition(self.task.task_id, "RUNNING", reason="开工", actor="test")
        self.datasets = DatasetRegistry(self.registry, self.projects)
        self.path = _grid(os.path.join(self.tempdir, "a.asc"))
        with open(self.path + ".json", "w", encoding="utf-8") as handle:
            json.dump({"crs": "EPSG:4547"}, handle)
        self.datasets.register("PRJ-1", self.path, task_id=self.task.task_id)
        self.deliverable = self.registry.register(
            ObjectType.DELIVERABLE,
            "DLV-1",
            {"task_id": self.task.task_id, "name": "变化掩膜"},
        )
        self.artifacts = ArtifactStore(root=self.tempdir, registry=self.registry)
        mask = _grid(os.path.join(self.tempdir, "mask.asc"))
        self.artifacts.register(mask, task_id=self.task.task_id, kind="change_mask", deliverable_id="DLV-1")
        self.reviews = ReviewEngine(self.registry)
        self.journal = RunJournal()
        engine = WorkflowEngine()
        run = engine.start(
            [Node("R1", "规则门", lambda ctx: NodeResult(NodeStatus.PASS, "checked=3"))],
            {},
            run_id="RUN-1",
        )
        self.journal.record(run, task_id=self.task.task_id, project_id="PRJ-1")
        self.tasks.attach_run(self.task.task_id, "RUN-1")
        self.tasks.transition(self.task.task_id, "COMPLETED", reason="完成", actor="test")

    def test_reject_requires_an_opinion(self) -> None:
        with self.assertRaises(ReviewError):
            self.reviews.submit("", "", "", "REJECT")
        with self.assertRaises(ReviewError):
            self.reviews.submit(self.task.task_id, "DLV-1", "审核员", "REJECT", "")
        self.assertEqual(len(self.reviews.list()), 0)

    def test_approve_marks_the_deliverable_accepted(self) -> None:
        record = self.reviews.submit(self.task.task_id, "DLV-1", "审核员", "APPROVE", "符合要求")
        self.assertEqual(record.payload["decision"], "APPROVE")
        self.assertTrue(self.reviews.is_finally_accepted("DLV-1"))
        self.assertEqual(self.registry.get("DLV-1").version, 2)

    def test_an_accepted_deliverable_refuses_a_second_review(self) -> None:
        self.reviews.submit(self.task.task_id, "DLV-1", "审核员", "APPROVE", "通过")
        with self.assertRaises(ReviewError):
            self.reviews.submit(self.task.task_id, "DLV-1", "另一位", "REJECT", "重新做")

    def test_a_reject_leaves_the_deliverable_unaccepted(self) -> None:
        self.reviews.submit(self.task.task_id, "DLV-1", "审核员", "REJECT", "边界不对")
        self.assertFalse(self.reviews.is_finally_accepted("DLV-1"))

    def test_trace_is_complete_when_every_link_exists(self) -> None:
        self.reviews.submit(self.task.task_id, "DLV-1", "审核员", "APPROVE", "通过")
        trace = build_trace(
            self.registry, self.task.task_id, journal=self.journal,
            artifacts=self.artifacts, reviews=self.reviews,
        )
        self.assertTrue(trace["complete"], trace["missing"])
        kinds = {link["kind"] for link in trace["links"]}
        for expected in ("project→task", "dataset→task", "run→task", "deliverable→task",
                         "artifact→deliverable", "review→deliverable"):
            self.assertIn(expected, kinds)
        self.assertEqual(len(trace["rules"]), 1)

    def test_trace_names_what_is_missing(self) -> None:
        trace = build_trace(self.registry, self.task.task_id)
        self.assertFalse(trace["complete"])
        missing = {entry["name"] for entry in trace["missing"]}
        self.assertIn("workflow_runs", missing)
        self.assertIn("review", missing)


if __name__ == "__main__":
    unittest.main()
