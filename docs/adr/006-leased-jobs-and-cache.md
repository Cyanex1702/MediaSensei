# ADR-006: Leased SQLite queue and content-derived processing cache

Status: Accepted

MediaSensei uses SQLite as the local job queue. Workers claim jobs transactionally and hold expiring leases; a new process recovers stale leases and resets only in-flight items. Checkpoints are item-oriented so completed work survives pause, crash, or restart.

Deterministic cache keys hash canonical input hash, processor id/version, parameters, and model revision. Cacheability is declared by the processor contract. This keeps API requests short, avoids a Redis/Celery requirement for the local MVP, and leaves the queue and executor boundaries replaceable for distributed runtimes later.
