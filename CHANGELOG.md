# Changelog

All notable changes to this project are documented in this file.

## Unreleased — 2026-11-18 — workflow execution, accuracy metrics and trace binding

### Added

- `GET /api/v1/audit/verify`: re-reads the JSONL audit file on demand and
  verifies its whole hash chain, reporting `ok=false` with the failing line
  instead of trusting the in-memory copy.
- Each change patch now reports mean/max absolute change and mean levels
  alongside its map bbox/centroid; a grid pair whose declared linear units
  differ is refused before any cell is compared.
- Dataset records persist `raster_type`, `linear_unit`, `linear_unit_code` and
  `linear_unit_m` from the GeoTIFF header, and validation compares them on
  re-probe. Raster profiles count non-finite cells separately instead of letting
  NaN/Inf poison min/max/mean; mask metrics exclude them from the confusion
  matrix, and an undeclared NODATA value is no longer assumed to be -9999.
  Change detection counts NODATA and non-finite cells separately, `threshold=0`
  marks only real non-zero differences, and a mask refuses a non-finite NODATA
  sentinel or writes a fractional one consistently in header and cells.
- A sidecar CRS or CRS model that contradicts the GeoTIFF header is recorded as
  `metadata_conflict` and fails re-validation; raster reads refuse it instead of
  choosing one source and silently computing area on the wrong units.
- GeoTIFF metadata now rejects a non-numeric `GDAL_NODATA`, non-finite pixel
  scale/tiepoint/matrix values and an extent that would overflow to NaN; a
  `.tif` whose header cannot supply bounds is registered as `INCOMPLETE` rather
  than READY with missing georeferencing.
- Domain registry mutations, task transitions and review submission are now
  serialized with re-entrant locks, so concurrent requests cannot double-create
  an id, apply two conflicting task edges or sign off the same deliverable twice.
- The model runtime now rejects a non-finite or out-of-range `temperature`,
  non-integer/out-of-range `max_tokens` and invalid `timeout_s` as
  `INVALID_OPTION`; `/model-runtime/chat` returns 400 instead of forwarding
  malformed JSON or reporting a provider failure.
- External GIS tools now require an absolute executable path, reject NUL bytes,
  non-scalar/non-finite placeholder values and a zero or >3600s timeout at load
  or run time; a bad argument is an explicit error, not a guessed default.
- GeoTIFF files are memory-mapped instead of copied into a bytes object.
  GeoTIFF dataset profiles now stream one band strip/tile by strip/tile
  (`read_mode=streamed_blocks`), so a large image no longer needs width*height
  Python floats in memory; real pixel counts and statistics are unchanged.
- Two GeoTIFF masks are now compared row by row in spatial order, so accuracy
  metrics on large classification/truth masks no longer load two full float
  arrays; alignment is still checked before any cell is counted.
- GeoTIFF strips and tiles using PackBits (compression 32773) are decoded, with
  truncated literal/repeat runs refused instead of yielding short pixel data.
- GeoTIFF 64-bit samples are decoded for unsigned/signed integer and float
  SampleFormat, so Float64 rasters are no longer refused as unsupported bits.
- An uncompressed GeoTIFF whose whole image is one strip is now read row by
  row from the mmap, so profile memory stays proportional to one image row
  instead of width*height floats.

- Workflow definition registry: typed nodes, atomic `var/workflows.json`,
  declared `inputs` alias mapping, `retry`, `failure_action=continue`,
  per-node `attempts`, execute and resume APIs.
- `geoops/ai/agent_executor.py`: Agent JSON plan loop, declared-tool whitelist,
  real builtin tool execution, per-step `tool_calls` and bounded steps; both
  builtin profile and change tools accept a selected `band` and treat NaN as
  NODATA; no scripted fallback. An Agent's registered `max_steps` is validated
  to 1–16 and used when a workflow node does not override it.
- Real nodes: `data_input` / `data_check`, `review`, builtin ASCII
  `gis_tool_call`, `agent_execute`, `change_detection`,
  `artifact_register`, `output`.
- `geoops/workflow/external_tools.py`: explicit `external:<id>` tools from
  `var/external-tools.json` (or `GEOOPS_EXTERNAL_TOOLS`), argument templates,
  no-shell subprocess execution, and non-zero exit as an error. Every call
  records the rendered command, exit code, stdout/stderr, timeout and elapsed
  milliseconds; a failed call carries the same details into the node output and
  the Agent's `tool_calls` instead of disappearing with the exception. A failed
  Agent result exposes both `steps` and `tool_calls` for the same evidence.
  The registry now refuses duplicate `tool_id` entries and non-finite timeouts
  instead of silently overwriting or passing them to subprocess.
- `GET /api/v1/execution-events`: flattened run and node events from the real
  run journal, optionally filtered by `task_id`.
- Survey areas: `SurveyAreaRegistry` with real project linkage and validated
  `minx/miny/maxx/maxy` bounds; `GET/POST /api/v1/survey-areas`.
