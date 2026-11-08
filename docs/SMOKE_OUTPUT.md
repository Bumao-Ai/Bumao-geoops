# Smoke output

This is the real output of `python -m geoops.smoke` from the local no-data run.
Absolute local paths are shortened to `<project>`; all
verdicts and values are unchanged. The run uses the vendored kernel at
`kernel/bumao_core/`.

```text
== 1. core adapter ==
kernel dir : <project>\kernel\bumao_core
engine     : <project>\kernel\bumao_core\engine.py
registry   : <project>\kernel\bumao_core\gate_registry.py
templates  : <project>\kernel\bumao_core\bumao_core_gates.py
core surface: configure=True register=True set_expected=True verify_registration=True main=True cmd_check=True cmd_whoami=True
expected gates : ['B1', 'B2', 'B3', 'B4']
registered     : ['B1', 'B2', 'B3', 'B4']
[Bumao GeoOps]: OK -- 4/4 gates confirmed via gate_registry
verify_registration -> True
  PASS B1
  PASS B2
  PASS B3
  PASS B4

== 2. domain registry ==
objects registered : 2
get PRJ-SMOKE-001 -> {"object_id": "PRJ-SMOKE-001", "object_type": "Project", "version": 1, "status": "registered", "created_at": "2026-11-08T14:18:20Z", "payload": {"name": "structural smoke project"}}
get TSK-SMOKE-001 -> {"object_id": "TSK-SMOKE-001", "object_type": "SurveyTask", "version": 1, "status": "registered", "created_at": "2026-11-08T14:18:20Z", "payload": {"project_id": "PRJ-SMOKE-001"}}
duplicate id -> rejected=True :: duplicate object_id: PRJ-SMOKE-001

== 3. dataset intake ==
register(None) -> status=SKIP crs='' reason=no path supplied
register(missing) -> status=SKIP relative_path=data\absent.tif reason=path does not exist: <project>\data\absent.tif

== 4. workflow (structural run) ==
  N1      SKIP dataset intake :: no path supplied
  N2      SKIP quality check :: no dataset registered
  N3      PASS quality report :: QR-SMOKE-001 recorded
run RUN-SMOKE-001 -> status=PASS skipped=2

== 5. workflow (failure stop) ==
  F1      PASS project registration :: project recorded
  F2      FAIL missing dataset check :: {"status": "FAIL", "checks": [{"name": "file_exists", "status": "FAIL", "detail": "path does not exist: <project>\\data\\absent.tif"}]}
  F3      SKIPPED deliverable :: upstream node failed
run RUN-SMOKE-002 -> status=FAIL skipped=1

== 6. quality checker ==
README without CRS -> {"status": "FAIL", "checks": [{"name": "file_exists", "status": "PASS", "detail": "<project>\\README.md"}, {"name": "file_readable", "status": "PASS", "detail": "16-byte header read"}, {"name": "crs_present", "status": "FAIL", "detail": "CRS field is empty"}]}
path=None -> {"status": "ERROR", "checks": [{"name": "runtime", "status": "ERROR", "detail": "TypeError: _path_exists: path should be string, bytes, os.PathLike or integer, not NoneType"}]}

== 7. api ==
GET /api/v1/health -> 200 {"status": "ok", "objects": 4, "context": {"registered_gates": ["B1", "B2", "B3", "B4"]}}
GET /api/v1/objects/PRJ-SMOKE-001 -> 200 {"object_id": "PRJ-SMOKE-001", "object_type": "Project", "version": 1, "status": "registered", "created_at": "2026-11-08T14:18:20Z", "payload": {"name": "structural smoke project"}}
GET /api/v1/objects/PRJ-NOT-FOUND -> 404 {"error": "object not found", "object_id": "PRJ-NOT-FOUND"}

assertions:
  PASS core surface complete
  PASS all host gates pass
  PASS duplicate id rejected
  PASS missing dataset returns SKIP
  PASS dataset intake did not crash
  PASS structural run completes with PASS
  PASS failed node stops later nodes
  PASS missing CRS fails
  PASS checker exception is ERROR
  PASS health endpoint returns 200
  PASS object endpoint returns 200
  PASS missing object returns 404

SMOKE PASS: 12 assertions
```
