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

- A runnable scaffold with four real entries: a Core adapter, a domain registry, a sequential workflow executor and a dataset quality checker.
- A small HTTP API with health and object-by-id endpoints.
- `--no-data` smoke mode that runs without any dataset.
- **Not included today:** real AI models, real GIS tools, multi-scenario support, persistent storage, a frontend.
- Real remote-sensing imagery and models are not bundled. You supply them.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the current layers.

## Run

Requirements: Python 3.12+. The kernel is vendored, so no external Bumao Core checkout is required.

Run the no-data smoke:

```bash
python -m geoops.smoke
```

With a real dataset (the sidecar `<path>.json` supplies CRS):

```bash
python -m geoops.smoke --data /path/to/imagery.tif
```

The no-data mode is the default. It registers transient domain objects, calls the kernel, runs a three-node workflow, exercises the quality checker and queries the API. The real output is in [docs/SMOKE_OUTPUT.md](docs/SMOKE_OUTPUT.md).

## Version boundary

The `0.1` in `v0.1.0-beta.3` is a version series rather than a completeness promise — a beta means the scaffold runs and somebody else can start it, while a formal `0.1.0` requires all fifteen acceptance criteria in the 0.1 specification, including a real model, a real GIS tool and full reverse traceability from deliverable to source data, model, tool, rules and review.

## Status

This is an ongoing exploration project. It may be paused or shelved at any time, and no delivery time is promised.

License: Apache License 2.0. See [LICENSE](LICENSE).
