# Work record — 2026-11-22

Scope: `bumao_geoops` backend and tests, plus the later console functional
pass recorded at the end of this file. The console's deep-space visual system
was authored by another contributor and is preserved: this pass adds controls
and data flows without replacing that visual system. Nothing was pushed to
the remote.

## Single-band one-bit GeoTIFF

Real change masks are frequently stored as 1-bit TIFFs, while the reader only
accepted 8/16/32/64-bit samples. The reader now handles single-band one-bit
strips and tiles:

- `TAG_FILL_ORDER` is read; only `FillOrder=1` (MSB-first) is accepted. LSB-first
  data is refused rather than silently producing reversed masks.
- `_block_bytes` centralizes strip/tile byte loading and decompression;
  `_unpack_1bit` then expands each row MSB-first with the TIFF row-byte padding,
  and rejects a block shorter than its declared rows.
- `_read_1bit_pixels` assembles full images in spatial row order; edge tiles are
  cropped to the real width/height.
- `_iter_1bit_values` streams one strip or one tile row at a time for profile and
  quality checks, without materializing the whole raster as Python floats.
- Supported compression for one-bit data: none (1), LZW (5), Deflate (8 and
  32946), PackBits (32773). Classic TIFF and BigTIFF both work.
- Explicitly refused: multi-band one-bit, `Predictor != 1`, `SampleFormat != 1`,
  `FillOrder != 1`, and JPEG/JPEG2000 one-bit.

## Dataset profile identity

`DatasetRegistry.profile` previously trusted the file at the registered path.
A same-size replacement after registration could therefore receive statistics
under the old dataset's identity. Profile now compares the registered size and
recomputes the SHA-256 before reading any pixel; a changed file is refused with
`content changed since registration; re-register`. The cost is one extra full
read per profile; correctness is preferred over silently mixing identities.

## Tests added

- One-bit strips across none/LZW/Deflate/PackBits, including profile statistics
  (`30` cells, mean `20/30`).
- Real multi-strip one-bit TIFF with spatial row ordering.
- Real tiled one-bit TIFF, including LZW/Deflate/PackBits compressed tiles.
- Real BigTIFF one-bit strip with 64-bit offsets.
- LSB-first one-bit refusal.
- Two georeferenced one-bit masks driven through `detect_changes`: changed
  cells, projected cell area, one connected patch and patch area.
- One-bit truth and prediction masks through `compare_masks`: TP/FP/FN/TN,
  precision, recall, F1, IoU and pixel accuracy.
- Dataset registration and profile of a georeferenced one-bit mask.
- HTTP registration and profile of the same one-bit mask, including the
  `streamed_blocks` read mode and a passing re-validation.
- HTTP profile refusal of a same-size file rewritten after registration,
  returning `409` instead of conflating integrity failure with a missing
  dataset.
- Profile refusal of a same-size file rewritten after registration.
- Explicit refusal of multi-band and signed one-bit samples.

## Verification

- Full suite: `Ran 388 tests`, `OK`.
- `test_geotiff_pixels`: `Ran 32 tests`, `OK`.
- `test_release`: `Ran 31 tests`, `OK`.
- `test_api_release`: `Ran 16 tests`, `OK`.
- Smoke: `SMOKE PASS: 73 assertions`.
- Commits recorded in this log before the upload pass were rewritten during the
  2026-11-22 sanitization; the pre-rewrite bundle is kept outside the repository.
  Every reachable tree and the tracked worktree now scan with `0` sensitive
  findings, and the legacy launcher is absent from all history.

## Console functional pass

The console keeps its twelve sections and the existing deep-space palette.
The pass makes previously static areas operate against real API data.

### Overview to working sections

- The four overview KPIs carry `data-goto` targets: projects, tasks, rules,
  artifacts.
- One `go(section, jump)` path now drives both the left nav and the KPI
  entries, updates the hash and scrolls the destination into view. KPI entries
  respond to click, Enter and Space and keep a visible focus ring. Left-nav
  clicks use the same jump, so switching sections no longer leaves the old
  scroll offset and clips the new masthead.

### Dataset profile and filtering

- The dataset toolbar gained a live filter over id, path and project/task;
  Esc clears it and an empty result offers a `Clear filter` action.
- The dataset table was reduced to five columns so its actions stay inside the
  card: dataset, project/task, CRS, size/hash, actions. Stats and Validate are
  stacked vertically.
