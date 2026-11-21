"""Tests for classic TIFF strip decoding, without GDAL."""

from __future__ import annotations

import os
import struct
import tempfile
import unittest
import zlib

from geoops.geotiff import (
    GeoTiffError,
    iter_geotiff_band_values,
    probe_geotiff,
    profile_geotiff_band,
    read_geotiff_pixels,
    write_geotiff_mask,
)
from geoops.survey.change import ChangeError, detect_changes, read_raster_grid

try:
    from PIL import Image

    _HAS_PIL = True
except ImportError:  # Pillow is optional; JPEG TIFFs are refused without it.
    Image = None
    _HAS_PIL = False


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


def _planar_tiff(path: str, plane_one, plane_two) -> None:
    count = 11
    data_offset = 8 + 2 + count * 12 + 4
    offsets_offset = data_offset
    counts_offset = offsets_offset + 8
    data_start = counts_offset + 8
    offsets = [data_start, data_start + 4]
    entries = [
        (256, 3, 1, 2),
        (257, 3, 1, 2),
        (258, 3, 2, 8 | (8 << 16)),
        (259, 3, 1, 1),
        (262, 3, 1, 1),
        (273, 4, 2, offsets_offset),
        (277, 3, 1, 2),
        (278, 3, 1, 2),
        (279, 4, 2, counts_offset),
        (284, 3, 1, 2),
        (339, 3, 2, 1 | (1 << 16)),
    ]
    body = struct.pack("<2sHI", b"II", 42, 8)
    body += struct.pack("<H", len(entries))
    for tag, typ, n, value in entries:
        body += struct.pack("<HHII", tag, typ, n, value)
    body += struct.pack("<I", 0)
    body += struct.pack("<2I", *offsets)
    body += struct.pack("<2I", 4, 4)
    body += bytes(plane_one) + bytes(plane_two)
    with open(path, "wb") as handle:
        handle.write(body)


def _planar_tiled_tiff(path: str, plane_one, plane_two) -> None:
    count = 12
    data_offset = 8 + 2 + count * 12 + 4
    offsets_offset = data_offset
    counts_offset = offsets_offset + 8
    data_start = counts_offset + 8
    offsets = [data_start, data_start + 4]
    entries = [
        (256, 3, 1, 2),
        (257, 3, 1, 2),
        (258, 3, 2, 8 | (8 << 16)),
        (259, 3, 1, 1),
        (262, 3, 1, 1),
        (277, 3, 1, 2),
        (284, 3, 1, 2),
        (322, 3, 1, 2),
        (323, 3, 1, 2),
        (324, 4, 2, offsets_offset),
        (325, 4, 2, counts_offset),
        (339, 3, 2, 1 | (1 << 16)),
    ]
    body = struct.pack("<2sHI", b"II", 42, 8)
    body += struct.pack("<H", len(entries))
    for tag, typ, n, value in entries:
        body += struct.pack("<HHII", tag, typ, n, value)
    body += struct.pack("<I", 0)
    body += struct.pack("<2I", *offsets)
    body += struct.pack("<2I", 4, 4)
    body += bytes(plane_one) + bytes(plane_two)
    with open(path, "wb") as handle:
        handle.write(body)


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


