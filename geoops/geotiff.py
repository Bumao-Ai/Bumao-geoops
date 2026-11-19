"""Read and write classic GeoTIFF, without GDAL.

Only classic TIFF (magic 42) with GeoTIFF tags is supported. The header parser
returns width, height, band count, EPSG code, pixel size and bounds when the
tags are present; an ordinary TIFF without those tags is refused rather than
guessed. Pixel decoding covers the codecs documented on
:func:`read_geotiff_pixels`; :func:`write_geotiff_mask` writes a real one-band
float32 GeoTIFF with PixelScale, Tiepoint, one EPSG GeoKey and GDAL_NODATA.

This is deliberately a narrow reader/writer: it does not replace GDAL, reproject
or build overviews. It exists so a real GeoTIFF can supply its own CRS and so a
change mask can leave as a georeferenced file on a machine with no geospatial
library installed.
"""

from __future__ import annotations

import os
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
        try:
            entries[tag] = _read_field(raw_file, endian, typ, n, raw)
        except GeoTiffError as exc:
            # Unknown ancillary types (for example JPEGTables with type 7)
            # are not fields this reader needs; a critical tag will still be
            # absent and fail explicitly below.
            if str(exc).startswith("unsupported TIFF field type"):
                continue
            raise
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


def _epsg_metadata(entries: Dict[int, Any]) -> Dict[str, str]:
    geo_keys = entries.get(TAG_GEOKEYS) or []
    if len(geo_keys) < 4:
        return {"crs": "", "crs_model": ""}
    key_count = int(geo_keys[3])
    for index in range(key_count):
        base = 4 + index * 4
        if base + 3 >= len(geo_keys):
            break
        key_id, location, _count, value = geo_keys[base:base + 4]
        if key_id in EPSG_KEYS and location == 0 and value:
            return {
                "crs": "EPSG:%d" % int(value),
                "crs_model": EPSG_KEYS[key_id],
            }
    return {"crs": "", "crs_model": ""}


def _raster_metadata(entries: Dict[int, Any], width: int, height: int) -> Dict[str, Any]:
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
    return {"nodata": nodata, "pixel_size": pixel_size, "bounds": bounds, **_epsg_metadata(entries)}


def _pillow_pixels(
    path: str,
    width: int,
    height: int,
    samples: int,
    compression: int,
    bits: int,
    entries: Dict[int, Any],
) -> Dict[str, Any]:
    try:
        from PIL import Image
    except ImportError as exc:
        raise GeoTiffError(
            "compression %s needs Pillow; install Pillow or convert the raster to LZW/Deflate"
            % compression
        ) from exc
    try:
        with Image.open(path) as image:
            if image.size != (int(width), int(height)):
                raise GeoTiffError(
                    "JPEG TIFF size %s does not match its header %s"
                    % (image.size, (int(width), int(height)))
                )
            bands = len(image.getbands())
            if bands != int(samples):
                raise GeoTiffError(
                    "JPEG TIFF has %d decoded bands, header says %d" % (bands, samples)
                )
            getter = getattr(image, "get_flattened_data", None)
            pixels = list(getter() if callable(getter) else image.getdata())
    except GeoTiffError:
        raise
    except Exception as exc:
        raise GeoTiffError("Pillow cannot decode the JPEG TIFF: %s" % exc) from exc
    values: List[float] = []
    for item in pixels:
        if isinstance(item, (tuple, list)):
            values.extend(float(value) for value in item)
        else:
            values.append(float(item))
    total = int(width) * int(height) * int(samples)
    if len(values) < total:
        raise GeoTiffError(
            "JPEG TIFF decoded %d samples, expected %d" % (len(values), total)
        )
    metadata = _raster_metadata(entries, int(width), int(height))
    return {
        "driver": "GTiff",
        "width": int(width),
        "height": int(height),
        "bands": int(bands),
        "bits_per_sample": int(bits),
        "compression": int(compression),
        "values": values[:total],
        "nodata": metadata["nodata"],
        "pixel_size": metadata["pixel_size"],
        "bounds": metadata["bounds"],
        "crs": metadata["crs"],
        "crs_model": metadata["crs_model"],
    }


