# MediaSensei 1.0.2 engineering audit

## Release status

Ready for a local, single-user MVP release with the native-tool and platform verification limits below. This is a source release: extract, install prerequisites, and use start.bat or sh start.sh. No GitHub repository or hosted Site was published.

## Problems found and fixes implemented

- **Windows startup:** `os.kill(pid, 0)` was used as a liveness probe even though Windows can terminate the target. Replaced it with a read-only process query and bound saved process IDs to creation times. A child-survival regression test covers the original failure.
- **API integration:** a hardcoded browser URL, mismatched smoke-test port, no configurable environment, and a superficial web-page check hid integration failures. Added a build-time API base, aligned launcher ports/configuration, and live browser tests against the API and worker.
- **Misleading offline state:** project/job failures cleared API health. Separated health polling from data errors, categorized network/timeout/HTTP/protocol failures, prevented overlapping polls and stale project responses, and reset project-specific results on switching. Fixed folder-picker setup after conditional mounting and refreshed tabular results when any job advances.
- **Blocking upload endpoints:** synchronous disk/SQLite operations ran in async handlers. Upload handlers now execute in FastAPI's thread pool and share bounded upload storage. Temporary filenames no longer derive from user filenames, avoiding Windows reserved-path problems.
- **ZIP safety and failure consistency:** extraction and catalog writes were interleaved; CRC or later-member failures could leave unqueued assets. Archives are staged and validated before catalog recording. Added path/drive/stream/symlink checks, limits, duplicate-path handling, empty-file handling, corrupt/encrypted errors, and guaranteed staging cleanup. The UI reports skipped entries.
- **Input errors:** unified structured HTTP/validation errors, removed raw request inputs from validation output, added request-size/origin boundaries and configurable CORS.
- **Processing:** fixed eager enum-alias evaluation for Markdown/HTML and NDJSON/SQLite aliases. Invalid image/OCR analyses now fail jobs rather than reporting success. Bounded DOCX XML expansion before allocation. Corrected the minimum Pillow version used by image hashing.
- **Jobs:** renewed leases during long-running items and refreshed hardware pressure readings between jobs. Added UI pause/resume/cancel/retry controls. Retained cached processing, scheduling, and persistent job architecture.
- **Other reliability:** unique temporary dataset-download archives avoid concurrent download collisions; log reads are bounded; plugin execution rejects untrusted source fingerprints before importing code.
- **Dependencies/release:** patched frontend vulnerabilities and matching peers, pinned tested Python constraints, aligned product metadata to 1.0.1, restored missing Unix launchers, added setup/development scripts, fixed environment ignore rules, strengthened bundle checks, and added cross-platform CI.

## Architecture assessment

The SQLite WAL catalog, immutable content-addressed originals, explicit processing adapters, and separate worker are appropriate for a single-user MVP. Existing product behavior and the Vinext/React presentation have been preserved. Upload/configuration modules now provide clearer boundaries.

The API and main UI remain large adapters. Catalog lists and several parsers materialize complete datasets, so this is not a distributed or arbitrary-size data platform. A future iteration should add pagination, streaming table profiles, app-factory dependency injection, and smaller feature-level UI/router modules. SQLite, disk writes, and job enqueueing do not form a single cross-resource transaction; catastrophic disk/database failures can still need operator recovery. This audit does not claim exhaustive proof of every possible failure.

## Feature inventory and verification

- Projects: create/list/switch; API persistence; browser creation and reload.
- Imports: single/multi-file and ZIP; spaces/Unicode; missing extensions; invalid/empty/oversized data; nested folders; duplicate names; traversal, drive/stream paths, CRC corruption and expansion limits.
- Images: inspection, thumbnails, transforms, quarantine/reactivation, malformed-image failure; original/derived downloads.
- Documents: indexing, local lexical/hash-vector retrieval and format aliases; browser search. No learned semantic embedding service is required.
- Tables: CSV ingestion, query/filter validation, export/download; format alias regression.
- Dataset tools: duplicate scan, deterministic split, leakage and export/download.
- Jobs: persistent state/events, error reporting, lease renewal; stale process identity and safe health checks.
- System/plugins: health, OpenAPI, CORS, runtime inventory/logs, rescan; trust rejection regression.
- Frontend: configured API contracts, FormData ZIP routing, timeout/network/HTTP errors, production build, live browser navigation, API/data-error isolation, upload recovery and mobile navigation.

## Original 1.0.1 verification results

