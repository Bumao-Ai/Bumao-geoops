# Architecture (current state)

This page describes the scaffold as it exists today. It does not describe
planned work.

## Layers

```text
User interaction / API
  GET /api/v1/health
  GET /api/v1/objects/{object_id}
  GET /api/v1/tasks              read-only task list (when an engine is supplied)
  GET /api/v1/audit              audit trail (when a policy is supplied)
  POST /api/v1/tasks             create a task (permission: task:create)
  POST /api/v1/tasks/{id}/transitions
                                 move a task (permission: task:transition)

AI and tool integration
  ai.runtime               OpenAI-compatible chat-completions client; env-configured,
                           NOT_CONFIGURED when no endpoint/model is supplied
  ai.nodes                 workflow node that makes a real model call and never fakes a reply
  catalog                  model / tool / agent records with checked availability
  GIS tool adapters        not implemented (no GDAL/QGIS/Rasterio on this host)

GeoOps domain core
  domain.registry          typed object registration and lookup
  domain.tasks             survey task lifecycle, separate from workflow runs
  domain.datasets          dataset intake and metadata probe
  workflow                 sequential node execution, resume from a failed node
  quality                  dataset checks and the execution report
  survey                   rule packs, the five-state rule engine and the rule gate node
  store                    atomic JSON snapshot of the in-memory state

Bumao Core (vendored, read-only)
  kernel/bumao_core/engine.py
  kernel/bumao_core/gate_registry.py
  kernel/bumao_core/bumao_core_gates.py
```

## What is implemented

