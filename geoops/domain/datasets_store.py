"""Dataset registration on top of the real metadata probe.

The probe in ``geoops/domain/datasets.py`` reads the file, computes its sha256
and takes the CRS from the sidecar. This registry refuses to register anything
that probe did not classify as READY: a missing file or an empty CRS is a refusal
with the probe's reason, not a dataset row with blanks.
"""

from __future__ import annotations

import math
import os
from typing import Any, Dict, List, Optional

from geoops.domain import datasets as probe
from geoops.domain.projects import ProjectRegistry
from geoops.domain.registry import DomainObject, DomainRegistry, ObjectType
from geoops.geotiff import GeoTiffError, profile_geotiff_band
from geoops.survey.change import (
    ChangeError,
    is_nodata,
    measure_raster_area,
    read_raster_grid,
    read_sidecar_crs,
)


class DatasetError(ValueError):
    """A dataset record was refused; nothing was written."""


class DatasetRegistry:
    def __init__(self, registry: DomainRegistry, projects: Optional[ProjectRegistry] = None) -> None:
        self.registry = registry
        self.projects = projects

    def register(
        self,
        project_id: str,
        path: str,
        label: str = "",
        dataset_id: str = "",
        task_id: str = "",
        synthetic: bool = False,
    ) -> DomainObject:
        project_id = str(project_id or "").strip()
        if not project_id:
            raise DatasetError("project_id is required")
        if self.projects is not None and self.projects.get(project_id) is None:
            raise DatasetError("unknown project_id: %s" % project_id)
        result = probe.register(path)
        if result.status != probe.STATUS_READY:
            raise DatasetError(
                "%s: %s" % (result.status, result.reason or "dataset did not pass intake")
            )
        dataset_id = str(dataset_id or result.dataset_id).strip()
        if self.registry.get(dataset_id) is not None:
            raise DatasetError("duplicate dataset_id: %s" % dataset_id)
        payload: Dict[str, Any] = {
            "dataset_id": dataset_id,
            "project_id": project_id,
            "task_id": str(task_id or "").strip(),
            "synthetic": bool(synthetic),
            "path": result.path,
            "label": str(label or "").strip(),
            "size_bytes": result.size_bytes,
            "sha256": result.sha256,
            "crs": result.crs,
            "crs_model": result.crs_model,
            "raster_type": result.raster_type,
            "linear_unit": result.linear_unit,
            "linear_unit_code": result.linear_unit_code,
            "linear_unit_m": result.linear_unit_m,
            "metadata_conflict": result.metadata_conflict,
            "metadata_source": result.metadata_source,
            "width": result.width,
            "height": result.height,
            "bands": result.bands,
            "bounds": result.bounds,
            "pixel_size": result.pixel_size,
            "dataset_version": 1,
        }
        try:
            return self.registry.register(ObjectType.DATASET, dataset_id, payload)
        except ValueError as exc:
            raise DatasetError(str(exc)) from exc

    def get(self, dataset_id: str) -> Optional[DomainObject]:
        obj = self.registry.get(dataset_id)
        if obj is None or obj.object_type is not ObjectType.DATASET:
            return None
        return obj

    def list(self, project_id: str = "") -> List[DomainObject]:
        rows = self.registry.list_by_type(ObjectType.DATASET)
        if project_id:
            rows = [row for row in rows if row.payload.get("project_id") == project_id]
        return rows

    def validate(self, dataset_id: str) -> Dict[str, Any]:
        """Re-probe the file and compare it with what was registered."""
        obj = self.get(dataset_id)
        if obj is None:
            raise DatasetError("unknown dataset_id: %s" % dataset_id)
        payload = obj.payload
        path = str(payload.get("path") or "")
        checks = []
        if not os.path.exists(path):
            checks.append({"name": "file_exists", "status": "FAIL", "detail": path})
            return {"dataset_id": dataset_id, "status": "FAIL", "checks": checks}
        checks.append({"name": "file_exists", "status": "PASS", "detail": path})
        try:
            fresh = probe.register(path)
        except Exception as exc:  # the probe itself failed; never PASS
            checks.append({"name": "probe", "status": "ERROR", "detail": "%s: %s" % (type(exc).__name__, exc)})
            return {"dataset_id": dataset_id, "status": "ERROR", "checks": checks}
        if fresh.sha256 != payload.get("sha256"):
            checks.append(
                {"name": "sha256", "status": "FAIL", "detail": "content changed on disk"}
            )
        else:
            checks.append({"name": "sha256", "status": "PASS", "detail": fresh.sha256})
        if fresh.metadata_conflict:
            checks.append(
                {"name": "metadata_conflict", "status": "FAIL", "detail": fresh.reason}
            )
        if not fresh.crs:
            checks.append({"name": "crs", "status": "FAIL", "detail": "CRS missing after re-probe"})
        elif payload.get("crs") and fresh.crs != payload.get("crs"):
            checks.append(
                {
                    "name": "crs",
                    "status": "FAIL",
                    "detail": "registered %s but re-probe reads %s"
                    % (payload.get("crs"), fresh.crs),
                }
            )
        else:
            checks.append({"name": "crs", "status": "PASS", "detail": fresh.crs})
        registered_model = str(payload.get("crs_model") or "").lower()
        if registered_model and fresh.crs_model != registered_model:
            checks.append(
                {
                    "name": "crs_model",
                    "status": "FAIL",
                    "detail": "registered %s but re-probe reads %s"
                    % (registered_model, fresh.crs_model),
                }
            )
        elif registered_model:
            checks.append({"name": "crs_model", "status": "PASS", "detail": fresh.crs_model})
        for name in ("width", "height", "bands", "raster_type", "linear_unit_code"):
            registered_value = payload.get(name)
            fresh_value = getattr(fresh, name)
            if registered_value is not None and fresh_value is not None and registered_value != fresh_value:
                checks.append(
                    {
                        "name": name,
                        "status": "FAIL",
                        "detail": "registered %s but re-probe reads %s"
                        % (registered_value, fresh_value),
                    }
                )
        registered_unit = str(payload.get("linear_unit") or "")
        if registered_unit and fresh.linear_unit != registered_unit:
            checks.append(
                {
                    "name": "linear_unit",
                    "status": "FAIL",
                    "detail": "registered %s but re-probe reads %s"
                    % (registered_unit, fresh.linear_unit),
                }
            )
        status = "PASS" if all(check["status"] == "PASS" for check in checks) else "FAIL"
        return {"dataset_id": dataset_id, "status": status, "checks": checks}

    def profile(self, dataset_id: str, band: int = 1) -> Dict[str, Any]:
        """Read the real raster pixels and return a profile; never guess values."""
        obj = self.get(dataset_id)
        if obj is None:
            raise DatasetError("unknown dataset_id: %s" % dataset_id)
        path = str(obj.payload.get("path") or "")
        if not path or not os.path.isfile(path):
            raise DatasetError("dataset file is missing: %s" % dataset_id)
        try:
            if os.path.getsize(path) != int(obj.payload.get("size_bytes") or -1):
                raise DatasetError(
                    "dataset file size changed since registration; re-register: %s"
                    % dataset_id
                )
            digest = probe._sha256(path)
        except OSError as exc:
            raise DatasetError("cannot read dataset file: %s" % exc) from exc
        if digest != str(obj.payload.get("sha256") or ""):
            raise DatasetError(
                "dataset file content changed since registration; re-register: %s"
                % dataset_id
            )
        suffix = os.path.splitext(path)[1].lower()
        if suffix in (".tif", ".tiff"):
            return self._profile_geotiff(dataset_id, obj, path, band)
        try:
            grid = read_raster_grid(path, band=band)
        except (ChangeError, TypeError, ValueError) as exc:
            raise DatasetError("cannot profile raster: %s" % exc) from exc
        nodata = grid["header"].get("nodata_value")
        nodata_cells = sum(1 for value in grid["values"] if is_nodata(value, nodata))
        non_finite_cells = sum(
            1
            for value in grid["values"]
            if not is_nodata(value, nodata) and not math.isfinite(value)
        )
        valid = [
            value
            for value in grid["values"]
            if not is_nodata(value, nodata) and math.isfinite(value)
        ]
        if not valid:
            raise DatasetError("raster %s has no valid cells after NODATA removal" % dataset_id)
        ncols = int(grid["ncols"])
        nrows = int(grid["nrows"])
        cellsize = float(grid["cellsize"])
        cellsize_y = float(grid.get("cellsize_y") or cellsize)
        try:
            area = measure_raster_area(grid)
        except ChangeError as exc:
            raise DatasetError("cannot measure raster area: %s" % exc) from exc
        xll = grid["header"].get("xllcorner")
        yll = grid["header"].get("yllcorner")
        bounds = None
        if xll is not None and yll is not None:
            bounds = [
                float(xll),
                float(yll),
                float(xll) + ncols * cellsize,
                float(yll) + nrows * cellsize_y,
            ]
        return {
            "dataset_id": dataset_id,
            "path": path,
            "format": grid.get("source_format") or "ascii",
            "read_mode": "whole_file",
            "bands": int(grid.get("bands") or 1),
            "band": int(grid.get("band") or 1),
            "ncols": ncols,
            "nrows": nrows,
            "cellsize": cellsize,
            "cellsize_y": cellsize_y,
            "cell_area_m2": (
                area["cell_area_m2"] if area["area_basis"] != "map_units" else None
            ),
            "footprint_area_m2": (
                area["footprint_area_m2"] if area["area_basis"] != "map_units" else None
            ),
            "footprint_area_map_units": (
                area["footprint_area_m2"] if area["area_basis"] == "map_units" else None
            ),
            "area_basis": area["area_basis"],
            "xllcorner": xll,
            "yllcorner": yll,
            "bounds": bounds,
            "crs": str(obj.payload.get("crs") or grid.get("crs") or ""),
            "crs_model": str(obj.payload.get("crs_model") or grid.get("crs_model") or ""),
            "raster_type": grid.get("raster_type"),
            "linear_unit": str(grid.get("linear_unit") or ""),
            "linear_unit_code": grid.get("linear_unit_code"),
            "linear_unit_m": grid.get("linear_unit_m"),
            "nodata": nodata,
            "valid_cells": len(valid),
            "nodata_cells": nodata_cells,
            "non_finite_cells": non_finite_cells,
            "min": min(valid),
            "max": max(valid),
            "mean": sum(valid) / len(valid),
        }

    def _profile_geotiff(
        self, dataset_id: str, obj: DomainObject, path: str, band: int
    ) -> Dict[str, Any]:
        """Profile a GeoTIFF block by block; peak memory is one strip/tile."""
        if obj.payload.get("metadata_conflict"):
            raise DatasetError(
                "dataset %s was registered with conflicting sidecar/header metadata"
                % dataset_id
            )
        try:
            info = profile_geotiff_band(path, band=band)
        except (GeoTiffError, TypeError, ValueError) as exc:
            raise DatasetError("cannot profile raster: %s" % exc) from exc
        header_crs = str(info.get("crs") or "").strip()
        header_model = str(info.get("crs_model") or "").strip().lower()
        side_crs, side_model = read_sidecar_crs(path)
        if header_crs and side_crs:
            if header_crs.upper().replace(" ", "") != side_crs.upper().replace(" ", ""):
                raise DatasetError(
                    "GeoTIFF %s has conflicting CRS: sidecar %s vs header %s"
                    % (dataset_id, side_crs, header_crs)
                )
        if header_model and side_model and header_model != side_model:
            raise DatasetError(
                "GeoTIFF %s has conflicting CRS model: sidecar %s vs header %s"
                % (dataset_id, side_model, header_model)
            )
        effective_crs = header_crs or side_crs
        effective_model = header_model or side_model
        if not info.get("valid_cells"):
            raise DatasetError(
                "raster %s has no valid cells after NODATA removal" % dataset_id
            )
        pixel_size = info.get("pixel_size") or []
        bounds = info.get("bounds")
        if not pixel_size or not bounds:
            raise DatasetError(
                "GeoTIFF %s has no pixel scale/tiepoint; cannot align it" % dataset_id
            )
        cellsize = float(pixel_size[0])
        cellsize_y = float(pixel_size[1]) if len(pixel_size) > 1 else cellsize
        if cellsize <= 0 or cellsize_y <= 0:
            raise DatasetError("GeoTIFF %s has a non-positive pixel size" % dataset_id)
        ncols = int(info["width"])
        nrows = int(info["height"])
        nodata = info.get("nodata")
        grid = {
            "ncols": ncols,
            "nrows": nrows,
            "cellsize": cellsize,
            "cellsize_y": cellsize_y,
            "crs": effective_crs,
            "crs_model": effective_model,
            "raster_type": info.get("raster_type", 1),
            "linear_unit": str(info.get("linear_unit") or ""),
            "linear_unit_code": info.get("linear_unit_code"),
            "linear_unit_m": (
                float(info["linear_unit_m"])
                if info.get("linear_unit_m") is not None
                else 1.0
            ),
            "header": {
                "ncols": ncols,
                "nrows": nrows,
                "xllcorner": bounds[0],
                "yllcorner": bounds[1],
                "cellsize": cellsize,
                "cellsize_y": cellsize_y,
                "nodata_value": nodata,
            },
        }
        try:
            area = measure_raster_area(grid)
        except ChangeError as exc:
            raise DatasetError("cannot measure raster area: %s" % exc) from exc
        return {
            "dataset_id": dataset_id,
            "path": path,
            "format": "geotiff",
            "read_mode": str(info.get("read_mode") or "streamed_blocks"),
            "bands": int(info.get("bands") or 1),
            "band": int(info.get("band") or band),
            "ncols": ncols,
            "nrows": nrows,
            "cellsize": cellsize,
            "cellsize_y": cellsize_y,
            "cell_area_m2": (
                area["cell_area_m2"] if area["area_basis"] != "map_units" else None
            ),
            "footprint_area_m2": (
                area["footprint_area_m2"] if area["area_basis"] != "map_units" else None
            ),
            "footprint_area_map_units": (
                area["footprint_area_m2"] if area["area_basis"] == "map_units" else None
            ),
            "area_basis": area["area_basis"],
            "xllcorner": bounds[0],
            "yllcorner": bounds[1],
            "bounds": [float(value) for value in bounds],
            "crs": effective_crs,
            "crs_model": effective_model,
            "raster_type": info.get("raster_type", 1),
            "linear_unit": str(info.get("linear_unit") or ""),
            "linear_unit_code": info.get("linear_unit_code"),
            "linear_unit_m": (
                float(info["linear_unit_m"])
                if info.get("linear_unit_m") is not None
                else 1.0
            ),
            "nodata": nodata,
            "valid_cells": int(info["valid_cells"]),
            "nodata_cells": int(info["nodata_cells"]),
            "non_finite_cells": int(info["non_finite_cells"]),
            "min": info["min"],
            "max": info["max"],
            "mean": info["mean"],
        }