- `GET /api/v1/datasets/<id>/profile`: real ASCII/GeoTIFF pixel summary
  (dimensions, bands, selected band, cellsize, origin, bounds, CRS, NODATA
  count, min/max/mean); `?band=N` selects a real band from a multiband GeoTIFF.
- Node policies: declared `outputs` aliases, dotted `preconditions`, and
  `success_condition` (`PASS`, `status == …`, or a dotted-path comparison) are
  executed; missing preconditions and failed conditions stop the node.
- `geoops/geotiff.py`: both classic TIFF (magic 42) and BigTIFF (magic 43,
  64-bit offsets, `LONG8`/`SLONG8`/`IFD8` field types) are read. The same
  GeoTIFF tags, strip/tile decoding and EPSG parsing apply; the writer still
  emits classic TIFF.
- `geoops/geotiff.py`: classic TIFF pixel decoding for uncompressed, LZW and
  Deflate images, striped or tiled, 8/16/32-bit chunky or separate-planar
  bands; JPEG/JPEG2000 decode through optional Pillow. Other codecs are
  explicit errors. Predictor=2 is undone per row with the sample's bit-width
  modulo (8/16/32-bit, signed or unsigned), so a wrapped 8-bit row no longer
  decodes above 255; the integer predictor is refused for float samples.
  A non-default TIFF Orientation is refused instead of silently returning
  rotated pixels as if they were north-up. A PixelIsPoint GeoTIFF has its
  bounds shifted half a cell from the pixel-centre tiepoint to the footprint.
- Change detection reports real square metres for a geographic grid: each row's
  cell area is evaluated at its own latitude on the WGS84 ellipsoid, so a
  one-degree cell is about 12.3 billion m2 instead of one.
- A GeoTIFF with non-square pixels keeps its row height: grids carry
  `cellsize_y`, alignment compares both cell dimensions, area is `sx * sy`, and
  the mask writer preserves both scales. ASCII mask output is refused when the
  cell is non-square because the format cannot express the height.
- Projected GeoTIFF linear units are read from GeoKey 3076: metre, foot, US
  survey foot and yard are converted to square metres for every area figure,
  and mask output writes the same unit code. An explicitly declared unit that
  the reader does not know is refused instead of being reported as metres.
- Dataset profiles now report `cell_area_m2` and `footprint_area_m2` (with
  `area_basis`) using the same geographic/linear-unit rules as change
  detection; when the CRS model is unknown the area is returned in map units
  under a separate key instead of being mislabelled as square metres.
- New audit rows carry `prev_hash`/`row_hash`, so reloading a file detects an
  edited row or a re-linked chain. Legacy rows without the chain still load and
  become the first chained link; corrupt JSON and missing fields remain errors.
- Change detection and quality comparison refuse a non-finite threshold or
  minimum area instead of silently writing an empty mask or an all-zero
  confusion matrix.
- Each change patch now carries its map-space `bbox`, cell-centre `centroid`
  and row/column extent, so a mask can be located without a vector library.
- Dataset registration records `crs_model` next to `crs`; re-validation now
  fails when the sidecar changes from projected to geographic (or back),
  instead of only comparing the EPSG string.
- A `GTRasterTypeGeoKey` outside PixelIsArea/PixelIsPoint is refused, and a
  dataset profile turns an unsupported linear unit into a dataset error rather
  than letting a raw `ChangeError` escape.
- Quality reports now expose `cellsize_y` alongside `cellsize`, so a non-square
  mask is not described as if it had square cells.
- `ModelTransformationTag` (34264) now supplies the affine georeferencing when
  a GeoTIFF has no PixelScale/Tiepoint pair; the probe reuses the pixel reader's
  metadata instead of keeping a second copy. Rotated or sheared transforms and
  non-north-up scales are refused.
- `DeliverableRegistry.verify_archive` re-hashes the archived copy against its
  manifest, checks the registry sha256, rejects paths outside the archive root,
  and reports missing or altered files. `GET
  /api/v1/deliverables/<id>/archive-verification` exposes the same check.
- `geoops/geotiff.py`: `write_geotiff_mask` writes a real classic GeoTIFF
  (one band, float32, uncompressed, strip layout) with ModelPixelScale,
  ModelTiepoint, one EPSG GeoKey and GDAL_NODATA; CRS/model are required rather
  than guessed.
- `geoops/domain/datasets.py`: a sidecar CRS no longer suppresses the GeoTIFF
  header probe; dimensions, bounds and pixel size are retained, and a header
  without EPSG is accepted only when the sidecar supplies the CRS. When both
  declare different CRSs, the sidecar still wins but the override and its
  header CRS are recorded in `reason` instead of disappearing.
- `DatasetRegistry.validate`: a re-probe now also fails when the CRS, width,
  height or band count no longer matches what was registered, not only when
  the sha256 changes.
