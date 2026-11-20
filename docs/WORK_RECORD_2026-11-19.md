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
- Quality metrics now require matching origins and CRS, not only dimensions and
  cell size; a shifted mask or a CRS mismatch is a refusal before any confusion
  matrix is computed. GeoTIFF masks written by this repo are accepted directly.
- ASCII imports accept ESRI cell-center origins (`xllcenter`/`yllcenter`) and
  normalise them to corners for change detection, profiles and quality metrics;
  a contradictory corner/center pair is refused instead of choosing one.
- Multiband GeoTIFF support: `read_raster_grid(path, band=N)`,
  `detect_changes(..., band=N)`, a workflow node's declared `band` and
  `GET /api/v1/datasets/<id>/profile?band=N` select a real band and refuse an
  out-of-range one; the test fixture is a chunky two-band georeferenced TIFF.
- Dataset re-validation now fails when a sidecar CRS, width, height or band
  count differs from the registered values, not only when the file hash changes.
- GeoTIFF input now reads BigTIFF as well as classic TIFF: 64-bit offsets,
  8-byte IFD counts and LONG8/SLONG8/IFD8 fields are parsed, so a real large
  GeoTIFF can supply dimensions, bounds, CRS and pixels.
- Quality metrics now use the same validated raster reader for ASCII masks:
  BOM, `xllcenter`/`yllcenter` and sidecar CRS are handled consistently, and a
  sidecar CRS mismatch between reference and prediction is refused.
- External tool calls now keep the rendered command, exit code, stdout/stderr,
  timeout and elapsed milliseconds; failed calls remain in the node output and
  Agent `tool_calls` instead of vanishing with the exception.
- GeoTIFF input can also take its CRS from a `<path>.json` sidecar when the
  header has no EPSG GeoKey, so change masks and profiles keep real georeferencing.
- Dataset intake now probes a classic GeoTIFF header even when a sidecar
  supplies the CRS, so width/height/bounds/pixel size are not dropped; a
  header without EPSG is accepted only when the sidecar provides one; when both
  declare different CRSs, the sidecar priority is now visible in `reason`.
- ASCII sidecar CRS: `read_raster_grid` reads `<path>.json` for `crs` and
  optional `crs_model`; EPSG:4326/3857 are inferred when the model is omitted,
  so ASCII input with a sidecar can write a georeferenced GeoTIFF mask.
- Caller-declared accuracy thresholds: `accuracy_thresholds` is validated (known
  metric, 0..1) and a below-minimum metric becomes `professional.accuracy_threshold`
  `FAIL`; no default threshold is invented. API and service tests cover pass and
  fail paths.
- `GET /api/v1/datasets/<id>/profile`: reads real ASCII or GeoTIFF pixels and
  returns dimensions, band count, cell size, origin, bounds, CRS, valid/NODATA
  counts, min/max/mean. An empty raster is a refusal, never a fabricated
  profile.
- A floating-point NaN `GDAL_NODATA` sentinel is excluded consistently by
  profiles, change detection and quality masks instead of counting as valid.
- Change detection now refuses grids whose CRS or CRS model differ, and grids
  where only one side declares a CRS; the Agent profile/change tools accept a
  selected band.
- ASCII change masks write their source CRS/model into a sibling `.json`
  sidecar; quality comparison refuses the same CRS mismatch on reference vs
  predicted masks.
- `SurveyAreaRegistry` and `GET/POST /api/v1/survey-areas`: a survey area
  requires a real project, name, type and CRS; optional bounds must be four
  finite numbers with positive extent.
- GeoTIFF Predictor=2 now wraps at the sample bit width for 8/16/32-bit
  signed or unsigned rows; a wrapped 8-bit row previously decoded above 255.
- A non-default TIFF Orientation is refused rather than silently decoding a
  rotated image as north-up.
- PixelIsPoint GeoTIFFs are read with their footprint shifted half a cell
  around the pixel-centre tiepoint; raster type is reported by the probe.
- Change area on a geographic grid is computed per row on the WGS84 ellipsoid,
  so `changed_area_m2` and `min_area_m2` are real square metres rather than
  square degrees.
- Non-square GeoTIFF cells keep their row height through change detection,
  area, dataset profiles and mask output; ASCII masks refuse that geometry.
- Projected GeoTIFF linear units (GeoKey 3076: metre, foot, US survey foot,
  yard) are converted to square metres for area and written back on the mask;
  unknown declared units are refused rather than silently called metres.
- Archiving now re-checks the deliverable file: a missing file or a sha256
  that no longer matches registration is refused before the status is changed.
  When an archive directory is configured (the console uses `var/archive`),
  archival copies the verified file into its own folder and writes a
  `manifest.json` with hashes and provenance.
- Agent records now validate `max_steps` to 1–16, and the workflow node uses
  that value when it does not declare its own step budget; a node override is
  also restricted to an integer 1–16.
- External tool configuration refuses duplicate `tool_id` entries and
  non-finite timeouts instead of overwriting a tool or passing `nan` to
  `subprocess`.
- Model runtime also reads `var/model-runtime.env` (`KEY=VALUE`, same four
  keys), while real environment variables win; unknown keys are
  `CONFIG_ERROR`, and `status()` exposes the file path, never the key.
- `GET /api/v1/models`, `/api/v1/agents`, `/api/v1/tools` catalog slices.
- `GET /api/v1/execution-events`: flattened run/node events from the real run
  journal, optionally filtered by `task_id`.
- Tests for LZW round-trip, tiled TIFF pixels, GeoTIFF and NODATA profiles,
  GeoTIFF mask output round-trip, survey areas and execution events.

## Verification

- Full suite: `Ran 321 tests in 29.7s`, `OK`.
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
- An automatic shutdown request was blocked by the runtime safety layer; no
  bypass was attempted. Shutdown remains a manual user action.































