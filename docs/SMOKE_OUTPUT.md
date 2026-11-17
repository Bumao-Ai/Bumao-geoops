# Smoke output

This is the real output of `python -m geoops.smoke` from the local no-data run
on 2026-11-17 (Python 3.12.4). Absolute local paths are shortened to
`<project>`; all verdicts and values are unchanged. The run uses the vendored
kernel at `kernel/bumao_core/`.

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
get PRJ-SMOKE-001 -> {"object_id": "PRJ-SMOKE-001", "object_type": "Project", "version": 1, "status": "registered", "created_at": "2026-11-17T13:56:09Z", "payload": {"name": "structural smoke project"}}
get TSK-SMOKE-001 -> {"object_id": "TSK-SMOKE-001", "object_type": "SurveyTask", "version": 1, "status": "registered", "created_at": "2026-11-17T13:56:09Z", "payload": {"project_id": "PRJ-SMOKE-001"}}
duplicate id -> rejected=True :: duplicate object_id: PRJ-SMOKE-001

== 2b. survey task engine ==
create -> {"task_id": "TSK-e9aba63874", "project_id": "PRJ-SMOKE-001", "name": "structural smoke task", "task_type": "land_use_classification", "status": "DRAFT", "version": 1, "created_at": "2026-11-17T13:56:09Z", "updated_at": "2026-11-17T13:56:09Z", "workflow_run_ids": [], "history": [{"event": "created", "from": "", "to": "DRAFT", "at": "2026-11-17T13:56:09Z", "reason": "task created", "actor": "smoke"}]}
DRAFT -> COMPLETED -> rejected=True :: transition DRAFT -> COMPLETED is not allowed; allowed from DRAFT: CANCELLED, READY
final -> status=COMPLETED version=6 transitions=5
COMPLETED -> RUNNING -> rejected=True
attach run on COMPLETED -> refused=True
unknown task -> rejected=True

== 3. dataset intake ==
register(None) -> status=SKIP crs='' reason=no path supplied
register(missing) -> status=SKIP relative_path=data\absent.tif reason=path does not exist: <project>\data\absent.tif

== 4. workflow (structural run) ==
  N1      SKIP dataset intake :: no path supplied
  N2      SKIP quality check :: no dataset registered
  N3      PASS quality report :: QR-SMOKE-001 recorded
run RUN-SMOKE-001 -> status=PASS skipped=2

== 4b. task / run linkage ==
task TSK-d7a27d1dab -> runs=['RUN-SMOKE-001'] duplicate_rejected=True status=COMPLETED

== 5. workflow (failure stop) ==
  F1      PASS project registration :: project recorded
  F2      FAIL missing dataset check :: {"status": "FAIL", "checks": [{"name": "file_exists", "status": "FAIL", "detail": "path does not exist: <repo>\\data\\absent.tif"}]}
  F3      SKIPPED deliverable :: upstream node failed
run RUN-SMOKE-002 -> status=FAIL skipped=1

== 5b. workflow resume ==
  F1      REUSED project registration :: reused from RUN-SMOKE-002
  F2      PASS  missing dataset check :: dataset present after intake fix
  F3      PASS  deliverable :: deliverable registered
run RUN-SMOKE-003 -> status=PASS resumed_from=RUN-SMOKE-002
resume refused (run already passed / shape changed) -> 2/2

== 5c. task follows the retry ==
task TSK-7b85773b46 -> status=COMPLETED runs=['RUN-SMOKE-002', 'RUN-SMOKE-003']

== 6. quality checker ==
README without CRS -> {"status": "FAIL", "checks": [{"name": "file_exists", "status": "PASS", "detail": "<repo>\\README.md"}, {"name": "file_readable", "status": "PASS", "detail": "16-byte header read"}, {"name": "crs_present", "status": "FAIL", "detail": "CRS field is empty"}]}
path=None -> {"status": "ERROR", "checks": [{"name": "runtime", "status": "ERROR", "detail": "TypeError: _path_exists: path should be string, bytes, os.PathLike or integer, not NoneType"}]}

