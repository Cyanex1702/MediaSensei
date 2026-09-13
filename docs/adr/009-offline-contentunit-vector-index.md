# ADR 009: Offline ContentUnit vector index

Status: accepted

MediaSensei parses document assets into deterministic, provenance-bearing ContentUnit chunks and stores normalized vectors in the existing local SQLite catalog. The built-in embedding provider uses versioned signed feature hashing, and retrieval performs bounded exact cosine scoring in-process.

This baseline is fully offline, restart-safe, and requires no model download or vector service. It favors transparent provenance and portability over learned semantic quality or approximate-search scale. Every vector records provider id, exact model revision, dimensions, source hash, and ContentUnit identity.

The document indexing processor is deterministic but not processing-cacheable because its successful execution atomically replaces asset-scoped ContentUnits and embeddings. Additive `EmbeddingProvider` and `VectorStoreProvider` protocols allow later learned and approximate adapters without changing document identities or retrieval provenance.
