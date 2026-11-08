"""Dataset quality checks: file existence, readability and CRS presence.

``ERROR`` means the check itself could not complete. It is never reported as
``PASS``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class QualityStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"


@dataclass
class CheckResult:
    name: str
    status: QualityStatus
    detail: str

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "status": self.status.value, "detail": self.detail}


@dataclass
class QualityResult:
    status: QualityStatus
    checks: List[CheckResult] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "checks": [check.to_dict() for check in self.checks],
        }


def check_dataset(path: Optional[str], metadata: Optional[Dict[str, Any]] = None) -> QualityResult:
    """Check a dataset path and its CRS metadata. Exceptions become ERROR."""
    checks: List[CheckResult] = []
    try:
        if not os.path.exists(path):
            checks.append(
                CheckResult("file_exists", QualityStatus.FAIL, "path does not exist: %s" % path)
            )
            return QualityResult(QualityStatus.FAIL, checks)
        checks.append(CheckResult("file_exists", QualityStatus.PASS, str(path)))

        if not os.path.isfile(path):
            checks.append(
                CheckResult("file_readable", QualityStatus.FAIL, "path is not a regular file")
            )
            return QualityResult(QualityStatus.FAIL, checks)

        with open(path, "rb") as handle:
            header = handle.read(16)
        checks.append(
            CheckResult("file_readable", QualityStatus.PASS, "%d-byte header read" % len(header))
        )

        crs = ""
        if isinstance(metadata, dict):
            crs = str(metadata.get("crs") or "").strip()
        if crs:
            checks.append(CheckResult("crs_present", QualityStatus.PASS, crs))
        else:
            checks.append(
                CheckResult("crs_present", QualityStatus.FAIL, "CRS field is empty")
            )

        status = (
            QualityStatus.PASS
            if all(check.status is QualityStatus.PASS for check in checks)
            else QualityStatus.FAIL
        )
        return QualityResult(status, checks)
    except Exception as exc:  # the checker itself failed; never report PASS
        checks.append(
            CheckResult("runtime", QualityStatus.ERROR, "%s: %s" % (type(exc).__name__, exc))
        )
        return QualityResult(QualityStatus.ERROR, checks)
