# ADR-002: SQLite metadata and DuckDB analytics

Status: Accepted

SQLite is the transactional catalog and persistent job queue. DuckDB/Arrow/Parquet are the analytical path for large tables. pandas and NumPy remain first-class SDK capabilities but are not persistent storage. The hosted preview maps the structured schema to D1, which preserves SQLite semantics.

Dataset Lab follows this split directly: SQLite stores projects, assets, analysis references, query history, mappings, metadata, and export provenance. DuckDB reads supported source formats and normalized Parquet for analytical work. PyArrow is the interchange boundary, normalized Parquet is immutable content-addressed storage, and pandas is an explicit SDK/export adapter rather than the source of truth.

All user predicates are compiled from validated columns and a fixed operator set. Values are bound parameters. Database imports require a table selected from the source catalog, so user input is quoted as an identifier rather than interpolated as SQL.
