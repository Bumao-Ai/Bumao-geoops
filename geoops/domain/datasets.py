"""Dataset intake with a real, non-crashing metadata probe.

No synthetic dataset is produced here. A missing path returns ``SKIP`` with a
written reason so the caller can continue; an unreadable file returns
``ERROR``. Metadata comes from a sidecar ``<path>.json`` file when present.

Metadata comes from the GeoTIFF header when readable, and from a sidecar
``<path>.json`` for CRS overrides and non-GeoTIFF formats. A sidecar CRS that
contradicts the header is recorded as a metadata conflict and fails
re-validation; no metadata is invented when neither source has it.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

from geoops.geotiff import GeoTiffError, probe_geotiff

STATUS_READY = "READY"
STATUS_INCOMPLETE = "INCOMPLETE"
STATUS_SKIP = "SKIP"
STATUS_ERROR = "ERROR"


@dataclass
class DatasetRecord:
    dataset_id: str
    path: str
    status: str
    size_bytes: Optional[int] = None
    sha256: str = ""
    crs: str = ""
    crs_model: str = ""
    raster_type: Optional[int] = None
    linear_unit: str = ""
    linear_unit_code: Optional[int] = None
    linear_unit_m: Optional[float] = None
    metadata_conflict: bool = False
    metadata_source: str = "none"
    reason: str = ""
    width: Optional[int] = None
    height: Optional[int] = None
    bands: Optional[int] = None
    bounds: Optional[list] = None
    pixel_size: Optional[list] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "path": self.path,
            "status": self.status,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "crs": self.crs,
            "crs_model": self.crs_model,
            "raster_type": self.raster_type,
            "linear_unit": self.linear_unit,
            "linear_unit_code": self.linear_unit_code,
            "linear_unit_m": self.linear_unit_m,
            "metadata_conflict": self.metadata_conflict,
            "metadata_source": self.metadata_source,
            "reason": self.reason,
            "width": self.width,
            "height": self.height,
            "bands": self.bands,
            "bounds": self.bounds,
            "pixel_size": self.pixel_size,
        }


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _probe_sidecar(path: str):
    sidecar = path + ".json"
    if not os.path.isfile(sidecar):
        return {}, "none"
    try:
        with open(sidecar, encoding="utf-8-sig") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        return {}, "sidecar-unreadable: %s" % exc
    if not isinstance(data, dict):
        return {}, "sidecar-not-an-object"
    return data, sidecar


def register(path: Optional[str]) -> DatasetRecord:
    """Probe a dataset path and return a record. Never raises on bad input."""
    if not path:
        return DatasetRecord("", "", STATUS_SKIP, reason="no path supplied")
    absolute = os.path.abspath(str(path))
    if not os.path.exists(absolute):
        return DatasetRecord(
            "", absolute, STATUS_SKIP, reason="path does not exist: %s" % absolute
        )
    if not os.path.isfile(absolute):
        return DatasetRecord(
            "", absolute, STATUS_SKIP, reason="path is not a regular file: %s" % absolute
        )
    try:
        size_bytes = os.path.getsize(absolute)
        digest = _sha256(absolute)
    except OSError as exc:
        return DatasetRecord(
            "", absolute, STATUS_ERROR, reason="cannot read file: %s" % exc
        )
    sidecar, source = _probe_sidecar(absolute)
    crs = str(sidecar.get("crs") or "").strip()
    raw_model = str(sidecar.get("crs_model") or "").strip()
    crs_model = raw_model.lower()
    invalid_sidecar_model = bool(raw_model) and crs_model not in (
        "geographic",
        "projected",
    )
    if invalid_sidecar_model:
        crs_model = ""
    extra: Dict[str, Any] = {}
    metadata_conflict = invalid_sidecar_model
    reason = "" if crs else "CRS field is empty in sidecar metadata"
    if invalid_sidecar_model:
        reason = "sidecar crs_model must be geographic or projected: %r" % raw_model
    if os.path.splitext(absolute)[1].lower() in (".tif", ".tiff"):
        try:
            info = probe_geotiff(absolute, require_crs=False)
        except GeoTiffError as exc:
            if not crs:
                reason = "GeoTIFF header unreadable: %s" % exc
        else:
            extra = info
            header_crs = str(info.get("crs") or "").strip()
            header_model = str(info.get("crs_model") or "").strip().lower()
            if header_model not in ("geographic", "projected"):
                header_model = ""
            if not crs:
                crs = header_crs
                source = "geotiff-header"
                reason = "" if crs else "GeoTIFF header has no EPSG GeoKey"
                crs_model = crs_model or header_model
            elif header_crs and header_crs.upper().replace(" ", "") != crs.upper().replace(" ", ""):
                reason = "sidecar CRS %s overrides GeoTIFF header %s (metadata conflict)" % (
                    crs, header_crs,
                )
                metadata_conflict = True
            elif header_model and crs_model and header_model != crs_model:
                reason = "sidecar CRS model %s conflicts with GeoTIFF header %s" % (
                    crs_model, header_model,
                )
                metadata_conflict = True
            else:
                crs_model = crs_model or header_model
    if not crs_model:
        normalized = crs.upper().replace(" ", "")
        if normalized == "EPSG:4326":
            crs_model = "geographic"
        elif normalized == "EPSG:3857":
            crs_model = "projected"
    georeferenced = True
    if extra and extra.get("bounds") is None:
        georeferenced = False
        reason = "GeoTIFF has a CRS but no pixel scale/tiepoint bounds"
    elif not extra and os.path.splitext(absolute)[1].lower() in (".tif", ".tiff"):
        georeferenced = False
        reason = "GeoTIFF header could not be read; metadata would come from a sidecar alone"
    if invalid_sidecar_model and not reason:
        reason = "sidecar crs_model must be geographic or projected: %r" % raw_model
    return DatasetRecord(
        dataset_id="DS-" + digest[:12],
        path=absolute,
        status=(
            STATUS_READY
            if crs and georeferenced and not metadata_conflict
            else STATUS_INCOMPLETE
        ),
        size_bytes=size_bytes,
        sha256=digest,
        crs=crs,
        crs_model=crs_model,
        raster_type=extra.get("raster_type"),
        linear_unit=str(extra.get("linear_unit") or ""),
        linear_unit_code=extra.get("linear_unit_code"),
        linear_unit_m=extra.get("linear_unit_m"),
        metadata_conflict=metadata_conflict,
        metadata_source=source,
        reason=reason,
        width=extra.get("width"),
        height=extra.get("height"),
        bands=extra.get("bands"),
        bounds=extra.get("bounds"),
        pixel_size=extra.get("pixel_size"),
    )
