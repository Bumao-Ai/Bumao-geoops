"""GeoTIFF header probe: reads real tags, refuses a TIFF without them."""

from __future__ import annotations

import json
import os
import struct
import tempfile
import unittest

from geoops.domain.datasets import register
from geoops.geotiff import GeoTiffError, probe_geotiff


def make_geotiff(path: str, epsg: int = 32650, pixel_is_point: bool = False) -> str:
    width, height = 4, 4
    count = 7
    key_count = 2 if pixel_is_point else 1
    key_words = 4 + key_count * 4
    ifd_offset = 8
    data_start = ifd_offset + 2 + count * 12 + 4
    scale_offset = data_start
    tie_offset = scale_offset + 24
    keys_offset = tie_offset + 48

    def entry(tag: int, typ: int, n: int, value: int) -> bytes:
        if typ == 3 and n == 1:
            return struct.pack("<HHI", tag, typ, n) + struct.pack("<HH", value, 0)
        return struct.pack("<HHI", tag, typ, n) + struct.pack("<I", value)

    out = b"II" + struct.pack("<H", 42) + struct.pack("<I", ifd_offset)
    out += struct.pack("<H", count)
    out += entry(256, 3, 1, width)
    out += entry(257, 3, 1, height)
    out += entry(258, 3, 1, 8)
    out += entry(277, 3, 1, 1)
    out += entry(33550, 12, 3, scale_offset)
    out += entry(33922, 12, 6, tie_offset)
    out += entry(34735, 3, key_words, keys_offset)
    out += struct.pack("<I", 0)
    out += struct.pack("<3d", 1.0, 1.0, 0.0)
    out += struct.pack("<6d", 0.0, 0.0, 0.0, 0.0, 4.0, 0.0)
    out += struct.pack("<4H", 1, 1, 0, key_count)
    out += struct.pack("<4H", 3072, 0, 1, epsg)
    if pixel_is_point:
        out += struct.pack("<4H", 1025, 0, 1, 2)
    with open(path, "wb") as handle:
        handle.write(out)
    return path


def make_transformed_geotiff(path: str, matrix, pixel_is_point: bool = False) -> str:
    width, height = 3, 2
    count = 6
    key_count = 2 if pixel_is_point else 1
    key_words = 4 + key_count * 4
    ifd_offset = 8
    data_start = ifd_offset + 2 + count * 12 + 4
    matrix_offset = data_start
    keys_offset = matrix_offset + 16 * 8

    def entry(tag: int, typ: int, n: int, value: int) -> bytes:
        if typ == 3 and n == 1:
            return struct.pack("<HHI", tag, typ, n) + struct.pack("<HH", value, 0)
        return struct.pack("<HHI", tag, typ, n) + struct.pack("<I", value)

    out = b"II" + struct.pack("<H", 42) + struct.pack("<I", ifd_offset)
    out += struct.pack("<H", count)
    out += entry(256, 3, 1, width)
    out += entry(257, 3, 1, height)
    out += entry(258, 3, 1, 8)
    out += entry(277, 3, 1, 1)
    out += entry(34264, 12, 16, matrix_offset)
    out += entry(34735, 3, key_words, keys_offset)
    out += struct.pack("<I", 0)
    out += struct.pack("<16d", *matrix)
    out += struct.pack("<4H", 1, 1, 0, key_count)
    out += struct.pack("<4H", 3072, 0, 1, 32650)
    if pixel_is_point:
        out += struct.pack("<4H", 1025, 0, 1, 2)
    with open(path, "wb") as handle:
        handle.write(out)
    return path


class GeoTiffTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.mkdtemp(prefix="geoops-tiff-")

    def test_real_tags_are_read(self) -> None:
        path = make_geotiff(os.path.join(self.tempdir, "a.tif"))
        info = probe_geotiff(path)
        self.assertEqual(info["crs"], "EPSG:32650")
        self.assertEqual(info["width"], 4)
        self.assertEqual(info["height"], 4)
        self.assertEqual(info["bounds"], [0.0, 0.0, 4.0, 4.0])
        self.assertEqual(info["pixel_size"], [1.0, 1.0])

    def test_a_plain_tiff_has_no_crs(self) -> None:
        path = os.path.join(self.tempdir, "plain.tif")
        with open(path, "wb") as handle:
            handle.write(b"II" + struct.pack("<H", 42) + struct.pack("<I", 8) + struct.pack("<H", 0) + struct.pack("<I", 0))
        with self.assertRaises(GeoTiffError):
            probe_geotiff(path)

    def test_pixel_is_point_shifts_bounds_by_half_a_cell(self) -> None:
        path = make_geotiff(os.path.join(self.tempdir, "point.tif"), pixel_is_point=True)
        info = probe_geotiff(path)
        self.assertEqual(info["raster_type"], 2)
        self.assertEqual(info["bounds"], [-0.5, 0.5, 3.5, 4.5])
        record = register(path)
        self.assertEqual(record.bounds, [-0.5, 0.5, 3.5, 4.5])

    def test_model_transformation_supplies_the_affine_origin(self) -> None:
        matrix = [
            2.0, 0.0, 0.0, 100.0,
            0.0, -3.0, 0.0, 200.0,
            0.0, 0.0, 0.0, 0.0,
            0.0, 0.0, 0.0, 1.0,
        ]
        path = make_transformed_geotiff(os.path.join(self.tempdir, "matrix.tif"), matrix)
        info = probe_geotiff(path)
        self.assertEqual(info["pixel_size"], [2.0, 3.0])
        self.assertEqual(info["bounds"], [100.0, 194.0, 106.0, 200.0])

    def test_model_transformation_with_rotation_is_refused(self) -> None:
        matrix = [
            2.0, 1.0, 0.0, 100.0,
            0.0, -3.0, 0.0, 200.0,
            0.0, 0.0, 0.0, 0.0,
            0.0, 0.0, 0.0, 1.0,
        ]
        path = make_transformed_geotiff(os.path.join(self.tempdir, "rotated.tif"), matrix)
        with self.assertRaises(GeoTiffError) as caught:
            probe_geotiff(path)
        self.assertIn("rotated", str(caught.exception))

    def test_dataset_intake_uses_the_header_without_a_sidecar(self) -> None:
        path = make_geotiff(os.path.join(self.tempdir, "b.tif"))
        record = register(path)
        self.assertEqual(record.status, "READY")
        self.assertEqual(record.crs, "EPSG:32650")
        self.assertEqual(record.metadata_source, "geotiff-header")
        self.assertEqual(record.width, 4)

    def test_sidecar_crs_does_not_drop_geotiff_dimensions(self) -> None:
        path = make_geotiff(os.path.join(self.tempdir, "c.tif"))
        with open(path + ".json", "w", encoding="utf-8") as handle:
            json.dump({"crs": "EPSG:4547"}, handle)
        record = register(path)
        self.assertEqual(record.status, "READY")
        self.assertEqual(record.crs, "EPSG:4547")
        self.assertTrue(record.metadata_source.endswith(".tif.json"))
        self.assertIn("overrides GeoTIFF header EPSG:32650", record.reason)
        self.assertEqual(record.width, 4)
        self.assertEqual(record.height, 4)
        self.assertEqual(record.bounds, [0.0, 0.0, 4.0, 4.0])
        self.assertEqual(record.pixel_size, [1.0, 1.0])

    def test_sidecar_crs_allows_a_geotiff_header_without_epsg(self) -> None:
        path = make_geotiff(os.path.join(self.tempdir, "d.tif"), epsg=0)
        with open(path + ".json", "w", encoding="utf-8") as handle:
            json.dump({"crs": "EPSG:4547"}, handle)
        record = register(path)
        self.assertEqual(record.status, "READY")
        self.assertEqual(record.crs, "EPSG:4547")
        self.assertEqual(record.width, 4)
        self.assertEqual(record.bounds, [0.0, 0.0, 4.0, 4.0])


if __name__ == "__main__":
    unittest.main()
