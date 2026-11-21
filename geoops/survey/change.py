"""Change detection on real rasters (ESRI ASCII or classic GeoTIFF).

This is a real calculation, not a placeholder: two aligned grids are read,
cells whose absolute difference reaches the threshold are marked, 4-neighbour
connectivity groups them into patches, and patches smaller than the declared
minimum area are dropped before the mask is written. A threshold of zero means
any non-zero difference; a positive threshold is inclusive. Values come from the
files; nothing is invented.

The output is an ESRI ASCII grid by default, or a one-band float32 GeoTIFF when
the output ends in ``.tif``/``.tiff`` and the source carries a CRS. Cell area is
``cellsize ** 2`` for a projected grid in metres; a geographic grid is measured
row by row on the WGS84 ellipsoid so the reported square metres are real rather
than square degrees.
"""

from __future__ import annotations

import json
import math
import os
import re
from typing import Any, Dict, List, Optional, Tuple

REQUIRED_HEADER = ("ncols", "nrows", "cellsize")
_NUMBER = re.compile(r"^[-+]?\d+(\.\d+)?([eE][-+]?\d+)?$")


class ChangeError(ValueError):
    """Raised when a grid pair cannot be compared; nothing is written."""


def is_nodata(value: Any, nodata: Any) -> bool:
    """Compare a cell with NODATA, including a floating-point NaN sentinel."""
    if nodata is None:
        return False
    try:
        if math.isnan(float(nodata)):
            return math.isnan(float(value))
    except (TypeError, ValueError):
        return False
    return value == nodata


def read_ascii_grid(path: str) -> Dict[str, Any]:
    """Read an ESRI ASCII grid and validate it before any cell is used."""
    path = str(path or "").strip()
    if not path:
        raise ChangeError("grid path must not be empty")
    if not os.path.exists(path):
        raise ChangeError("grid not found: %s" % path)
    if not os.path.isfile(path):
        raise ChangeError("grid is not a regular file: %s" % path)
    with open(path, encoding="utf-8-sig") as handle:
        lines = [line.strip() for line in handle.read().splitlines() if line.strip()]
    if not lines:
        raise ChangeError("grid is empty: %s" % path)

    header: Dict[str, float] = {}
    index = 0
    while index < len(lines):
        parts = lines[index].split()
        if len(parts) != 2 or _NUMBER.match(parts[1]) is None or _NUMBER.match(parts[0]):
            break
        key = parts[0].lower()
        if key in header:
            raise ChangeError("duplicate header key %r in %s" % (parts[0], path))
        header[key] = float(parts[1])
        index += 1

    missing = [key for key in REQUIRED_HEADER if key not in header]
    if missing:
        raise ChangeError("grid %s is missing header key(s): %s" % (path, ", ".join(missing)))
    ncols = header["ncols"]
    nrows = header["nrows"]
    if ncols != int(ncols) or nrows != int(nrows) or ncols < 1 or nrows < 1:
        raise ChangeError("grid %s has an invalid size: %r x %r" % (path, ncols, nrows))
    if header["cellsize"] <= 0:
        raise ChangeError("grid %s has a non-positive cellsize" % path)

    # ESRI ASCII permits either a corner or a cell-center origin. Normalise to
    # the corner used everywhere else; if both are present they must agree.
    for corner_key, center_key in (("xllcorner", "xllcenter"), ("yllcorner", "yllcenter")):
        if corner_key not in header and center_key not in header:
            raise ChangeError("grid %s has no %s/%s header" % (path, corner_key, center_key))
        if corner_key in header and center_key in header:
            derived = header[center_key] - header["cellsize"] / 2.0
            if abs(header[corner_key] - derived) > 1e-9:
                raise ChangeError(
                    "grid %s declares conflicting %s and %s" % (path, corner_key, center_key)
                )
        elif corner_key not in header:
            header[corner_key] = header[center_key] - header["cellsize"] / 2.0

    values: List[float] = []
    for line in lines[index:]:
        for token in line.split():
            if _NUMBER.match(token) is None:
                raise ChangeError("grid %s has a non-numeric cell %r" % (path, token))
            values.append(float(token))
    expected = int(ncols) * int(nrows)
    if len(values) != expected:
        raise ChangeError(
            "grid %s declares %d cells but carries %d" % (path, expected, len(values))
        )
    return {
        "path": path,
        "header": header,
        "ncols": int(ncols),
        "nrows": int(nrows),
        "cellsize": header["cellsize"],
        "cellsize_y": header["cellsize"],
        "values": values,
    }


