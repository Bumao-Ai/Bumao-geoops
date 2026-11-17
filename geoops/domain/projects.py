"""Project registration with the metadata the 0.1 specification requires.

A project is registered only when its code, type, area, CRS and vertical datum
are all present. A missing field is refused instead of being filled with a
guess. The code is unique across projects: two records may not claim the same
project number.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from geoops.domain.registry import DomainObject, DomainRegistry, ObjectType

REQUIRED_FIELDS = ("project_code", "name", "project_type", "area", "crs", "vertical_datum")
OPTIONAL_FIELDS = ("description", "client", "contact", "created_by")


class ProjectError(ValueError):
    """A project record was refused; nothing was written."""


class ProjectRegistry:
    def __init__(self, registry: DomainRegistry) -> None:
        self.registry = registry

    def register(
        self,
        project_id: str,
        project_code: str,
        name: str,
        project_type: str,
        area: str,
        crs: str,
        vertical_datum: str,
        **extra: Any
    ) -> DomainObject:
        values = {
            "project_code": project_code,
            "name": name,
            "project_type": project_type,
            "area": area,
            "crs": crs,
            "vertical_datum": vertical_datum,
        }
        missing = [key for key, value in values.items() if not str(value or "").strip()]
        if missing:
            raise ProjectError("missing required project fields: %s" % ", ".join(missing))
        code = str(project_code).strip()
        for existing in self.list():
            if str(existing.payload.get("project_code") or "") == code:
                raise ProjectError("duplicate project_code: %s" % code)
        payload: Dict[str, Any] = {key: str(value).strip() for key, value in values.items()}
        for key in OPTIONAL_FIELDS:
            if extra.get(key):
                payload[key] = str(extra[key]).strip()
        try:
            return self.registry.register(
                ObjectType.PROJECT, str(project_id or "").strip(), payload
            )
        except ValueError as exc:
            raise ProjectError(str(exc)) from exc

    def get(self, project_id: str) -> Optional[DomainObject]:
        obj = self.registry.get(project_id)
        if obj is None or obj.object_type is not ObjectType.PROJECT:
            return None
        return obj

    def list(self) -> List[DomainObject]:
        return self.registry.list_by_type(ObjectType.PROJECT)
