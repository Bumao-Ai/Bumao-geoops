"""Pixel-level accuracy for two aligned masks.

Reads ESRI ASCII grids or classic GeoTIFF masks (first band) and reports a real
confusion matrix. Two GeoTIFF masks are streamed in row order, so neither the
reference nor the prediction is materialized as a full Python float list. A
GeoTIFF without pixel scale/tiepoint is refused because its cells cannot be
aligned. A synthetic reference is allowed for testing, but the returned object
carries ``synthetic_reference`` only when the caller says so; the arithmetic
itself is never fabricated.
"""

from __future__ import annotations

import os
import math
from itertools import zip_longest
from typing import Any, Dict, Iterator, Tuple

from geoops.survey.change import is_nodata


class MetricsError(ValueError):
    """The two grids cannot be compared."""


def read_ascii_grid(path: str) -> Dict[str, Any]:
    """Read an ASCII mask through the same validated grid reader as change."""
    from geoops.survey.change import ChangeError, read_raster_grid

    try:
        grid = read_raster_grid(path)
    except ChangeError as exc:
        raise MetricsError(str(exc)) from exc
    return {
        "path": os.path.abspath(grid["path"]),
        "header": grid["header"],
        "ncols": grid["ncols"],
        "nrows": grid["nrows"],
        "cellsize": grid["cellsize"],
        "cellsize_y": grid.get("cellsize_y") or grid["cellsize"],
        "nodata": (
            float(grid["header"]["nodata_value"])
            if grid["header"].get("nodata_value") is not None
            else None
        ),
        "crs": grid.get("crs") or "",
        "crs_model": grid.get("crs_model") or "",
        "values": grid["values"],
    }


def mask_descriptor(path: str) -> Dict[str, Any]:
    """Read mask metadata without materializing GeoTIFF pixels."""
    suffix = os.path.splitext(str(path or ""))[1].lower()
    if suffix in (".tif", ".tiff"):
        from geoops.geotiff import GeoTiffError, probe_geotiff
        from geoops.survey.change import read_sidecar_crs

        try:
            info = probe_geotiff(path, require_crs=False)
        except GeoTiffError as exc:
            raise MetricsError("cannot read GeoTIFF mask %s: %s" % (path, exc)) from exc
        pixel_size = info.get("pixel_size")
        bounds = info.get("bounds")
        if not pixel_size or not bounds:
            raise MetricsError(
                "GeoTIFF mask %s has no pixel scale/tiepoint; cannot align it" % path
            )
        header_crs = str(info.get("crs") or "").strip()
        header_model = str(info.get("crs_model") or "").strip().lower()
        side_crs, side_model = read_sidecar_crs(path)
        if header_crs and side_crs:
            if header_crs.upper().replace(" ", "") != side_crs.upper().replace(" ", ""):
                raise MetricsError(
                    "GeoTIFF %s has conflicting CRS: sidecar %s vs header %s"
                    % (path, side_crs, header_crs)
                )
        if header_model and side_model and header_model != side_model:
            raise MetricsError(
                "GeoTIFF %s has conflicting CRS model: sidecar %s vs header %s"
                % (path, side_model, header_model)
            )
        sx = float(pixel_size[0])
        sy = float(pixel_size[1]) if len(pixel_size) > 1 else sx
        if sx <= 0 or sy <= 0:
            raise MetricsError("GeoTIFF mask %s has a non-positive pixel size" % path)
        return {
            "path": os.path.abspath(path),
            "format": "geotiff",
            "ncols": int(info["width"]),
            "nrows": int(info["height"]),
            "cellsize": sx,
            "cellsize_y": sy,
            "xllcorner": bounds[0],
            "yllcorner": bounds[1],
            "crs": header_crs or side_crs,
            "crs_model": header_model or side_model,
            "nodata": info.get("nodata"),
        }
    ascii_grid = read_ascii_grid(path)
    return {
        **ascii_grid,
        "format": "ascii",
        "xllcorner": ascii_grid["header"].get("xllcorner"),
        "yllcorner": ascii_grid["header"].get("yllcorner"),
    }