def _sidecar_crs(path: str) -> Tuple[str, str]:
    sidecar = path + ".json"
    if not os.path.isfile(sidecar):
        return "", ""
    try:
        if os.path.getsize(sidecar) > 1024 * 1024:
            return "", ""
        with open(sidecar, encoding="utf-8-sig") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return "", ""
    if not isinstance(data, dict):
        return "", ""
    crs = str(data.get("crs") or "").strip()
    model = str(data.get("crs_model") or "").strip().lower()
    if model not in ("geographic", "projected"):
        model = ""
    if crs and not model:
        normalized = crs.upper().replace(" ", "")
        if normalized == "EPSG:4326":
            model = "geographic"
        elif normalized == "EPSG:3857":
            model = "projected"
    return crs, model


def read_sidecar_crs(path: str) -> Tuple[str, str]:
    """Public access to the sidecar CRS/model used by the raster readers."""
    return _sidecar_crs(path)


def read_raster_grid(path: str, band: int = 1) -> Dict[str, Any]:
    """Read an ASCII grid or a classic/BigTIFF GeoTIFF (selected band, default 1)."""
    try:
        band = int(band)
    except (TypeError, ValueError) as exc:
        raise ChangeError("band must be a positive integer") from exc
    if band < 1:
        raise ChangeError("band must be a positive integer")
    suffix = os.path.splitext(str(path or ""))[1].lower()
    if suffix in (".tif", ".tiff"):
        from geoops.geotiff import GeoTiffError, read_geotiff_pixels

        try:
            image = read_geotiff_pixels(path)
        except GeoTiffError as exc:
            raise ChangeError("GeoTIFF pixel read failed: %s" % exc) from exc
        pixel_size = image.get("pixel_size")
        bounds = image.get("bounds")
        if not pixel_size or not bounds:
            raise ChangeError(
                "GeoTIFF %s has no pixel scale/tiepoint; cannot align it" % path
            )
        bands = int(image.get("bands") or 1)
        if band > bands:
            raise ChangeError("GeoTIFF %s has %d band(s), not band %d" % (path, bands, band))
        values = image["values"][band - 1::bands]
        sx = float(pixel_size[0])
        sy = float(pixel_size[1]) if len(pixel_size) > 1 else sx
        if sx <= 0 or sy <= 0:
            raise ChangeError("GeoTIFF %s has a non-positive pixel size" % path)
        header_crs = str(image.get("crs") or "").strip()
        header_model = str(image.get("crs_model") or "").strip().lower()
        side_crs, side_model = _sidecar_crs(path)
        left = header_crs.upper().replace(" ", "")
        right = side_crs.upper().replace(" ", "")
        if left and right and left != right:
            raise ChangeError(
                "GeoTIFF %s has conflicting CRS: sidecar %s vs header %s"
                % (path, side_crs, header_crs)
            )
        if header_model and side_model and header_model != side_model:
            raise ChangeError(
                "GeoTIFF %s has conflicting CRS model: sidecar %s vs header %s"
                % (path, side_model, header_model)
            )
        crs = header_crs or side_crs
        crs_model = header_model or side_model
        return {
            "path": path,
            "header": {
                "ncols": image["width"],
                "nrows": image["height"],
                "xllcorner": bounds[0],
                "yllcorner": bounds[1],
                "cellsize": sx,
                "cellsize_y": sy,
                "nodata_value": image.get("nodata"),
            },
            "ncols": int(image["width"]),
            "nrows": int(image["height"]),
            "cellsize": sx,
            "cellsize_y": sy,
            "values": values,
            "source_format": "geotiff",
            "bands": bands,
            "band": band,
            "crs": crs,
            "crs_model": crs_model,
            "raster_type": image.get("raster_type", 1),
            "linear_unit": str(image.get("linear_unit") or ""),
            "linear_unit_code": image.get("linear_unit_code"),
            "linear_unit_m": (
                float(image["linear_unit_m"])
                if image.get("linear_unit_m") is not None else 1.0
            ),
        }
    if band != 1:
        raise ChangeError("ASCII grid %s has one band, not band %d" % (path, band))
    grid = read_ascii_grid(path)
    crs, crs_model = _sidecar_crs(path)
    return {
        **grid,
        "band": 1,
        "crs": crs,
        "crs_model": crs_model,
        "raster_type": None,
        "linear_unit": "",
        "linear_unit_code": None,
        "linear_unit_m": 1.0,
    }


