"""Tests for classic TIFF strip decoding, without GDAL."""

from __future__ import annotations

import os
import struct
import tempfile
import unittest
import zlib

from geoops.geotiff import GeoTiffError, read_geotiff_pixels
from geoops.survey.change import ChangeError, detect_changes, read_raster_grid


def _tiff(path: str, values, compression: int = 1) -> None:
    raw = bytes(values)
    payload = raw
    if compression in (8, 32946):
        payload = zlib.compress(raw)
    count = 11
    data_offset = 8 + 2 + count * 12 + 4
    entries = [
        (256, 3, 1, 2),
        (257, 3, 1, 2),
        (258, 3, 1, 8),
        (259, 3, 1, compression),
        (262, 3, 1, 1),
        (273, 4, 1, data_offset),
        (277, 3, 1, 1),
        (278, 3, 1, 2),
        (279, 4, 1, len(payload)),
        (284, 3, 1, 1),
        (339, 3, 1, 1),
    ]
    body = struct.pack("<2sHI", b"II", 42, 8)
    body += struct.pack("<H", len(entries))
    for tag, typ, n, value in entries:
        body += struct.pack("<HHII", tag, typ, n, value)
    body += struct.pack("<I", 0)
    body += payload
    with open(path, "wb") as handle:
        handle.write(body)


def _georeferenced_tiff(path: str, values, scale=(10.0, 10.0, 0.0), tie=(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)) -> None:
    raw = bytes(values)
    count = 13
    data_offset = 8 + 2 + count * 12 + 4
    scale_offset = data_offset
    tie_offset = scale_offset + 24
    data_start = tie_offset + 48
    entries = [
        (256, 3, 1, 2),
        (257, 3, 1, 2),
        (258, 3, 1, 8),
        (259, 3, 1, 1),
        (262, 3, 1, 1),
        (273, 4, 1, data_start),
        (277, 3, 1, 1),
        (278, 3, 1, 2),
        (279, 4, 1, len(raw)),
        (284, 3, 1, 1),
        (339, 3, 1, 1),
        (33550, 12, 3, scale_offset),
        (33922, 12, 6, tie_offset),
    ]
    body = struct.pack("<2sHI", b"II", 42, 8)
    body += struct.pack("<H", len(entries))
    for tag, typ, n, value in entries:
        body += struct.pack("<HHII", tag, typ, n, value)
    body += struct.pack("<I", 0)
    body += struct.pack("<3d", *scale)
    body += struct.pack("<6d", *tie)
    body += raw
    with open(path, "wb") as handle:
        handle.write(body)


class GeoTiffPixelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "grid.tif")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_uncompressed_pixels_are_decoded(self) -> None:
        _tiff(self.path, [1, 2, 3, 4])
        image = read_geotiff_pixels(self.path)
        self.assertEqual(image["width"], 2)
        self.assertEqual(image["height"], 2)
        self.assertEqual(image["bands"], 1)
        self.assertEqual(image["values"], [1.0, 2.0, 3.0, 4.0])

    def test_deflate_pixels_are_decoded(self) -> None:
        _tiff(self.path, [9, 8, 7, 6], compression=8)
        image = read_geotiff_pixels(self.path)
        self.assertEqual(image["values"], [9.0, 8.0, 7.0, 6.0])

    def test_lzw_is_refused_explicitly(self) -> None:
        _tiff(self.path, [1, 2, 3, 4], compression=5)
        with self.assertRaises(GeoTiffError):
            read_geotiff_pixels(self.path)

    def test_georeferenced_geotiff_is_a_change_grid(self) -> None:
        _georeferenced_tiff(self.path, [1, 2, 3, 4], scale=(10.0, 10.0, 0.0))
        grid = read_raster_grid(self.path)
        self.assertEqual(grid["ncols"], 2)
        self.assertEqual(grid["nrows"], 2)
        self.assertEqual(grid["cellsize"], 10.0)
        self.assertEqual(grid["header"]["xllcorner"], 0.0)
        self.assertEqual(grid["header"]["yllcorner"], -20.0)
        self.assertEqual(grid["values"], [1.0, 2.0, 3.0, 4.0])

    def test_geotiff_pair_runs_change_detection(self) -> None:
        baseline = os.path.join(self.tmp.name, "baseline.tif")
        comparison = os.path.join(self.tmp.name, "comparison.tif")
        _georeferenced_tiff(baseline, [1, 1, 1, 1])
        _georeferenced_tiff(comparison, [2, 1, 1, 1])
        result = detect_changes(baseline, comparison, threshold=1.0, min_area_m2=0.0)
        self.assertEqual(result["ncols"], 2)
        self.assertEqual(result["nrows"], 2)
        self.assertEqual(result["changed_cells"], 1)
        self.assertEqual(result["kept_cells"], 1)
        self.assertEqual(result["mask"], [1, 0, 0, 0])

    def test_geotiff_without_georeferencing_cannot_be_a_change_grid(self) -> None:
        _tiff(self.path, [1, 2, 3, 4])
        with self.assertRaises(ChangeError):
            read_raster_grid(self.path)


if __name__ == "__main__":
    unittest.main()
