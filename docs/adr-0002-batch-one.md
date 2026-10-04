# Batch 1 architecture

The existing catalog, SHA-256 store and worker remain the infrastructure. Operation definitions contain versioned parameter, input/output, compatibility and documentation metadata. Tabular execution is a pure dataframe function; asset adapters enqueue the original image/media/document/table processors. Trusted SDK callers can register an operation and callable executor explicitly. User-supplied Python execution belongs to Batch 3.

A workflow is an ordered, typed pipeline. Each node receives a TabularDataset and returns a table plus optional report. Combine introduces another dataset input: its content hash is captured when queued and used throughout execution and replay. A node can change the schema; parameter compatibility is checked against that node's actual input. Reports do not change working revisions.

Runs persist queued/running/completed/failed state, input and output hashes, library versions, resolved parameters, progress and per-step events. Every successful step records a content-addressed checkpoint; retry resumes from those outputs. Working-copy publication uses an optimistic revision check in the same transaction as completion, preventing stale concurrent writes. Versions freeze data and branch lineage; restore changes the working branch only.

Recipe placeholders resolve recursively, preserving numeric/boolean/list types. Missing required values fail before execution. Saved workflows and reusable recipes have separate persisted records. API, CLI, local SDK, generated Python and exported notebooks share the operation implementation. ZIP replay bundles include every joined snapshot, with aliases separating different revisions of the same joined dataset.

Queries use DuckDB with bound values, validated identifiers, a 256 MiB memory budget and at most 200 rows per response. Display positions are computed before filtering and sorting, so selection refers to source rows in the current revision. Table mutation clears selection. Transforms retain the existing 200,000 row / 256 MiB Parquet / 1 GiB decoded working limits. Explode, melt, joins, one-hot encoding and chart points have output bounds. These are explicit resource limits, not claims of unlimited data size.

Regular-expression filtering uses RE2 through DuckDB/Arrow; arithmetic features use a restricted AST with numeric operators, no eval, calls, attributes or subscriptions. Remote data is not sent by any Batch 1 table operation. Charts save both the definition and results with the source hash; report exports contain actual charts rather than requiring a running server.

Forest is the default palette. Spectrum, Charcoal and Beige replace semantic CSS variables across the shell, tables, forms and charts. Theme selection persists locally and is applied before hydration. Guided/Expert presentation and Guide recommendations remain independent preferences.