- `Profile` calls the real
  `GET /api/v1/datasets/<id>/profile?band=N`. The full-width profile card shows
  grid, band, cell size, CRS, valid/NODATA/non-finite counts, range, mean,
  footprint, read mode and bounds. The valid percentage, NODATA percentage and
  mean are computed from the API counts; no placeholder numbers are used.
- A single-band ASCII raster asked for `band=2` returns the backend refusal;
  the UI reports `Profile unavailable` instead of inventing statistics.
- The data masthead now says `GeoTIFF header`. The registration note records
  the real capabilities: Classic TIFF and BigTIFF, strips and tiles, 1-bit
  single-band; multi-band 1-bit, FillOrder=2 and JPEG are refused.
- The card note states that Profile reads real pixels and Validate only
  re-probes the hash and CRS without changing the file.

### Quality accuracy

- The quality form now exposes `reference_path`, optional `predicted_path`,
  `synthetic_reference` and five optional thresholds
  (`pixel_accuracy`, `precision`, `recall`, `f1`, `iou`), validated as 0–1.
- These controls are enabled only for `target_type=deliverable`; switching to
  a dataset disables them and explains that the backend refuses that
  combination. A threshold without a reference path is blocked in the browser.
- Target ids are populated from `/api/v1/datasets` and
  `/api/v1/deliverables`; selecting an object fills an empty task id.
- The result card renders PA, precision, recall, F1 and IoU, the TP/FP/FN/TN
  matrix, valid/NODATA/non-finite cells, thresholds, reference and prediction
  paths, and the synthetic-reference flag. A missing reference and an unsupported
  dataset target are shown as distinct states; backend ERROR text is shown as
  ERROR.
- The report table gained an Accuracy column. Report ids are buttons and load
  that report back into the result card. Report ordering is newest first.
- A pre-existing selection bug was fixed: `loadQualityReports` no longer always
  selects `reports[0]`, so a newly generated report is not overwritten by an
  older one.
- The three-column quality check layout now breaks names at explicit `<wbr>`
  points and keeps the status pill and evidence text from overlapping.

### Responsive and bilingual checks

- At 1280 px the data and quality grids stack their working card above the
  form. The dataset table then uses the full 897 px and needs no horizontal
  scroll; the quality result card is 897 px wide and check names get a 168 px
  column.
- At 390 px the page has `overflowX=0`; the profile grid is one column and
  accuracy metrics use three columns. The dataset table scrolls inside its
  card instead of widening the page.
- The English pass covers the new dataset, profile, quality and accuracy
  labels. A browser pass reports no Chinese UI leftovers in the checked
  controls. Backend/user data (dataset label and sample note) stays in its
  original language.

### Verification

- Browser fixture: a real local API built with `create_server`, a five-by-four
  ASCII dataset, a deliverable and a reference mask. Chrome/Puppeteer checks
  covered the 12 sections, four KPI jumps, dataset filter and clear, real
  profile, the deliberate band-2 refusal, dataset/deliverable quality modes,
  a real `POST /api/v1/quality-reports`, 100% PA/F1/IoU, report selection and
  390 px layout. Separate submits proved the browser refuses an out-of-range
  threshold and a threshold without a reference path before calling the API.
- Full suite after this pass: `Ran 388 tests in 31.788s`, `OK`.
- Smoke: `SMOKE PASS: 73 assertions`.
- `node --check geoops/web/ui.js`: pass.
- The only browser console error in the final matrix is the deliberate
  `band=2` 404 used to prove the refusal path.
- Working tree: clean. The frontend and test changes are in the final test
  commit. The sanitized history was uploaded to GitHub on 2026-11-22 as the
  `v0.1.0-beta.4` test build; the final audit reports `0` sensitive findings.
  The current `8790` service still reports an empty dataset/report registry,
  so these new paths were browser-verified against the fixture API, not
  claimed as live-registry evidence on `8790`.
## Still not claimed

The fifteen 0.1 acceptance items are still not all met. One-bit support and
profile identity checks are software-path hardening only; they do not replace
the user's real remote-sensing imagery, real model endpoint, real external GIS
tool, real classification/geometry truth samples, review identities, formal
archive disk or production database/object-store/TLS/backup environment. No
synthetic fixture is presented as that evidence.