- `geoops/survey/change.py`: change detection reads ASCII or classic/BigTIFF
  rasters through one reader; `read_raster_grid(path, band=1)` and
  `detect_changes(..., band=N)` select one band from a multiband GeoTIFF
  (an out-of-range band is refused); workflow `change_detection` nodes accept
  a declared `band`; ASCII headers may declare cell-center origins
  (`xllcenter`/`yllcenter`) which are normalised to corners, and a
  contradictory corner/center pair is refused; a sidecar `crs` (with optional
  `crs_model`) supplies a missing GeoTIFF header CRS as well as ASCII CRS, so
  either input can write a georeferenced output; a `.tif`/`.tiff` output writes
  a one-band float32 GeoTIFF mask with the source PixelScale, Tiepoint, EPSG
  GeoKey and GDAL_NODATA. Output without a source CRS is refused; `.asc`
  remains ASCII; two grids whose CRS or CRS model differ, or where only one
  grid declares a CRS, are refused before any comparison. An ASCII mask also
  writes its source CRS/model into a sibling `.json` sidecar.
- `geoops/survey/change.py`: a shared `is_nodata` check treats a floating-point
  NaN sentinel as NODATA in change detection, dataset profiles and quality
  masks, instead of letting NaN cells count as valid values.
- `geoops/quality/service.py`: optional `accuracy_thresholds` adds a real
  `professional.accuracy_threshold` check; below-minimum metrics are `FAIL`,
  invalid keys/values or thresholds without a reference mask are refused, and
  no default threshold is assumed.
- `geoops/quality/metrics.py`: mask comparison now refuses a CRS or CRS model
  that differs between reference and predicted, including a CRS present on
  only one side, before reporting a confusion matrix.
- `geoops/quality/metrics.py`: ASCII or GeoTIFF mask confusion matrix with
  TP/FP/FN/TN, pixel accuracy, precision, recall, F1 and IoU; NODATA excluded;
  mismatched dimensions, cell size, origin or CRS refused. ASCII masks go
  through the same validated reader as change detection, so a BOM, a
  cell-center origin or a sidecar CRS is handled identically instead of being
  silently dropped.
- Quality API accepts `reference_path`, `predicted_path`, `synthetic_reference`
  and writes an `accuracy` object into the report.
- Quality reports now carry `basis`, `method`, `data` and `evidence` alongside
  the status and layer checks.
- `APPROVE` review is refused unless its linked quality report is `PASS`.
- Synthetic provenance: datasets and deliverables carry `synthetic`, and the
  quality report inherits it.
- API: `POST /api/v1/deliverables/<id>/artifacts` binds a real file hash to an
  existing deliverable; artifact→deliverable trace links become fillable.
- Docs: `docs/WORKFLOW_ENGINE.md`, `docs/WORK_RECORD_2026-11-18.md`.

### Tests

- `276 tests OK`; `SMOKE PASS: 73 assertions`. Synthetic trace run produced
  `complete=True`, `missing=0`; it is explicitly marked synthetic, not a
  real acceptance.

## Unreleased — 2026-11-17 — real OpenAI-compatible model runtime

### Added

- `geoops/ai/runtime.py`: OpenAI-compatible `POST /chat/completions` client,
  configured from `GEOOPS_MODEL_BASE_URL`, `GEOOPS_MODEL_API_KEY`,
  `GEOOPS_MODEL_NAME` (optional `GEOOPS_MODEL_TIMEOUT`). Missing configuration
  raises `NOT_CONFIGURED`; provider HTTP errors, invalid JSON, empty messages
  and unreachable endpoints fail explicitly. The key is never returned by
  `status()` or written to audit/log output.
- `ModelRuntime.from_env` also reads the ignored local `var/model-runtime.env`
  (same four keys, `KEY=VALUE`); real environment variables win, unknown keys
  become `CONFIG_ERROR`, and `status()` exposes only the config path, never the
  key.
- `geoops/ai/nodes.py`: a workflow node that makes a real model call and
  records the reply, usage and latency; an unconfigured runtime makes the run
  `ERROR`, never a fake `PASS`.
- API: `GET /api/v1/model-runtime`, `POST /api/v1/model-runtime/probe`,
  `POST /api/v1/model-runtime/chat`, permission `model:invoke`.
- Console: model-runtime card on AI resources with state, model, endpoint,
  auth, timeout, real probe and real prompt; no placeholder output.
- CLI: `python -m geoops.ai status|probe|chat`.
- Launcher: passes `var\console-tokens.json` when present; local token in
  `var\console-token.txt` (ignored, never committed).
- Docs: `docs/MODEL_RUNTIME.md`.

### Tests

- `213 tests OK`; `test_model_runtime.py` uses a real local HTTP provider.

## Unreleased — 2026-11-17 — 0.1 release surface and book-style console

### Added

- Deliverable registry (`geoops/domain/deliverables.py`): real-file registration
  with sha256/size, version, task binding; archive is refused until a review
  marks the deliverable `accepted`, and also if the file is missing or no
  longer matches its registered sha256. With `archive_dir` (the console uses
  `var/archive`), archival copies the verified file into a per-deliverable
  folder and writes a `manifest.json` with source path, sha256, size, actor and
  note.