def read_geotiff_pixels(path: str) -> Dict[str, Any]:
    """Decode classic TIFF strips or tiles for uncompressed/LZW/Deflate.

    Chunky and separate-planar bands are supported; other codecs are refused
    explicitly. No value is guessed: a missing block or a short decode is an
    error.
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
    if compression not in (1, 5, 7, 8, 32946, 34712):
        raise GeoTiffError(
            "unsupported TIFF compression %s; uncompressed, LZW, Deflate, JPEG or JPEG2000 only"
            % compression
        )
    if compression in (7, 34712):
        return _pillow_pixels(path, width, height, samples, compression, bits, entries)
    if planar not in (1, 2):
        raise GeoTiffError("unsupported PlanarConfiguration: %s" % planar)
    if predictor not in (1, 2):
        raise GeoTiffError("unsupported TIFF predictor: %s" % predictor)
    if sample_format not in (1, 2, 3):
        raise GeoTiffError("unsupported SampleFormat: %s" % sample_format)
    total = int(width) * int(height) * int(samples)
    samples_per_block = 1 if planar == 2 else int(samples)

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
        grid = columns * rows
        required_tiles = grid * (int(samples) if planar == 2 else 1)
        if len(tile_offsets) < required_tiles:
            raise GeoTiffError("TIFF has fewer tiles than its declared grid")
        values = [0.0] * total
        planes = range(int(samples)) if planar == 2 else [0]
        for plane in planes:
            for tile_index in range(grid):
                block_index = plane * grid + tile_index if planar == 2 else tile_index
                offset, count = tile_offsets[block_index], tile_counts[block_index]
                tile_values = block_values(
                    int(offset), int(count), "tile %d" % block_index
                )
                expected_tile = int(tile_width) * int(tile_length) * samples_per_block
                if len(tile_values) < expected_tile:
                    raise GeoTiffError(
                        "TIFF tile %d decoded %d samples, expected %d"
                        % (block_index, len(tile_values), expected_tile)
                    )
                if predictor == 2:
                    _undo_predictor(
                        tile_values,
                        int(tile_width) * samples_per_block,
                        samples_per_block,
                    )
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
                        source = (row * int(tile_width) + col) * samples_per_block
                        target = (target_row * int(width) + target_col) * int(samples)
                        if planar == 2:
                            target += plane
                        for band in range(samples_per_block):
                            values[target + band] = tile_values[source + band]
    else:
        offsets = entries.get(TAG_STRIP_OFFSETS)
        byte_counts = entries.get(TAG_STRIP_BYTE_COUNTS)
        if not isinstance(offsets, list) or not offsets:
            raise GeoTiffError("TIFF has no StripOffsets")
        if not isinstance(byte_counts, list) or len(byte_counts) != len(offsets):
            raise GeoTiffError("TIFF StripByteCounts do not match StripOffsets")
        if planar == 2:
            if len(offsets) % int(samples):
                raise GeoTiffError("separate planar StripOffsets do not match bands")
            strips_per_plane = len(offsets) // int(samples)
            values = [0.0] * total
            for plane in range(int(samples)):
                plane_values: List[float] = []
                for index in range(
                    plane * strips_per_plane, (plane + 1) * strips_per_plane
                ):
                    plane_values.extend(
                        block_values(
                            int(offsets[index]), int(byte_counts[index]), "strip %d" % index
                        )
                    )
                if predictor == 2:
                    _undo_predictor(plane_values, int(width), 1)
                expected_plane = int(width) * int(height)
                if len(plane_values) < expected_plane:
                    raise GeoTiffError(
                        "TIFF band %d decoded %d samples, expected %d"
                        % (plane, len(plane_values), expected_plane)
                    )
                for index in range(expected_plane):
                    values[index * int(samples) + plane] = plane_values[index]
        else:
            for index, (offset, count) in enumerate(zip(offsets, byte_counts)):
                values.extend(block_values(int(offset), int(count), "strip %d" % index))

    if predictor == 2 and planar == 1 and not (322 in entries or 324 in entries):
        # Strip horizontal differencing is per image row; tile predictor was
        # reversed per tile above.
        _undo_predictor(values, int(width) * int(samples), int(samples))

    if len(values) < total:
        raise GeoTiffError(
            "TIFF decoded %d samples, expected %d" % (len(values), total)
        )
    values = values[:total]
    metadata = _raster_metadata(entries, int(width), int(height))

    return {
        "driver": "GTiff",
        "width": int(width),
        "height": int(height),
        "bands": int(samples),
        "bits_per_sample": bits,
        "compression": int(compression),
        "values": values,
        "nodata": metadata["nodata"],
        "pixel_size": metadata["pixel_size"],
        "bounds": metadata["bounds"],
        "crs": metadata["crs"],
        "crs_model": metadata["crs_model"],
    }


def _crs_number(crs: str) -> int:
    value = str(crs or "").strip().upper()
    if not value.startswith("EPSG:"):
        raise GeoTiffError("GeoTIFF output needs a CRS such as EPSG:4326")
    try:
        number = int(value[5:])
    except ValueError as exc:
        raise GeoTiffError("invalid EPSG code: %s" % crs) from exc
    if number <= 0 or number > 65535:
        raise GeoTiffError("EPSG code out of GeoKey range: %d" % number)
    return number


def write_geotiff_mask(
    path: str,
    *,
    width: int,
    height: int,
    cellsize: float,
    xllcorner: float,
    yllcorner: float,
    crs: str,
    crs_model: str,
    values: List[float],
    nodata: float = -9999.0,
) -> str:
    """Write a one-band float32, uncompressed classic GeoTIFF mask.

    Only the georeferencing this program actually knows is written: PixelScale,
    Tiepoint, one EPSG GeoKey and GDAL_NODATA. The output is a real TIFF that
    this reader and GDAL can open; it is not a renamed ASCII file.
    """
    path = str(path or "").strip()
    if not path:
        raise GeoTiffError("GeoTIFF output path is empty")
    if not path.lower().endswith((".tif", ".tiff")):
        raise GeoTiffError("GeoTIFF output path must end in .tif or .tiff")
    width, height = int(width), int(height)
    if width <= 0 or height <= 0:
        raise GeoTiffError("GeoTIFF dimensions must be positive")
    if len(values) != width * height:
        raise GeoTiffError(
            "GeoTIFF has %d values for %dx%d pixels" % (len(values), width, height)
        )
    cellsize = float(cellsize)
    xllcorner, yllcorner = float(xllcorner), float(yllcorner)
    if cellsize <= 0 or not all(
        value == value and abs(value) != float("inf")
        for value in (cellsize, xllcorner, yllcorner)
    ):
        raise GeoTiffError("GeoTIFF georeferencing contains a non-finite value")
    crs_model = str(crs_model or "").strip().lower()
    if crs_model not in ("geographic", "projected"):
        raise GeoTiffError("GeoTIFF output needs crs_model geographic or projected")
    epsg = _crs_number(crs)
    nodata = float(nodata)

    pixel_offset = 8
    pixel_bytes = width * height * 4
    pixel_data = bytearray()
    for raw in values:
        number = float(raw)
        if not (number == number and abs(number) != float("inf")):
            raise GeoTiffError("GeoTIFF mask contains a non-finite value")
        pixel_data.extend(struct.pack("<f", number))
    ifd_offset = pixel_offset + len(pixel_data)
    if ifd_offset % 2:
        pixel_data.append(0)
        ifd_offset += 1

    top = yllcorner + height * cellsize
    geo_keys = [
        1,
        1,
        0,
        3,
        1024,
        0,
        1,
        2 if crs_model == "geographic" else 1,
        1025,
        0,
        1,
        1,
        2048 if crs_model == "geographic" else 3072,
        0,
        1,
        epsg,
    ]
    specs = [
        (256, 4, 1, struct.pack("<I", width)),
        (257, 4, 1, struct.pack("<I", height)),
        (258, 3, 1, struct.pack("<H", 32)),
        (259, 3, 1, struct.pack("<H", 1)),
        (262, 3, 1, struct.pack("<H", 1)),
        (273, 4, 1, struct.pack("<I", pixel_offset)),
        (277, 3, 1, struct.pack("<H", 1)),
        (278, 4, 1, struct.pack("<I", height)),
        (279, 4, 1, struct.pack("<I", pixel_bytes)),
        (284, 3, 1, struct.pack("<H", 1)),
        (339, 3, 1, struct.pack("<H", 3)),
        (
            33550,
            12,
            3,
            struct.pack("<3d", cellsize, cellsize, 0.0),
        ),
        (
            33922,
            12,
            6,
            struct.pack("<6d", 0.0, 0.0, 0.0, xllcorner, top, 0.0),
        ),
        (34735, 3, 16, struct.pack("<16H", *geo_keys)),
        (
            42113,
            2,
            len(repr(nodata)) + 1,
            (repr(nodata) + "\x00").encode("latin-1"),
        ),
    ]

    ifd_size = 2 + 12 * len(specs) + 4
    aux_cursor = ifd_offset + ifd_size
    aux_data = bytearray()
    ifd_bytes = bytearray(struct.pack("<H", len(specs)))
    for tag, typ, count, payload in specs:
        if len(payload) <= 4:
            value_field = payload + b"\x00" * (4 - len(payload))
        else:
            align = 8 if typ == 12 else (2 if typ in (3, 4) else 1)
            padding = (-aux_cursor) % align
            aux_data.extend(b"\x00" * padding)
            aux_cursor += padding
            value_field = struct.pack("<I", aux_cursor)
            aux_data.extend(payload)
            aux_cursor += len(payload)
        ifd_bytes.extend(struct.pack("<HHI", tag, typ, count))
        ifd_bytes.extend(value_field)
    ifd_bytes.extend(struct.pack("<I", 0))

    body = b"II" + struct.pack("<H", 42) + struct.pack("<I", ifd_offset)
    body += bytes(pixel_data)
    body += bytes(ifd_bytes)
    body += bytes(aux_data)
    absolute = os.path.abspath(path)
    os.makedirs(os.path.dirname(absolute) or ".", exist_ok=True)
    temp_path = absolute + ".tmp"
    with open(temp_path, "wb") as handle:
        handle.write(body)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp_path, absolute)
    return absolute


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