def _validate_mask_alignment(reference: Dict[str, Any], predicted: Dict[str, Any]) -> None:
    if reference["ncols"] != predicted["ncols"] or reference["nrows"] != predicted["nrows"]:
        raise MetricsError(
            "grid dimensions differ: %dx%d vs %dx%d"
            % (
                reference["ncols"],
                reference["nrows"],
                predicted["ncols"],
                predicted["nrows"],
            )
        )
    if abs(reference["cellsize"] - predicted["cellsize"]) > 1e-9:
        raise MetricsError(
            "grid cell sizes differ: %s vs %s"
            % (reference["cellsize"], predicted["cellsize"])
        )
    if abs(float(reference["cellsize_y"]) - float(predicted["cellsize_y"])) > 1e-9:
        raise MetricsError(
            "grid cell heights differ: %s vs %s"
            % (reference["cellsize_y"], predicted["cellsize_y"])
        )
    for key in ("xllcorner", "yllcorner"):
        ref_origin, pred_origin = reference.get(key), predicted.get(key)
        if ref_origin is None or pred_origin is None:
            raise MetricsError("grid %s is missing; cannot confirm alignment" % key)
        if abs(float(ref_origin) - float(pred_origin)) > 1e-9:
            raise MetricsError(
                "grid origins differ at %s: %s vs %s"
                % (key, ref_origin, pred_origin)
            )
    left_crs = str(reference.get("crs") or "").strip().upper().replace(" ", "")
    right_crs = str(predicted.get("crs") or "").strip().upper().replace(" ", "")
    left_model = str(reference.get("crs_model") or "").strip().lower()
    right_model = str(predicted.get("crs_model") or "").strip().lower()
    if bool(left_crs) != bool(right_crs):
        raise MetricsError("grid CRS is present in only one mask")
    if left_crs and left_crs != right_crs:
        raise MetricsError("grid CRS differ: %s vs %s" % (left_crs, right_crs))
    if left_crs and bool(left_model) != bool(right_model):
        raise MetricsError("grid CRS model is present in only one mask")
    if left_model and left_model != right_model:
        raise MetricsError(
            "grid CRS model differ: %s vs %s" % (left_model, right_model)
        )


def _count_cells(
    reference_values: Iterator[float],
    predicted_values: Iterator[float],
    reference_nodata: Any,
    predicted_nodata: Any,
    threshold: float,
) -> Dict[str, int]:
    tp = fp = fn = tn = skipped_nodata = skipped_non_finite = 0
    sentinel = object()
    for ref_value, pred_value in zip_longest(
        reference_values, predicted_values, fillvalue=sentinel
    ):
        if ref_value is sentinel or pred_value is sentinel:
            raise MetricsError("mask grids decoded to different cell counts")
        if is_nodata(ref_value, reference_nodata) or is_nodata(
            pred_value, predicted_nodata
        ):
            skipped_nodata += 1
            continue
        if not math.isfinite(ref_value) or not math.isfinite(pred_value):
            skipped_non_finite += 1
            continue
        ref_positive = ref_value > threshold
        pred_positive = pred_value > threshold
        if ref_positive and pred_positive:
            tp += 1
        elif pred_positive:
            fp += 1
        elif ref_positive:
            fn += 1
        else:
            tn += 1
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "skipped_nodata": skipped_nodata,
        "skipped_non_finite": skipped_non_finite,
    }


def read_mask_grid(path: str) -> Dict[str, Any]:
    """Read an ASCII or GeoTIFF mask; GeoTIFF must carry georeferencing."""
    suffix = os.path.splitext(str(path or ""))[1].lower()
    if suffix in (".tif", ".tiff"):
        from geoops.survey.change import ChangeError, read_raster_grid

        try:
            grid = read_raster_grid(path)
        except ChangeError as exc:
            raise MetricsError("cannot read GeoTIFF mask %s: %s" % (path, exc)) from exc
        nodata = grid["header"].get("nodata_value")
        return {
            "path": os.path.abspath(path),
            "ncols": grid["ncols"],
            "nrows": grid["nrows"],
            "cellsize": grid["cellsize"],
            "cellsize_y": grid.get("cellsize_y") or grid["cellsize"],
            "xllcorner": grid["header"].get("xllcorner"),
            "yllcorner": grid["header"].get("yllcorner"),
            "crs": grid.get("crs") or "",
            "crs_model": grid.get("crs_model") or "",
            "nodata": float(nodata) if nodata is not None else None,
            "values": grid["values"],
        }
    ascii_grid = read_ascii_grid(path)
    return {
        **ascii_grid,
        "xllcorner": ascii_grid["header"].get("xllcorner"),
        "yllcorner": ascii_grid["header"].get("yllcorner"),
        "crs": ascii_grid.get("crs") or "",
        "crs_model": ascii_grid.get("crs_model") or "",
    }


