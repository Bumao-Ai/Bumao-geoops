"""Tests for classic TIFF strip decoding, without GDAL."""

from __future__ import annotations

import os
import struct
import tempfile
import unittest
import zlib

from geoops.geotiff import GeoTiffError, read_geotiff_pixels
from geoops.survey.change import ChangeError, detect_changes, read_raster_grid


def _lzw_encode(values) -> bytes:
    dictionary = {bytes([value]): value for value in range(256)}
    clear, eoi, next_code, width = 256, 258, 258, 9
    codes = []
    bits = []

    def emit(code: int, code_width: int) -> None:
        bits.extend(format(code, "0%db" % code_width))

    emit(clear, width)
    current = b""
    for value in values:
        symbol = bytes([value])
        candidate = current + symbol
        if candidate in dictionary:
            current = candidate
            continue
        emit(dictionary[current], width)
        if next_code < 4096:
            dictionary[candidate] = next_code
            next_code += 1
            if width < 12 and next_code == (1 << width) - 1:
                width += 1
        current = symbol
    if current:
        emit(dictionary[current], width)
    emit(eoi, width)
    while len(bits) % 8:
        bits.append("0")
    text = "".join(bits)
    return int(text, 2).to_bytes(len(text) // 8, "big") if text else b""


def _tiled_tiff(path: str, values) -> None:
    count = 12
    data_offset = 8 + 2 + count * 12 + 4
    offsets_offset = data_offset
    counts_offset = offsets_offset + 8
    tile_data_start = counts_offset + 8
    tiles = [bytes(values[0:2]), bytes(values[2:4])]
    offsets = [tile_data_start, tile_data_start + 2]
    entries = [
        (256, 3, 1, 2),
        (257, 3, 1, 2),
        (258, 3, 1, 8),
        (259, 3, 1, 1),
        (262, 3, 1, 1),
        (277, 3, 1, 1),
        (284, 3, 1, 1),
        (339, 3, 1, 1),
        (322, 3, 1, 2),
        (323, 3, 1, 1),
        (324, 4, 2, offsets_offset),
        (325, 4, 2, counts_offset),
    ]
    body = struct.pack("<2sHI", b"II", 42, 8)
    body += struct.pack("<H", len(entries))
    for tag, typ, n, value in entries:
        body += struct.pack("<HHII", tag, typ, n, value)
    body += struct.pack("<I", 0)
    body += struct.pack("<2I", *offsets)
    body += struct.pack("<2I", 2, 2)
    body += tiles[0] + tiles[1]
    with open(path, "wb") as handle:
        handle.write(body)


def _tiff(path: str, values, compression: int = 1) -> None:
    raw = bytes(values)
    payload = raw
    if compression in (8, 32946):
        payload = zlib.compress(raw)
    elif compression == 5:
        payload = _lzw_encode(values)
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

    def test_lzw_pixels_are_decoded(self) -> None:
        _tiff(self.path, [1, 2, 3, 4], compression=5)
        image = read_geotiff_pixels(self.path)
        self.assertEqual(image["values"], [1.0, 2.0, 3.0, 4.0])

    def test_tiled_pixels_are_decoded(self) -> None:
        _tiled_tiff(self.path, [1, 2, 3, 4])
        image = read_geotiff_pixels(self.path)
        self.assertEqual(image["values"], [1.0, 2.0, 3.0, 4.0])

    def test_unsupported_compression_is_refused_explicitly(self) -> None:
        _tiff(self.path, [1, 2, 3, 4], compression=7)
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
