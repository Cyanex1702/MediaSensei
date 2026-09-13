# Pipeline and job architecture

Milestone 1 implements a separate local worker process over a SQLite-backed queue. API requests enqueue work and return; `mediasensei worker run` owns execution. Job states are `queued`, `running`, `paused`, `completed`, `completed_with_errors`, `failed`, and `cancelled`.

## Persistence and recovery

Workers claim one job transactionally and receive a time-limited lease. They renew that lease between bounded batches. If a process exits, a later worker detects the expired lease, resets only `running` items to `pending`, and resumes from the persisted checkpoint. Completed, cached, skipped, and failed items remain terminal.

Each job stores total, processed, failed, skipped, and cached counters plus a JSON checkpoint. Per-item state includes attempt count, input hash/reference, output or user-safe error details, cache key, and update time. Structured events explain queue, claim, schedule, recovery, failure, pause, resume, retry, cancel, and completion transitions.

## Deterministic cache

A cache key is SHA-256 over canonical JSON containing:

- input content hash;
- processor id and version;
- normalized parameters;
- model revision.

Only deterministic, cacheable processors consult and populate the cache. A hit records access time and increments its hit counter. Embedding/model adapters can opt out or include an exact model revision.

## Adaptive scheduler

Scheduler profiles are Eco, Balanced (default), Maximum, and Custom. The scheduler detects CPU threads, total/available RAM, disk headroom, and future GPU fields. Node resource hints cover CPU, RAM, network, disk, GPU, and VRAM.

Balanced starts from half of logical CPU threads, capped at eight, then resource hints reduce it. Less than 10 GiB disk or 2 GiB available RAM restricts concurrency to one; less than 2 GiB disk or 512 MiB RAM pauses new work. A required unavailable GPU also pauses the node.

The worker executes bounded thread batches. Pillow processors create immutable thumbnails and transforms; Tesseract and FFmpeg adapters use bounded subprocesses without a shell. Media cache keys include the exact FFmpeg version, and derived objects retain source hash, parameters, MIME type, duration, and tool revision. Document parsing, chunking, and local embedding run through the same worker boundary. Document indexing is deterministic but deliberately not processing-cacheable because it atomically replaces asset-scoped ContentUnits and embeddings; its exact parser, chunk, and model revisions remain persisted. Dataset-provider imports are non-deterministic, non-cacheable network jobs because remote access can fail independently; reproducibility comes from persisting the resolved revision and complete selected-file manifest. Each file is checkpointed, completed files are skipped after restart, and SHA-256 storage still deduplicates identical bytes. Future learned model adapters remain behind the same provider and queue contracts.
