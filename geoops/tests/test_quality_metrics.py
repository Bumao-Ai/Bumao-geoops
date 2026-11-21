"""Tests for the ASCII mask confusion-matrix metrics."""

from __future__ import annotations

import os
import tempfile
import unittest

from geoops.quality.metrics import MetricsError, compare_masks, read_ascii_grid, read_mask_grid
from geoops.geotiff import write_geotiff_mask
from geoops.tests.test_geotiff_pixels import _georeferenced_tiff, _tiff


def _grid(path: str, values: str, nodata: str = "-9999") -> None:
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(
            "ncols 3\nnrows 2\nxllcorner 0\nyllcorner 0\ncellsize 10\n%s\n%s\n"
            % ("NODATA_value " + nodata, values)
        )


class MetricsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.reference = os.path.join(self.tmp.name, "ref.asc")
        self.predicted = os.path.join(self.tmp.name, "pred.asc")
        _grid(self.reference, "1 1 0\n0 1 0")
        _grid(self.predicted, "1 0 0\n0 1 1")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_confusion_matrix_is_real_arithmetic(self) -> None:
        result = compare_masks(self.reference, self.predicted, synthetic_reference=True)
        self.assertEqual(result["cells"]["tp"], 2)
        self.assertEqual(result["cells"]["fp"], 1)
        self.assertEqual(result["cells"]["fn"], 1)
        self.assertEqual(result["cells"]["tn"], 2)
        self.assertAlmostEqual(result["metrics"]["pixel_accuracy"], 4 / 6)
        self.assertAlmostEqual(result["metrics"]["precision"], 2 / 3)
        self.assertAlmostEqual(result["metrics"]["recall"], 2 / 3)
        self.assertAlmostEqual(result["metrics"]["f1"], 2 / 3)
        self.assertAlmostEqual(result["metrics"]["iou"], 0.5)
        self.assertTrue(result["synthetic_reference"])

    def test_nodata_cells_are_excluded(self) -> None:
        reference = os.path.join(self.tmp.name, "ref_nodata.asc")
        predicted = os.path.join(self.tmp.name, "pred_nodata.asc")
        _grid(reference, "1 -9999 0\n0 1 0")
        _grid(predicted, "1 1 0\n0 1 1")
        result = compare_masks(reference, predicted)
        self.assertEqual(result["cells"]["valid"], 5)
        self.assertEqual(result["cells"]["skipped_nodata"], 1)
        self.assertEqual(result["cells"]["tp"], 2)

    def test_non_finite_cells_are_excluded_from_the_matrix(self) -> None:
        reference = os.path.join(self.tmp.name, "ref_inf.asc")
        predicted = os.path.join(self.tmp.name, "pred_inf.asc")
        _grid(reference, "1 1e999 0\n0 1 0")
        _grid(predicted, "1 1 0\n0 1 1")
        result = compare_masks(reference, predicted)
        self.assertEqual(result["cells"]["valid"], 5)
        self.assertEqual(result["cells"]["skipped_non_finite"], 1)
        self.assertEqual(result["cells"]["tp"], 2)

    def test_undeclared_nodata_does_not_swallow_a_real_value(self) -> None:
        reference = os.path.join(self.tmp.name, "ref_no_nodata.asc")
        predicted = os.path.join(self.tmp.name, "pred_no_nodata.asc")
        text = "ncols 3\nnrows 1\nxllcorner 0\nyllcorner 0\ncellsize 10\n-9999 1 0\n"
        for path in (reference, predicted):
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(text)
        result = compare_masks(reference, predicted)
        self.assertEqual(result["cells"]["valid"], 3)
        self.assertEqual(result["cells"]["skipped_nodata"], 0)

    def test_non_finite_threshold_is_refused(self) -> None:
        with self.assertRaises(MetricsError):
            compare_masks(self.reference, self.predicted, threshold=float("nan"))

    def test_dimension_mismatch_is_refused(self) -> None:
        other = os.path.join(self.tmp.name, "other.asc")
        with open(other, "w", encoding="utf-8") as handle:
            handle.write("ncols 2\nnrows 1\ncellsize 10\n0 0\n")
        with self.assertRaises(MetricsError):
            compare_masks(self.reference, other)

    def test_reader_reports_missing_values(self) -> None:
        broken = os.path.join(self.tmp.name, "broken.asc")
        with open(broken, "w", encoding="utf-8") as handle:
            handle.write("ncols 2\nnrows 2\ncellsize 10\n0 0\n0\n")
        with self.assertRaises(MetricsError):
            read_ascii_grid(broken)

    def test_center_origin_masks_are_normalised(self) -> None:
        center = os.path.join(self.tmp.name, "center.asc")
        with open(center, "w", encoding="utf-8") as handle:
            handle.write("ncols 2\nnrows 1\nxllcenter 5\nyllcenter 5\ncellsize 10\n1 0\n")
        grid = read_ascii_grid(center)
        self.assertEqual(grid["header"]["xllcorner"], 0.0)
        self.assertEqual(grid["header"]["yllcorner"], 0.0)

    def test_sidecar_crs_mismatch_is_refused(self) -> None:
        with open(self.reference + ".json", "w", encoding="utf-8") as handle:
            handle.write('{"crs": "EPSG:3857"}')
        with open(self.predicted + ".json", "w", encoding="utf-8") as handle:
            handle.write('{"crs": "EPSG:4547"}')
        with self.assertRaises(MetricsError) as caught:
            compare_masks(self.reference, self.predicted)
        self.assertIn("CRS differ", str(caught.exception))


    def test_geotiff_mask_without_georeferencing_is_refused(self) -> None:
        tiff = os.path.join(self.tmp.name, "mask.tif")
        _tiff(tiff, [1, 0, 0, 1])
        with self.assertRaises(MetricsError):
            read_mask_grid(tiff)

    def test_georeferenced_geotiff_masks_compute_accuracy(self) -> None:
        reference = os.path.join(self.tmp.name, "ref.tif")
        predicted = os.path.join(self.tmp.name, "pred.tif")
        _georeferenced_tiff(reference, [1, 1, 0, 0])
        _georeferenced_tiff(predicted, [1, 0, 0, 1])
        result = compare_masks(reference, predicted)
        self.assertEqual(result["cells"]["tp"], 1)
        self.assertEqual(result["cells"]["fp"], 1)
        self.assertEqual(result["cells"]["fn"], 1)
        self.assertEqual(result["cells"]["tn"], 1)

    def test_mixed_ascii_reference_and_geotiff_prediction_align(self) -> None:
        reference = os.path.join(self.tmp.name, "mixed_ref.asc")
        predicted = os.path.join(self.tmp.name, "mixed_pred.tif")
        with open(reference, "w", encoding="utf-8") as handle:
            handle.write(
                "ncols 2\nnrows 2\nxllcorner 0\nyllcorner 0\ncellsize 10\n"
                "NODATA_value -9999\n1 0\n0 1\n"
            )
        with open(reference + ".json", "w", encoding="utf-8") as handle:
            handle.write('{"crs": "EPSG:4547", "crs_model": "projected"}')
        write_geotiff_mask(
            predicted,
            width=2,
            height=2,
            cellsize=10.0,
            xllcorner=0.0,
            yllcorner=0.0,
            crs="EPSG:4547",
            crs_model="projected",
            values=[1.0, 1.0, 0.0, 0.0],
        )
        result = compare_masks(reference, predicted)
        self.assertEqual(result["cells"]["tp"], 1)
        self.assertEqual(result["cells"]["fp"], 1)
        self.assertEqual(result["cells"]["fn"], 1)
        self.assertEqual(result["cells"]["tn"], 1)

    def test_geotiff_masks_with_different_origins_are_refused(self) -> None:
        reference = os.path.join(self.tmp.name, "ref_origin.tif")
        predicted = os.path.join(self.tmp.name, "pred_origin.tif")
        _georeferenced_tiff(
            reference, [1, 0, 0, 1], tie=(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        )
        _georeferenced_tiff(
            predicted, [1, 0, 0, 1], tie=(0.0, 0.0, 0.0, 100.0, 0.0, 0.0)
        )
        with self.assertRaises(MetricsError) as caught:
            compare_masks(reference, predicted)
        self.assertIn("origins differ", str(caught.exception))

    def test_geotiff_masks_with_different_crs_are_refused(self) -> None:
        reference = os.path.join(self.tmp.name, "ref_crs.tif")
        predicted = os.path.join(self.tmp.name, "pred_crs.tif")
        for path, crs, model in (
            (reference, "EPSG:3857", "projected"),
            (predicted, "EPSG:4326", "geographic"),
        ):
            write_geotiff_mask(
                path,
                width=2,
                height=2,
                cellsize=10.0,
                xllcorner=0.0,
                yllcorner=0.0,
                crs=crs,
                crs_model=model,
                values=[1.0, 0.0, 0.0, 1.0],
            )
        with self.assertRaises(MetricsError) as caught:
            compare_masks(reference, predicted)
        self.assertIn("CRS differ", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
