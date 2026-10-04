# Dataset and RAG workflows

## Dataset workflow

1. Connect or import a source with revision and license provenance.
2. Catalog immutable assets by SHA-256.
3. Inspect and run deterministic validation/quality nodes.
4. Review explicit issues; quarantine is logical and reversible.
5. Map assets/content units plus annotations into samples.
6. Split with a recorded seed and run cross-split leakage checks.
7. Create an immutable dataset version.
8. Export media, Parquet metadata, dataset card, manifests, locks, and checksums.

## RAG workflow

1. Import TXT, Markdown, HTML, DOCX, or PDF assets. Raw bytes are SHA-256 addressed and retained unchanged.
2. Run the queued `document.index` processor. The local parser extracts headings, paragraphs, pages, and format-specific locators into provenance-bearing blocks.
3. Build deterministic ContentUnit chunks with a configurable word target and overlap. Every chunk records asset/source identity, heading, block range, page range when available, word range, and content hash.
4. Generate normalized 384-dimensional embeddings with the dependency-light `local-hash-embedding` provider. Model revision and dimensions persist with every vector.
5. Store vectors as portable little-endian float32 BLOBs in the embedded SQLite index. Exact cosine search is bounded, project-scoped, and filterable by asset id.
6. Debug top-k scores, excerpts, documents, headings, and page references through Knowledge Lab, `document search`, or the versioned REST API. Retrieval never calls a cloud model and performs no answer generation.
7. Replace the local provider later through the additive `EmbeddingProvider` and `VectorStoreProvider` plugin contracts without changing document or ContentUnit identities.
## Dataset Lab workflow

1. Import CSV, TSV, XLSX, JSON, JSONL, Parquet, SQLite, or DuckDB. The raw file is hashed and retained unchanged.
2. Run the queued `tabular.inspect` processor. It normalizes the selected sheet/table to content-addressed Parquet and records the Arrow schema.
3. Inspect row/column counts, missing values, distinct counts, ranges, means, representative rows, and low-cardinality frequencies.
4. Filter, search, sort, paginate, select visible columns, and request frequencies through the validated query builder. Column names are schema-checked and values are parameterized; arbitrary SQL is never accepted.
5. Map external columns to MediaSensei fields and attach custom metadata. Both persist across restarts.
6. Export the full table or a validated query to CSV, TSV, XLSX, JSON, JSONL, Parquet, SQLite, or DuckDB. Existing destinations are never overwritten, and every export records its SHA-256 checksum.

Advanced Python users can call `TabularEngine.to_pandas()` for a bounded, validated query result as a pandas DataFrame.

## Video and audio workflow

1. Import a supported video (`mp4`, `mov`, `mkv`, `webm`, `avi`, `m4v`) or audio (`wav`, `mp3`, `flac`, `m4a`, `ogg`, `aac`) file. The original bytes enter content-addressed storage and are never rewritten.
2. Run `media.inspect`. `ffprobe` records container, duration, bit rate, codecs, video dimensions/FPS/pixel format, and audio sample rate/channels/layout. Enable full-decode validation only when needed because it is more expensive.
3. Generate a video thumbnail or audio waveform. Each preview is a new immutable object linked to the source hash and exact FFmpeg revision.
4. Request MP4/WebM video or WAV/FLAC/MP3/OGG audio transcoding. Clips add bounded start and duration parameters. Metadata is stripped from the derivative and retained separately in catalog provenance.
5. Run the separate worker. FFmpeg subprocesses never use a shell, have bounded time/output, and run with conservative scheduler hints. If the binaries are missing, only affected items fail and remain retryable after installation.
6. Inspect assets, analysis, and derivative records through `media list`, `/api/v1/projects/{project_id}/media`, or Media Lab.

## Revision-pinned provider import

1. Install the optional providers extra and configure credentials through the provider’s native environment or config (`HF_TOKEN`/`HUGGING_FACE_HUB_TOKEN` for private Hugging Face data; Kaggle’s official client configuration for Kaggle). Credentials never enter MediaSensei metadata.
2. Create or choose a project with `approved_external` or `unrestricted` data policy. A `local_only` project rejects remote imports.
3. Review the requested `owner/dataset`, optional revision, glob allow/ignore patterns, maximum file count, per-file bytes, and total bytes. Pass `--allow-remote` (or `allow_remote: true` in REST) to explicitly authorize the network operation.
4. Queue the import, then run the worker. Hugging Face aliases resolve to a commit hash; Kaggle resolves to a numeric dataset version before files are cataloged.
5. Inspect `provider show IMPORT_ID` or the Sources surface for source URI, provider version, requested/resolved revision, license, manifest hash, counters, and per-file status.
6. Retry the failed job item after a transient error. Already completed files remain checkpointed; repeated bytes converge on one content-addressed object while each catalog asset retains its source-file provenance.