def _deflate_predictor8_tiff(path: str, values, width: int = 2) -> None:
    encoded = []
    for start in range(0, len(values), width):
        row = [int(value) for value in values[start:start + width]]
        encoded.append(row[0] % 256)
        for index in range(1, len(row)):
            encoded.append((row[index] - row[index - 1]) % 256)
    payload = zlib.compress(bytes(encoded))
    count = 12
    data_offset = 8 + 2 + count * 12 + 4
    entries = [
        (256, 3, 1, width),
        (257, 3, 1, len(values) // width),
        (258, 3, 1, 8),
        (259, 3, 1, 8),
        (262, 3, 1, 1),
        (273, 4, 1, data_offset),
        (277, 3, 1, 1),
        (278, 3, 1, len(values) // width),
        (279, 4, 1, len(payload)),
        (284, 3, 1, 1),
        (317, 3, 1, 2),
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


def _deflate_predictor16_tiff(path: str, values, width: int = 2) -> None:
    encoded = []
    for start in range(0, len(values), width):
        row = [int(value) for value in values[start:start + width]]
        encoded.append(row[0] % 65536)
        for index in range(1, len(row)):
            encoded.append((row[index] - row[index - 1]) % 65536)
    payload = zlib.compress(struct.pack("<%dH" % len(encoded), *encoded))
    count = 12
    data_offset = 8 + 2 + count * 12 + 4
    entries = [
        (256, 3, 1, width),
        (257, 3, 1, len(values) // width),
        (258, 3, 1, 16),
        (259, 3, 1, 8),
        (262, 3, 1, 1),
        (273, 4, 1, data_offset),
        (277, 3, 1, 1),
        (278, 3, 1, len(values) // width),
        (279, 4, 1, len(payload)),
        (284, 3, 1, 1),
        (317, 3, 1, 2),
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


def _oriented_tiff(path: str, values) -> None:
    raw = bytes(values)
    count = 12
    data_offset = 8 + 2 + count * 12 + 4
    entries = [
        (256, 3, 1, 2),
        (257, 3, 1, 2),
        (258, 3, 1, 8),
        (259, 3, 1, 1),
        (262, 3, 1, 1),
        (273, 4, 1, data_offset),
        (274, 3, 1, 6),
        (277, 3, 1, 1),
        (278, 3, 1, 2),
        (279, 4, 1, len(raw)),
        (284, 3, 1, 1),
        (339, 3, 1, 1),
    ]
    body = struct.pack("<2sHI", b"II", 42, 8)
    body += struct.pack("<H", len(entries))
    for tag, typ, n, value in entries:
        body += struct.pack("<HHII", tag, typ, n, value)
    body += struct.pack("<I", 0)
    body += raw
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


def _georeferenced_multiband_tiff(path: str, values) -> None:
    """A 2x2 chunky two-band GeoTIFF with PixelScale and Tiepoint, no GeoKey."""
    raw = bytes(values)
    count = 13
    data_offset = 8 + 2 + count * 12 + 4
    scale_offset = data_offset
    tie_offset = scale_offset + 24
    data_start = tie_offset + 48
    entries = [
        (256, 3, 1, 2),
        (257, 3, 1, 2),
        (258, 3, 2, 8 | (8 << 16)),
        (259, 3, 1, 1),
        (262, 3, 1, 2),
        (273, 4, 1, data_start),
        (277, 3, 1, 2),
        (278, 3, 1, 2),
        (279, 4, 1, len(raw)),
        (284, 3, 1, 1),
        (339, 3, 2, 1 | (1 << 16)),
        (33550, 12, 3, scale_offset),
        (33922, 12, 6, tie_offset),
    ]
    body = struct.pack("<2sHI", b"II", 42, 8)
    body += struct.pack("<H", len(entries))
    for tag, typ, n, value in entries:
        body += struct.pack("<HHII", tag, typ, n, value)
    body += struct.pack("<I", 0)
    body += struct.pack("<3d", 10.0, 10.0, 0.0)
    body += struct.pack("<6d", 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    body += raw
    with open(path, "wb") as handle:
        handle.write(body)


def _bigtiff(path: str, values) -> None:
    """A minimal 2x2 BigTIFF with PixelScale and Tiepoint, no GeoKey."""
    raw = bytes(values)
    count = 13
    data_start = 16 + 8 + count * 20 + 8
    scale_offset = data_start
    tie_offset = scale_offset + 24
    pixel_start = tie_offset + 48
    entries = [
        (256, 3, 1, struct.pack("<H", 2) + b"\0" * 6),
        (257, 3, 1, struct.pack("<H", 2) + b"\0" * 6),
        (258, 3, 1, struct.pack("<H", 8) + b"\0" * 6),
        (259, 3, 1, struct.pack("<H", 1) + b"\0" * 6),
        (262, 3, 1, struct.pack("<H", 1) + b"\0" * 6),
        (273, 16, 1, struct.pack("<Q", pixel_start)),
        (277, 3, 1, struct.pack("<H", 1) + b"\0" * 6),
        (278, 3, 1, struct.pack("<H", 2) + b"\0" * 6),
        (279, 16, 1, struct.pack("<Q", len(raw))),
        (284, 3, 1, struct.pack("<H", 1) + b"\0" * 6),
        (339, 3, 1, struct.pack("<H", 1) + b"\0" * 6),
        (33550, 12, 3, struct.pack("<Q", scale_offset)),
        (33922, 12, 6, struct.pack("<Q", tie_offset)),
    ]
    body = struct.pack("<2sHHHQ", b"II", 43, 8, 0, 16)
    body += struct.pack("<Q", count)
    for tag, typ, n, value_field in entries:
        body += struct.pack("<HHQ", tag, typ, n) + value_field
    body += struct.pack("<Q", 0)
    body += struct.pack("<3d", 10.0, 10.0, 0.0)
    body += struct.pack("<6d", 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
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

    def test_deflate_predictor_wraps_16bit_rows(self) -> None:
        path = os.path.join(self.tmp.name, "predictor16.tif")
        _deflate_predictor16_tiff(path, [40000, 100, 50000, 200])
        image = read_geotiff_pixels(path)
        self.assertEqual(image["values"], [40000.0, 100.0, 50000.0, 200.0])

    def test_rotated_orientation_is_refused_not_misread(self) -> None:
        path = os.path.join(self.tmp.name, "rotated.tif")
        _oriented_tiff(path, [1, 2, 3, 4])
        with self.assertRaises(GeoTiffError) as caught:
            read_geotiff_pixels(path)
        self.assertIn("Orientation=6", str(caught.exception))

    def test_deflate_pixels_are_decoded(self) -> None:
        _tiff(self.path, [9, 8, 7, 6], compression=8)
        image = read_geotiff_pixels(self.path)
        self.assertEqual(image["values"], [9.0, 8.0, 7.0, 6.0])

    def test_deflate_predictor_wraps_8bit_rows(self) -> None:
        path = os.path.join(self.tmp.name, "predictor.tif")
        _deflate_predictor8_tiff(path, [200, 10, 50, 5])
        image = read_geotiff_pixels(path)
        self.assertEqual(image["values"], [200.0, 10.0, 50.0, 5.0])

    def test_bigtiff_header_and_pixels_are_read(self) -> None:
        path = os.path.join(self.tmp.name, "big.tif")
        _bigtiff(path, [1, 2, 3, 4])
        info = probe_geotiff(path, require_crs=False)
        self.assertEqual(info["width"], 2)
        self.assertEqual(info["height"], 2)
        self.assertEqual(info["bounds"], [0.0, -20.0, 20.0, 0.0])
        image = read_geotiff_pixels(path)
        self.assertEqual(image["values"], [1.0, 2.0, 3.0, 4.0])
        grid = read_raster_grid(path)
        self.assertEqual(grid["cellsize"], 10.0)
        self.assertEqual(grid["crs"], "")

    def test_multiband_band_is_selected(self) -> None:
        path = os.path.join(self.tmp.name, "multi.tif")
        _georeferenced_multiband_tiff(path, [1, 5, 2, 6, 3, 7, 4, 8])
        grid = read_raster_grid(path, band=2)
        self.assertEqual(grid["band"], 2)
        self.assertEqual(grid["values"], [5.0, 6.0, 7.0, 8.0])
        with self.assertRaises(ChangeError):
            read_raster_grid(path, band=3)

    def test_lzw_pixels_are_decoded(self) -> None:
        _tiff(self.path, [1, 2, 3, 4], compression=5)
        image = read_geotiff_pixels(self.path)
        self.assertEqual(image["values"], [1.0, 2.0, 3.0, 4.0])

    def test_tiled_pixels_are_decoded(self) -> None:
        _tiled_tiff(self.path, [1, 2, 3, 4])
        image = read_geotiff_pixels(self.path)
        self.assertEqual(image["values"], [1.0, 2.0, 3.0, 4.0])

    def test_separate_planar_bands_are_interleaved(self) -> None:
        _planar_tiff(self.path, [1, 2, 3, 4], [5, 6, 7, 8])
        image = read_geotiff_pixels(self.path)
        self.assertEqual(image["bands"], 2)
        self.assertEqual(image["values"], [1.0, 5.0, 2.0, 6.0, 3.0, 7.0, 4.0, 8.0])

    def test_separate_planar_tiles_are_interleaved(self) -> None:
        _planar_tiled_tiff(self.path, [1, 2, 3, 4], [5, 6, 7, 8])
        image = read_geotiff_pixels(self.path)
        self.assertEqual(image["bands"], 2)
        self.assertEqual(image["values"], [1.0, 5.0, 2.0, 6.0, 3.0, 7.0, 4.0, 8.0])

    @unittest.skipUnless(_HAS_PIL, "Pillow is not installed; JPEG TIFF decoding is optional")
    def test_jpeg_rgb_tiff_is_interleaved(self) -> None:
        image = Image.new("RGB", (2, 2))
        image.putdata([(10, 20, 30), (40, 50, 60), (70, 80, 90), (100, 110, 120)])
        image.save(self.path, format="TIFF", compression="jpeg")
        decoded = read_geotiff_pixels(self.path)
        self.assertEqual(decoded["bands"], 3)
        self.assertEqual(len(decoded["values"]), 12)

    def test_written_geotiff_has_real_georeferencing(self) -> None:
        path = os.path.join(tempfile.mkdtemp(prefix="geoops-write-"), "mask.tif")
        write_geotiff_mask(
            path,
            width=2,
            height=2,
            cellsize=10.0,
            xllcorner=500000.0,
            yllcorner=4500000.0,
            crs="EPSG:4326",
            crs_model="geographic",
            values=[1.0, 0.0, -9999.0, 1.0],
            nodata=-9999.0,
        )
        probe = probe_geotiff(path)
        self.assertEqual(probe["width"], 2)
        self.assertEqual(probe["height"], 2)
        self.assertEqual(probe["crs"], "EPSG:4326")
        self.assertEqual(probe["pixel_size"], [10.0, 10.0])
        self.assertEqual(probe["bounds"], [500000.0, 4500000.0, 500020.0, 4500020.0])
        image = read_geotiff_pixels(path)
        self.assertEqual(image["crs"], "EPSG:4326")
        self.assertEqual(image["crs_model"], "geographic")
        self.assertEqual(image["nodata"], -9999.0)
        self.assertEqual(image["values"], [1.0, 0.0, -9999.0, 1.0])

    def test_streamed_band_values_match_full_decode_for_every_layout(self) -> None:
        fixtures = [
            ("strip", lambda p: _tiff(p, [1, 2, 3, 4])),
            ("lzw", lambda p: _tiff(p, [1, 2, 3, 4], compression=5)),
            ("deflate", lambda p: _tiff(p, [1, 2, 3, 4], compression=8)),
            ("predictor8", lambda p: _deflate_predictor8_tiff(p, [200, 10, 50, 5])),
            ("predictor16", lambda p: _deflate_predictor16_tiff(p, [40000, 100, 50000, 200])),
            ("tiled", lambda p: _tiled_tiff(p, [1, 2, 3, 4])),
            ("planar", lambda p: _planar_tiff(p, [1, 2, 3, 4], [5, 6, 7, 8])),
            ("planar_tiled", lambda p: _planar_tiled_tiff(p, [1, 2, 3, 4], [5, 6, 7, 8])),
            ("multiband", lambda p: _georeferenced_multiband_tiff(p, [1, 5, 2, 6, 3, 7, 4, 8])),
            ("bigtiff", lambda p: _bigtiff(p, [1, 2, 3, 4])),
        ]
        for label, builder in fixtures:
            with self.subTest(layout=label):
                builder(self.path)
                image = read_geotiff_pixels(self.path)
                for band in range(1, image["bands"] + 1):
                    expected = image["values"][band - 1::image["bands"]]
                    streamed = list(iter_geotiff_band_values(self.path, band))
                    self.assertEqual(streamed, expected)

    def test_profile_geotiff_band_counts_nodata_without_full_decode(self) -> None:
        write_geotiff_mask(
            self.path,
            width=2,
            height=2,
            cellsize=10.0,
            xllcorner=0.0,
            yllcorner=0.0,
            crs="EPSG:4326",
            crs_model="geographic",
            values=[1.0, 0.0, -9999.0, 1.0],
            nodata=-9999.0,
        )
        profile = profile_geotiff_band(self.path)
        self.assertEqual(profile["valid_cells"], 3)
        self.assertEqual(profile["nodata_cells"], 1)
        self.assertEqual(profile["non_finite_cells"], 0)
        self.assertEqual(profile["min"], 0.0)
        self.assertEqual(profile["max"], 1.0)
        self.assertAlmostEqual(profile["mean"], 2.0 / 3.0)

    def test_unsupported_compression_is_refused_explicitly(self) -> None:
        _tiff(self.path, [1, 2, 3, 4], compression=6)
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