== 7. api ==
GET /api/v1/health -> 200 {"status": "ok", "objects": 8, "writes": "enabled", "context": {"registered_gates": ["B1", "B2", "B3", "B4"]}}
GET /api/v1/objects/PRJ-SMOKE-001 -> 200 {"object_id": "PRJ-SMOKE-001", "object_type": "Project", "version": 1, "status": "registered", "created_at": "2026-11-17T13:56:09Z", "payload": {"name": "structural smoke project"}}
GET /api/v1/objects/PRJ-NOT-FOUND -> 404 {"error": "object not found", "object_id": "PRJ-NOT-FOUND"}
GET /api/v1/objects/TSK-d7a27d1dab -> 200 {"object_id": "TSK-d7a27d1dab", "object_type": "SurveyTask", "version": 5, "status": "COMPLETED", "created_at": "2026-11-17T13:56:09Z", "payload": {"task_id": "TSK-d7a27d1dab", "project_id": "PRJ-SMOKE-001", "name": "smoke run link task", "task_type": "land_use_classification", "status": "COMPLETED", "version": 5, "created_at": "2026-11-17T13:56:09Z", "updated_at": "2026-11-17T13:56:09Z", "workflow_run_ids": ["RUN-SMOKE-001"], "history": [{"event": "created", "from": "", "to": "DRAFT", "at": "2026-11-17T13:56:09Z", "reason": "task created", "actor": ""}, {"event": "transition", "from": "DRAFT", "to": "READY", "at": "2026-11-17T13:56:09Z", "reason": "preconditions listed", "actor": ""}, {"event": "transition", "from": "READY", "to": "RUNNING", "at": "2026-11-17T13:56:09Z", "reason": "workflow running", "actor": ""}, {"event": "run_attached", "from": "RUNNING", "to": "RUNNING", "at": "2026-11-17T13:56:09Z", "reason": "workflow run attached", "actor": ""}, {"event": "transition", "from": "RUNNING", "to": "COMPLETED", "at": "2026-11-17T13:56:09Z", "reason": "run recorded", "actor": ""}]}}
GET /api/v1/tasks -> 200 count=3

== 7b. write api with permission gate ==
POST task without token -> 401 {"error": "missing token"}
POST task with admin token -> 201 task=TSK-ec3f53563c status=DRAFT
  transition -> READY : 200
  transition -> RUNNING : 200
  transition -> COMPLETED : 200
task TSK-ec3f53563c over http -> status=COMPLETED
viewer token transition -> 403 {"error": "permission task:transition required"}
GET /api/v1/audit without token -> 401

== 8. survey rules ==
pack p01_dataset -> 4 rules ['R-DS-001', 'R-DS-002', 'R-DS-003', 'R-TASK-001']
  R-DS-001   PASS    数据集必须声明坐标参考系 :: crs=EPSG:4490
  R-DS-002   PASS    数据集文件必须存在且为常规文件 :: <project>\README.md (5162 bytes)
  R-DS-003   PASS    元数据来源必须可追溯 :: metadata source: sidecar:README.md.json
  R-TASK-001 PASS    任务必须关联已登记项目 :: project PRJ-SMOKE-001 registered
summary -> {"PASS": 4, "FAIL": 0, "WARNING": 0, "SKIPPED": 0, "ERROR": 0, "total": 4, "blocking": 0}
  R-DS-001   FAIL    数据集必须声明坐标参考系 :: CRS field is empty
  R-DS-002   PASS    数据集文件必须存在且为常规文件 :: <project>\README.md (5162 bytes)
  R-DS-003   WARNING 元数据来源必须可追溯 :: no metadata source recorded
  R-TASK-001 PASS    任务必须关联已登记项目 :: project PRJ-SMOKE-001 registered
summary -> {"PASS": 2, "FAIL": 1, "WARNING": 1, "SKIPPED": 0, "ERROR": 0, "total": 4, "blocking": 1}
unregistered project -> {"PASS": 3, "FAIL": 1, "WARNING": 0, "SKIPPED": 0, "ERROR": 0, "total": 4, "blocking": 1}
task type without rules -> total=0

== 8b. rule gate node ==
  R1   FAIL    rule gate :: blocking rules: R-DS-001(FAIL)
  R2   SKIPPED deliverable :: upstream node failed
run RUN-SMOKE-006 -> status=FAIL
  R1   PASS    rule gate :: checked=4 pass=4 warning=0 skipped=0 error=0
  R2   PASS    deliverable :: deliverable registered
run RUN-SMOKE-007 -> status=PASS
warning-only run RUN-SMOKE-008 -> status=PASS stored=['PASS', 'PASS', 'WARNING', 'PASS']
no-rule task run RUN-SMOKE-009 -> node=SKIP detail=no rule applies to task_type 'map_compilation'; nothing was checked

== 9. snapshot persistence ==
saved -> objects=10 tasks=4 file=<tmp>/geoops-smoke-x2mlaizn\state.json
restored -> {"objects": 10, "tasks": 4}
restored task TSK-7b85773b46 -> status=COMPLETED version=8 runs=['RUN-SMOKE-002', 'RUN-SMOKE-003']
corrupt snapshot -> rejected=True
older snapshot version -> refused :: snapshot version 0 is older than 1; no migration path is implemented

== 10. execution report ==
report -> task=TSK-7b85773b46 runs=2 rules={'PASS': 3, 'WARNING': 1} quality=FAIL review=NOT_RECORDED artifacts=1
report files -> <tmp>/geoops-smoke-x2mlaizn\report.json | <tmp>/geoops-smoke-x2mlaizn\report.md

== 11. token file and audit file ==
token file -> grants=1 admin_ok=True unknown_ok=False
audit file -> rows=2 denied=1 first_fp=0ba28528
corrupt audit line -> rejected=True

== 12. deliverable registry ==
registered -> id=ART-5647b1a6fc30 size=49 sha=5647b1a6fc30
bound artifact -> id=ART-33c6e1c4f8e4 deliverable=DLV-SMOKE-002 files=1
unregistered deliverable -> refused :: deliverable not registered: DLV-NOT-REGISTERED
verify before edit -> ok=True
verify after edit -> ok=False detail=artifact content changed since registration: ortho_result.tif