- Backend regression run: 35 tests passed; 1 FFmpeg integration test skipped because binaries were unavailable. The additional long-running lease test initially had a fixture type error (Project object rather than ID); after correcting the test fixture it passed separately. Final aggregate: **36 backend tests passed, 1 skipped**.
- Client contract suite: **8 passed**, covering API base/download URLs, multipart single/ZIP routes, server errors, network failures, malformed responses and timeouts.
- TypeScript: `npm run typecheck` passed. Frontend lint and Python Ruff checks passed after resolving an import-order finding.
- `npm run build` passed on Node 24.16.0. Patched npm dependency tree: **0 reported vulnerabilities**. Python `pip check`: no broken requirements.
- Live production browser smoke: passed API connection, project creation, single/multiple-file uploads, ZIP extraction and real worker processing, Library, document retrieval, Jobs, System/plugin rescan, HTTP failure/health isolation, invalid upload recovery, reload persistence, and mobile navigation. **No browser page exceptions.**
- API health and OpenAPI, CORS/origin restrictions, upload/request limits, invalid/empty/corrupt files, document/table aliases, image transforms, exports and persistence are covered by the backend suite.
- Native Windows launcher: dependency setup, production build, and readiness checks passed with web, API, and worker running together. Windows ZIP and Linux/macOS tarballs passed release manifest verification (200 files each, version 1.0.1); SHA-256 checksums accompany the bundles.

## Remaining limitations

- FFmpeg/ffprobe and Tesseract are not installed in the audit environment. The real FFmpeg test is explicitly skipped; native media transcoding and OCR success are not certified here. Missing tools produce visible job errors. Install them before releasing those capabilities to users who require them.
- Hugging Face/Kaggle and remote acquisition were inspected but live external imports were not run; credentials, remote policy, service availability, and large downloads are outside deterministic local QA.
- Windows was executed locally. macOS/Linux scripts and CI are included, but native execution on those operating systems remains a release-owner CI check.
- No load/soak test at multi-gigabyte limits was performed; bounded synthetic limits test rejection paths. Keep configured limits appropriate to available RAM/disk.
- No user authentication or full OS sandbox for plugins: local trusted workstation use only. Installed/approved Python plugins are executable code.
- The framework is Vinext beta; its build prints non-fatal route classification information. Historical Sites database artifacts remain for compatibility and are not the catalog used by the MVP.

## Important changed files

| File | Purpose |
|---|---|
| `apps/api/main.py` | Health, safe upload integration, structured errors, request handling, export isolation |
| `apps/api/config.py`, `middleware.py`, `uploads.py` | Validated settings, request/origin limits, safe upload and ZIP service |
| `lib/core-api.ts`, `components/mediasensei-app.tsx` | Configurable API, errors/timeouts, reliable state and recovery controls |
| `packages/core/src/mediasensei/domain/documents.py`, `tabular.py` | Supported extension aliases |
| `packages/core/src/mediasensei/infrastructure/images.py`, `documents.py`, `worker.py`, `plugins.py` | Processing failures, resource bounds, leases, trust ordering |
| `scripts/mediasensei_launcher.py` | Safe process health/ownership, setup, aligned services and ports |
| `scripts/e2e_smoke.py`, `browser-smoke.mjs`, `run-python.mjs` | Production browser integration and correct Python selection |
| `tests/test_audit_regressions.py`, `core-api.test.mjs`, `test_real_app_flow.py` | Critical regression coverage |
| `package*.json`, `pyproject.toml`, `requirements-lock.txt`, `vite.config.ts` | Patched dependencies, reproducibility, version/API configuration |
| `scripts/release.py`, `.github/workflows/ci.yml`, launch scripts | Complete source bundles and platform verification |
| `.env.example`, `.gitignore`, `README.md`, `CHANGELOG.md` | Setup, configuration, release notes and operating limits |

## Sources used for dependency/runtime decisions

- FastAPI's [thread-pool behavior for synchronous handlers](https://fastapi.tiangolo.com/async/).
- React's [server-function denial-of-service advisory](https://github.com/advisories/GHSA-wx67-qw84-cm4g).
- Vite's [Windows filesystem-boundary advisory](https://github.com/advisories/GHSA-fx2h-pf6j-xcff).
- The npm audit API and resolved package metadata were checked against the actual dependency tree.

## 1.0.2 startup follow-up (2026-09-07)

The user reported startup failure and no browser opening from an installation under `S:\AE TEST`. The supplied API/worker logs showed startup; the web log was empty. The original readiness failure did not reproduce when the complete launcher was rerun, so its precise cause is not established.

A separate logging defect was reproduced: spawning `npm.cmd --version` with DETACHED_PROCESS returned success but captured no output. Removing that flag while keeping CREATE_NO_WINDOW captured the version correctly. This fixes the diagnostic blind spot without opening service windows.

The patch also saves launcher messages and per-service readiness results, reports exited processes immediately, bypasses HTTP proxies for loopback probes, and raises the default startup allowance from 60 to 180 seconds (configurable from 10 to 1800). Browser-opening failures leave healthy services running and print a manual URL.

Four focused regression tests pass: readiness after 75 simulated seconds, immediate failure on an exited web process, persistent connection-error details on timeout, and actual Windows npm log capture in a path containing spaces. Ruff passes for both changed Python files. Earlier full-application results above are from 1.0.1 and are not claimed as a fresh full-suite run for this patch.

Final 1.0.2 validation: dependency refresh succeeded with zero npm vulnerabilities; the production build passed; the full Windows launcher started API, worker, and web. Browser checks returned HTTP 200 for both web and API, version 1.0.2, visible API online, and no page exceptions. The repaired web log contains Wrangler readiness and request output. A subsequent launcher invocation reused the healthy services and requested the default browser. User workspace and settings were preserved.
