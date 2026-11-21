# Work record — 2026-11-21

Scope: `bumao_geoops` backend, tests and documentation only. The console under
`geoops/web/` is being refactored by another contributor; none of its files,
`README.md` or the launcher assets were modified or committed here. Nothing
was pushed to the remote.

## GeoTIFF correctness

- A projected GeoTIFF normally declares both its base geographic GeoKey (`2048`)
  and its projected GeoKey (`3072`). The projected key now always decides the
  raster CRS; key order can no longer label a projected image as `EPSG:4326`.
- A user-defined CRS key value `32767` is refused as unsupported instead of
  being reported as a fake EPSG code, and a GeoKey directory whose declared
  key count is longer than its data is a header error.
- A malformed TIFF header or probe now closes its memory map on every path, so
  a failed open does not keep a Windows file lock alive through a traceback.
- `probe_geotiff` reports the TIFF compression code. A JPEG/JPEG2000 dataset
  profile is labelled `read_mode=pillow_full_image`; only decoded/streamed
  layouts claim `streamed_blocks`.

## Model runtime and quality guards

- `max_tokens` must be a real whole number: `1.5` is refused instead of being
  truncated to `1`, and booleans are refused for `max_tokens`, `temperature`
  and `timeout_s`.
- An invalid `GEOOPS_MODEL_TIMEOUT` is reported as `CONFIG_ERROR`; it no
  longer becomes 60 seconds without notice.
- A negative `compare_masks` threshold is refused: on a 0/1 mask it would count
  every background cell as positive and produce a meaningless matrix.

## Path and identity safety

- Object ids are used as archive folder names. `DomainRegistry.register` and
  snapshot restore now require a plain name and refuse `../escape`, separators,
  NUL and control characters.
- A relative `ArtifactStore` path must resolve inside the store root; `../` can
  no longer register a file outside it.

## Verification

- Full suite: `Ran 375 tests in 31.698s`, `OK`.
- Smoke: `SMOKE PASS: 73 assertions`.
- Working tree after the backend work contained only the other contributor's
  front-end changes; no backend file was left uncommitted.

## Still not claimed

The fifteen 0.1 acceptance items are still not all met. This session added
software-path guards and corrected CRS interpretation, but it did not receive
the real remote-sensing imagery, real model endpoint, real external GIS tool,
real accuracy truth samples, review identities, formal archive disk or
production database/object-store/TLS/backup environment required for formal
acceptance. No synthetic sample is presented as that evidence.