== 13. token expiry and rotation ==
expired token -> known=False allowed=False reason=token expired
rotated token -> old_known=False new_perms=['task:create', 'task:transition']

== 14. product rules (ortho / change detection) ==
pack p02_products -> total=7 ortho=4 change=3
ortho PASS context -> {"PASS": 4, "FAIL": 0, "WARNING": 0, "SKIPPED": 0, "ERROR": 0, "total": 4, "blocking": 0}
ortho geographic CRS -> blocking=['R-OR-001']
change detection CRS mismatch -> blocking=['R-CD-002']

== 15. rule gate then registration, one run ==
  O1   PASS    ortho rules :: checked=4 pass=4 warning=0 skipped=0 error=0
  O2   PASS    register product :: registered ART-903941e5ddc9 (42 bytes) sha256=903941e5ddc9
run RUN-SMOKE-010 -> status=PASS artifacts=1
bad CRS run -> status=FAIL register_node=SKIPPED artifacts=0
run report -> rules={'PASS': 4} artifacts=1

== 16. change detection end to end ==
  C1   PASS    change rules :: checked=3 pass=3 warning=0 skipped=0 error=0
  C2   PASS    change detect :: changed=3 kept=2 dropped=1 patches=1 area=200.00 m2 nodata=1 mask=change_mask.asc
  C3   PASS    register change mask :: registered ART-1e6b131621d8 (142 bytes) sha256=1e6b131621d8
change run RUN-SMOKE-012 -> status=PASS changed=3 kept=2 dropped=1 patches=1 area=200.0 artifacts=1
mask -> ones=2 nodata_cells=1 cellsize=10.0
registered mask -> 1e6b1316 sha_match=True
unaligned grids -> status=FAIL :: grids are not aligned: xllcorner differs (500000.0 vs 500010.0)

== 17. console shell ==
console -> status=200 nav=9 overview objects=10 tasks=4 rules=7 artifacts=2 runs=1

assertions:
  PASS core surface complete
  PASS all host gates pass
  PASS duplicate id rejected
  PASS task created in DRAFT
  PASS illegal task transition rejected
  PASS legal task path recorded
  PASS terminal task rejects transitions
  PASS run attaches only while running
  PASS unknown task rejected
  PASS missing dataset returns SKIP
  PASS dataset intake did not crash
  PASS structural run completes with PASS
  PASS run attached once to task
  PASS failed node stops later nodes
  PASS resume reuses passed node and completes
  PASS resume rejects a passed run and a changed shape
  PASS task records the failed run and the retry
  PASS missing CRS fails
  PASS checker exception is ERROR
  PASS health endpoint returns 200
  PASS object endpoint returns 200
  PASS missing object returns 404
  PASS task object served over api
  PASS task list endpoint returns tasks
  PASS write without token is refused and audited
  PASS admin token creates a task
  PASS http transitions reach COMPLETED
  PASS viewer token cannot transition
  PASS audit endpoint needs its own token
  PASS rule pack loads four rules
  PASS complete context passes all rules
  PASS missing CRS fails and missing sidecar warns
  PASS unregistered project blocks
  PASS rules are scoped by task type
  PASS blocking rule stops the deliverable
  PASS fixed context passes the gate and reaches the deliverable
  PASS warning-only gate passes with the warning recorded
  PASS gate with no applicable rule records SKIP
  PASS snapshot restores every object and task
  PASS task status, version and runs survive a restart
  PASS corrupt snapshot is rejected
  PASS an older snapshot version is refused, not guessed
  PASS report round-trips through json
  PASS markdown report names the task and the unrecorded review
  PASS token file grants the real token and no other
  PASS audit rows survive a reload without the raw token
  PASS corrupt audit file is refused, not trimmed
  PASS registered size and hash match the file
  PASS registering the same file twice returns the same row
  PASS artifact binds to a registered deliverable
  PASS a file cannot bind to an unregistered deliverable
  PASS verify passes on an untouched file
  PASS an edited file no longer verifies
  PASS artifact index reloads with the same count
  PASS report carries the registered deliverable file
  PASS an expired token is refused with its own reason
  PASS rotation drops the old token and keeps its permissions
  PASS rotation can narrow the permissions
  PASS product pack loads and is scoped 4 + 3
  PASS a complete ortho context passes all four rules
  PASS a geographic CRS blocks the ortho product
  PASS mismatched CRSs block change detection
  PASS one run passes the ortho rules and registers the hash
  PASS a geographic CRS stops the run before registration
  PASS the report carries both the rule verdicts and the file hash
  PASS one run gates, compares, writes and registers the change mask
  PASS the written mask carries exactly the kept cells and the nodata hole
  PASS the registered hash is the hash of the file that was written
  PASS unaligned grids fail before a mask is written
  PASS the console shell is served with its nine sections
  PASS the console overview counts match the live registry
  PASS the run journal serves the real change run
  PASS the journal refuses a duplicate run_id

SMOKE PASS: 73 assertions
```