def _check_alignment(baseline: Dict[str, Any], comparison: Dict[str, Any]) -> None:
    for key in ("cellsize", "xllcorner", "yllcorner"):
        if abs(baseline["header"][key] - comparison["header"][key]) > 1e-9:
            raise ChangeError(
                "grids are not aligned: %s differs (%r vs %r)"
                % (key, baseline["header"][key], comparison["header"][key])
            )
    left_cell_y = float(baseline["header"].get("cellsize_y", baseline["header"]["cellsize"]))
    right_cell_y = float(comparison["header"].get("cellsize_y", comparison["header"]["cellsize"]))
    if abs(left_cell_y - right_cell_y) > 1e-9:
        raise ChangeError(
            "grids are not aligned: cell height differs (%r vs %r)"
            % (left_cell_y, right_cell_y)
        )
    if baseline["ncols"] != comparison["ncols"] or baseline["nrows"] != comparison["nrows"]:
        raise ChangeError(
            "grids are not aligned: size %dx%d vs %dx%d"
            % (baseline["ncols"], baseline["nrows"], comparison["ncols"], comparison["nrows"])
        )
    left_crs = str(baseline.get("crs") or "").strip().upper().replace(" ", "")
    right_crs = str(comparison.get("crs") or "").strip().upper().replace(" ", "")
    left_model = str(baseline.get("crs_model") or "").strip().lower()
    right_model = str(comparison.get("crs_model") or "").strip().lower()
    if bool(left_crs) != bool(right_crs):
        raise ChangeError("grids are not aligned: CRS is present in only one grid")
    if left_crs and left_crs != right_crs:
        raise ChangeError(
            "grids are not aligned: CRS differs (%s vs %s)" % (left_crs, right_crs)
        )
    if left_crs and bool(left_model) != bool(right_model):
        raise ChangeError("grids are not aligned: CRS model is present in only one grid")
    if left_model and left_model != right_model:
        raise ChangeError(
            "grids are not aligned: CRS model differs (%s vs %s)"
            % (left_model, right_model)
        )
    left_unit_m = float(baseline.get("linear_unit_m") or 1.0)
    right_unit_m = float(comparison.get("linear_unit_m") or 1.0)
    if abs(left_unit_m - right_unit_m) > 1e-12:
        raise ChangeError(
            "grids are not aligned: linear unit differs (%r m vs %r m)"
            % (left_unit_m, right_unit_m)
        )


def _patches(mask: List[int], ncols: int, nrows: int) -> List[Dict[str, Any]]:
    """Group changed cells by 4-neighbour connectivity."""
    visited = [False] * len(mask)
    found: List[Dict[str, Any]] = []
    for start, changed in enumerate(mask):
        if not changed or visited[start]:
            continue
        stack = [start]
        visited[start] = True
        cells: List[int] = []
        while stack:
            cell = stack.pop()
            cells.append(cell)
            row, col = divmod(cell, ncols)
            if col > 0 and mask[cell - 1] and not visited[cell - 1]:
                visited[cell - 1] = True
                stack.append(cell - 1)
            if col + 1 < ncols and mask[cell + 1] and not visited[cell + 1]:
                visited[cell + 1] = True
                stack.append(cell + 1)
            if row > 0 and mask[cell - ncols] and not visited[cell - ncols]:
                visited[cell - ncols] = True
                stack.append(cell - ncols)
            if row + 1 < nrows and mask[cell + ncols] and not visited[cell + ncols]:
                visited[cell + ncols] = True
                stack.append(cell + ncols)
        found.append({"cells": cells, "count": len(cells)})
    return found


