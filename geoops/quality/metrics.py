"""Pixel-level accuracy for two aligned masks.

Reads ESRI ASCII grids or classic GeoTIFF masks (first band) and reports a real
confusion matrix. A GeoTIFF without pixel scale/tiepoint is refused because its
cells cannot be aligned. A synthetic reference is allowed for testing, but the
returned object carries ``synthetic_reference`` only when the caller says so;
the arithmetic itself is never fabricated.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Tuple

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
        "nodata": float(grid["header"].get("nodata_value", -9999.0)),
        "crs": grid.get("crs") or "",
        "values": grid["values"],
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
            "xllcorner": grid["header"].get("xllcorner"),
            "yllcorner": grid["header"].get("yllcorner"),
            "crs": grid.get("crs") or "",
            "nodata": float(nodata) if nodata is not None else -9999.0,
            "values": grid["values"],
        }
    ascii_grid = read_ascii_grid(path)
    return {
        **ascii_grid,
        "xllcorner": ascii_grid["header"].get("xllcorner"),
        "yllcorner": ascii_grid["header"].get("yllcorner"),
        "crs": ascii_grid.get("crs") or "",
    }


def compare_masks(
    reference_path: str,
    predicted_path: str,
    threshold: float = 0.0,
    synthetic_reference: bool = False,
) -> Dict[str, Any]:
    """Compare positive cells in two aligned ASCII grids.

    A cell is positive when its value is greater than ``threshold`` and is not
    NODATA. Cells where either grid is NODATA are excluded and counted.
    """
    reference = read_mask_grid(reference_path)
    predicted = read_mask_grid(predicted_path)
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
    for key in ("xllcorner", "yllcorner"):
        ref_origin, pred_origin = reference.get(key), predicted.get(key)
        if ref_origin is None or pred_origin is None:
            raise MetricsError("grid %s is missing; cannot confirm alignment" % key)
        if abs(float(ref_origin) - float(pred_origin)) > 1e-9:
            raise MetricsError(
                "grid origins differ at %s: %s vs %s"
                % (key, ref_origin, pred_origin)
            )
    if reference.get("crs") and predicted.get("crs") and reference["crs"] != predicted["crs"]:
        raise MetricsError(
            "grid CRS differ: %s vs %s" % (reference["crs"], predicted["crs"])
        )

    tp = fp = fn = tn = skipped = 0
    for ref_value, pred_value in zip(reference["values"], predicted["values"]):
        if is_nodata(ref_value, reference["nodata"]) or is_nodata(pred_value, predicted["nodata"]):
            skipped += 1
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

    valid = tp + fp + fn + tn
    if valid == 0:
        raise MetricsError("no comparable cells: every cell is NODATA")

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
            "total": valid + skipped,
        },
        "cells": {
            "valid": valid,
            "skipped_nodata": skipped,
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
