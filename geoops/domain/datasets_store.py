"""Dataset registration on top of the real metadata probe.

The probe in ``geoops/domain/datasets.py`` reads the file, computes its sha256
and takes the CRS from the sidecar. This registry refuses to register anything
that probe did not classify as READY: a missing file or an empty CRS is a refusal
with the probe's reason, not a dataset row with blanks.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from geoops.domain import datasets as probe
from geoops.domain.projects import ProjectRegistry
from geoops.domain.registry import DomainObject, DomainRegistry, ObjectType
from geoops.survey.change import ChangeError, read_raster_grid


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
        for name in ("width", "height", "bands"):
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
            grid = read_raster_grid(path, band=band)
        except (ChangeError, TypeError, ValueError) as exc:
            raise DatasetError("cannot profile raster: %s" % exc) from exc
        nodata = grid["header"].get("nodata_value")
        valid = [value for value in grid["values"] if nodata is None or value != nodata]
        if not valid:
            raise DatasetError("raster %s has no valid cells after NODATA removal" % dataset_id)
        ncols = int(grid["ncols"])
        nrows = int(grid["nrows"])
        cellsize = float(grid["cellsize"])
        xll = grid["header"].get("xllcorner")
        yll = grid["header"].get("yllcorner")
        bounds = None
        if xll is not None and yll is not None:
            bounds = [
                float(xll),
                float(yll),
                float(xll) + ncols * cellsize,
                float(yll) + nrows * cellsize,
            ]
        return {
            "dataset_id": dataset_id,
            "path": path,
            "format": grid.get("source_format") or "ascii",
            "bands": int(grid.get("bands") or 1),
            "band": int(grid.get("band") or 1),
            "ncols": ncols,
            "nrows": nrows,
            "cellsize": cellsize,
            "xllcorner": xll,
            "yllcorner": yll,
            "bounds": bounds,
            "crs": str(obj.payload.get("crs") or grid.get("crs") or ""),
            "crs_model": str(grid.get("crs_model") or ""),
            "nodata": nodata,
            "valid_cells": len(valid),
            "nodata_cells": len(grid["values"]) - len(valid),
            "min": min(valid),
            "max": max(valid),
            "mean": sum(valid) / len(valid),
        }
