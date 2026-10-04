# Offline document retrieval pipeline

Document indexing is a local worker operation over immutable assets. It creates replaceable, provenance-bearing ContentUnits and embeddings without modifying source bytes or calling an external model.

## Parsing and chunking

`DocumentParser` supports UTF-8 text, Markdown headings, safe HTML text extraction, DOCX Open XML paragraphs/headings, and PDF pages through pypdf. Parsers apply format-specific size/page limits, ignore executable HTML content, and return a persisted parser revision. A failed or empty parse is isolated to its job item.

`StructureAwareChunker` groups blocks by active heading and splits normalized word sequences using bounded `max_words` and `overlap_words` parameters. Deterministic ContentUnit ids include the asset, source hash, sequence, content hash, and chunking parameters. Locators retain heading, block range, page range when available, word range, sequence, word count, and content hash.

## Local embeddings and search

`LocalHashEmbeddingProvider` creates normalized 384-dimensional vectors from signed SHA-256 feature hashing over word unigrams and bigrams. It is deterministic, dependency-light, fully offline, and versioned as `mediasensei-hash-embedding-v1`. It is a retrieval baseline rather than a claim of learned semantic quality.

Vectors are serialized as portable little-endian float32 BLOBs. `SQLiteVectorIndex` selects active project candidates through `(project_id, model_id, model_revision)`, computes exact cosine similarity in-process, applies an optional asset filter and minimum score, then returns bounded top-k hits with source filename, title, text, and locator. The provider protocols allow a learned embedder or approximate vector store later without changing the domain.

## Persistence behavior

An indexing transaction upserts content-keyed analysis, removes only prior `document_chunk` ContentUnits and their embeddings for the selected asset, inserts the replacement set, and updates one asset-level index record. The processor is deterministic but not processing-cacheable because cache hits would skip these required asset-scoped side effects. Re-running the job is idempotent and restart-safe.