- Three-layer quality service (`geoops/quality/service.py`): file/structure,
  spatial data and professional verification. A missing professional sample is
  `NOT_RECORDED` and the aggregate is `PARTIAL`; a changed file fails the sha256
  check. Reports are written atomically to `var/quality/*.json` and registered
  as `QualityReport`.
- API: `GET/POST /api/v1/deliverables`, `POST /api/v1/deliverables/<id>/archive`,
  `GET/POST /api/v1/quality-reports`, `GET /api/v1/settings`. New permissions
  `deliverable:write` and `quality:write`; every write audited.
- Console: twelve sections (总览 / 项目 / 任务 / AI 资源 / 数据 / 流程 / 规则 /
  质量 / 成果 / 审核 / 追溯 / 设置). Project, AI resource, quality, deliverable,
  review and settings pages all use real endpoints.
- Book-style visual system v2.0 (`geoops/web/ui.css`): exact HX paper / ink /
  celadon / cinnabar / Dai blue / ochre / gold tokens, Dai-blue spine, paper
  cards, gold hairlines, cinnabar live dot, dark warm-paper theme. No pure white,
  no pure black, no rainbow gradients.
- Docs: `docs/FRONTEND_BOOKSTYLE_V2.md`; twelve new screenshots under
  `docs/ui-preview/v2-*.png`.

### Tests

- `206 tests OK`; new `test_quality_deliverable.py` (7) and
  `test_api_quality.py` (3).
- Smoke nav assertion updated from nine to twelve sections.

## Unreleased — 2026-11-17 — 0.1 domain layer

### Added

- Project registry: `project_code / name / project_type / area / crs /
  vertical_datum` are mandatory, `project_code` is globally unique, and a
  duplicate id or code is refused (`geoops/domain/projects.py`).
- Dataset registry: registration re-reads the real file, computes sha256 and
  takes the CRS from a sidecar **or from a classic GeoTIFF header**. Missing
  file, empty CRS or unreadable header is a refusal, not a blank row.
  `validate(dataset_id)` re-probes and reports PASS/FAIL/ERROR per check.
- `geoops/geotiff.py`: narrow header-only GeoTIFF reader (ModelPixelScale,
  ModelTiepoint, GeoKeyDirectory). Reads EPSG, width, height, bands, bounds and
  pixel size without GDAL. BigTIFF and pixel decoding are explicitly out of
  scope.
- Catalog: models, tools and agents are separate records. `builtin:` adapters
  must be ones this repository implements; `external:` adapters must point at
  an existing path; an agent referencing unknown models/tools is refused and
  inherits the availability of its dependencies.
- Review gate: `APPROVE` is the only action that marks a deliverable
  `accepted`; `REJECT`/`RERUN` require an opinion; an already accepted
  deliverable refuses further review. Records carry reviewer, time, opinion and
  the deliverable version at review time.
- Structured trace: `GET /api/v1/tasks/<id>/trace` assembles
  project → datasets → runs → rule nodes → deliverables → artifacts → reviews.
  Missing links are listed as `NOT_RECORDED` with a reason and `complete=false`.
- API write endpoints: `POST /api/v1/projects|datasets|catalog|reviews`, behind
  `project:write / dataset:write / catalog:write / review:write`; every allow
  and deny is audited. Read endpoints for projects, datasets, dataset validate,
  catalog and reviews.
- Console: nav grows to nine sections with 数据 / 审核 / 追溯 pages: project and
  dataset registration, dataset re-validation, catalog availability, review
  submission and a task trace view.

### Tests

- `test_release.py` 18 tests, `test_api_release.py` 8 tests,
  `test_geotiff.py` 3 tests. Full suite: 196 tests.

## Unreleased — 2026-11-16

### Added

- `geoops/domain/tasks.py`: `TaskEngine` and `SurveyTask`. The task lifecycle
  (`DRAFT → READY → RUNNING ⇄ PAUSED → COMPLETED`, plus `FAILED` for retry and
  `CANCELLED` from any non-terminal state) is now a real state machine kept
  separate from workflow execution. Every transition is appended to the task
  history with time, reason and actor; the record is mirrored into the domain
  registry so the HTTP API can serve it.
- Rejections leave the task unchanged: an edge not listed in `ALLOWED`, a
  no-op transition, an empty reason on `COMPLETED`/`CANCELLED`, an unknown
  task id and a duplicate run attach all raise `TaskError` with a readable
  message instead of being applied.
- `geoops/api/app.py`: read-only `GET /api/v1/tasks` list, served only when a
  task engine is supplied. The API cannot transition a task on its own.
- `geoops/tests/test_tasks.py`: 12 unit tests (project checks, every illegal
  edge, close-reason requirement, FAILED retry, identical transition, run
  attach rules, unknown ids, allowed-target reporting).
- `geoops/smoke.py`: new section `2b. survey task engine` and `4b. task / run
  linkage`, plus assertions that the API serves a task object by id and lists
  tasks. The run id attached to a task is the one that actually executed.