| Entry | Real behavior |
|---|---|
| `geoops/core_adapter` | Loads the vendored kernel from `kernel/bumao_core/`, registers four host gates built from Core templates, and calls `configure`, `register`, `set_expected`, `verify_registration`, `GateRegistry.validate` and `GateRegistry.run_all`. |
| `geoops/domain/registry.py` | Thirteen domain object types, `register`, `get`, `list_by_type`, `update` (in-place payload patch, `version += 1`, unknown id refused), duplicate-id rejection. In-memory only. |
| `geoops/domain/tasks.py` | `TaskEngine` owns the task state machine: `DRAFT → READY → RUNNING ⇄ PAUSED → COMPLETED`, with `FAILED` for retry and `CANCELLED` from any non-terminal state. An edge not listed in `ALLOWED` is rejected with a readable reason and leaves the task untouched. A run attaches only while `RUNNING` and only once. The task record is mirrored into the registry so the API can serve it. |
| `geoops/domain/datasets.py` | `datasets.register(path)` reports file existence, size, SHA-256, CRS and, for a classic GeoTIFF, width/height/bands/bounds/pixel size from the header. Missing input returns `SKIP`; unreadable input returns `ERROR`; no CRS is `INCOMPLETE`; the call does not raise. |
| `geoops/domain/projects.py` | `ProjectRegistry.register` requires `project_code / name / project_type / area / crs / vertical_datum`, refuses a blank field, a duplicate id or a duplicate `project_code`. |
| `geoops/domain/datasets_store.py` | `DatasetRegistry` refuses a dataset whose probe is not READY or whose project is unknown, stores the real hash/CRS/metadata, and `validate()` re-probes the file: content change, missing CRS or a probe failure is FAIL/ERROR, never PASS. |
| `geoops/geotiff.py` | Header-only classic-TIFF reader for `ModelPixelScale`, `ModelTiepoint` and `GeoKeyDirectory`. Returns EPSG, size, band count, bounds and pixel size without GDAL; BigTIFF, out-of-line tags beyond the file and pixel decoding are refused or out of scope. |
| `geoops/ai/runtime.py` | OpenAI-compatible `POST /chat/completions` client configured from `GEOOPS_MODEL_BASE_URL` / `GEOOPS_MODEL_API_KEY` / `GEOOPS_MODEL_NAME`. Missing configuration raises `NOT_CONFIGURED`; provider HTTP errors, non-JSON replies, empty content and unreachable endpoints fail explicitly. The key is never returned by `status()` or audit output. |
| `geoops/ai/nodes.py` | `model_chat_node` calls the runtime inside a workflow and records text, model, usage and latency. Without a configured endpoint the node ends `ERROR`, never `PASS` with placeholder content. |
| `geoops/catalog.py` | Model / Tool / Agent records with checked availability: `builtin:` must be an implemented adapter, `external:` must exist on disk, an agent with unknown dependencies is refused and inherits dependency availability. |
| `geoops/review.py` | `ReviewEngine.submit` writes a ReviewRecord and moves the deliverable: only `APPROVE` sets `accepted`, `REJECT`/`RERUN` need an opinion, an already accepted deliverable refuses further review. |
| `geoops/trace.py` | `build_trace` assembles project → datasets → runs → rule nodes → deliverables → artifacts → reviews, links them, and lists absent links as `NOT_RECORDED` with reasons and `complete=false`. |
| `geoops/workflow/executor.py` | Runs nodes in order, records `PASS` / `FAIL` / `ERROR` / `SKIP` / `SKIPPED` / `REUSED`, stops on `FAIL` or `ERROR`, continues on `SKIP`. `resume(nodes, previous)` restarts at the failed node, carries already-passed nodes forward as `REUSED` with their outputs placed in `context["node_outputs"]`, and refuses to run when the node list no longer matches the previous run. `WorkflowEngine` keeps run history and rejects duplicate run ids. |
| `geoops/workflow/journal.py` | `RunJournal` appends each finished run as one JSON line (with task / project / actor and timestamp) and `fsync`s before returning. A duplicate `run_id` is refused; a corrupt or truncated line makes the whole file fail to load instead of silently dropping rows. Optional file backing; without a path the journal is in-memory. |
| `geoops/quality/checker.py` | Checks file existence, readability and non-empty CRS. Returns `PASS` / `FAIL` / `ERROR`; an exception is never reported as `PASS`. |
| `geoops/survey/rules.py` | `SurveyRuleEngine` loads JSON rule packs and evaluates them into five states: `PASS`, `FAIL`, `WARNING`, `SKIPPED`, `ERROR`. A rule whose condition is not met is `SKIPPED`; a missing validator or a validator exception is `ERROR`. Neither is ever upgraded to `PASS`. `FAIL` and `ERROR` both block. |
| `geoops/survey/packs/p01_dataset.json` | Four dataset-intake rules for the 0.1 scenario: CRS declared, file exists, metadata source traceable (warning), task linked to a registered project. Conditions are applicability filters only, so the field being judged is never its own precondition. |
| `geoops/survey/nodes.py` | `rule_check_node(...)` turns the rule engine into a workflow node. Blocking rules (`FAIL` or `ERROR`) fail the node, so later nodes stop; `ERROR` keeps node status `ERROR` instead of being flattened to `FAIL`. `WARNING` / `SKIPPED` pass through but every result is written to `context["rule_results"][node_id]`. A task type with no applicable rule is recorded as `SKIP`, never `PASS`. |
| `geoops/api/app.py` | Read endpoints (health, overview counts, object-by-id, task list, run journal, projects, datasets and dataset `validate`, catalog, deliverables, quality reports, model-runtime status, settings, reviews, task trace, rule pack metadata, artifact index under `audit:read`, audit) and write endpoints (create/transition task, register project, register dataset, register catalog object, register deliverable and archive it, generate a quality report, submit review, probe/chat with the configured model under `model:invoke`). Writes are refused before the body is read: missing or unknown token 401, missing permission 403, body over 64 KB 413, invalid JSON 400. The API has no built-in accounts. |
| `geoops/api/__main__.py` | `python -m geoops.api` starts the API and the console on one port. `--demo` registers one real project and three tasks through the domain API; `--tokens`, `--audit` and `--artifacts` point at real files. Without `--tokens` the server is read-only. |
| `geoops/web/index.html`, `ui.css`, `ui.js` | The console shell, served from a whitelist at `/ui/`. HX 书香 v2.0 palette (paper, ink, celadon, cinnabar, Dai blue, ochre, gold), Dai-blue spine, paper cards and gold hairlines. Twelve sections: 总览 / 项目 / 任务 / AI 资源 / 数据 / 流程 / 规则 / 质量 / 成果 / 审核 / 追溯 / 设置. Every panel renders endpoint data; a missing endpoint, a missing token and an empty list each have their own empty state, and nothing is filled in with sample numbers. The AI resources page shows the real model-runtime state and can send a live probe/prompt; without an endpoint it shows `NOT_CONFIGURED` and no reply. Theme, palette and zoom persist in `localStorage`; the token lives only in `sessionStorage`. |
| `geoops/api/security.py` | `PermissionPolicy` stores only sha256 hashes of tokens (grant by token or by hash, load from a `geoops-tokens` JSON file that refuses raw-token entries and duplicate hashes) and maps them to `task:create` / `task:transition` / `project:write` / `dataset:write` / `catalog:write` / `review:write` / `audit:read`. `AuditLog` records every allow and deny with a token fingerprint (sha256 prefix, never the raw token), appends each row to a JSONL file with `fsync`, and refuses to load a corrupt file instead of dropping rows. |
| `geoops/store.py` | `SnapshotStore` writes the registry and task engine to one JSON file atomically: a uniquely named temp file beside the target, `fsync`, then a replace that retries while a reader still holds the target open (Windows refuses the swap with WinError 5 until the handle closes). Saves are serialised inside the process. `load` refuses an older version ("no migration path is implemented") and a newer one instead of guessing. Restores validate the whole file on empty probe objects first, so a corrupt or clashing snapshot leaves the live state untouched. |
| `geoops/artifacts.py` | `ArtifactStore` registers a real file with sha256, size, path and owning task, optionally bound to a registered `Deliverable` (an unknown id, or an object of another type, is refused). A missing file, a directory, a symlink, a second registration of the same content, or a path whose content changed are all refused. `verify` recomputes the hash, so an edited or deleted deliverable stops matching. The index saves atomically and reloads. |
| `geoops/delivery/nodes.py` | `artifact_register_node` registers the file named by a context key as a workflow node. A missing path, a refused registration or a failed verification is a `FAIL` node, so later nodes are skipped instead of publishing an unchecked product. A passing node writes the row into `context["artifacts"][node_id]`. |
| `geoops/survey/change.py` | Real change detection on two ESRI ASCII grids, standard library only. `read_ascii_grid` validates the header (required keys, integer size, positive cellsize, cell count equal to `ncols * nrows`, numeric cells, no duplicate keys); `detect_changes` requires aligned origin/cellsize/size, marks cells whose absolute difference reaches the threshold, skips nodata pairs, groups cells by 4-neighbour connectivity, drops patches below `min_area_m2`, and reports cell and patch areas from `cellsize ** 2`. `write_change_mask` writes the mask with the source header, nodata preserved and the same nodata value. Cell area is square metres only when the grid CRS is projected in metres; that stays the rule engine's job (R-OR-001 / R-CD-002). |
| `geoops/survey/change_node.py` | `change_detect_node` reads the two grid paths and the output path from the context, computes the mask, writes it, and puts the observed statistics (changed / kept / dropped / nodata cells, patches, area, mask path) into `context["change_result"]`. A refused input fails the node, so no mask is registered for a comparison that did not happen. |
| `geoops/quality/report.py` | `build_report` copies recorded task, run, rule, quality, deliverable, registered file and review values into one report; any section that was not supplied is written as `NOT_RECORDED` with a reason instead of being guessed. `write_report` writes JSON or Markdown atomically. |

