# ADR 010: Resolve dataset providers to immutable revisions

## Status

Accepted for Milestone 6.

## Context

Provider aliases such as a Hugging Face branch or Kaggle’s current dataset version can move while an import is running. Recording only the user’s alias cannot reproduce the selected files, and downloading before a manifest exists makes restart recovery ambiguous.

## Decision

Every provider import resolves once to a `DatasetSnapshot` with a provider version, immutable resolved revision, source URI, license/metadata, and normalized file manifest. Hugging Face uses the exact repository commit; Kaggle uses the numeric dataset version and detects a revision change during download. The selected, budget-checked manifest is persisted before file work begins. A non-cacheable worker checkpoints each file and imports bytes through the existing SHA-256 object store. Provider credentials remain outside all persisted records.

## Consequences

Imports can be replayed and audited against exact provenance, retries avoid completed files, and identical bytes retain physical deduplication. Providers that cannot expose or enforce a stable revision must fail rather than silently claim reproducibility. Network imports require explicit authorization and a project policy that permits external data.