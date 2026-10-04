# ADR-004: Persistent local worker architecture

Status: Accepted

Long work does not run in API requests. A separate local worker claims SQLite jobs, checkpoints item completion, applies resource-aware concurrency, and can resume interrupted runs. The queue boundary is abstract so remote/distributed workers can be added without changing pipeline definitions.
