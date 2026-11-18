"""Tests for the ASCII mask confusion-matrix metrics."""

from __future__ import annotations

import os
import tempfile
import unittest

from geoops.quality.metrics import MetricsError, compare_masks, read_ascii_grid, read_mask_grid
from geoops.tests.test_geotiff_pixels import _tiff


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

    def test_geotiff_mask_without_georeferencing_is_refused(self) -> None:
        tiff = os.path.join(self.tmp.name, "mask.tif")
        _tiff(tiff, [1, 0, 0, 1])
        with self.assertRaises(MetricsError):
            read_mask_grid(tiff)


if __name__ == "__main__":
    unittest.main()
