"""GeoTIFF header probe: reads real tags, refuses a TIFF without them."""

from __future__ import annotations

import os
import struct
import tempfile
import unittest

from geoops.domain.datasets import register
from geoops.geotiff import GeoTiffError, probe_geotiff


def make_geotiff(path: str, epsg: int = 32650) -> str:
    width, height = 4, 4
    count = 7
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
    out += entry(34735, 3, 8, keys_offset)
    out += struct.pack("<I", 0)
    out += struct.pack("<3d", 1.0, 1.0, 0.0)
    out += struct.pack("<6d", 0.0, 0.0, 0.0, 0.0, 4.0, 0.0)
    out += struct.pack("<8H", 1, 1, 0, 1, 3072, 0, 1, epsg)
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

    def test_dataset_intake_uses_the_header_without_a_sidecar(self) -> None:
        path = make_geotiff(os.path.join(self.tempdir, "b.tif"))
        record = register(path)
        self.assertEqual(record.status, "READY")
        self.assertEqual(record.crs, "EPSG:32650")
        self.assertEqual(record.metadata_source, "geotiff-header")
        self.assertEqual(record.width, 4)


if __name__ == "__main__":
    unittest.main()