- `geoops/workflow/executor.py`: `resume(nodes, previous)` and
  `WorkflowEngine`. A failed run can be retried from the node that failed;
  nodes that already passed are recorded as `REUSED` with their original
  output, and their outputs are placed in `context["node_outputs"]`. Resume is
  refused when the previous run did not fail, when the node count or node
  identity changed, when an earlier node did not end in `PASS`, or when the
  previous run id is reused. `WorkflowEngine` keeps run history and rejects
  duplicate run ids. `WorkflowRun` now carries `resumed_from`.
- `geoops/smoke.py`: sections `5b. workflow resume` and `5c. task follows the
  retry` — a real failed run (`RUN-SMOKE-002`) is resumed as
  `RUN-SMOKE-003`, and a task records both runs through `FAILED → RUNNING`.
- `geoops/tests/test_workflow.py`: 11 unit tests for stop-on-failure,
  ERROR-as-not-PASS, reuse, every refusal path, duplicate run ids, history and
  output carry-forward.
- `geoops/survey/rules.py`: `SurveyRuleEngine` with data-driven rule packs and
  five result states (`PASS` / `FAIL` / `WARNING` / `SKIPPED` / `ERROR`). An
  unmet condition is `SKIPPED`, a missing validator or a validator exception is
  `ERROR` — neither is ever reported as `PASS`. `FAIL` and `ERROR` block.
  Rule packs are validated fully before loading: missing fields, unknown
  severity, duplicate ids and ids already loaded are rejected with nothing
  partially applied.
- `geoops/survey/packs/p01_dataset.json`: four real dataset-intake rules for
  `land_use_classification` (CRS declared, file exists, metadata source
  traceable as a warning, task linked to a registered project). Conditions are
  applicability filters, so a missing value fails the rule instead of skipping
  it.
- `geoops/survey/` package exposing the engine and result types.
- `geoops/smoke.py`: section `8. survey rules` evaluates the pack against a
  complete context, the real intake record (no CRS, no sidecar), an
  unregistered project and a different task type.
- `geoops/tests/test_rules.py`: 12 unit tests covering pack loading, every
  rejection path, SKIPPED and ERROR semantics, severity mapping and scoping.
- `geoops/survey/nodes.py`: `rule_check_node(...)`, the rule engine as an
  explicit workflow node. Blocking rules (`FAIL` / `ERROR`) fail the node and
  stop later nodes; an `ERROR` rule keeps node status `ERROR` instead of being
  flattened to `FAIL`; `WARNING` / `SKIPPED` continue the run but every result
  is stored in `context["rule_results"][node_id]`. A task type with no
  applicable rule records `SKIP`, not `PASS`.
- `geoops/smoke.py`: section `8b. rule gate node` — a blocked deliverable, a
  fixed context that reaches it, a warning-only pass and a no-rule SKIP.
- `geoops/tests/test_rule_nodes.py`: 7 unit tests for blocking, warnings,
  zero-rule skip, validator exception, context builder and skipped conditions.
- `geoops/store.py`: `SnapshotStore` saves the registry and task engine to one
  JSON snapshot atomically (`fsync` + `os.replace`) and restores them. The file
  is validated on empty probe objects before the live state is touched, so a
  corrupt, duplicate or clashing snapshot is refused whole. `DomainRegistry`
  and `TaskEngine` gain `restore(...)`, which keeps version, status and
  history instead of re-registering at version 1.
- `geoops/smoke.py`: section `9. snapshot persistence` — save, restore into
  fresh objects, version/run survival and a corrupt file refusal.
- `geoops/tests/test_store.py`: 8 unit tests (roundtrip, atomic save, missing
  and corrupt files, wrong format, duplicate ids, live clash, bad task row).
- Engineering tier registered as **core** in `docs/ENGINEERING_TIER.md`, with
  the criteria and the gaps that still block release listed in the same file.
- `geoops/quality/report.py`: `build_report(...)` copies recorded values only
  (task, runs, rule results, quality report, deliverable, review) and marks any
  missing section `NOT_RECORDED` with a reason. `render_markdown` renders the
  same records; `write_report` writes JSON or Markdown atomically and rejects
  an unknown format or a foreign payload.
- `geoops/smoke.py`: section `10. execution report` — a real report over the
  retried task, both runs, the rule results and the failing quality report,
  written as JSON and Markdown.
- `geoops/tests/test_report.py`: 7 unit tests (missing task/id, copied records,
  NOT_RECORDED sections, Markdown content, atomic JSON write, format rejection).
- `geoops/api/security.py`: `PermissionPolicy` (token → `task:create` /
  `task:transition` / `audit:read`) and `AuditLog` (allow/deny rows with a
  sha256 fingerprint instead of the raw token).
- `geoops/api/app.py`: write endpoints `POST /api/v1/tasks` and
  `POST /api/v1/tasks/{id}/transitions`, plus `GET /api/v1/audit`. The gate
  runs before the body is read: 401 for a missing or unknown token, 403 for
  a missing permission, 413 for a body over 64 KB, 400 for invalid JSON or a
  refused transition. Writes stay disabled unless a policy is supplied.
