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

from geoops.artifacts import ArtifactStore
from geoops.geotiff import read_geotiff_pixels, write_geotiff_mask
from geoops.survey.change import (
    ChangeError,
    detect_changes,
    read_ascii_grid,
    read_raster_grid,
    write_change_mask,
)
from geoops.survey.change_node import change_detect_node
from geoops.tests.test_geotiff_pixels import _georeferenced_tiff
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
        self.assertEqual(result["changed_area_m2"], 200)

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

    def test_geotiff_sidecar_crs_fills_a_header_without_epsg(self) -> None:
        path = os.path.join(self.tempdir, "plain-georef.tif")
        _georeferenced_tiff(path, bytes([1, 2, 3, 4]))
        with open(path + ".json", "w", encoding="utf-8") as handle:
            json.dump({"crs": "EPSG:3857"}, handle)
        grid = read_raster_grid(path)
        self.assertEqual(grid["crs"], "EPSG:3857")
        self.assertEqual(grid["crs_model"], "projected")
        self.assertEqual(grid["values"], [1, 2, 3, 4])


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