def _geographic_cell_area_m2(
    cellsize_x_deg: float, cellsize_y_deg: float, latitude_deg: float
) -> float:
    """Area of a degree cell at a latitude, on the WGS84 ellipsoid."""
    phi = math.radians(max(-90.0, min(90.0, latitude_deg)))
    metres_per_degree_lat = (
        111132.92
        - 559.82 * math.cos(2 * phi)
        + 1.175 * math.cos(4 * phi)
        - 0.0023 * math.cos(6 * phi)
    )
    metres_per_degree_lon = (
        111412.84 * math.cos(phi)
        - 93.5 * math.cos(3 * phi)
        + 0.118 * math.cos(5 * phi)
    )
    return abs(
        cellsize_x_deg * metres_per_degree_lon
        * cellsize_y_deg * metres_per_degree_lat
    )


def _row_areas_m2(grid: Dict[str, Any]) -> Tuple[List[float], str]:
    """Return one cell area per row and the basis used to compute it."""
    cellsize = float(grid["cellsize"])
    cellsize_y = float(grid.get("cellsize_y") or cellsize)
    nrows = int(grid["nrows"])
    model = str(grid.get("crs_model") or "").strip().lower()
    raw_unit = grid.get("linear_unit_m")
    unit_metres = float(raw_unit) if raw_unit is not None else 1.0
    if model == "projected" and grid.get("linear_unit") and unit_metres <= 0:
        raise ChangeError(
            "projected grid declares unsupported linear unit %s; area cannot be "
            "reported in square metres" % grid.get("linear_unit")
        )
    if model == "geographic":
        top = float(grid["header"]["yllcorner"]) + nrows * cellsize_y
        areas = [
            _geographic_cell_area_m2(cellsize, cellsize_y, top - (row + 0.5) * cellsize_y)
            for row in range(nrows)
        ]
        return areas, "geographic_wgs84"
    return [cellsize * cellsize_y * unit_metres ** 2] * nrows, (
        "projected" if model == "projected" else "map_units"
    )