- `geoops/smoke.py`: section `7b. write api with permission gate` — a refused
  anonymous write, an authorised create, the full transition path over HTTP,
  a forbidden viewer transition and a guarded audit endpoint.
- `geoops/tests/test_api_write.py`: 11 unit tests for the gate, the audit trail, body limits, the full HTTP path and a server with writes disabled.
- `geoops/api/security.py`: grants are now stored as sha256 hashes only.
  `PermissionPolicy.from_file` loads a `geoops-tokens` file and refuses raw
  `token` fields and duplicate hashes. `AuditLog(path=...)` appends each row to
  JSONL with `fsync` and reloads it; a corrupt or incomplete line raises
  `AuditError` instead of being dropped.
- `geoops/smoke.py`: section `11. token file and audit file` — a file-granted
  token, a reloaded audit trail and a corrupt audit line.
- `geoops/tests/test_audit.py`: token and audit file tests — hash-only grants, every token file rejection, audit persistence, trimming and corrupt files.
- `geoops/artifacts.py`: `ArtifactStore` — registers a real file with sha256,
  size, path and owning task; refuses a missing file, directory, symlink, a
  duplicate id, or a path whose content changed; `verify`/`verify_all` recompute
  the hash so an edit or deletion is reported, not ignored; index saves
  atomically and reloads.
- `geoops/quality/report.py`: new `artifact_files` section (RECORDED or
  NOT_RECORDED with reason) and a Markdown table naming path, size and hash.
- `geoops/smoke.py`: section `12. deliverable registry` — real hash and size,
  idempotent re-registration, verify before and after an edit, index reload, and
  the report carrying the file.
- `geoops/tests/test_artifacts.py`: 12 unit tests for every refusal, the
  idempotent and changed-content paths, tamper and deletion detection, the index
  round trip, and the report section.
- `geoops/artifacts.py`: a registration can be bound to a `Deliverable` id.
  The id is looked up in the domain registry first: no registry, an unknown id
  or an object of another type is refused, so a file cannot claim an
  unregistered 成果. `for_deliverable` returns the files of one deliverable.
- `geoops/smoke.py`: section 12 also binds a second file to `DLV-SMOKE-002`
  and shows an unregistered id being refused.
- `geoops/tests/test_artifacts.py`: 4 binding tests added (16 in this module).
- `geoops/api/security.py`: token entries accept `issued_at` / `expires_at` in
  strict UTC; an expired token is refused with its own reason instead of being
  treated as unknown, `expires_at` before `issued_at` and loose timestamps are
  refused, `revoke` drops a grant and `rotate` replaces one token with another
  (permissions kept or narrowed). `check` returns the reason the audit row
  records.
- `geoops/api/app.py`: an expired token gets 401 `token expired`, a missing
  permission still gets 403.
- `geoops/api/app.py` (fix): a refusal decided before reading the body now
  drains the bounded body before closing. Closing with bytes still queued made
  the socket send RST, and on Windows the client lost the 401/403/413 it was
  owed — the API test suite failed intermittently (1 run in 3) until this
  drain was added; 5 consecutive full runs pass after it.
- `geoops/smoke.py`: section `13. token expiry and rotation` — an expired token
  refused with its reason, a rotation that drops the old token, and a rotation
  that narrows permissions.
- `geoops/tests/test_tokens.py`: 10 unit tests for expiry, timestamp
  validation, the file entry with expiry, rotation (full, narrowed, unknown) and
  revocation.
- `geoops/survey/packs/p02_products.json`: 7 product rules — four for
  `ortho_generation` (projected CRS, positive GSD, nodata warning, product file)
  and three for `change_detection` (two distinct inputs, equal CRSs, change-area
  warning).
- `geoops/survey/rules.py`: eight new validators (`crs_projected`,
  `gsd_recorded`, `nodata_declared`, `deliverable_file`, `two_inputs`,
  `crs_match`, `change_threshold`, plus the shared file check). Geographic EPSG
  codes (4326/4490/4258/4269/4610) are refused as a product CRS; a non-EPSG
  string is refused rather than passed through.
- `geoops/smoke.py`: section `14. product rules` — the pack scope (4 + 3), a
  complete ortho context passing, a geographic CRS blocking, and mismatched
  CRSs blocking change detection. The no-rule demo now uses `map_compilation`,
  a type that genuinely has no rules.
- `geoops/tests/test_rule_packs.py`: 12 unit tests (pack shape, type scoping,
  every ortho failure path, the nodata warning not blocking, both change inputs,
  a shared file, duplicate ids across packs, a type with no rules).
- `geoops/delivery/nodes.py`: `artifact_register_node` turns registration into a
  workflow step. It registers the file named by `context[path_key]`, verifies the
  hash it just wrote, and fails the node (skipping later nodes) on an empty path,
  a refused registration or a failed verification. A passing node records the row
  in `context["artifacts"][node_id]`.
- `geoops/smoke.py`: section `15. rule gate then registration, one run` — the
  ortho gate followed by the register node on one clean file, the same pair
  stopped by a geographic CRS with registration skipped and nothing registered,
  and the report carrying four PASS rule rows plus the file hash.
