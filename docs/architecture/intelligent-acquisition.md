# Intelligent Acquisition architecture

Milestone 8 adds an image-first, prompt-or-specification acquisition subsystem. It is a separate bounded context from revision-pinned dataset imports: discovery finds candidate URLs and metadata; acquisition explicitly authorizes remote bytes; evaluation decides whether each item is accepted, rejected, or quarantined for review; accepted content enters the existing immutable SHA-256 object store and catalog.

## Lifecycle

`AcquisitionRequest → AcquisitionPlan → AcquisitionRun → AcquisitionQuery → AcquisitionCandidate → AcquisitionDecision`

A rule-based planner is the offline baseline. It compiles topic, target, categories, resolution, quality, relevance mode, providers, and safety ceilings into a validated `AcquisitionSpec`. The plan stores generated queries, selected provider capabilities, and a conservative candidate estimate before any network request occurs. Optional future planners may improve the plan, but they do not change its validated shape or the separate network-authorization boundary.

The run is one non-cacheable worker item with candidate-level persistent checkpoints. Discovery providers return metadata-only pages. The safe downloader then revalidates each HTTPS redirect, blocks credentials and non-public addresses, streams to a bounded temporary file, and enforces byte ceilings. Image inspection validates decoding, MIME, dimensions, quality, SHA-256 exact duplicates, and optional pHash near duplicates. Relevance is metadata-based by default and may return a human-review decision. Rejected bytes are removed before CAS ingestion; review assets are quarantined; accepted assets are active and retain provider, query, remote identity, URL, author, license, retrieval URL, evaluator scores, and run identity.

## Target yield and stopping

The target is accepted assets, not search results. After each cycle, the worker persists observed yield and estimates the next bounded batch. It replenishes until the target is reached or a candidate, request, download-byte, storage-byte, provider-exhaustion, policy, pause, or cancellation boundary stops it. A run below target completes as `completed_with_shortfall` with an explicit stop reason. Restart recovery returns interrupted candidates to a safe retryable state and never repeats accepted assets.

## Extensibility

The domain already models image, video, audio, document, and tabular modalities, but Milestone 8 executes images only. Plugin API 1.5 finalizes typed structural contracts for discovery, downloading, planning, and relevance after evidence from Wikimedia Commons, Openverse, direct URLs, deterministic adapters, and core integration. The stability boundary and remaining non-goals are recorded in `docs/plugin-contract-report.md`.