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
import zlib
from typing import Any, Dict, List, Optional

TAG_WIDTH = 256
TAG_HEIGHT = 257
TAG_BITS = 258
TAG_COMPRESSION = 259
TAG_PHOTOMETRIC = 262
TAG_STRIP_OFFSETS = 273
TAG_SAMPLES = 277
TAG_ROWS_PER_STRIP = 278
TAG_STRIP_BYTE_COUNTS = 279
TAG_PLANAR_CONFIG = 284
TAG_PREDICTOR = 317
TAG_SAMPLE_FORMAT = 339
TAG_GDAL_NODATA = 42113
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


def _read_entries(path: str):
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
    return endian, raw_file, entries


def probe_geotiff(path: str) -> Dict[str, Any]:
    endian, raw_file, entries = _read_entries(path)

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


def _lzw_decode(data: bytes) -> bytes:
    """Decode TIFF LZW (MSB-first codes, early code-width change)."""
    dictionary: Dict[int, bytes] = {index: bytes([index]) for index in range(256)}
    clear, eoi, next_code, width = 256, 257, 258, 9
    bit_buffer = 0
    bit_count = 0
    output = bytearray()
    previous: Optional[bytes] = None

    def reset() -> None:
        nonlocal dictionary, next_code, width, previous
        dictionary = {index: bytes([index]) for index in range(256)}
        next_code, width, previous = 258, 9, None

    for byte in data:
        bit_buffer = (bit_buffer << 8) | byte
        bit_count += 8
        while bit_count >= width:
            bit_count -= width
            code = (bit_buffer >> bit_count) & ((1 << width) - 1)
            bit_buffer &= (1 << bit_count) - 1
            if code == clear:
                reset()
                continue
            if code == eoi:
                if len(output) == 0:
                    raise GeoTiffError("LZW stream ended without image data")
                return bytes(output)
            if previous is None:
                entry = dictionary.get(code)
                if entry is None:
                    raise GeoTiffError("LZW first code %d is not in the dictionary" % code)
            elif code in dictionary:
                entry = dictionary[code]
            elif code == next_code:
                entry = previous + previous[:1]
            else:
                raise GeoTiffError("LZW code %d is out of range" % code)
            output.extend(entry)
            if previous is not None and next_code < 4096:
                dictionary[next_code] = previous + entry[:1]
                next_code += 1
                # TIFF LZW switches width one code early (511, 1023, 2047).
                if width < 12 and next_code == (1 << width) - 1:
                    width += 1
            previous = entry
    if len(output) == 0:
        raise GeoTiffError("LZW stream has no image data")
    return bytes(output)


def _decode_samples(raw: bytes, endian: str, bits: int, sample_format: int) -> List[float]:
    bytes_per_sample = bits // 8
    count = len(raw) // bytes_per_sample
    if count <= 0:
        raise GeoTiffError("empty TIFF strip or tile")
    if bits == 8:
        if sample_format == 3:
            raise GeoTiffError("8-bit float samples are invalid")
        fmt = ("%db" if sample_format == 2 else "%dB") % count
    elif bits == 16:
        if sample_format == 3:
            raise GeoTiffError("16-bit float samples are not supported")
        fmt = "%d%s" % (count, "h" if sample_format == 2 else "H")
    else:
        fmt = "%d%s" % (count, {1: "I", 2: "i", 3: "f"}[sample_format])
    try:
        return [float(value) for value in struct.unpack(endian + fmt, raw[:count * bytes_per_sample])]
    except struct.error as exc:
        raise GeoTiffError("TIFF strip or tile is truncated: %s" % exc) from exc


def _undo_predictor(values: List[float], row_values: int, samples: int) -> None:
    if row_values <= 0 or len(values) % row_values:
        return
    for start in range(0, len(values), row_values):
        for index in range(start + samples, start + row_values):
            values[index] = values[index] + values[index - samples]


