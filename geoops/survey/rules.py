"""Survey rule engine (0.1 module 06).

Rules are data: a JSON pack lists rule definitions with the fields required by
the 0.1 specification (``rule_id``, ``rule_name``, ``domain``, ``task_type``,
``description``, ``condition``, ``validator``, ``severity``,
``failure_action``, ``evidence_requirement``, ``version``, ``enabled``).
Validators are named callables registered on the engine.

Five result states are used and no state is silently upgraded:

* ``PASS``    — the validator ran and returned true.
* ``FAIL``    — the validator ran and returned false, severity ``error``.
* ``WARNING`` — the validator ran and returned false, severity ``warning``.
* ``SKIPPED`` — the rule does not apply because its condition is not met.
* ``ERROR``   — the validator is missing or raised. An exception is never
  reported as ``PASS``, and ``ERROR`` blocks like ``FAIL``.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

REQUIRED_FIELDS = (
    "rule_id",
    "rule_name",
    "domain",
    "task_type",
    "description",
    "condition",
    "validator",
    "severity",
    "failure_action",
    "evidence_requirement",
    "version",
    "enabled",
)

SEVERITIES = ("error", "warning")


class RuleStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    WARNING = "WARNING"
    SKIPPED = "SKIPPED"
    ERROR = "ERROR"


class RuleError(ValueError):
    """Raised for a malformed rule pack. A bad pack is not loaded partially."""


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@dataclass
class RuleDefinition:
    rule_id: str
    rule_name: str
    domain: str
    task_type: str
    description: str
    condition: Dict[str, str]
    validator: str
    severity: str
    failure_action: str
    evidence_requirement: str
    version: str
    enabled: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "domain": self.domain,
            "task_type": self.task_type,
            "description": self.description,
            "condition": dict(self.condition),
            "validator": self.validator,
            "severity": self.severity,
            "failure_action": self.failure_action,
            "evidence_requirement": self.evidence_requirement,
            "version": self.version,
            "enabled": self.enabled,
        }


@dataclass
class RuleResult:
    rule_id: str
    rule_name: str
    status: RuleStatus
    detail: str
    evidence: str = ""
    at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "status": self.status.value,
            "detail": self.detail,
            "evidence": self.evidence,
            "at": self.at or _now(),
        }


def _definition(row: Dict[str, Any]) -> RuleDefinition:
    if not isinstance(row, dict):
        raise RuleError("a rule must be an object, got %r" % (row,))
    missing = [name for name in REQUIRED_FIELDS if name not in row]
    if missing:
        raise RuleError("rule is missing fields: %s" % ", ".join(missing))
    rule_id = str(row["rule_id"] or "").strip()
    if not rule_id:
        raise RuleError("rule_id must not be empty")
    severity = str(row["severity"] or "").strip().lower()
    if severity not in SEVERITIES:
        raise RuleError("rule %s has unknown severity %r" % (rule_id, row["severity"]))
    condition = row["condition"]
    if not isinstance(condition, dict):
        raise RuleError("rule %s condition must be an object" % rule_id)
    if not isinstance(row["enabled"], bool):
        raise RuleError("rule %s enabled must be true or false" % rule_id)
    return RuleDefinition(
        rule_id=rule_id,
        rule_name=str(row["rule_name"] or "").strip(),
        domain=str(row["domain"] or "").strip(),
        task_type=str(row["task_type"] or "").strip(),
        description=str(row["description"] or "").strip(),
        condition={str(key): str(value) for key, value in condition.items()},
        validator=str(row["validator"] or "").strip(),
        severity=severity,
        failure_action=str(row["failure_action"] or "").strip(),
        evidence_requirement=str(row["evidence_requirement"] or "").strip(),
        version=str(row["version"] or "").strip(),
        enabled=bool(row["enabled"]),
    )


# --- built-in validators -------------------------------------------------
# Each returns (ok, detail). Raising is allowed; the engine turns it into ERROR.


def _crs_present(context: Dict[str, Any]) -> Tuple[bool, str]:
    crs = str(context.get("crs") or "").strip()
    return (bool(crs), "crs=%s" % crs if crs else "CRS field is empty")


def _path_exists(context: Dict[str, Any]) -> Tuple[bool, str]:
    path = str(context.get("path") or "").strip()
    if not path:
        return False, "no path supplied"
    if not os.path.exists(path):
        return False, "path does not exist: %s" % path
    if not os.path.isfile(path):
        return False, "path is not a regular file: %s" % path
    return True, "%s (%d bytes)" % (path, os.path.getsize(path))


def _project_linked(context: Dict[str, Any]) -> Tuple[bool, str]:
    project_id = str(context.get("project_id") or "").strip()
    if not project_id:
        return False, "task has no project_id"
    registered = context.get("project_registered")
    if registered is not True:
        return False, "project %s is not registered in the domain registry" % project_id
    return True, "project %s registered" % project_id


def _metadata_source(context: Dict[str, Any]) -> Tuple[bool, str]:
    source = str(context.get("metadata_source") or "").strip()
    if source and source != "none":
        return True, "metadata source: %s" % source
    return False, "no metadata source recorded"


# Geographic (degree) systems that must not be accepted as a product CRS.
GEOGRAPHIC_EPSG = {"4326", "4258", "4269", "4490", "4610"}


def _crs_projected(context: Dict[str, Any]) -> Tuple[bool, str]:
    crs = str(context.get("crs") or "").strip().upper()
    if not crs:
        return False, "crs is empty"
    match = re.fullmatch(r"EPSG:(\d{4,6})", crs)
    if not match:
        return False, "crs %r is not an EPSG code" % crs
    code = match.group(1)
    if code in GEOGRAPHIC_EPSG:
        return False, "EPSG:%s is geographic; a product needs a projected CRS" % code
    return True, "crs=%s (projected)" % crs


def _gsd_recorded(context: Dict[str, Any]) -> Tuple[bool, str]:
    value = context.get("gsd_m")
    if value is None or value == "":
        return False, "gsd_m is missing"
    try:
        gsd = float(value)
    except (TypeError, ValueError):
        return False, "gsd_m is not a number: %r" % (value,)
    if gsd <= 0:
        return False, "gsd_m must be positive, got %r" % (gsd,)
    return True, "gsd_m=%s" % gsd


def _nodata_declared(context: Dict[str, Any]) -> Tuple[bool, str]:
    if "nodata" not in context or context.get("nodata") is None:
        return False, "nodata is not declared"
    return True, "nodata=%r" % (context.get("nodata"),)


def _file_check(path: str) -> Tuple[bool, str]:
    if not path:
        return False, "no path supplied"
    if not os.path.exists(path):
        return False, "path does not exist: %s" % path
    if not os.path.isfile(path):
        return False, "path is not a regular file: %s" % path
    return True, "%s (%d bytes)" % (path, os.path.getsize(path))


def _deliverable_file(context: Dict[str, Any]) -> Tuple[bool, str]:
    return _file_check(str(context.get("deliverable_path") or "").strip())


def _two_inputs(context: Dict[str, Any]) -> Tuple[bool, str]:
    baseline = str(context.get("baseline_path") or "").strip()
    comparison = str(context.get("comparison_path") or "").strip()
    if not baseline or not comparison:
        return False, "both baseline_path and comparison_path are required"
    if os.path.abspath(baseline) == os.path.abspath(comparison):
        return False, "baseline and comparison point at the same file"
    ok_base, why_base = _file_check(baseline)
    if not ok_base:
        return False, "baseline: %s" % why_base
    ok_new, why_new = _file_check(comparison)
    if not ok_new:
        return False, "comparison: %s" % why_new
    return True, "baseline=%s | comparison=%s" % (why_base, why_new)


def _crs_match(context: Dict[str, Any]) -> Tuple[bool, str]:
    baseline = str(context.get("crs_baseline") or "").strip().upper()
    comparison = str(context.get("crs_comparison") or "").strip().upper()
    if not baseline or not comparison:
        return False, "both crs_baseline and crs_comparison are required"
    if baseline != comparison:
        return False, "CRS differ: %s vs %s" % (baseline, comparison)
    return True, "both %s" % baseline


def _change_threshold(context: Dict[str, Any]) -> Tuple[bool, str]:
    value = context.get("min_area_m2")
    if value is None or value == "":
        return False, "min_area_m2 is missing"
    try:
        area = float(value)
    except (TypeError, ValueError):
        return False, "min_area_m2 is not a number: %r" % (value,)
    if area <= 0:
        return False, "min_area_m2 must be positive, got %r" % (area,)
    return True, "min_area_m2=%s" % area


BUILTIN_VALIDATORS: Dict[str, Callable[[Dict[str, Any]], Tuple[bool, str]]] = {
    "crs_present": _crs_present,
    "path_exists": _path_exists,
    "project_linked": _project_linked,
    "metadata_source": _metadata_source,
    "crs_projected": _crs_projected,
    "gsd_recorded": _gsd_recorded,
    "nodata_declared": _nodata_declared,
    "deliverable_file": _deliverable_file,
    "two_inputs": _two_inputs,
    "crs_match": _crs_match,
    "change_threshold": _change_threshold,
}


def _condition_met(rule: RuleDefinition, context: Dict[str, Any]) -> Tuple[bool, str]:
    for key, expected in rule.condition.items():
        value = context.get(key)
        empty = value is None or (isinstance(value, str) and not value.strip())
        if empty:
            return False, "condition not met: %s is missing or empty" % key
        if expected != "*" and str(value) != expected:
            return False, "condition not met: %s=%r, expected %r" % (key, value, expected)
    return True, ""


class SurveyRuleEngine:
    """Load rule packs and evaluate them against a task context."""

    def __init__(self, validators: Optional[Dict[str, Callable]] = None) -> None:
        self._validators: Dict[str, Callable] = dict(BUILTIN_VALIDATORS)
        if validators:
            self._validators.update(validators)
        self._rules: List[RuleDefinition] = []

    # -- registration -----------------------------------------------------
    def register(self, name: str, validator: Callable) -> None:
        if not callable(validator):
            raise RuleError("validator %r is not callable" % name)
        self._validators[str(name)] = validator

    def load_pack(self, path: str) -> List[RuleDefinition]:
        with open(path, encoding="utf-8-sig") as handle:
            data = json.load(handle)
        if not isinstance(data, dict) or not isinstance(data.get("rules"), list):
            raise RuleError("pack %s has no rules list" % path)
        return self.load_dicts(data["rules"])

    def load_dicts(self, rows: Iterable[Dict[str, Any]]) -> List[RuleDefinition]:
        parsed = [_definition(row) for row in rows]
        seen = set()
        duplicates = []
        for rule in parsed:
            if rule.rule_id in seen:
                duplicates.append(rule.rule_id)
            seen.add(rule.rule_id)
        if duplicates:
            raise RuleError("duplicate rule_id: %s" % ", ".join(sorted(set(duplicates))))
        existing = {rule.rule_id for rule in self._rules}
        clash = sorted(existing.intersection(seen))
        if clash:
            raise RuleError("rule_id already loaded: %s" % ", ".join(clash))
        self._rules.extend(parsed)
        return parsed

    # -- inspection -------------------------------------------------------
    def rules(self) -> List[RuleDefinition]:
        return list(self._rules)

    def enabled_rules(self, task_type: str) -> List[RuleDefinition]:
        return [
            rule
            for rule in self._rules
            if rule.enabled and rule.task_type in (task_type, "*")
        ]

    # -- evaluation -------------------------------------------------------
    def evaluate(self, task_type: str, context: Optional[Dict[str, Any]] = None) -> List[RuleResult]:
        ctx = {} if context is None else context
        results: List[RuleResult] = []
        for rule in self.enabled_rules(task_type):
            met, why = _condition_met(rule, ctx)
            if not met:
                results.append(
                    RuleResult(rule.rule_id, rule.rule_name, RuleStatus.SKIPPED, why, "", _now())
                )
                continue
            validator = self._validators.get(rule.validator)
            if validator is None:
                results.append(
                    RuleResult(
                        rule.rule_id,
                        rule.rule_name,
                        RuleStatus.ERROR,
                        "validator not registered: %s" % rule.validator,
                        rule.evidence_requirement,
                        _now(),
                    )
                )
                continue
            try:
                outcome = validator(ctx)
            except Exception as exc:
                results.append(
                    RuleResult(
                        rule.rule_id,
                        rule.rule_name,
                        RuleStatus.ERROR,
                        "%s: %s" % (type(exc).__name__, exc),
                        rule.evidence_requirement,
                        _now(),
                    )
                )
                continue
            ok, detail = self._normalize(outcome)
            if ok:
                status = RuleStatus.PASS
            elif rule.severity == "warning":
                status = RuleStatus.WARNING
            else:
                status = RuleStatus.FAIL
            evidence = rule.evidence_requirement
            if detail:
                evidence = "%s | %s" % (evidence, detail) if evidence else detail
            results.append(
                RuleResult(rule.rule_id, rule.rule_name, status, detail, evidence, _now())
            )
        return results

    @staticmethod
    def _normalize(outcome: Any) -> Tuple[bool, str]:
        if isinstance(outcome, bool):
            return outcome, ""
        if isinstance(outcome, tuple) and len(outcome) >= 2:
            return bool(outcome[0]), str(outcome[1])
        if isinstance(outcome, dict) and "ok" in outcome:
            return bool(outcome.get("ok")), str(outcome.get("detail") or "")
        raise RuleError("validator returned an unsupported value: %r" % (outcome,))

    @staticmethod
    def summary(results: Iterable[RuleResult]) -> Dict[str, Any]:
        counts = {status.value: 0 for status in RuleStatus}
        for result in results:
            counts[result.status.value] += 1
        counts["total"] = sum(1 for _ in results)
        counts["blocking"] = counts[RuleStatus.FAIL.value] + counts[RuleStatus.ERROR.value]
        return counts

    @staticmethod
    def blocking(results: Iterable[RuleResult]) -> List[RuleResult]:
        return [
            result
            for result in results
            if result.status in (RuleStatus.FAIL, RuleStatus.ERROR)
        ]
