"""Pixel-level accuracy for two aligned masks.

This module deliberately does not pretend to read GeoTIFF. It reads ESRI ASCII
grids (the same fixture format used by the local demo) and reports a real
confusion matrix. A synthetic reference is allowed for testing, but the
returned object carries ``synthetic_reference`` only when the caller says so;
the arithmetic itself is never fabricated.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Tuple


class MetricsError(ValueError):
    """The two grids cannot be compared."""


HEADER_KEYS = {
    "ncols",
    "nrows",
    "xllcorner",
    "yllcorner",
    "xllcenter",
    "yllcenter",
    "cellsize",
    "nodata_value",
}


def read_ascii_grid(path: str) -> Dict[str, Any]:
    path = str(path or "").strip()
    if not path:
        raise MetricsError("grid path is required")
    if not os.path.exists(path):
        raise MetricsError("grid does not exist: %s" % path)
    if not os.path.isfile(path):
        raise MetricsError("grid is not a regular file: %s" % path)
    header: Dict[str, float] = {}
    values: list[float] = []
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                parts = line.split()
                if not parts:
                    continue
                key = parts[0].lower()
                if key in HEADER_KEYS and len(parts) == 2:
                    header[key] = float(parts[1])
                else:
                    values.extend(float(part) for part in parts)
    except (OSError, ValueError) as exc:
        raise MetricsError("cannot read ASCII grid %s: %s" % (path, exc)) from exc

    for key in ("ncols", "nrows", "cellsize"):
        if key not in header:
            raise MetricsError("grid %s has no %s header" % (path, key))
    ncols = int(header["ncols"])
    nrows = int(header["nrows"])
    if ncols <= 0 or nrows <= 0:
        raise MetricsError("grid %s has invalid dimensions %dx%d" % (path, ncols, nrows))
    if len(values) != ncols * nrows:
        raise MetricsError(
            "grid %s has %d values, expected %d" % (path, len(values), ncols * nrows)
        )
    return {
        "path": os.path.abspath(path),
        "ncols": ncols,
        "nrows": nrows,
        "cellsize": float(header["cellsize"]),
        "nodata": float(header.get("nodata_value", -9999.0)),
        "values": values,
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
    reference = read_ascii_grid(reference_path)
    predicted = read_ascii_grid(predicted_path)
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

    tp = fp = fn = tn = skipped = 0
    for ref_value, pred_value in zip(reference["values"], predicted["values"]):
        if ref_value == reference["nodata"] or pred_value == predicted["nodata"]:
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
