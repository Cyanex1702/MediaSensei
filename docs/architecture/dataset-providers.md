# Dataset-provider architecture

Milestone 6 adds an import boundary for Hugging Face and Kaggle without coupling provider SDKs to the domain core. `DatasetProviderRegistry` exposes available adapters; each adapter resolves a requested `owner/dataset` and optional revision to a `DatasetSnapshot` before bytes move. Hugging Face records the exact repository commit. Kaggle records the numeric dataset version and rechecks it after a file download to detect a moving dataset.

## Import sequence

```text
API / CLI / Sources
        │ explicit remote authorization + project policy
        ▼
provider_import (queued request and bounded selection options)
        │
        ▼
resolve immutable DatasetSnapshot
        │ persist Source + selected ProviderImportFile manifest
        ▼
dataset-provider.import worker job
        │ one bounded file at a time
        ▼
SHA-256 object store ── Asset linked to Source and provider path
```

Allow and ignore globs run against normalized POSIX relative paths. Unsafe absolute/traversal paths are rejected. Known file sizes are checked before download, the download stream is bounded again, known SHA-256 values are verified, and the configured total byte budget is enforced across the import. Files excluded by filters or limits never become assets.

## Recovery and provenance

The selected manifest is persisted before download. Each file moves through `pending`, `importing`, `completed`, `skipped`, or `failed`; retries revisit only nonterminal files. Import counters and user-safe errors remain inspectable after process restart. Successful assets retain provider id/version, dataset id, requested and resolved revisions, provider path, source URI, and license metadata. The manifest hash covers the immutable snapshot, selected files, and selection options.

Provider tokens and Kaggle credentials are consumed only by the official SDK clients. They are excluded from request hashes, manifests, Source/Asset metadata, catalog rows, responses, and worker events. Remote operations require both a compatible project data policy and explicit per-request authorization.