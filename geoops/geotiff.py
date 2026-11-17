"""Read GeoTIFF georeferencing from the file header, without GDAL.

Only classic TIFF (magic 42) with GeoTIFF tags is supported. The parser returns
width, height, band count, EPSG code, pixel size and bounds when the tags are
present; an ordinary TIFF without those tags is refused rather than guessed.

This is deliberately a narrow reader: it does not decode pixels and it does not
replace GDAL. It exists so a real GeoTIFF can supply its own CRS to the dataset
registry on a machine where no geospatial library is installed.
"""

from __future__ import annotations

import struct
from typing import Any, Dict, List, Optional

TAG_WIDTH = 256
TAG_HEIGHT = 257
TAG_BITS = 258
TAG_SAMPLES = 277
TAG_PIXEL_SCALE = 33550
TAG_TIEPOINT = 33922
TAG_GEOKEYS = 34735
TAG_DOUBLE_PARAMS = 34736
TAG_ASCII_PARAMS = 34737

TYPE_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 11: 4, 12: 8}
EPSG_KEYS = {3072: "projected", 2048: "geographic"}


class GeoTiffError(ValueError):
    """The file is not a georeferenced classic GeoTIFF."""


def _unpack(fmt: str, data: bytes) -> Any:
    try:
        return struct.unpack(fmt, data)
    except struct.error as exc:
        raise GeoTiffError("truncated GeoTIFF field: %s" % exc) from exc


def _read_field(data: bytes, endian: str, typ: int, count: int, raw: bytes) -> Any:
    if typ not in TYPE_SIZES:
        raise GeoTiffError("unsupported TIFF field type %d" % typ)
    size = TYPE_SIZES[typ] * count
    if size > 4:
        offset = struct.unpack(endian + "I", raw)[0]
        raw = data[offset:offset + size]
        if len(raw) < size:
            raise GeoTiffError("GeoTIFF field points past end of file")
    if typ == 2:
        return raw[:count].decode("latin-1", "replace")
    if typ == 3:
        return list(struct.unpack(endian + "%dH" % count, raw[:count * 2]))
    if typ == 4:
        return list(struct.unpack(endian + "%dI" % count, raw[:count * 4]))
    if typ == 12:
        return list(struct.unpack(endian + "%dd" % count, raw[:count * 8]))
    if typ == 11:
        return list(struct.unpack(endian + "%df" % count, raw[:count * 4]))
    if typ == 1:
        return list(raw[:count])
    raise GeoTiffError("unsupported TIFF field type %d" % typ)


def probe_geotiff(path: str) -> Dict[str, Any]:
    with open(path, "rb") as handle:
        head = handle.read(8)
        if len(head) < 8:
            raise GeoTiffError("file is shorter than a TIFF header")
        endian = {b"II": "<", b"MM": ">"}.get(head[:2])
        if endian is None:
            raise GeoTiffError("not a TIFF file (bad byte order)")
        magic = _unpack(endian + "H", head[2:4])[0]
        if magic == 43:
            raise GeoTiffError("BigTIFF is not supported; use classic TIFF")
        if magic != 42:
            raise GeoTiffError("not a classic TIFF (magic %d)" % magic)
        ifd_offset = _unpack(endian + "I", head[4:8])[0]
        handle.seek(0)
        raw_file = handle.read()
        entries = {}
        for tag, typ, n, raw in _iter_entries(raw_file, endian, ifd_offset):
            entries[tag] = _read_field(raw_file, endian, typ, n, raw)

    width = _first(entries.get(TAG_WIDTH))
    height = _first(entries.get(TAG_HEIGHT))
    samples = _first(entries.get(TAG_SAMPLES)) or 1
    bits = _first(entries.get(TAG_BITS))
    if not width or not height:
        raise GeoTiffError("GeoTIFF has no image width/height")

    crs = ""
    geo_keys = entries.get(TAG_GEOKEYS) or []
    if len(geo_keys) >= 4:
        key_count = geo_keys[3]
        for index in range(key_count):
            base = 4 + index * 4
            if base + 3 >= len(geo_keys):
                break
            key_id, location, key_count_value, value = geo_keys[base:base + 4]
            if key_id in EPSG_KEYS and location == 0 and value:
                crs = "EPSG:%d" % value
                break
    if not crs:
        raise GeoTiffError("GeoTIFF has no EPSG GeoKey")

    scale = entries.get(TAG_PIXEL_SCALE) or []
    tie = entries.get(TAG_TIEPOINT) or []
    bounds = None
    pixel_size = None
    if len(scale) >= 2 and len(tie) >= 6:
        sx, sy = float(scale[0]), float(scale[1])
        i, j, _k, x, y, _z = [float(value) for value in tie[:6]]
        left = x - i * sx
        top = y + j * sy
        bounds = [left, top - height * sy, left + width * sx, top]
        pixel_size = [sx, sy]

    return {
        "driver": "GTiff",
        "width": int(width),
        "height": int(height),
        "bands": int(samples),
        "bits_per_sample": int(bits) if bits else None,
        "crs": crs,
        "bounds": bounds,
        "pixel_size": pixel_size,
    }


def _iter_entries(data: bytes, endian: str, ifd_offset: int):
    count = _unpack(endian + "H", data[ifd_offset:ifd_offset + 2])[0]
    start = ifd_offset + 2
    for index in range(count):
        entry = data[start + index * 12:start + (index + 1) * 12]
        if len(entry) < 12:
            raise GeoTiffError("truncated TIFF entry")
        tag, typ, n, _raw = struct.unpack(endian + "HHII", entry)
        yield tag, typ, n, entry[8:12]


def _first(values: Optional[List[Any]]) -> Optional[int]:
    if not values:
        return None
    return int(values[0])
