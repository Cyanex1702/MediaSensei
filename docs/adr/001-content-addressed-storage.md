# ADR-001: SHA-256 content-addressed object storage

Status: Accepted

Raw and derived bytes are stored at `objects/sha256/<first-two>/<hash>`. Imports stream hashes, copy through a temporary file, verify integrity, and atomically materialize the object. Metadata references object keys. This makes exact deduplication and immutable versioning natural; garbage collection must be explicit and reference-aware.
