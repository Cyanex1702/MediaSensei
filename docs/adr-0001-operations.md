# ADR 0001: Incremental 2.0 operation and dataset foundation

Status: accepted for the first 2.0 milestone.

The existing SQLite catalog, immutable SHA-256 objects and worker queue remain authoritative. New additive tables store logical working datasets, immutable version manifests, operation runs and recipes. No existing table is dropped or rewritten. UI/API/SDK use one operation implementation. Long transforms use the existing worker and resource scheduler; previews are bounded and never alter working state.

Working-head updates use compare-and-swap on a revision. Concurrent operations based on stale input fail rather than silently overwriting later work. Outputs are immutable Parquet objects; versions reference hashes. Retry must be idempotent. Operation cache keys include operation configuration and installed library versions.

The first milestone deliberately bounds dataframe operations to 200,000 rows / 256 MiB Parquet. Query pagination uses existing DuckDB. These are explicit product limits, not a claim of arbitrary-scale streaming transforms. Cross-modality processors remain intact and are exposed in dedicated labs; full unification follows after the tabular abstraction is proven.

Repository audit: the main API and React component are large adapters; acquisition has substantial existing API/worker support but no current navigation. Document index/chunks, image OCR/derivatives, media extraction, and exports already exist. New modules should be separated rather than adding new business logic to either giant adapter. Existing tests run as the baseline; detailed milestone verification is recorded in docs/2.0-status.md.
