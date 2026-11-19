"""Survey areas: the spatial extent a task or project works inside.

A survey area is registered against a real project and a declared CRS. Bounds
are optional, but when they are supplied they must be four finite numbers in
``minx, miny, maxx, maxy`` order with a positive extent. Nothing is guessed:
missing project, missing CRS or malformed bounds are refusals.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence

from geoops.domain.projects import ProjectRegistry
from geoops.domain.registry import DomainObject, DomainRegistry, ObjectType

REQUIRED_FIELDS = ("project_id", "name", "area_type", "crs")


class SurveyAreaError(ValueError):
    """A survey area was refused; nothing was written."""


def _parse_bounds(raw: Any) -> List[float]:
    if raw is None:
        return []
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise SurveyAreaError("bounds must be a list of four numbers")
    if len(raw) != 4:
        raise SurveyAreaError("bounds must contain exactly four numbers")
    values: List[float] = []
    for item in raw:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise SurveyAreaError("bounds must contain only numbers")
        value = float(item)
        if not math.isfinite(value):
            raise SurveyAreaError("bounds must contain finite numbers")
        values.append(value)
    minx, miny, maxx, maxy = values
    if minx >= maxx or miny >= maxy:
        raise SurveyAreaError("bounds must be minx, miny, maxx, maxy with positive extent")
    return values


class SurveyAreaRegistry:
    def __init__(self, registry: DomainRegistry, projects: Optional[ProjectRegistry] = None) -> None:
        self.registry = registry
        self.projects = projects

    def register(
        self,
        area_id: str,
        project_id: str,
        name: str,
        area_type: str,
        crs: str,
        bounds: Optional[Sequence[float]] = None,
        description: str = "",
        task_id: str = "",
    ) -> DomainObject:
        values = {
            "project_id": project_id,
            "name": name,
            "area_type": area_type,
            "crs": crs,
        }
        missing = [key for key, value in values.items() if not str(value or "").strip()]
        if missing:
            raise SurveyAreaError("missing required survey area fields: %s" % ", ".join(missing))
        if self.projects is not None and self.projects.get(str(project_id).strip()) is None:
            raise SurveyAreaError("unknown project_id: %s" % project_id)
        payload: Dict[str, Any] = {key: str(value).strip() for key, value in values.items()}
        parsed = _parse_bounds(bounds)
        if parsed:
            payload["bounds"] = parsed
        if str(description or "").strip():
            payload["description"] = str(description).strip()
        if str(task_id or "").strip():
            payload["task_id"] = str(task_id).strip()
        try:
            return self.registry.register(
                ObjectType.SURVEY_AREA, str(area_id or "").strip(), payload
            )
        except ValueError as exc:
            raise SurveyAreaError(str(exc)) from exc

    def get(self, area_id: str) -> Optional[DomainObject]:
        obj = self.registry.get(area_id)
        if obj is None or obj.object_type is not ObjectType.SURVEY_AREA:
            return None
        return obj

    def list(self, project_id: str = "") -> List[DomainObject]:
        rows = self.registry.list_by_type(ObjectType.SURVEY_AREA)
        if project_id:
            rows = [row for row in rows if row.payload.get("project_id") == project_id]
        return rows
