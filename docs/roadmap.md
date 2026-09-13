# MVP roadmap

## Complete foundation

- Repository scaffold, React working surface, D1 schema/migrations, Python core, SQLite catalog, SHA-256 object store, plugin SDK, docs, CI foundation, and deterministic safety tests.

## Complete Milestone 1 — local jobs and deterministic cache

- Separate local worker process, transactional queue claims, expiring leases, restart recovery, item checkpoints, pause/resume/cancel, failed-item retry, structured events, deterministic cache, cache statistics, adaptive scheduler profiles, API/CLI controls, and a persisted Pipeline UI.

## Complete Milestone 2 — full image path

- Pillow validation and corruption detection, EXIF-safe metadata, thumbnails, native pHash, blur scoring, exact/perceptual duplicate groups, pluggable OCR with Tesseract, immutable resize/convert derivatives, all required deterministic split strategies, exact/perceptual leakage checks, processed-media + Parquet export, API/CLI operations, persisted Image Lab/Split Safety/Exports UI, migrations, and restart tests.

## Complete Milestone 3 — DuckDB/Arrow Dataset Lab

- Immutable eight-format structured imports, content-addressed Parquet normalization, Arrow schemas, missingness/distinct/range/mean/frequency profiles, parameterized sorting/filtering/search/pagination, visible-column selection, schema mapping, custom metadata, pandas access, eight-format atomic exports, API/CLI operations, persisted Dataset Lab UI, migrations, and restart/cache tests.

## Complete Milestone 4 — FFmpeg video/audio path

- Immutable video/audio imports, shell-free bounded ffprobe/FFmpeg execution, container and stream metadata, optional full-decode validation, video thumbnails, audio waveforms, clip extraction, video/audio transcoding, exact tool revision provenance, deterministic cache integration, API/CLI operations, persisted Media Lab UI, migrations, and worker/API tests.

## Complete Milestone 5 — offline document retrieval

- Immutable TXT/Markdown/HTML/DOCX/PDF imports, structure-aware parsing, provenance-bearing ContentUnit chunks, configurable word overlap, deterministic 384-dimensional local embeddings, an embedded SQLite exact-cosine index, additive embedding/vector-store plugin contracts, API/CLI operations, persisted Knowledge Lab UI, migrations, and restart/API/CLI/parser tests.

## Complete Milestone 6 — revision-pinned dataset providers

- Hugging Face and Kaggle adapters, provider capability discovery, exact resolved revision provenance, manifest-first selection, allow/ignore filters, file and total byte budgets, explicit network authorization, project policy enforcement, credentials excluded from persistence, SHA-256 content-addressed ingestion, per-file checkpoint/retry, API/CLI/SDK surfaces, persisted Sources UI, hosted/local migrations, and deterministic adapter/restart tests.

## Complete Milestone 8 — Intelligent Acquisition & Prompt-Based Discovery

- Prompt and manual-spec planning, inspectable pre-network plans, Wikimedia Commons, Openverse, and direct-URL discovery, separate explicit remote authorization, HTTPS/public-address/redirect/byte enforcement, deterministic image validation and deduplication, metadata/human relevance decisions, adaptive accepted-yield replenishment, persistent candidate checkpoints, explicit shortfall, API/CLI/SDK surfaces, persisted Acquisition UI, hosted/local migrations, and deterministic restart/interface tests. See the [architecture](architecture/intelligent-acquisition.md) and [full milestone specification](milestones/milestone-8-intelligent-acquisition.md).

## Complete Plugin Integration and SDK Finalization

- Plugin API 1.5 typed records, validated registrations, API-range and structural compatibility checks, explicit permissions, failure/duplicate isolation, secret-safe diagnostics, runtime discovery-provider registration, typed downloader/planner/relevance adapters, Openverse as a second production discovery source, full package scaffolding, CLI/API inventory and validation, persisted Plugins UI, `py.typed`, ADR/evidence documentation, and deterministic compatibility tests.

## Complete Plugin Hardening and Reliability

- Exact SHA-256 trust approvals and revocation, hostile SDK record and component limits, timeout-bound analyzer subprocesses with scrubbed environments, explicit atomic runtime generations and reload API, analyzer and discovery-provider templates, safe failure recovery, cross-platform one-click dependency/update/start launchers, dashboard guidance, and deterministic reliability tests.

## Complete Packaging and Release

- MediaSensei 1.0 version synchronization, Apache-2.0 package metadata, deterministic Windows/Linux/macOS bundles, embedded file manifests, traversal-safe SHA-256 verification, detached OpenSSL signing and verification, Python wheel/source builds, cross-platform full-stack smoke testing, read-only release verification CI, native sandbox packaging profiles, changelog, security policy, release guide, and a Release readiness UI.

## Current vertical slice

- Project overview, governed Intelligent Acquisition, validated and hardened plugin integrations, multimodal library, complete image/media/document preparation, duplicate review, OCR actions, dataset splitting and leakage safety, persistent pipeline operations, dataset profiling, offline retrieval debugging, versions, reproducible exports, one-click desktop setup, and verified release artifacts.

## MVP status

All planned MVP milestones are complete. Future work is post-1.0 product expansion and does not block this release.

> The supplied standalone specification names this Milestone 8. Milestone 7 is not yet defined in this roadmap.

Every milestone must pass tests, lint, type checks, frontend build, migration verification, restart behavior, and documentation review before expansion.
