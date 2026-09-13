# Batch 2 delivery checklist

Scope: phases 7â€“10 of the MediaSensei 2.0 master specification. Batch 1 and all four themes remain supported.

- [x] Image inspection, metadata, quality/distributions, OCR, duplicates and dataset controls
- [x] Parameterized image transforms with before/after previews and immutable outputs
- [x] Video player, metadata, trim/transcode/FPS, frame sampling, scene detection and contact sheets
- [x] Audio player, waveform/spectrogram, trim/convert/resample/channels, loudness, silence and segmentation
- [x] Document structure, cleanup, four chunk strategies, quality, embeddings, retrieval and complete RAG bundles
- [x] Editable acquisition plan, explicit network consent, test/start, progress, review and pause/resume/cancel
- [x] Focused backend, native media and browser QA; Batch 1 regression checks
- [x] Versioned source archive, checksum, release verification and updated documentation

Evidence is recorded here as checks finish. Batch 3 and final certification remain separate.

## Acceptance evidence — 2026-09-09

Backend: 156 passed, zero skipped (61.58 seconds). Focused initial run: 18 passed; native/OCR selection: 25 passed; additional concurrent-snapshot check: 1 passed. Separate-process replay: 2 passed. Eight client tests, TypeScript, Ruff, frontend lint and production build passed. Batch 1 browser: 20 checks; Batch 2 production browser: 13 checks with loaded media players and downloaded ZIPs. API/worker restart: 6 checks passed. Source archives include version agreement, manifests and SHA-256 verification.

Fixes: implicit EXIF/GPS retention, pre-rotation image bounds, consistent RAG document/index snapshots, deterministic asset/player selection, development watcher isolation, fresh workbench Python installation and stale documentation. Existing replay/player assertions remain intact.

For browser fixtures, set MEDIASENSEI_WORKSPACE to an isolated audit workspace and configure FFmpeg/ffprobe; run scripts/create-batch-two-fixtures.py, start API/worker/web against that same workspace, then scripts/batch-two-smoke.mjs. scripts/verify-persistence.py creates and removes its own isolated workspace. Historical logs remain in .audit; continuation logs are prefixed continuation-.

Only Windows was executed. External acquisition providers were not contacted; consent/review/control tests use synthetic local candidates. The source release carries no credentials or native binaries.