def read_geotiff_pixels(path: str) -> Dict[str, Any]:
    """Decode classic TIFF strips or tiles for uncompressed/LZW/Deflate.

    Chunky bands are supported; separate planar bands and other codecs are
    refused explicitly. No value is guessed: a missing block or a short decode
    is an error.
    """
    endian, raw_file, entries = _read_entries(path)
    width = _first(entries.get(TAG_WIDTH))
    height = _first(entries.get(TAG_HEIGHT))
    samples = _first(entries.get(TAG_SAMPLES)) or 1
    bit_values = entries.get(TAG_BITS) or []
    bits = int(bit_values[0]) if bit_values else 8
    compression = _first(entries.get(TAG_COMPRESSION)) or 1
    planar = _first(entries.get(TAG_PLANAR_CONFIG)) or 1
    predictor = _first(entries.get(TAG_PREDICTOR)) or 1
    sample_format = _first(entries.get(TAG_SAMPLE_FORMAT)) or 1
    if not width or not height:
        raise GeoTiffError("TIFF has no image width/height")
    if bits not in (8, 16, 32):
        raise GeoTiffError("unsupported BitsPerSample: %s" % bits)
    if compression not in (1, 5, 8, 32946):
        raise GeoTiffError(
            "unsupported TIFF compression %s; uncompressed, LZW or Deflate only"
            % compression
        )
    if planar != 1:
        raise GeoTiffError("separate planar TIFF bands are not supported")
    if predictor not in (1, 2):
        raise GeoTiffError("unsupported TIFF predictor: %s" % predictor)
    if sample_format not in (1, 2, 3):
        raise GeoTiffError("unsupported SampleFormat: %s" % sample_format)
    total = int(width) * int(height) * int(samples)

    def block_values(offset: int, count: int, label: str) -> List[float]:
        if offset < 0 or count <= 0 or offset + count > len(raw_file):
            raise GeoTiffError("TIFF %s points outside the file" % label)
        raw = raw_file[int(offset):int(offset) + int(count)]
        if compression == 5:
            raw = _lzw_decode(raw)
        elif compression in (8, 32946):
            try:
                raw = zlib.decompress(raw)
            except zlib.error as exc:
                raise GeoTiffError("Deflate %s is corrupt: %s" % (label, exc)) from exc
        return _decode_samples(raw, endian, bits, sample_format)

    values: List[float] = []
    tile_width = _first(entries.get(322))
    tile_length = _first(entries.get(323))
    tile_offsets = entries.get(324)
    tile_counts = entries.get(325)
    if 322 in entries or 323 in entries or 324 in entries or 325 in entries:
        if not tile_width or not tile_length:
            raise GeoTiffError("tiled TIFF has no TileWidth/TileLength")
        if not isinstance(tile_offsets, list) or not tile_offsets:
            raise GeoTiffError("TIFF has no TileOffsets")
        if not isinstance(tile_counts, list) or len(tile_counts) != len(tile_offsets):
            raise GeoTiffError("TIFF TileByteCounts do not match TileOffsets")
        columns = (int(width) + int(tile_width) - 1) // int(tile_width)
        rows = (int(height) + int(tile_length) - 1) // int(tile_length)
        if len(tile_offsets) < columns * rows:
            raise GeoTiffError("TIFF has fewer tiles than its declared grid")
        values = [0.0] * total
        for tile_index, (offset, count) in enumerate(zip(tile_offsets, tile_counts)):
            tile_values = block_values(
                int(offset), int(count), "tile %d" % tile_index
            )
            expected_tile = int(tile_width) * int(tile_length) * int(samples)
            if len(tile_values) < expected_tile:
                raise GeoTiffError(
                    "TIFF tile %d decoded %d samples, expected %d"
                    % (tile_index, len(tile_values), expected_tile)
                )
            if predictor == 2:
                _undo_predictor(tile_values, int(tile_width) * int(samples), int(samples))
            tile_row = tile_index // columns
            tile_col = tile_index % columns
            for row in range(int(tile_length)):
                target_row = tile_row * int(tile_length) + row
                if target_row >= int(height):
                    break
                for col in range(int(tile_width)):
                    target_col = tile_col * int(tile_width) + col
                    if target_col >= int(width):
                        break
                    source = (row * int(tile_width) + col) * int(samples)
                    target = (target_row * int(width) + target_col) * int(samples)
                    for band in range(int(samples)):
                        values[target + band] = tile_values[source + band]
    else:
        offsets = entries.get(TAG_STRIP_OFFSETS)
        byte_counts = entries.get(TAG_STRIP_BYTE_COUNTS)
        if not isinstance(offsets, list) or not offsets:
            raise GeoTiffError("TIFF has no StripOffsets")
        if not isinstance(byte_counts, list) or len(byte_counts) != len(offsets):
            raise GeoTiffError("TIFF StripByteCounts do not match StripOffsets")
        for index, (offset, count) in enumerate(zip(offsets, byte_counts)):
            values.extend(block_values(int(offset), int(count), "strip %d" % index))

    if predictor == 2 and not (322 in entries or 324 in entries):
        # Strip horizontal differencing is per image row; tile predictor was
        # reversed per tile above.
        _undo_predictor(values, int(width) * int(samples), int(samples))

    if len(values) < total:
        raise GeoTiffError(
            "TIFF decoded %d samples, expected %d" % (len(values), total)
        )
    values = values[:total]

    scale = entries.get(TAG_PIXEL_SCALE) or []
    tie = entries.get(TAG_TIEPOINT) or []
    nodata = None
    raw_nodata = entries.get(TAG_GDAL_NODATA)
    if isinstance(raw_nodata, str) and raw_nodata.strip().strip("\x00"):
        try:
            nodata = float(raw_nodata.strip().strip("\x00"))
        except ValueError:
            nodata = None
    pixel_size = None
    bounds = None
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
        "bits_per_sample": bits,
        "compression": int(compression),
        "values": values,
        "nodata": nodata,
        "pixel_size": pixel_size,
        "bounds": bounds,
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
