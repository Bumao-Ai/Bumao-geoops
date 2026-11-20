# Bumao GeoOps

An exploration project, in progress. It may be paused or shelved at any time; no delivery timeline is promised.

**Bumao GeoOps is a governance layer for AI-assisted surveying work.** Models, agents and professional tools operate under one rule set, so tasks, permissions, tool calls and deliverables are constrained, checked and traceable.

The first intended scenario is land-use classification and change investigation from remote-sensing imagery: task creation, data intake, AI execution, rule checks, quality review and archive in one chain.

![Bumao GeoOps icon](assets/bumao-geoops-icon.jpg)

*Icon: a survey instrument (total station / theodolite) on a tripod standing over a topographic map, with a blue-to-green gradient and a starburst on the right. It stands for measurement and field operations on terrain data, not a map viewer.*

## Why it is needed

AI is already part of survey work, but tasks, permissions, tool calls and deliverable quality rarely share one constraint system or one evidence trail. Quality is watched by people, and when something goes wrong it is hard to trace back.

## Built on Bumao Core

Bumao Core provides general governance: rule execution, gates, evidence and audit. GeoOps does only the survey domain and does not copy the kernel.

The kernel is vendored at `kernel/bumao_core/`: synced from Bumao Core `v0.2.2` (commit `06d78fb`, 25 files byte-identical). GeoOps adaptation lives only in `geoops/core_adapter/`; no survey business code is added to the kernel. Cloning this repository is enough to run the scaffold.

## What exists today

- A console with twelve real sections and the HX 书香 v2.0 visual system: overview, projects, tasks, AI resources, data, workflow runs, rules, quality, deliverables, reviews, trace/audit and settings. Project registration, dataset re-validation, catalog registration, deliverable registration/archive, quality checks and review submission are backed by permission-gated endpoints with an audit trail.
- A three-layer quality service: file/structure checks (existence, hash, size), spatial checks (CRS, dimensions, bounds when recorded), and professional verification that can only pass with a human sample and a written note. Without that note the aggregate is `PARTIAL`, never `PASS`. Reports are written to `var/quality/` and registered as `QualityReport` objects. ASCII or GeoTIFF mask accuracy can add a real TP/FP/FN/TN confusion matrix with pixel accuracy, precision, recall, F1 and IoU; mismatched origin or CRS is refused, and caller-declared minimum thresholds turn a below-threshold metric into `FAIL`; no threshold is invented by the server.
- Deliverables are real files with a recorded sha256 and size; only an approving review flips them to `accepted`, and only then may they be archived.
- A real OpenAI-compatible model runtime: any endpoint exposing `POST /chat/completions` can be configured with `GEOOPS_MODEL_BASE_URL`, `GEOOPS_MODEL_API_KEY` and `GEOOPS_MODEL_NAME`. The console shows `READY` / `NOT_CONFIGURED`, can send a real probe and a real prompt, and reports the provider's reply, model, latency and token usage. No endpoint is bundled and no reply is fabricated. See [docs/MODEL_RUNTIME.md](docs/MODEL_RUNTIME.md).
- Real pixel-level change detection on two aligned rasters: ESRI ASCII (corner or cell-center origin) and classic GeoTIFF (uncompressed, LZW or Deflate, strip or tiled, chunky or separate-planar bands, 8/16/32-bit; JPEG/JPEG2000 via optional Pillow). Threshold, 4-neighbour patches, minimum area, written ASCII or one-band float32 GeoTIFF mask with the source georeferencing.
- A workflow engine over `var/workflows.json`: typed nodes, real node actions, an Agent JSON-plan loop with declared-tool whitelist and real builtin tool calls, `inputs` aliases, retry and failure policy, execute/resume with node outputs, run journal and structured trace. See [docs/WORKFLOW_ENGINE.md](docs/WORKFLOW_ENGINE.md).
- An HTTP API with health, overview, object-by-id, task list, run journal and flattened execution events, projects and validated survey areas, datasets (including `validate` and a real `/profile` pixel summary), catalog, deliverables (and `archive`, plus `POST /deliverables/<id>/artifacts` for real-file binding), quality reports, settings, reviews, task trace, rule packs, artifact index, audit and the HTML console at `/ui/`.
- `--no-data` smoke mode that runs without any dataset.
- **Not included today:** a bundled model endpoint (the runtime is real, but you must point it at your own compatible endpoint), an installed GDAL/QGIS/Rasterio binary (the `external:<id>` adapter can run one only when you configure its path in `var/external-tools.json`), map views, a login page, publishing, and workflow-definition CRUD in the console (run history and real execution are present; definitions are still file/API-level). GeoTIFF support is real pixel decoding for uncompressed/LZW/Deflate strip and tile files with chunky or separate-planar bands, plus JPEG/JPEG2000 through optional Pillow; mask output is uncompressed one-band float32 GeoTIFF; BigTIFF and reprojection remain out of scope.
- Real remote-sensing imagery and model endpoints are not bundled. You supply them.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the current layers, [docs/MODEL_RUNTIME.md](docs/MODEL_RUNTIME.md) for model connection, [docs/WORKFLOW_ENGINE.md](docs/WORKFLOW_ENGINE.md) for definition execution and resume, [docs/USER_INPUT_CHECKLIST.md](docs/USER_INPUT_CHECKLIST.md) for the assets only you can supply, and [docs/ui-preview/](docs/ui-preview/) for screenshots of the console as it actually renders.

- Engineering tier: core. The decision, its criteria and the gaps that remain are recorded in [docs/ENGINEERING_TIER.md](docs/ENGINEERING_TIER.md). Tier is not release readiness.

## Run

Requirements: Python 3.12+. The kernel is vendored, so no external Bumao Core checkout is required.

Run the API and the console:

```bash
python -m geoops.api --demo
```

The console is then at <http://127.0.0.1:8787/ui/>. Without `--tokens` the server is read-only; pass `--tokens file.json`, `--audit audit.jsonl`, `--artifacts artifacts.json` and `--runs runs.jsonl` to use real files.

On Windows, `启动布猫测绘智序.cmd` (and the `布猫·测绘智序` shortcut on the desktop) starts the demo server on port 8790 only when nothing is listening there, then opens the console in the browser. When `var\console-tokens.json` exists it is passed with `--tokens`, so the local token in `var\console-token.txt` can use write and `model:invoke` endpoints; without that file the server is read-only.

Run the no-data smoke:

```bash
python -m geoops.smoke
```

With a real dataset (the sidecar `<path>.json` supplies CRS):

```bash
python -m geoops.smoke --data /path/to/imagery.tif
```

The no-data mode is the default. It registers transient domain objects, calls the kernel, drives the task state machine, runs a three-node workflow, exercises the quality checker and queries the API. The real output is in [docs/SMOKE_OUTPUT.md](docs/SMOKE_OUTPUT.md).

Run the unit tests:

```bash
python -m unittest discover -s geoops\tests -t .
```

288 tests; JPEG-TIFF decoding additionally uses Pillow when installed. The smoke run makes 73 assertions.

## Version boundary

The `0.1` in `v0.1.0-beta.3` is a version series rather than a completeness promise — a beta means the scaffold runs and somebody else can start it, while a formal `0.1.0` requires all fifteen acceptance criteria in the 0.1 specification, including a real model, a real GIS tool and full reverse traceability from deliverable to source data, model, tool, rules and review.

## Status

This is an ongoing exploration project. It may be paused or shelved at any time, and no delivery time is promised.

License: Apache License 2.0. See [LICENSE](LICENSE).
