# Batch 4 â€” release certification

Status: local release certification completed as 2.0.0-rc.1 on 2026-09-10. Batch 3 alpha.4 is preserved separately. Native macOS/Linux qualification remains unexecuted.

Recovered scope: regression, browser acceptance, migration/restart verification, deterministic packaging, manifests/checksums, version synchronization, security/release documentation and realistic platform evidence. This is release engineering, with no additional product feature expansion.

## Acceptance ledger

- [x] Full backend regression and focused release tests
- [x] TypeScript, frontend lint, Ruff, client contracts and production build
- [x] Batch 1, 2 and 3 acceptance against production
- [x] Existing-catalog migration, API/worker restart and persisted output hashes
- [x] Deterministic platform archives, tamper rejection and secret/artifact exclusions
- [x] Wheel/source distribution verification and clean installed-package execution
- [x] Synchronized versions, security/release guidance and checksummed deliverables

Platform claims are limited to actual execution. Windows is available on this host; Linux/macOS CI configuration and source packaging are not substitutes for native certification. Authenticated remote provider tests require an actual authorized provider dataset and credentials; controlled provider tests are reported separately.


## Exact acceptance evidence

| Gate | Executed result |
|---|---|
| Full Python regression | 186 passed, 0 failed, 0 skipped; 110.53 seconds |
| Focused release tests | 11 passed; deterministic Windows/Linux/macOS rebuilds, tampering, unsafe paths, duplicate names, tar links, malformed manifests and additive catalog migration |
| Batch 3 focused native/integration | 19 passed, zero skips; real System.Speech and whisper.cpp worker outputs |
| Client contracts | 8 passed, zero skips |
| TypeScript, frontend lint, Ruff | Passed |
| Production build | Passed |
| Batch 1 production browser | 20 checks; zero page errors |
| Batch 2 production browser | 13 checks; zero page errors |
| Batch 3 production browser | 8 checks; zero page errors |
| API/worker restart | 8 checks, including persisted jobs, output hashes, models and scripts |
| Clean installed wheel | 6 checks from a separate venv, isolated Python mode outside the checkout; bundled native script and real durable model training |
| Installed dependencies / package metadata | pip check clean; wheel and sdist pass Twine |
| Distribution | Three verified source archives, embedded manifests and SHA256SUMS; final archive rebuild comparison recorded in release-verification.json |

Python 3.12.14, Node 24.19.0, FFmpeg/ffprobe 9.0.1, Windows native OCR/System.Speech, native Windows Credential Manager, whisper.cpp b4938 and tiny.en were exercised. Browser used Microsoft Edge through Playwright. Native binary/model hashes are recorded with the delivered evidence. Two upstream FastAPI/Starlette test-client deprecation warnings remain; no test assertions were removed or weakened.

## Platform and provider limits

Windows is the only native operating system executed. This host has no callable WSL or Docker runtime. Linux/macOS archives were built, checksum-verified and rebuilt deterministically on Windows; the CI matrix was updated but not run remotely. Windows-only speech reports unavailable elsewhere. Native macOS/Linux keyrings and non-English ASR were not certified. No authenticated remote dataset was downloaded; consent, revocation and error redaction used controlled provider adapters.

The original deleted Phase 11–14 wording remains unavailable. Batch 3 implements the recovered/reconstructed scope documented before implementation: lexical fitted models, supervised language classification and a restricted operation-call Playground, not general Python or neural semantic embedding models. No hosted site, repository or release was published. Artifacts are unsigned; SHA-256 checksums do not establish publisher identity.

## Changed files and delivery boundary

Batch 4 changes scripts/release.py, scripts/verify-persistence.py, scripts/verify-installed-core.py, tests/test_batch_four.py, portable browser/fixture selection, CI, version metadata and release/security documents. ADR 0005 explains the release-candidate choice. The full source-level changed-file map against the supplied DOCS.zip is delivered in changed-files.json.

All local implementation and acceptance work for Batches 2–4 is closed. Future work is owner-led platform/provider qualification and signing/publication. Existing private workspace data was not used for acceptance: tests and browser fixtures ran in isolated synthetic workspaces.