- `geoops/tests/test_delivery.py`: 7 unit tests (hash and size in the detail,
  the row in the context, missing/empty path, unregistered deliverable, a later
  node skipped, and two runs of one file staying consistent).
- `geoops/store.py` (fix): a save used the fixed name `<state>.tmp`, so two
  threads saving at once fought over one temp file and `os.replace` failed with
  `WinError 5`. Each save now uses `tempfile.mkstemp` in the target directory and
  serialises under a lock. `os.replace` is retried (up to ~3 s) while another
  handle still has the snapshot open, and reports a file that stays locked.
- `geoops/store.py`: `load` distinguishes an older version ("no migration path
  is implemented") from a newer one, and refuses a non-integer version, instead
  of one flat "unsupported version" message.
- `geoops/artifacts.py` (fix): registration and verification are serialised, and
  the index save uses a unique temp file with the same replace retry.
- `geoops/tests/test_concurrency.py`: 8 tests written before the fixes above —
  8 parallel saves, a reader loop against a writer loop (a writer failure fails
  the test), no leftover temp files, older/newer version refusal, parallel
  registration of distinct files and of one file, and parallel audit appends.
- `geoops/survey/change.py`: real change detection on two ESRI ASCII grids,
  standard library only. The reader validates every header key it needs
  (integer size, positive cellsize, cell count equal to `ncols * nrows`,
  numeric cells, no duplicate keys). `detect_changes` refuses unaligned grids,
  marks cells whose absolute difference reaches the threshold, skips nodata
  pairs, groups cells by 4-neighbour connectivity, drops patches below
  `min_area_m2`, and reports areas from `cellsize ** 2`. `write_change_mask`
  writes the mask with the source header and keeps nodata as nodata.
- `geoops/survey/change_node.py`: `change_detect_node` — a refused input fails
  the node, so no mask is registered for a comparison that did not happen; a
  passing node reports the observed cells, patches and area and puts the mask
  path into `context["change_result"]`.
- `geoops/tests/test_change.py`: 13 unit tests on a hand-countable fixture
  (5x4 at cellsize 10, one nodata cell, a 2-cell and a 1-cell patch): grid
  validation refusals, unaligned grids, threshold boundaries, patch
  connectivity, `min_area` filtering, mask round-trip, and the node's fail and
  pass paths including registration and verification of the mask.
- `geoops/smoke.py`: new section `16. change detection end to end` — two real
  grids pass the change rules, are compared, the mask is written, and the hash
  of that file is registered; an unaligned pair fails before any mask exists.
- `geoops/api/app.py` (fix): a POST to an unknown path was answered 404 and the
  connection closed with the body still queued, so Windows clients sometimes
  received a reset instead of the 404. The body is now drained first; a
  regression test repeats the request 20 times.
- `geoops/store.py` (fix): a reader that opened the snapshot exactly while a
  save replaced it saw `WinError 5`; `load` now retries the open for a bounded
  time and reports a file that stays locked, and the concurrency reader test
  fails on any exception rather than only on `StoreError`.

- `geoops/web/` and `GET /ui/`: the console shell, served from a whitelist inside
  the API process. Visual language follows the three HX frontends (paper
  palettes, weight-300 body, glass cards, mono micro-labels, hairline tables,
  pill badges) with the 书香 palette as the default; six sections 概览 / 任务 /
  流程 / 规则 / 成果 / 审计, light and dark, six paper colours, A−/A+ zoom.
- `GET /api/v1/overview` (counts only, no records or paths), `GET /api/v1/rules`
  (pack metadata read from the pack files) and `GET /api/v1/artifacts`
  (`audit:read`, returns the registered rows). The console calls these plus the
  existing task and audit endpoints.
- The console never invents data: a missing endpoint says 未开放, a missing
  token says 需令牌 with the required permission, an empty list says 未记录. The
  only non-endpoint content is the engineering gap list, which mirrors
  `docs/ENGINEERING_TIER.md`.
- `python -m geoops.api [--demo] [--tokens FILE] [--audit FILE] [--artifacts FILE]`
  runs the API and console together; read-only unless `--tokens` is given.
- `geoops/tests/test_ui.py`: 7 unit tests — page markup with no external
  requests, CSS/JS content types, path whitelist (a traversal attempt is 404),
  `node --check` on the console script (skipped if node is absent), overview
  counts against the live registry, rule packs against the files on disk, and
  the artifact endpoint's 401 / 200 behaviour.
- `geoops/smoke.py`: section `17. console shell` — the shell is served with six
  sections, and its overview numbers equal the smoke's own registry, task and
  rule counts.
- Screenshots of the running console are in `docs/ui-preview/` (real captures
  from the local server, not mockups).
- `geoops/workflow/journal.py`: `RunJournal` writes each finished run as one
  JSON line (`fsync` before returning) with its task, project, actor and
  timestamp. A duplicate `run_id` is refused, and a corrupt or truncated line
  refuses the whole file instead of dropping rows. `--runs FILE` keeps the
  journal on disk; without it the journal is in-memory.
- `GET /api/v1/runs`: the run journal with node verdicts, plus `by_status`
  counts. `--demo` now runs one real workflow (rule gate on a task type no pack
  covers, so the node honestly reports SKIP) and journals it, instead of
  creating empty records only.
- The 流程 page shows that journal: run id, task, status, node count, skipped,
  `resumed_from`, timestamp, and one row per node with its verdict and detail.
  Without a journal the page says 未配置, with no records it says 还没有运行记录.
- `geoops/tests/test_journal.py`: 11 unit tests — recording, duplicate refusal,
  failed and skipped nodes, `resumed_from`, status counts, reload, corrupt and
  duplicated files, a missing directory, limits, and 8 concurrent writers.
- `geoops/tests/test_ui.py` (extended): the runs endpoint serves the journal and
  is 404 when no journal is supplied.
- `geoops/smoke.py` (extended): the console serves the real change run from the
  journal; a duplicate `run_id` is refused.
- `启动布猫测绘智序.cmd` plus desktop and repository shortcuts: double-click
  opens the console, starting the demo server first only when port 8790 is not
  already listening.

### Verification

- `python -m geoops.smoke` → `SMOKE PASS: 73 assertions`, exit code 0
  (Python 3.12.4, vendored kernel `v0.2.2` untouched). Output recorded in
  `docs/SMOKE_OUTPUT.md`.
- `python -m unittest geoops.tests.test_tasks geoops.tests.test_workflow geoops.tests.test_rules geoops.tests.test_rule_nodes geoops.tests.test_store geoops.tests.test_report geoops.tests.test_api_write geoops.tests.test_audit geoops.tests.test_artifacts geoops.tests.test_tokens geoops.tests.test_rule_packs geoops.tests.test_delivery geoops.tests.test_concurrency geoops.tests.test_change geoops.tests.test_journal geoops.tests.test_ui -v`
  → 166 tests, `OK`.

Real per-module counts (re-counted, not estimated): `test_tasks` 12,
`test_workflow` 11, `test_rules` 12, `test_rule_nodes` 7, `test_store` 8,
`test_report` 7, `test_api_write` 13, `test_audit` 10, `test_artifacts` 16,
`test_tokens` 10, `test_rule_packs` 12, `test_delivery` 7,
`test_concurrency` 8, `test_change` 13, `test_journal` 11, `test_ui` 9.

## v0.1.0-beta.3 — 2026-11-09

### Changed

- Vendored kernel `kernel/bumao_core/` synced from Bumao Core `v0.2.0` (commit `f315041`) to `v0.2.2` (commit `06d78fb`).
- 12 kernel files that were absent are now included: the nine `jiancha/` modules, `jiancha/schema/reason_codes.json`, `jiancha/jiancha_canshu.json`, `test_jiancha_loader.py`, and the package `__init__.py` updates.
- 2 kernel files updated in place: `gate_registry.py`, `HOST_CONTRACT.md`.
- The complete vendored kernel is now 25 files, byte-identical to the `v0.2.2` release tree.
- `README.md`: kernel provenance line now points at `v0.2.2` (commit `06d78fb`); version-boundary line now names `v0.1.0-beta.3`.

### Behaviour

- `python -m geoops.smoke` still completes the full no-data pipeline: core surface complete, 4/4 host gates pass, `verify_registration -> True`, workflow PASS, quality checker FAIL/ERROR handling unchanged, three API endpoints return 200/200/404.
- No host module was overwritten; the kernel keeps its own relative imports and the adapter still loads it from `kernel/bumao_core`.

### Version basis

- Normal promotion of the existing release series: `v0.1.0-beta.2` → `v0.1.0-beta.3`.
- No additional `+0.1` was applied for the kernel move: the vendored kernel was already on the `0.2.x` line (`v0.2.0`), so `v0.2.0` → `v0.2.2` stays inside the same `0.2.x` tier instead of crossing into it.

### Verification

- `python -m geoops.smoke` → `SMOKE PASS: 12 assertions`, exit code 0.
- Kernel per-file SHA256 comparison against `v0.2.2`: 25/25 match, 0 missing, 0 extra, 0 mismatch.
- Release asset extracted into a clean directory and the same smoke run was repeated there: `SMOKE PASS: 12 assertions`, exit code 0.

### Assets

- `bumao-geoops-v0.1.0-beta.3.zip`
- `SHA256SUMS`

## Release history

| Version | Date | Kernel | Notes |
| --- | --- | --- | --- |
| v0.1.0-beta.1 | 2026-11-08 | v0.2.0 (`f315041`) | Bootstrap scaffold, first runnable beta |
| v0.1.0-beta.2 | 2026-11-09 | v0.2.0 (`f315041`) | Second beta of the 0.1 series |
| v0.1.0-beta.3 | 2026-11-09 | v0.2.2 (`06d78fb`) | Vendored kernel synced to v0.2.2, full 25-file tree |













