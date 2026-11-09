# Changelog

All notable changes to this project are documented in this file.

## v0.1.0-beta.3 — 2026-11-09

### Changed

- Vendored kernel `kernel/bumao_core/` synced from Bumao Core `v0.2.0` (commit `f315041`) to `v0.2.2` (commit `06d78fb`).
- 12 kernel files that were absent are now included: the nine `jiancha/` modules, `jiancha/schema/reason_codes.json`, `jiancha/jiancha_canshu.json`, `test_jiancha_loader.py`, and the package `__init__.py` updates.
- 2 kernel files updated in place: `gate_registry.py`, `HOST_CONTRACT.md`.
- The complete vendored kernel is now 25 files, byte-identical to the `v0.2.2` release tree.
- `README.md`: kernel provenance line now points at `v0.2.2` (commit `06d78fb`); version-boundary line now names `v0.1.0-beta.3`.

### Behaviour

- `python -m geoops.smoke` still completes the full no-data pipeline: core surface complete, 4/4 host gates pass, `verify_registration -> True`, workflow PASS, quality checker FAIL/ERROR handling unchanged, three API endpoints return 200/200/404.
- No host module was overwritten; the kernel keeps its own relative imports and the adapter still loads it from `kernel/bumao_core`.

### Version basis

- Normal promotion of the existing release series: `v0.1.0-beta.2` → `v0.1.0-beta.3`.
- No additional `+0.1` was applied for the kernel move: the vendored kernel was already on the `0.2.x` line (`v0.2.0`), so `v0.2.0` → `v0.2.2` stays inside the same `0.2.x` tier instead of crossing into it.

### Verification

- `python -m geoops.smoke` → `SMOKE PASS: 12 assertions`, exit code 0.
- Kernel per-file SHA256 comparison against `v0.2.2`: 25/25 match, 0 missing, 0 extra, 0 mismatch.
- Release asset extracted into a clean directory and the same smoke run was repeated there: `SMOKE PASS: 12 assertions`, exit code 0.

### Assets

- `bumao-geoops-v0.1.0-beta.3.zip`
- `SHA256SUMS`

## Release history

| Version | Date | Kernel | Notes |
| --- | --- | --- | --- |
| v0.1.0-beta.1 | 2026-11-08 | v0.2.0 (`f315041`) | Bootstrap scaffold, first runnable beta |
| v0.1.0-beta.2 | 2026-11-09 | v0.2.0 (`f315041`) | Second beta of the 0.1 series |
| v0.1.0-beta.3 | 2026-11-09 | v0.2.2 (`06d78fb`) | Vendored kernel synced to v0.2.2, full 25-file tree |