def _patch_area_m2(cells: List[int], ncols: int, row_areas: List[float]) -> float:
    return sum(row_areas[cell // ncols] for cell in cells)


def _patch_geometry(
    cells: List[int],
    ncols: int,
    nrows: int,
    xllcorner: float,
    yllcorner: float,
    cellsize_x: float,
    cellsize_y: float,
) -> Dict[str, Any]:
    """Map a patch's cells to its footprint and cell-centre centroid."""
    rows = [cell // ncols for cell in cells]
    cols = [cell % ncols for cell in cells]
    left = xllcorner + min(cols) * cellsize_x
    right = xllcorner + (max(cols) + 1) * cellsize_x
    top = yllcorner + nrows * cellsize_y
    upper = top - min(rows) * cellsize_y
    lower = top - (max(rows) + 1) * cellsize_y
    center_x = sum(xllcorner + (col + 0.5) * cellsize_x for col in cols) / len(cells)
    center_y = sum(top - (row + 0.5) * cellsize_y for row in rows) / len(cells)
    return {
        "bbox": [left, lower, right, upper],
        "centroid": [center_x, center_y],
        "row_min": min(rows),
        "row_max": max(rows),
        "col_min": min(cols),
        "col_max": max(cols),
    }


def measure_raster_area(grid: Dict[str, Any]) -> Dict[str, Any]:
    """Return the raster footprint and mean cell area in square metres."""
    row_areas, basis = _row_areas_m2(grid)
    ncols = int(grid["ncols"])
    return {
        "cell_area_m2": sum(row_areas) / len(row_areas),
        "footprint_area_m2": sum(row_areas) * ncols,
        "area_basis": basis,
    }


def _patch_values(
    cells: List[int],
    baseline_values: List[float],
    comparison_values: List[float],
) -> Dict[str, float]:
    """Return mean/max absolute change and mean levels for one patch."""
    before = [baseline_values[cell] for cell in cells]
    after = [comparison_values[cell] for cell in cells]
    deltas = [abs(right - left) for left, right in zip(before, after)]
    return {
        "mean_abs_delta": sum(deltas) / len(deltas),
        "max_abs_delta": max(deltas),
        "mean_baseline": sum(before) / len(before),
        "mean_comparison": sum(after) / len(after),
    }


def detect_changes(
    baseline_path: str,
    comparison_path: str,
    threshold: float = 1.0,
    min_area_m2: float = 0.0,
    band: int = 1,
) -> Dict[str, Any]:
    """Compare two aligned grids and return a mask plus its statistics."""
    try:
        threshold = float(threshold)
        min_area_m2 = float(min_area_m2)
    except (TypeError, ValueError) as exc:
        raise ChangeError("threshold and min_area_m2 must be numbers") from exc
    if not math.isfinite(threshold) or not math.isfinite(min_area_m2):
        raise ChangeError("threshold and min_area_m2 must be finite")
    if threshold < 0:
        raise ChangeError("threshold must not be negative")
    if min_area_m2 < 0:
        raise ChangeError("min_area_m2 must not be negative")
    baseline = read_raster_grid(baseline_path, band=band)
    comparison = read_raster_grid(comparison_path, band=band)
    _check_alignment(baseline, comparison)

    nodata_a = baseline["header"].get("nodata_value")
    nodata_b = comparison["header"].get("nodata_value")
    row_areas, area_basis = _row_areas_m2(baseline)
    cell_area = sum(row_areas) / len(row_areas)
    mask: List[int] = []
    invalid_mask: List[bool] = []
    nodata_cells = 0
    non_finite_cells = 0
    changed_cells = 0
    for left, right in zip(baseline["values"], comparison["values"]):
        if is_nodata(left, nodata_a) or is_nodata(right, nodata_b):
            nodata_cells += 1
            mask.append(0)
            invalid_mask.append(True)
            continue
        if not math.isfinite(left) or not math.isfinite(right):
            non_finite_cells += 1
            mask.append(0)
            invalid_mask.append(True)
            continue
        invalid_mask.append(False)
        changed = (right != left) if threshold == 0 else abs(right - left) >= threshold
        mask.append(1 if changed else 0)
        if changed:
            changed_cells += 1

    patches = _patches(mask, baseline["ncols"], baseline["nrows"])
    for patch in patches:
        patch["area_m2"] = _patch_area_m2(patch["cells"], baseline["ncols"], row_areas)
        patch.update(
            _patch_geometry(
                patch["cells"],
                baseline["ncols"],
                baseline["nrows"],
                float(baseline["header"]["xllcorner"]),
                float(baseline["header"]["yllcorner"]),
                baseline["cellsize"],
                baseline["cellsize_y"],
            )
        )
        patch.update(
            _patch_values(
                patch["cells"],
                baseline["values"],
                comparison["values"],
            )
        )
    dropped = [patch for patch in patches if patch["area_m2"] < min_area_m2]
    for patch in dropped:
        for cell in patch["cells"]:
            mask[cell] = 0
    kept = [patch for patch in patches if patch["area_m2"] >= min_area_m2]
    for number, patch in enumerate(kept, start=1):
        patch["patch_id"] = number

    kept_cells = sum(patch["count"] for patch in kept)
    changed_area = sum(patch["area_m2"] for patch in kept)
    return {
        "ncols": baseline["ncols"],
        "nrows": baseline["nrows"],
        "cellsize": baseline["cellsize"],
        "cellsize_y": baseline["cellsize_y"],
        "cell_area_m2": cell_area,
        "area_basis": area_basis,
        "band": int(baseline.get("band") or band),
        "threshold": threshold,
        "min_area_m2": min_area_m2,
        "total_cells": len(mask),
        "changed_cells": changed_cells,
        "kept_cells": kept_cells,
        "dropped_cells": changed_cells - kept_cells,
        "nodata_cells": nodata_cells,
        "non_finite_cells": non_finite_cells,
        "changed_area_m2": changed_area,
        "patches": [
            {
                "patch_id": patch["patch_id"],
                "cells": patch["count"],
                "area_m2": patch["area_m2"],
                "mean_abs_delta": patch["mean_abs_delta"],
                "max_abs_delta": patch["max_abs_delta"],
                "mean_baseline": patch["mean_baseline"],
                "mean_comparison": patch["mean_comparison"],
                "bbox": patch["bbox"],
                "centroid": patch["centroid"],
                "row_min": patch["row_min"],
                "row_max": patch["row_max"],
                "col_min": patch["col_min"],
                "col_max": patch["col_max"],
            }
            for patch in kept
        ],
        "dropped_patches": len(dropped),
        "mask": mask,
        "invalid_mask": invalid_mask,
        "header": dict(baseline["header"]),
        "crs": baseline.get("crs") or "",
        "crs_model": baseline.get("crs_model") or "",
        "raster_type": baseline.get("raster_type"),
        "linear_unit": baseline.get("linear_unit") or "",
        "linear_unit_code": baseline.get("linear_unit_code"),
        "linear_unit_m": (
            baseline.get("linear_unit_m")
            if baseline.get("linear_unit_m") is not None else 1.0
        ),
    }


def write_change_mask(result: Dict[str, Any], path: str, nodata_value: float = -9999) -> str:
    """Write the mask as ASCII, or as a real GeoTIFF when the suffix is .tif."""
    path = str(path or "").strip()
    if not path:
        raise ChangeError("output path must not be empty")
    try:
        nodata_value = float(nodata_value)
    except (TypeError, ValueError) as exc:
        raise ChangeError("nodata_value must be a finite number") from exc
    if not math.isfinite(nodata_value):
        raise ChangeError("nodata_value must be a finite number")
    cellsize_y = float(result.get("cellsize_y") or result["cellsize"])
    is_tiff = path.lower().endswith((".tif", ".tiff"))
    if not is_tiff and abs(cellsize_y - float(result["cellsize"])) > 1e-9:
        raise ChangeError(
            "ASCII masks cannot carry a non-square cell; write the mask as .tif"
        )
    if is_tiff:
        from geoops.geotiff import GeoTiffError, write_geotiff_mask

        crs = str(result.get("crs") or "").strip()
        crs_model = str(result.get("crs_model") or "").strip()
        if not crs or crs_model not in ("geographic", "projected"):
            raise ChangeError(
                "GeoTIFF mask output requires a source CRS and CRS model; "
                "use an ASCII source or write the mask as .asc"
            )
        values = [
            float(nodata_value) if invalid else float(value)
            for value, invalid in zip(result["mask"], result["invalid_mask"])
        ]
        try:
            return write_geotiff_mask(
                path,
                width=int(result["ncols"]),
                height=int(result["nrows"]),
                cellsize=float(result["cellsize"]),
                cellsize_y=cellsize_y,
                linear_unit_code=result.get("linear_unit_code"),
                xllcorner=float(result["header"]["xllcorner"]),
                yllcorner=float(result["header"]["yllcorner"]),
                crs=crs,
                crs_model=crs_model,
                values=values,
                nodata=float(nodata_value),
            )
        except GeoTiffError as exc:
            raise ChangeError("cannot write GeoTIFF mask: %s" % exc) from exc
    path = os.path.abspath(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    header = result["header"]
    nodata_text = repr(nodata_value)
    lines = [
        "ncols %d" % result["ncols"],
        "nrows %d" % result["nrows"],
        "xllcorner %s" % repr(header["xllcorner"]),
        "yllcorner %s" % repr(header["yllcorner"]),
        "cellsize %s" % repr(result["cellsize"]),
        "NODATA_value %s" % nodata_text,
    ]
    mask = result["mask"]
    invalid = result["invalid_mask"]
    ncols = result["ncols"]
    for row in range(result["nrows"]):
        cells = []
        for col in range(ncols):
            index = row * ncols + col
            cells.append(nodata_text if invalid[index] else str(mask[index]))
        lines.append(" ".join(cells))
    text = "\n".join(lines) + "\n"
    temp_path = path + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp_path, path)
    crs = str(result.get("crs") or "").strip()
    crs_model = str(result.get("crs_model") or "").strip()
    if crs and crs_model:
        sidecar = path + ".json"
        sidecar_tmp = sidecar + ".tmp"
        with open(sidecar_tmp, "w", encoding="utf-8") as handle:
            json.dump({"crs": crs, "crs_model": crs_model}, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(sidecar_tmp, sidecar)
    return path
