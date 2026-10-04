# Architecture overview

MediaSensei is organized around one domain core and multiple adapters.

```text
React workspace / CLI / Python SDK / REST API
                    │
            Application services
       projects · import · jobs · versions
                    │
               Domain core
 asset · content unit · sample · feature · dataset
                    │
 providers/plugins · SQLite · object store · workers
```

## Boundaries

- `packages/core` owns domain invariants, local catalog behavior, storage safety, and the public Python surface.
- `apps/api` translates HTTP requests into core operations and exposes `/api/v1`.
- `app` and `components` provide the React working surface. The UI never reaches into database tables directly.
- `packages/plugin-sdk` contains versioned, deliberately small contracts. Plugins declare capabilities and permissions.
- Provider, OCR, model, vector-store, and export implementations are adapters; they do not appear in domain entities.

## Persistence

Local desktop/notebook use stores metadata in `metadata/mediasensei.db` and bytes in the SHA-256 object tree. The hosted preview uses D1 for durable workspace records and keeps the same logical entity names. Larger analytical workloads will materialize Arrow/Parquet and be queried with DuckDB; pandas remains an SDK surface, not the system of record.

## Jobs and pipelines

Long work is represented as persisted jobs. A node declares inputs, outputs, parameters, resource hints, determinism, cacheability, and provider identity. Deterministic cache keys combine input hash, processor id/version, parameters, and model revision. Checkpoints are item-oriented so completed assets do not repeat after restart.

The local worker executes behind that queue abstraction. The complete image path uses the same contracts for inspection, pHash, OCR, derivatives, splitting, leakage checks, and export; see [Image pipeline](image-pipeline.md). Video/audio processing uses a shell-free FFmpeg adapter for probing, decode validation, previews, clips, and transcoding; see [Media pipeline](media-pipeline.md). Document processing extracts structured blocks, persists ContentUnit chunks, embeds locally, and searches an embedded vector index; see [Document retrieval pipeline](document-pipeline.md). Remote dataset ingestion resolves a provider snapshot once, persists its file manifest, and imports each file through retryable checkpoints; see [Dataset providers](dataset-providers.md).

## Security and policy

- Localhost is the default API bind.
- Project data policy defaults to `local_only`.
- Credentials are referenced by logical ids and never enter project manifests.
- Imports normalize filenames, cap request size, and never trust client paths.
- No CAPTCHA, access-control, or dataset-gate bypass is in scope.