def compare_masks(
    reference_path: str,
    predicted_path: str,
    threshold: float = 0.0,
    synthetic_reference: bool = False,
) -> Dict[str, Any]:
    """Compare positive cells in two aligned ASCII or GeoTIFF masks.

    A cell is positive when its value is greater than ``threshold`` and is not
    NODATA. Cells where either grid is NODATA are excluded and counted. Two
    GeoTIFF masks are consumed row by row instead of loaded whole.
    """
    try:
        threshold = float(threshold)
    except (TypeError, ValueError) as exc:
        raise MetricsError("threshold must be a number") from exc
    if not math.isfinite(threshold):
        raise MetricsError("threshold must be finite")
    if threshold < 0:
        raise MetricsError(
            "threshold must not be negative; a 0/1 mask would count background as positive"
        )
    reference = mask_descriptor(reference_path)
    predicted = mask_descriptor(predicted_path)
    _validate_mask_alignment(reference, predicted)
    if reference.get("format") == "geotiff" and predicted.get("format") == "geotiff":
        from geoops.geotiff import GeoTiffError, iter_geotiff_band_values

        try:
            counts = _count_cells(
                iter_geotiff_band_values(reference_path, 1),
                iter_geotiff_band_values(predicted_path, 1),
                reference["nodata"],
                predicted["nodata"],
                threshold,
            )
        except GeoTiffError as exc:
            raise MetricsError("cannot read GeoTIFF mask: %s" % exc) from exc
    elif reference.get("format") == "geotiff" or predicted.get("format") == "geotiff":
        reference_grid = read_mask_grid(reference_path)
        predicted_grid = read_mask_grid(predicted_path)
        counts = _count_cells(
            reference_grid["values"],
            predicted_grid["values"],
            reference_grid["nodata"],
            predicted_grid["nodata"],
            threshold,
        )
    else:
        counts = _count_cells(
            reference["values"],
            predicted["values"],
            reference["nodata"],
            predicted["nodata"],
            threshold,
        )

    tp = counts["tp"]
    fp = counts["fp"]
    fn = counts["fn"]
    tn = counts["tn"]
    skipped_nodata = counts["skipped_nodata"]
    skipped_non_finite = counts["skipped_non_finite"]

    valid = tp + fp + fn + tn
    if valid == 0:
        raise MetricsError("no comparable cells: every cell is NODATA or non-finite")

    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    if precision is not None and recall is not None and (precision + recall):
        f1 = 2 * precision * recall / (precision + recall)
    else:
        f1 = None
    iou = tp / (tp + fp + fn) if (tp + fp + fn) else None

    return {
        "format": "geoops-quality-metrics",
        "version": 1,
        "reference_path": reference["path"],
        "predicted_path": predicted["path"],
        "synthetic_reference": bool(synthetic_reference),
        "threshold": float(threshold),
        "grid": {
            "ncols": reference["ncols"],
            "nrows": reference["nrows"],
            "cellsize": reference["cellsize"],
            "cellsize_y": reference["cellsize_y"],
            "total": valid + skipped_nodata + skipped_non_finite,
        },
        "cells": {
            "valid": valid,
            "skipped_nodata": skipped_nodata,
            "skipped_non_finite": skipped_non_finite,
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "tn": tn,
        },
        "metrics": {
            "pixel_accuracy": (tp + tn) / valid,
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "iou": iou,
        },
    }
