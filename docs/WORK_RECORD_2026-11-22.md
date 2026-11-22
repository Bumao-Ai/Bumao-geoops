# Work record — 2026-11-22

Scope: `bumao_geoops` backend, tests and documentation only. The console under
`geoops/web/` is being refactored by another contributor; none of its files,
`README.md` or the launcher assets were modified or committed here. Nothing
was pushed to the remote.

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
- Dataset registration and profile of a georeferenced one-bit mask.
- Profile refusal of a same-size file rewritten after registration.

## Verification

- Full suite: `Ran 382 tests in 28.605s`, `OK`.
- `test_geotiff_pixels`: `Ran 29 tests`, `OK`.
- `test_release`: `Ran 31 tests`, `OK`.
- Smoke: `SMOKE PASS: 73 assertions`.
- Commits: `98b555c`, `3f7485c`, `714ad2e`, `7e8dbd3`, `796e4aa`, `cf13ad1`.
  All local; no push.

## Still not claimed

The fifteen 0.1 acceptance items are still not all met. One-bit support and
profile identity checks are software-path hardening only; they do not replace
the user's real remote-sensing imagery, real model endpoint, real external GIS
tool, real classification/geometry truth samples, review identities, formal
archive disk or production database/object-store/TLS/backup environment. No
synthetic fixture is presented as that evidence.
