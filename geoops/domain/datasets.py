"""Dataset intake with a real, non-crashing metadata probe.

No synthetic dataset is produced here. A missing path returns ``SKIP`` with a
written reason so the caller can continue; an unreadable file returns
``ERROR``. Metadata comes from a sidecar ``<path>.json`` file when present.

Raster CRS extraction from imagery itself requires a geospatial reader and is
not part of the current scaffold. The sidecar is the only metadata source here.
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
    extra: Dict[str, Any] = {}
    reason = "" if crs else "CRS field is empty in sidecar metadata"
    if os.path.splitext(absolute)[1].lower() in (".tif", ".tiff"):
        try:
            info = probe_geotiff(absolute, require_crs=False)
        except GeoTiffError as exc:
            if not crs:
                reason = "GeoTIFF header unreadable: %s" % exc
        else:
            extra = info
            header_crs = str(info.get("crs") or "").strip()
            if not crs:
                crs = header_crs
                source = "geotiff-header"
                reason = "" if crs else "GeoTIFF header has no EPSG GeoKey"
            elif header_crs and header_crs.upper().replace(" ", "") != crs.upper().replace(" ", ""):
                reason = "sidecar CRS overrides GeoTIFF header %s" % header_crs
    return DatasetRecord(
        dataset_id="DS-" + digest[:12],
        path=absolute,
        status=STATUS_READY if crs else STATUS_INCOMPLETE,
        size_bytes=size_bytes,
        sha256=digest,
        crs=crs,
        metadata_source=source,
        reason=reason,
        width=extra.get("width"),
        height=extra.get("height"),
        bands=extra.get("bands"),
        bounds=extra.get("bounds"),
        pixel_size=extra.get("pixel_size"),
    )
