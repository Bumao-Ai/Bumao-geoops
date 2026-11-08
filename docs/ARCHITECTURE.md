# Architecture (current state)

This page describes the scaffold as it exists today. It does not describe
planned work.

## Layers

```text
User interaction / API
  GET /api/v1/health
  GET /api/v1/objects/{object_id}

AI and tool integration
  not implemented: no model adapter, no GIS tool adapter

GeoOps domain core
  domain.registry          typed object registration and lookup
  domain.datasets          dataset intake and metadata probe
  workflow                 sequential node execution with records
  quality                  dataset checks with PASS / FAIL / ERROR

Bumao Core (vendored, read-only)
  kernel/bumao_core/engine.py
  kernel/bumao_core/gate_registry.py
  kernel/bumao_core/bumao_core_gates.py
```

## What is implemented

| Entry | Real behavior |
|---|---|
| `geoops/core_adapter` | Loads the vendored kernel from `kernel/bumao_core/`, registers four host gates built from Core templates, and calls `configure`, `register`, `set_expected`, `verify_registration`, `GateRegistry.validate` and `GateRegistry.run_all`. |
| `geoops/domain/registry.py` | Thirteen domain object types, `register`, `get`, `list_by_type`, duplicate-id rejection. In-memory only. |
| `geoops/domain/datasets.py` | `datasets.register(path)` reports file existence, size, SHA-256 and sidecar CRS. Missing input returns `SKIP`; unreadable input returns `ERROR`; the call does not raise. |
| `geoops/workflow/executor.py` | Runs nodes in order, records `PASS` / `FAIL` / `ERROR` / `SKIP` / `SKIPPED`, stops on `FAIL` or `ERROR`, continues on `SKIP`. |
| `geoops/quality/checker.py` | Checks file existence, readability and non-empty CRS. Returns `PASS` / `FAIL` / `ERROR`; an exception is never reported as `PASS`. |
| `geoops/api/app.py` | Two real HTTP endpoints over the domain registry: health and object-by-id. |

## Smoke

```text
python -m geoops.smoke            # no data; structural run only
python -m geoops.smoke --data P   # same pipeline over a user-supplied dataset
```

The no-data run registers transient domain objects, calls the kernel, runs the
workflow, exercises the quality checker with real pass/fail/error paths, and
queries the HTTP API. It requires no imagery. The real output of a local run is
recorded in `docs/SMOKE_OUTPUT.md`.