## Task and workflow are separate

A task is the business goal; a workflow is one way to carry it out. `TaskEngine`
records state, transitions and history; `workflow.executor` runs nodes. A task
may attach more than one run (retry after a failed node), and a run never moves
the task by itself — the caller has to transition the task, so a failed node
cannot silently complete it.

## Resume

A failed run is not discarded. `resume` re-executes from the node that failed
and records every earlier node as `REUSED` with its original output, so the new
record shows what actually ran again and what was carried forward. Reuse is
refused when an earlier node did not end in `PASS`, when the node count or
node identity changed, when the previous run did not fail, or when the resume
reuses the previous run id. A task follows the retry through its own state
machine (`FAILED → RUNNING`) and records both run ids.

## Security

There is no built-in account store. A caller supplies a `PermissionPolicy`,
either directly or from a token file whose entries are sha256 hashes — a file
with a raw `token` field is refused, so a leaked policy file does not hand out
usable credentials. An entry may carry `issued_at` / `expires_at` (strict UTC
`YYYY-MM-DDTHH:MM:SSZ`); an expired token stops authorising and the API answers
401 `token expired` instead of pretending it was never issued. `revoke` drops a
grant and `rotate` replaces one token with another, keeping or narrowing its
permissions. Every decision, allow or deny, goes to the audit trail with a
truncated hash of the presented token; with a path configured the row is
appended and `fsync`ed, and loading a corrupt audit file raises `AuditError`
rather than silently dropping the rows that would have shown the gap.

## Delivery

Registration is a workflow step, not a side effect of writing a file. In the
reference pipeline the rule gate runs first and `artifact_register_node` second,
so one run either produces both the rule verdicts and the file hash, or stops at
the gate with the product unregistered. A geographic CRS, a missing file or a
failed hash check therefore cannot reach the report as a deliverable.

## Rules

Rules are data, not code paths. A pack lists definitions with the fields the
0.1 specification requires; a validator is looked up by name. Evaluation has
five outcomes and no silent upgrade: an unmet condition is `SKIPPED`, a missing
validator or a validator exception is `ERROR`, a false result is `FAIL` under
`severity: error` and `WARNING` under `severity: warning`. `FAIL` and `ERROR`
block the deliverable; `SKIPPED` and `WARNING` do not, but they stay in the
result list so a report cannot present them as passed.

`rule_check_node` is the bridge into the workflow: a blocking rule fails the
node and stops later nodes, an `ERROR` rule keeps the node status `ERROR` rather
than flattening it to `FAIL`, and `WARNING` / `SKIPPED` let the run continue
while every result stays in `context["rule_results"][node_id]`. A task type with
no applicable rule records `SKIP`, never `PASS`.

Two packs ship with the project:

| pack | task type | rules | what is checked |
|---|---|---|---|
| `p01_dataset.json` | `land_use_classification` | 4 | CRS declared, file exists as a regular file, metadata source traceable (warning), task linked to a registered project |
| `p02_products.json` | `ortho_generation` | 4 | CRS is a projected EPSG code (4326/4490 refused), GSD recorded and positive, nodata declared (warning), product file exists |
| `p02_products.json` | `change_detection` | 3 | two distinct existing inputs, both CRSs equal, minimum change area declared (warning) |

Every validator returns `(ok, detail)` and its evidence string names the field
it read, so a failure can be traced to one value rather than to "the rules".

## Smoke

```text
python -m geoops.smoke            # no data; structural run only
python -m geoops.smoke --data P   # same pipeline over a user-supplied dataset
```

The no-data run registers transient domain objects, calls the kernel, runs the
workflow, exercises the quality checker with real pass/fail/error paths, and
queries the HTTP API. It requires no imagery. The real output of a local run is
recorded in `docs/SMOKE_OUTPUT.md`.
