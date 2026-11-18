"""Quality checks for datasets and deliverables.

The check is three-layered on purpose:

1. file and structure — the file must exist, be a regular file and match its
   registered hash/size;
2. spatial data — CRS, dimensions and bounds from the dataset record; a
   deliverable that is not bound to a dataset leaves this layer NOT_RECORDED;
3. professional verification — only a human sample with a written note can
   pass this layer. Missing professional evidence is NOT_RECORDED, never PASS.

An aggregate verdict can only be PASS when all three layers passed. FAIL and
ERROR win over everything; a missing layer yields PARTIAL. A report is written
to the configured report directory and registered as a QualityReport object.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import uuid
from typing import Any, Dict, List, Optional

from geoops.domain.datasets_store import DatasetError, DatasetRegistry
from geoops.domain.registry import DomainObject, DomainRegistry, ObjectType

FORMAT = "geoops-quality-report"
VERSION = 1
PROGRAM = "geoops-quality/0.1.0"


class QualityError(ValueError):
    """A quality check was refused or the target is unknown."""


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _check(name: str, status: str, detail: str, layer: str) -> Dict[str, Any]:
    return {"name": name, "status": status, "detail": str(detail), "layer": layer}


def _write_atomic(path: str, payload: Dict[str, Any]) -> str:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    handle, temp_path = tempfile.mkstemp(
        prefix=os.path.basename(path) + ".", suffix=".tmp", dir=os.path.dirname(path)
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
    except BaseException:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise
    return path


class QualityService:
    def __init__(
        self,
        registry: DomainRegistry,
        datasets: Optional[DatasetRegistry] = None,
        report_dir: Optional[str] = None,
    ) -> None:
        self.registry = registry
        self.datasets = datasets
        self.report_dir = os.path.abspath(report_dir) if report_dir else None

    # ------------------------------------------------------------------ checks
    def _dataset_checks(self, dataset_id: str) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
        if self.datasets is None:
            raise QualityError("dataset registry is not configured")
        obj = self.datasets.get(dataset_id)
        if obj is None:
            raise QualityError("unknown dataset_id: %s" % dataset_id)
        payload = obj.payload
        checks: List[Dict[str, Any]] = []
        try:
            validation = self.datasets.validate(dataset_id)
            for row in validation.get("checks", []):
                checks.append(
                    _check(
                        "dataset.%s" % row.get("name", "check"),
                        str(row.get("status") or "ERROR"),
                        str(row.get("detail") or ""),
                        "file" if row.get("name") in ("file_exists", "sha256") else "spatial",
                    )
                )
        except (DatasetError, OSError) as exc:
            checks.append(_check("dataset.validate", "ERROR", str(exc), "file"))

        crs = str(payload.get("crs") or "").strip()
        checks.append(
            _check("spatial.crs", "PASS" if crs else "FAIL", crs or "CRS is empty", "spatial")
        )
        width = payload.get("width")
        height = payload.get("height")
        if width and height:
            checks.append(
                _check(
                    "spatial.dimensions",
                    "PASS",
                    "%s x %s, %s band(s)" % (width, height, payload.get("bands") or "—"),
                    "spatial",
                )
            )
        else:
            checks.append(
                _check(
                    "spatial.dimensions",
                    "NOT_RECORDED",
                    "width/height were not available at registration",
                    "spatial",
                )
            )
        bounds = payload.get("bounds")
        checks.append(
            _check(
                "spatial.bounds",
                "PASS" if bounds else "NOT_RECORDED",
                json.dumps(bounds, ensure_ascii=False) if bounds else "bounds were not recorded",
                "spatial",
            )
        )
        return checks, {"dataset_id": dataset_id, "crs": crs}

    def _deliverable_checks(self, deliverable_id: str) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
        deliverable = self.registry.get(deliverable_id)
        if deliverable is None or deliverable.object_type is not ObjectType.DELIVERABLE:
            raise QualityError("unknown deliverable_id: %s" % deliverable_id)
        payload = deliverable.payload
        path = str(payload.get("path") or "")
        checks: List[Dict[str, Any]] = []
        if not os.path.exists(path):
            checks.append(_check("file.exists", "FAIL", "path does not exist: %s" % path, "file"))
            return checks, {"deliverable_id": deliverable_id}
        checks.append(_check("file.exists", "PASS", path, "file"))
        if not os.path.isfile(path):
            checks.append(_check("file.regular", "FAIL", "not a regular file", "file"))
            return checks, {"deliverable_id": deliverable_id}
        checks.append(_check("file.regular", "PASS", "regular file", "file"))
        actual_size = os.path.getsize(path)
        expected_size = payload.get("size_bytes")
        checks.append(
            _check(
                "file.size",
                "PASS" if actual_size == expected_size else "FAIL",
                "actual=%s registered=%s" % (actual_size, expected_size),
                "file",
            )
        )
        if not payload.get("sha256"):
            checks.append(_check("file.sha256", "NOT_RECORDED", "no registered hash", "file"))
        else:
            import hashlib

            digest = hashlib.sha256()
            with open(path, "rb") as handle:
                while True:
                    chunk = handle.read(1024 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
            checks.append(
                _check(
                    "file.sha256",
                    "PASS" if digest.hexdigest() == payload.get("sha256") else "FAIL",
                    digest.hexdigest(),
                    "file",
                )
            )

        dataset_id = str(payload.get("dataset_id") or "").strip()
        if dataset_id:
            try:
                dataset_checks, _ = self._dataset_checks(dataset_id)
                checks.extend(dataset_checks)
            except QualityError as exc:
                checks.append(_check("spatial.link", "ERROR", str(exc), "spatial"))
        else:
            checks.append(
                _check(
                    "spatial.link",
                    "NOT_RECORDED",
                    "deliverable is not bound to a registered dataset",
                    "spatial",
                )
            )
        return checks, {"deliverable_id": deliverable_id, "dataset_id": dataset_id or None}

    @staticmethod
    def _verdict(checks: List[Dict[str, Any]]) -> str:
        statuses = [str(row.get("status") or "ERROR") for row in checks]
        if "ERROR" in statuses:
            return "ERROR"
        if "FAIL" in statuses:
            return "FAIL"
        if "NOT_RECORDED" in statuses:
            return "PARTIAL"
        return "PASS"

    # ------------------------------------------------------------------ public
    def evaluate(
        self,
        target_type: str,
        target_id: str,
        task_id: str = "",
        professional_sample: bool = False,
        sample_note: str = "",
        actor: str = "",
        reference_path: str = "",
        predicted_path: str = "",
        synthetic_reference: bool = False,
    ) -> DomainObject:
        target_type = str(target_type or "").strip().lower()
        target_id = str(target_id or "").strip()
        if not target_id:
            raise QualityError("target_id is required")
        accuracy = None
        if target_type == "dataset":
            checks, target = self._dataset_checks(target_id)
            task_id = str(task_id or "").strip()
        elif target_type == "deliverable":
            checks, target = self._deliverable_checks(target_id)
            deliverable = self.registry.get(target_id)
            if not task_id:
                task_id = str(deliverable.payload.get("task_id") or "") if deliverable else ""
        else:
            raise QualityError("target_type must be dataset or deliverable")

        if reference_path:
            if target_type != "deliverable":
                raise QualityError("accuracy comparison requires target_type=deliverable")
            deliverable = self.registry.get(target_id)
            predicted_path = str(predicted_path or (deliverable.payload.get("path") if deliverable else "")).strip()
            try:
                from geoops.quality.metrics import MetricsError, compare_masks

                accuracy = compare_masks(
                    reference_path,
                    predicted_path,
                    synthetic_reference=synthetic_reference,
                )
                checks.append(
                    _check(
                        "professional.accuracy",
                        "PASS",
                        json.dumps(accuracy["metrics"], ensure_ascii=False),
                        "professional",
                    )
                )
            except (MetricsError, ValueError) as exc:
                checks.append(_check("professional.accuracy", "ERROR", str(exc), "professional"))
                accuracy = {"status": "ERROR", "error": str(exc)}

        if professional_sample:
            note = str(sample_note or "").strip()
            if not note:
                raise QualityError("professional sample requires a written note")
            checks.append(
                _check(
                    "professional.sample",
                    "PASS",
                    "human sample recorded: %s" % note,
                    "professional",
                )
            )
        else:
            checks.append(
                _check(
                    "professional.sample",
                    "NOT_RECORDED",
                    "no independent sample or professional review was supplied",
                    "professional",
                )
            )

        status = self._verdict(checks)
        report_id = "QR-%s" % uuid.uuid4().hex[:10]
        target_object = self.registry.get(target_id)
        synthetic = bool(target_object.payload.get("synthetic")) if target_object else False
        layers = {}
        for layer in ("file", "spatial", "professional"):
            rows = [row for row in checks if row["layer"] == layer]
            layers[layer] = {
                "status": self._verdict(rows) if rows else "NOT_RECORDED",
                "checks": rows,
            }
        report: Dict[str, Any] = {
            "format": FORMAT,
            "version": VERSION,
            "report_id": report_id,
            "target_type": target_type,
            "target": target,
            "task_id": task_id or None,
            "synthetic": synthetic,
            "status": status,
            "layers": layers,
            "checks": checks,
            "accuracy": accuracy,
            "basis": "GeoOps three-layer quality service: file/structure, spatial metadata, professional verification",
            "method": "sha256 and size check; CRS/bounds check; human sample and written note; mask confusion matrix when reference and predicted paths are supplied",
            "data": {
                "target_type": target_type,
                "target": target,
                "target_id": target_id,
                "reference_path": str(reference_path or ""),
                "predicted_path": str(predicted_path or ""),
            },
            "evidence": {
                "target_id": target_id,
                "target_path": str(target_object.payload.get("path") or "")
                if target_object is not None
                else "",
                "target_sha256": str(target_object.payload.get("sha256") or "")
                if target_object is not None
                else "",
                "check_count": len(checks),
                "accuracy_computed": accuracy is not None,
            },
            "generated_at": _now(),
            "program": PROGRAM,
            "actor": str(actor or "").strip(),
        }
        report_path = None
        if self.report_dir:
            report_path = _write_atomic(
                os.path.join(self.report_dir, "%s.json" % report_id), report
            )
            report["report_path"] = report_path
        payload = dict(report)
        try:
            return self.registry.register(
                ObjectType.QUALITY_REPORT,
                report_id,
                payload,
                status=status.lower(),
            )
        except ValueError as exc:
            raise QualityError(str(exc)) from exc

    def get(self, report_id: str) -> Optional[DomainObject]:
        obj = self.registry.get(report_id)
        if obj is None or obj.object_type is not ObjectType.QUALITY_REPORT:
            return None
        return obj

    def list(self, task_id: str = "", target_id: str = "") -> List[DomainObject]:
        rows = self.registry.list_by_type(ObjectType.QUALITY_REPORT)
        if task_id:
            rows = [row for row in rows if row.payload.get("task_id") == task_id]
        if target_id:
            rows = [
                row
                for row in rows
                if str((row.payload.get("target") or {}).get("dataset_id") or (row.payload.get("target") or {}).get("deliverable_id") or "") == target_id
            ]
        return rows
