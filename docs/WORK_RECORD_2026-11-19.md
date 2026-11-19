# Work record — 2026-11-19

Scope: `bumao_geoops` backend and documentation only. The console in
`geoops/web/` is being refactored by another contributor and was not modified
here.

## Added

- Classic GeoTIFF pixel decoding for LZW and tiled layouts, in addition to the
  existing uncompressed/Deflate strip support. LZW uses MSB-first codes with
  the TIFF early code-width change; predictor reversal is applied per block
  (strip or tile), with chunky or separate-planar bands. JPEG/JPEG2000
  remains an explicit refusal.
- `GET /api/v1/datasets/<id>/profile`: reads real ASCII or GeoTIFF pixels and
  returns dimensions, band count, cell size, origin, valid/NODATA counts,
  min/max/mean. An empty raster is a refusal, never a fabricated profile.
- `SurveyAreaRegistry` and `GET/POST /api/v1/survey-areas`: a survey area
  requires a real project, name, type and CRS; optional bounds must be four
  finite numbers with positive extent.
- `GET /api/v1/models`, `/api/v1/agents`, `/api/v1/tools` catalog slices.
- `GET /api/v1/execution-events`: flattened run/node events from the real run
  journal, optionally filtered by `task_id`.
- Tests for LZW round-trip, tiled TIFF pixels, GeoTIFF and NODATA profiles,
  survey areas and execution events.

## Verification

- Full suite: `Ran 276 tests in 26.2s`, `OK`.
- Smoke: `SMOKE PASS: 73 assertions`.
- Temporary-port API check: `/api/v1/health` = `ok`; `/api/v1/survey-areas` and
  `/api/v1/models` routed correctly.
- Live service on `127.0.0.1:8790` was restarted with the current code; `/ui/`
  returned 200, `/api/v1/survey-areas` and `/api/v1/execution-events` responded,
  and a real 2×2 ASCII dataset registered through the API returned a profile
  of `ncols=2`, `nrows=2`, `valid_cells=4`, `min=1`, `max=4`, `mean=2.5`.

## Still blocked or not claimed

- Real model endpoint remains `NOT_CONFIGURED`; no endpoint, key or model id
  was supplied.
- Real imagery, ground-truth samples, GDAL/QGIS and formal review accounts are
  still required for the remaining 0.1 acceptance items.
- The requested 23:25 shutdown was not executed; run it manually at the
  requested time.


