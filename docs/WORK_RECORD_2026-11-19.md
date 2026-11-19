# Work record — 2026-11-19

Scope: `bumao_geoops` backend and documentation only. The console in
`geoops/web/` is being refactored by another contributor and was not modified
here.

## Added

- Classic GeoTIFF pixel decoding for LZW and tiled layouts, in addition to the
  existing uncompressed/Deflate strip support. LZW uses MSB-first codes with
  the TIFF early code-width change; predictor reversal is applied per block
  (strip or tile), with chunky or separate-planar bands. JPEG/JPEG2000
  decode through optional Pillow; when Pillow is absent they remain explicit
  refusals.
- TIFF parser tolerance: unsupported ancillary field types (such as
  JPEGTables) are skipped instead of failing a file whose critical tags are
  valid; required tags still fail explicitly when absent.
- GeoTIFF mask output: `write_change_mask` writes ASCII for `.asc`, or a real
  one-band float32 classic GeoTIFF for `.tif`/`.tiff` when the source carries
  `crs` and `crs_model`. The writer emits ModelPixelScale, ModelTiepoint, one
  EPSG GeoKey and GDAL_NODATA; missing source CRS is refused, not guessed.
- GeoTIFF reader now returns `crs`/`crs_model` alongside size and georeferencing,
  so a change mask can reuse the source CRS.
- `GET /api/v1/datasets/<id>/profile`: reads real ASCII or GeoTIFF pixels and
  returns dimensions, band count, cell size, origin, bounds, CRS, valid/NODATA
  counts, min/max/mean. An empty raster is a refusal, never a fabricated
  profile.
- `SurveyAreaRegistry` and `GET/POST /api/v1/survey-areas`: a survey area
  requires a real project, name, type and CRS; optional bounds must be four
  finite numbers with positive extent.
- `GET /api/v1/models`, `/api/v1/agents`, `/api/v1/tools` catalog slices.
- `GET /api/v1/execution-events`: flattened run/node events from the real run
  journal, optionally filtered by `task_id`.
- Tests for LZW round-trip, tiled TIFF pixels, GeoTIFF and NODATA profiles,
  GeoTIFF mask output round-trip, survey areas and execution events.

## Verification

- Full suite: `Ran 281 tests in 27.5s`, `OK`.
- Smoke: `SMOKE PASS: 73 assertions`.
- GeoTIFF writer round-trip: 2×2 float32 mask read back with EPSG:4326,
  pixel size 10 and bounds `[500000, 4500000, 500020, 4500020]`; NODATA
  `-9999` preserved.
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





