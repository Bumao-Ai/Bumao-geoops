"""Tests for change detection on real ASCII grids.

The fixtures are written here, so the expected cells are hand-countable:
4 rows x 5 cells at cellsize 10 (100 m2 per cell), one nodata cell.

    baseline                        comparison
    10 10 10 10 10                  10 10 10 10 10
    10 10 10 10 10                  10 20 20 10 10   <- 2-cell patch, 200 m2
    10 10 10 10 10                  10 10 10 10 10
    10 10 10 10 -9999               10 10 30 10 -9999 <- 1-cell patch, 100 m2

Standard library only: run with

    python -m unittest geoops.tests.test_change -v
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from geoops.ai.agent_executor import execute_tool
from geoops.artifacts import ArtifactStore
from geoops.geotiff import read_geotiff_pixels, write_geotiff_mask
from geoops.survey.change import (
    ChangeError,
    detect_changes,
    is_nodata,
    read_ascii_grid,
    read_raster_grid,
    write_change_mask,
)
from geoops.survey.change_node import change_detect_node
from geoops.tests.test_geotiff_pixels import _georeferenced_tiff, _georeferenced_multiband_tiff
from geoops.workflow import NodeStatus, run

BASELINE = """ncols 5
nrows 4
xllcorner 500000
yllcorner 4500000
cellsize 10
NODATA_value -9999
10 10 10 10 10
10 10 10 10 10
10 10 10 10 10
10 10 10 10 -9999
"""

COMPARISON = """ncols 5
nrows 4
xllcorner 500000
yllcorner 4500000
cellsize 10
NODATA_value -9999
10 10 10 10 10
10 20 20 10 10
10 10 10 10 10
10 10 30 10 -9999
"""


class ChangeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.mkdtemp(prefix="geoops-change-")
        self.baseline = os.path.join(self.tempdir, "baseline.asc")
        self.comparison = os.path.join(self.tempdir, "comparison.asc")
        self._write(self.baseline, BASELINE)
        self._write(self.comparison, COMPARISON)

    @staticmethod
    def _write(path, text):
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)

    def test_read_grid_validates_and_returns_cells(self) -> None:
        grid = read_ascii_grid(self.baseline)
        self.assertEqual(grid["ncols"], 5)
        self.assertEqual(grid["nrows"], 4)
        self.assertEqual(len(grid["values"]), 20)
        self.assertEqual(grid["values"][0], 10)

    def test_missing_header_key_is_refused(self) -> None:
        broken = os.path.join(self.tempdir, "broken.asc")
        self._write(broken, "ncols 3\nnrows 2\nxllcorner 0\ncellsize 1\n1 2 3\n4 5 6\n")
        with self.assertRaises(ChangeError) as caught:
            read_ascii_grid(broken)
        self.assertIn("yllcorner", str(caught.exception))

    def test_cell_count_mismatch_is_refused(self) -> None:
        broken = os.path.join(self.tempdir, "short.asc")
        self._write(broken, "ncols 3\nnrows 2\nxllcorner 0\nyllcorner 0\ncellsize 1\n1 2 3\n4 5\n")
        with self.assertRaises(ChangeError):
            read_ascii_grid(broken)

    def test_non_numeric_cell_is_refused(self) -> None:
        broken = os.path.join(self.tempdir, "text.asc")
        self._write(broken, "ncols 2\nnrows 1\nxllcorner 0\nyllcorner 0\ncellsize 1\n1 x\n")
        with self.assertRaises(ChangeError):
            read_ascii_grid(broken)

    def test_cell_center_origin_is_normalized_to_corners(self) -> None:
        centered = os.path.join(self.tempdir, "centered.asc")
        self._write(
            centered,
            "ncols 2\nnrows 2\nxllcenter 5\nyllcenter 5\ncellsize 10\n1 2\n3 4\n",
        )
        grid = read_ascii_grid(centered)
        self.assertEqual(grid["header"]["xllcorner"], 0.0)
        self.assertEqual(grid["header"]["yllcorner"], 0.0)
        self.assertEqual(grid["values"], [1.0, 2.0, 3.0, 4.0])

    def test_conflicting_corner_and_center_origins_are_refused(self) -> None:
        broken = os.path.join(self.tempdir, "origin-conflict.asc")
        self._write(
            broken,
            "ncols 1\nnrows 1\nxllcorner 0\nxllcenter 100\n"
            "yllcorner 0\ncellsize 10\n1\n",
        )
        with self.assertRaises(ChangeError) as caught:
            read_ascii_grid(broken)
        self.assertIn("conflicting", str(caught.exception))

    def test_detection_counts_match_the_fixture(self) -> None:
        result = detect_changes(self.baseline, self.comparison, threshold=1, min_area_m2=0)
        self.assertEqual(result["changed_cells"], 3)
        self.assertEqual(result["nodata_cells"], 1)
        self.assertEqual(len(result["patches"]), 2)
        self.assertEqual(result["changed_area_m2"], 300)

    def test_min_area_drops_the_small_patch(self) -> None:
        result = detect_changes(self.baseline, self.comparison, threshold=1, min_area_m2=150)
        self.assertEqual(result["changed_cells"], 3)
        self.assertEqual(result["kept_cells"], 2)
        self.assertEqual(result["dropped_cells"], 1)
        self.assertEqual(result["dropped_patches"], 1)
        self.assertEqual(len(result["patches"]), 1)
        self.assertEqual(result["patches"][0]["area_m2"], 200)
        self.assertEqual(result["patches"][0]["mean_abs_delta"], 10)
        self.assertEqual(result["patches"][0]["max_abs_delta"], 10)
        self.assertEqual(result["patches"][0]["mean_baseline"], 10)
        self.assertEqual(result["patches"][0]["mean_comparison"], 20)
        self.assertEqual(result["patches"][0]["bbox"], [500010.0, 4500020.0, 500030.0, 4500030.0])
        self.assertEqual(result["patches"][0]["centroid"], [500020.0, 4500025.0])
        self.assertEqual(result["patches"][0]["row_min"], 1)
        self.assertEqual(result["patches"][0]["row_max"], 1)
        self.assertEqual(result["patches"][0]["col_min"], 1)
        self.assertEqual(result["patches"][0]["col_max"], 2)
        self.assertEqual(result["changed_area_m2"], 200)

    def test_zero_threshold_only_marks_real_differences(self) -> None:
        unchanged = detect_changes(self.baseline, self.baseline, threshold=0, min_area_m2=0)
        self.assertEqual(unchanged["changed_cells"], 0)
        self.assertEqual(unchanged["nodata_cells"], 1)
        self.assertEqual(unchanged["patches"], [])
        changed = detect_changes(self.baseline, self.comparison, threshold=0, min_area_m2=0)
        self.assertEqual(changed["changed_cells"], 3)

    def test_high_threshold_finds_nothing(self) -> None:
        result = detect_changes(self.baseline, self.comparison, threshold=11)
        self.assertEqual(result["changed_cells"], 1)
        self.assertEqual(result["patches"][0]["cells"], 1)
        result = detect_changes(self.baseline, self.comparison, threshold=21)
        self.assertEqual(result["changed_cells"], 0)

    def test_unaligned_grids_are_refused(self) -> None:
        shifted = os.path.join(self.tempdir, "shifted.asc")
        self._write(shifted, COMPARISON.replace("xllcorner 500000", "xllcorner 500010"))
        with self.assertRaises(ChangeError) as caught:
            detect_changes(self.baseline, shifted)
        self.assertIn("not aligned", str(caught.exception))

    def test_mask_round_trip_keeps_cells_and_nodata(self) -> None:
        result = detect_changes(self.baseline, self.comparison, threshold=1, min_area_m2=150)
        mask_path = write_change_mask(result, os.path.join(self.tempdir, "mask.asc"))
        mask = read_ascii_grid(mask_path)
        nodata_count = sum(1 for value in mask["values"] if value == mask["header"]["nodata_value"])
        self.assertEqual(nodata_count, 1)
        self.assertEqual([value for value in mask["values"] if value == 1], [1, 1])
        self.assertEqual(mask["values"][-1], -9999)
        self.assertEqual(mask["ncols"], 5)

    def test_a_fractional_nodata_sentinel_is_written_consistently(self) -> None:
        result = detect_changes(self.baseline, self.comparison, threshold=1, min_area_m2=150)
        mask_path = write_change_mask(
            result, os.path.join(self.tempdir, "fractional.asc"), nodata_value=-9999.5
        )
        mask = read_ascii_grid(mask_path)
        self.assertEqual(mask["header"]["nodata_value"], -9999.5)
        self.assertEqual(mask["values"][-1], -9999.5)

    def test_write_change_mask_refuses_a_non_finite_nodata(self) -> None:
        result = detect_changes(self.baseline, self.comparison, threshold=1, min_area_m2=150)
        with self.assertRaises(ChangeError):
            write_change_mask(
                result, os.path.join(self.tempdir, "bad-nodata.asc"), nodata_value=float("nan")
            )

    def test_geotiff_mask_is_a_real_tiff_with_source_georeferencing(self) -> None:
        result = detect_changes(self.baseline, self.comparison, threshold=1, min_area_m2=150)
        result["crs"] = "EPSG:3857"
        result["crs_model"] = "projected"
        mask_path = write_change_mask(
            result, os.path.join(self.tempdir, "mask.tif")
        )
        image = read_geotiff_pixels(mask_path)
        self.assertEqual(image["width"], 5)
        self.assertEqual(image["height"], 4)
        self.assertEqual(image["crs"], "EPSG:3857")
        self.assertEqual(image["crs_model"], "projected")
        self.assertEqual(image["pixel_size"], [10.0, 10.0])
        self.assertEqual(image["values"][-1], -9999.0)
        self.assertEqual(sum(1 for value in image["values"] if value == 1.0), 2)

    def test_geotiff_mask_without_crs_is_refused(self) -> None:
        result = detect_changes(self.baseline, self.comparison)
        with self.assertRaises(ChangeError) as caught:
            write_change_mask(result, os.path.join(self.tempdir, "mask.tif"))
        self.assertIn("source CRS", str(caught.exception))

    def test_ascii_sidecar_crs_enables_a_geotiff_mask(self) -> None:
        for path in (self.baseline, self.comparison):
            with open(path + ".json", "w", encoding="utf-8") as handle:
                json.dump({"crs": "EPSG:3857"}, handle)
        result = detect_changes(self.baseline, self.comparison, threshold=1, min_area_m2=150)
        self.assertEqual(result["crs"], "EPSG:3857")
        self.assertEqual(result["crs_model"], "projected")
        mask_path = write_change_mask(result, os.path.join(self.tempdir, "mask-from-ascii.tif"))
        image = read_geotiff_pixels(mask_path)
        self.assertEqual(image["crs"], "EPSG:3857")
        self.assertEqual(image["crs_model"], "projected")

    def test_ascii_mask_keeps_source_crs_in_a_sidecar(self) -> None:
        for path in (self.baseline, self.comparison):
            with open(path + ".json", "w", encoding="utf-8") as handle:
                json.dump({"crs": "EPSG:4547", "crs_model": "projected"}, handle)
        result = detect_changes(self.baseline, self.comparison, threshold=1, min_area_m2=150)
        mask_path = write_change_mask(result, os.path.join(self.tempdir, "sidecar-mask.asc"))
        sidecar = mask_path + ".json"
        self.assertTrue(os.path.isfile(sidecar))
        grid = read_raster_grid(mask_path)
        self.assertEqual(grid["crs"], "EPSG:4547")
        self.assertEqual(grid["crs_model"], "projected")

    def test_geotiff_sidecar_crs_fills_a_header_without_epsg(self) -> None:
        path = os.path.join(self.tempdir, "plain-georef.tif")
        _georeferenced_tiff(path, bytes([1, 2, 3, 4]))
        with open(path + ".json", "w", encoding="utf-8") as handle:
            json.dump({"crs": "EPSG:3857"}, handle)
        grid = read_raster_grid(path)
        self.assertEqual(grid["crs"], "EPSG:3857")
        self.assertEqual(grid["crs_model"], "projected")
        self.assertEqual(grid["values"], [1, 2, 3, 4])

    def test_a_sidecar_crs_that_conflicts_with_the_header_is_refused(self) -> None:
        path = os.path.join(self.tempdir, "conflict.tif")
        write_geotiff_mask(
            path, width=2, height=2, cellsize=10.0, cellsize_y=10.0,
            xllcorner=0.0, yllcorner=0.0, crs="EPSG:4547",
            crs_model="projected", values=[1.0, 2.0, 3.0, 4.0],
        )
        with open(path + ".json", "w", encoding="utf-8") as handle:
            json.dump({"crs": "EPSG:4326", "crs_model": "geographic"}, handle)
        with self.assertRaises(ChangeError) as caught:
            read_raster_grid(path)
        self.assertIn("conflicting CRS", str(caught.exception))

    def test_projected_cells_in_us_survey_feet_report_square_metres(self) -> None:
        baseline = os.path.join(self.tempdir, "feet-base.tif")
        comparison = os.path.join(self.tempdir, "feet-comp.tif")
        for path, values in (
            (baseline, [0.0, 0.0, 0.0, 0.0]),
            (comparison, [5.0, 0.0, 0.0, 0.0]),
        ):
            write_geotiff_mask(
                path, width=2, height=2, cellsize=10.0, cellsize_y=20.0,
                xllcorner=0.0, yllcorner=0.0, crs="EPSG:2277",
                crs_model="projected", values=values, linear_unit_code=9003,
            )
        result = detect_changes(baseline, comparison, threshold=1)
        foot = 1200.0 / 3937.0
        self.assertEqual(result["linear_unit"], "US survey foot")
        self.assertAlmostEqual(result["cell_area_m2"], 200.0 * foot * foot, delta=1e-6)
        self.assertAlmostEqual(result["changed_area_m2"], 200.0 * foot * foot, delta=1e-6)
        mask = os.path.join(self.tempdir, "feet-mask.tif")
        write_change_mask(result, mask)
        image = read_geotiff_pixels(mask)
        self.assertEqual(image["linear_unit_code"], 9003)
        self.assertEqual(image["linear_unit"], "US survey foot")

    def test_grids_with_different_linear_units_are_refused(self) -> None:
        baseline = os.path.join(self.tempdir, "unit-base.tif")
        comparison = os.path.join(self.tempdir, "unit-comp.tif")
        write_geotiff_mask(
            baseline, width=2, height=2, cellsize=10.0, cellsize_y=10.0,
            xllcorner=0.0, yllcorner=0.0, crs="EPSG:2277",
            crs_model="projected", values=[0.0, 0.0, 0.0, 0.0],
        )
        write_geotiff_mask(
            comparison, width=2, height=2, cellsize=10.0, cellsize_y=10.0,
            xllcorner=0.0, yllcorner=0.0, crs="EPSG:2277",
            crs_model="projected", values=[5.0, 0.0, 0.0, 0.0],
            linear_unit_code=9003,
        )
        with self.assertRaises(ChangeError) as caught:
            detect_changes(baseline, comparison, threshold=1)
        self.assertIn("linear unit", str(caught.exception))

    def test_non_square_pixels_keep_their_height_and_area(self) -> None:
        baseline = os.path.join(self.tempdir, "rect-base.tif")
        comparison = os.path.join(self.tempdir, "rect-comp.tif")
        write_geotiff_mask(
            baseline, width=2, height=2, cellsize=10.0, cellsize_y=20.0,
            xllcorner=500000.0, yllcorner=4500000.0, crs="EPSG:3857",
            crs_model="projected", values=[0.0, 0.0, 0.0, 0.0],
        )
        write_geotiff_mask(
            comparison, width=2, height=2, cellsize=10.0, cellsize_y=20.0,
            xllcorner=500000.0, yllcorner=4500000.0, crs="EPSG:3857",
            crs_model="projected", values=[5.0, 0.0, 0.0, 0.0],
        )
        result = detect_changes(baseline, comparison, threshold=1)
        self.assertEqual(result["cellsize_y"], 20.0)
        self.assertEqual(result["cell_area_m2"], 200.0)
        self.assertEqual(result["changed_area_m2"], 200.0)
        mask = os.path.join(self.tempdir, "rect-mask.tif")
        write_change_mask(result, mask)
        image = read_geotiff_pixels(mask)
        self.assertEqual(image["pixel_size"][:2], [10.0, 20.0])
        with self.assertRaises(ChangeError) as caught:
            write_change_mask(result, os.path.join(self.tempdir, "rect-mask.asc"))
        self.assertIn("non-square", str(caught.exception))

    def test_non_finite_threshold_and_min_area_are_refused(self) -> None:
        with self.assertRaises(ChangeError):
            detect_changes(self.baseline, self.comparison, threshold=float("nan"))
        with self.assertRaises(ChangeError):
            detect_changes(self.baseline, self.comparison, min_area_m2=float("inf"))

    def test_changed_area_on_a_geographic_grid_uses_real_metres(self) -> None:
        baseline = os.path.join(self.tempdir, "geo-base.asc")
        comparison = os.path.join(self.tempdir, "geo-comp.asc")
        self._write(
            baseline,
            "ncols 4\nnrows 4\nxllcorner 0\nyllcorner 0\ncellsize 1\n"
            + " ".join(["0"] * 16) + "\n",
        )
        values = ["0"] * 16
        values[0] = "5"
        values[15] = "5"
        self._write(
            comparison,
            "ncols 4\nnrows 4\nxllcorner 0\nyllcorner 0\ncellsize 1\n"
            + " ".join(values) + "\n",
        )
        for path in (baseline, comparison):
            with open(path + ".json", "w", encoding="utf-8") as handle:
                json.dump({"crs": "EPSG:4326", "crs_model": "geographic"}, handle)
        result = detect_changes(baseline, comparison, threshold=1, min_area_m2=0)
        self.assertEqual(result["area_basis"], "geographic_wgs84")
        self.assertGreater(result["cell_area_m2"], 1.2e10)
        self.assertEqual(len(result["patches"]), 2)
        north, south = result["patches"]
        self.assertLess(north["area_m2"], south["area_m2"])
        self.assertAlmostEqual(
            north["area_m2"] + south["area_m2"], result["changed_area_m2"], places=3
        )

    def test_change_detection_refuses_a_crs_mismatch(self) -> None:
        baseline = os.path.join(self.tempdir, "crs-3857.tif")
        comparison = os.path.join(self.tempdir, "crs-4326.tif")
        write_geotiff_mask(
            baseline, width=2, height=2, cellsize=10.0, xllcorner=500000.0,
            yllcorner=4500000.0, crs="EPSG:3857", crs_model="projected",
            values=[1.0, 2.0, 3.0, 4.0],
        )
        write_geotiff_mask(
            comparison, width=2, height=2, cellsize=10.0, xllcorner=500000.0,
            yllcorner=4500000.0, crs="EPSG:4326", crs_model="geographic",
            values=[1.0, 9.0, 3.0, 4.0],
        )
        with self.assertRaises(ChangeError) as caught:
            detect_changes(baseline, comparison, threshold=1)
        self.assertIn("CRS differs", str(caught.exception))

    def test_change_detection_selects_a_multiband_band(self) -> None:
        baseline = os.path.join(self.tempdir, "band-base.tif")
        comparison = os.path.join(self.tempdir, "band-comp.tif")
        _georeferenced_multiband_tiff(baseline, [1, 1, 2, 2, 3, 3, 4, 4])
        _georeferenced_multiband_tiff(comparison, [1, 10, 2, 20, 3, 30, 4, 40])
        band_two = detect_changes(baseline, comparison, threshold=5, band=2)
        self.assertEqual(band_two["band"], 2)
        self.assertEqual(band_two["changed_cells"], 4)
        band_one = detect_changes(baseline, comparison, threshold=5, band=1)
        self.assertEqual(band_one["changed_cells"], 0)
        with self.assertRaises(ChangeError):
            detect_changes(baseline, comparison, band=3)

    def test_agent_profile_tool_selects_a_band(self) -> None:
        path = os.path.join(self.tempdir, "agent-multiband.tif")
        _georeferenced_multiband_tiff(path, [1, 5, 2, 6, 3, 7, 4, 8])
        result = execute_tool(
            "builtin:ascii_grid_profile",
            {"adapter": "builtin:ascii_grid_profile"},
            {"path": path, "band": 2},
        )
        self.assertEqual(result["band"], 2)
        self.assertEqual(result["valid_cells"], 4)
        self.assertEqual(result["min"], 5.0)
        self.assertEqual(result["max"], 8.0)

    def test_a_nan_sentinel_is_compared_as_nodata(self) -> None:
        self.assertTrue(is_nodata(float("nan"), float("nan")))
        self.assertFalse(is_nodata(1.0, float("nan")))
        self.assertTrue(is_nodata(-9999.0, -9999.0))

    def test_a_non_finite_cell_is_excluded_from_change(self) -> None:
        broken = os.path.join(self.tempdir, "infinite.asc")
        self._write(
            broken,
            COMPARISON.replace("10 10 10 10 10", "1e999 10 10 10 10", 1),
        )
        result = detect_changes(self.baseline, broken, threshold=1, min_area_m2=0)
        self.assertEqual(result["nodata_cells"], 1)
        self.assertEqual(result["non_finite_cells"], 1)
        self.assertTrue(result["invalid_mask"][0])
        self.assertEqual(result["changed_cells"], 3)


class ChangeNodeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.mkdtemp(prefix="geoops-change-node-")
        self.baseline = os.path.join(self.tempdir, "baseline.asc")
        self.comparison = os.path.join(self.tempdir, "comparison.asc")
        with open(self.baseline, "w", encoding="utf-8") as handle:
            handle.write(BASELINE)
        with open(self.comparison, "w", encoding="utf-8") as handle:
            handle.write(COMPARISON)

    def test_node_writes_the_mask_and_reports_stats(self) -> None:
        node = change_detect_node("C1", "change detect", threshold=1, min_area_m2=150)
        context = {
            "baseline_path": self.baseline,
            "comparison_path": self.comparison,
            "change_output_path": os.path.join(self.tempdir, "mask.asc"),
            "min_area_m2": 150,
        }
        outcome = run([node], context, run_id="RUN-C-1")
        self.assertEqual(outcome.status, NodeStatus.PASS)
        self.assertEqual(context["change_result"]["kept_cells"], 2)
        self.assertTrue(os.path.isfile(context["change_result"]["mask_path"]))

    def test_node_fails_when_the_output_path_is_missing(self) -> None:
        node = change_detect_node("C1", "change detect")
        outcome = run(
            [node],
            {"baseline_path": self.baseline, "comparison_path": self.comparison},
            run_id="RUN-C-2",
        )
        self.assertEqual(outcome.status, NodeStatus.FAIL)

    def test_node_writes_a_geotiff_mask_from_geotiff_sources(self) -> None:
        baseline = os.path.join(self.tempdir, "baseline.tif")
        comparison = os.path.join(self.tempdir, "comparison.tif")
        write_geotiff_mask(
            baseline,
            width=2,
            height=2,
            cellsize=10.0,
            xllcorner=500000.0,
            yllcorner=4500000.0,
            crs="EPSG:3857",
            crs_model="projected",
            values=[10.0, 10.0, 10.0, 10.0],
        )
        write_geotiff_mask(
            comparison,
            width=2,
            height=2,
            cellsize=10.0,
            xllcorner=500000.0,
            yllcorner=4500000.0,
            crs="EPSG:3857",
            crs_model="projected",
            values=[10.0, 20.0, 10.0, 10.0],
        )
        node = change_detect_node("C2", "change detect", threshold=1)
        context = {
            "baseline_path": baseline,
            "comparison_path": comparison,
            "change_output_path": os.path.join(self.tempdir, "mask.tif"),
        }
        outcome = run([node], context, run_id="RUN-C-3")
        self.assertEqual(outcome.status, NodeStatus.PASS)
        image = read_geotiff_pixels(context["change_result"]["mask_path"])
        self.assertEqual(image["crs"], "EPSG:3857")
        self.assertEqual(image["values"], [0.0, 1.0, 0.0, 0.0])

    def test_node_fails_on_a_missing_grid(self) -> None:
        node = change_detect_node("C1", "change detect")
        outcome = run(
            [node],
            {
                "baseline_path": self.baseline,
                "comparison_path": os.path.join(self.tempdir, "gone.asc"),
                "change_output_path": os.path.join(self.tempdir, "mask.asc"),
            },
            run_id="RUN-C-3",
        )
        self.assertEqual(outcome.status, NodeStatus.FAIL)

    def test_mask_can_be_registered_and_verified(self) -> None:
        store = ArtifactStore(root=self.tempdir)
        node = change_detect_node("C1", "change detect", threshold=1, min_area_m2=150)
        context = {
            "baseline_path": self.baseline,
            "comparison_path": self.comparison,
            "change_output_path": os.path.join(self.tempdir, "mask.asc"),
            "min_area_m2": 150,
        }
        run([node], context, run_id="RUN-C-4")
        row = store.register(context["change_result"]["mask_path"], kind="change_mask")
        self.assertEqual(store.verify(row["artifact_id"])["artifact_id"], row["artifact_id"])


if __name__ == "__main__":
    unittest.main()
