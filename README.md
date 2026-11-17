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
- A three-layer quality service: file/structure checks (existence, hash, size), spatial checks (CRS, dimensions, bounds when recorded), and professional verification that can only pass with a human sample and a written note. Without that note the aggregate is `PARTIAL`, never `PASS`. Reports are written to `var/quality/` and registered as `QualityReport` objects.
- Deliverables are real files with a recorded sha256 and size; only an approving review flips them to `accepted`, and only then may they be archived.
- Real pixel-level change detection on two ASCII grids (threshold, 4-neighbour patches, minimum area, written mask).
- An HTTP API with health, overview, object-by-id, task list, run journal, projects, datasets (and `validate`), catalog, deliverables (and `archive`), quality reports, settings, reviews, task trace, rule packs, artifact index, audit and the HTML console at `/ui/`.
- `--no-data` smoke mode that runs without any dataset.
- **Not included today:** a real AI model runtime, an external GIS tool (GDAL/QGIS/Rasterio are not installed), map views, a login page, publishing, and workflow-definition CRUD in the console (run history and real execution are present; definitions are still file/API-level). The GeoTIFF reader is header-only and classic-TIFF-only; it does not decode pixels.
- Real remote-sensing imagery and models are not bundled. You supply them.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the current layers, and [docs/ui-preview/](docs/ui-preview/) for screenshots of the console as it actually renders.

- Engineering tier: core. The decision, its criteria and the gaps that remain are recorded in [docs/ENGINEERING_TIER.md](docs/ENGINEERING_TIER.md). Tier is not release readiness.

## Run

Requirements: Python 3.12+. The kernel is vendored, so no external Bumao Core checkout is required.

Run the API and the console:

```bash
python -m geoops.api --demo
```

The console is then at <http://127.0.0.1:8787/ui/>. Without `--tokens` the server is read-only; pass `--tokens file.json`, `--audit audit.jsonl`, `--artifacts artifacts.json` and `--runs runs.jsonl` to use real files.

On Windows, `启动布猫测绘智序.cmd` (and the `布猫·测绘智序` shortcut on the desktop) starts the demo server on port 8790 only when nothing is listening there, then opens the console in the browser.

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
python -m unittest geoops.tests.test_tasks geoops.tests.test_workflow geoops.tests.test_rules geoops.tests.test_rule_nodes geoops.tests.test_store geoops.tests.test_report geoops.tests.test_api_write geoops.tests.test_audit geoops.tests.test_artifacts geoops.tests.test_tokens geoops.tests.test_rule_packs geoops.tests.test_delivery geoops.tests.test_concurrency geoops.tests.test_change geoops.tests.test_journal geoops.tests.test_ui geoops.tests.test_release geoops.tests.test_api_release geoops.tests.test_geotiff geoops.tests.test_quality_deliverable geoops.tests.test_api_quality -v
```

206 tests, standard library only. The smoke run makes 73 assertions.

## Version boundary

The `0.1` in `v0.1.0-beta.3` is a version series rather than a completeness promise — a beta means the scaffold runs and somebody else can start it, while a formal `0.1.0` requires all fifteen acceptance criteria in the 0.1 specification, including a real model, a real GIS tool and full reverse traceability from deliverable to source data, model, tool, rules and review.

## Status

This is an ongoing exploration project. It may be paused or shelved at any time, and no delivery time is promised.

License: Apache License 2.0. See [LICENSE](LICENSE).
