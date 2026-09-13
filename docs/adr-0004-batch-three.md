# ADR: Batch 3 integration boundaries

Status: accepted for implementation.

Add model revisions, public connection references, saved Playground scripts and voice personalities as additive SQLite tables. Model weights and training snapshots are immutable JSON objects in the existing SHA-256 store. Never deserialize pickle or execute model-supplied code. A saved revision is the full model artifact hash, not a mutable model name. Archival blocks new model jobs; existing provenance and exports remain readable.

Training, document embedding, voice generation and transcription run through JobQueue/LocalWorker with ProcessorSpec revisions. Playground compiles a restricted AST into existing Workbench steps and retains source hashes beside run IDs. There is no eval, exec or second execution scheduler. Replay continues to use the public operation implementation.

OS keyring backends are allowlisted to native credential services. Secrets are passed only to the selected provider instance in memory, not environment variables or job parameters. Missing/locked credential stores fail with generic errors. Workers recheck connection status and project external-access policy. Untrusted provider errors are redacted before persistence.

TF-IDF is a fitted lexical retrieval adapter, not semantic understanding. Supervised language classification requires caller-provided language labels and reports uncertainty. Voice generation and ASR use local native providers only after explicit action. Windows speech and whisper.cpp subprocesses receive bounded arguments and scrubbed environments; no shell is used. Existing plugin permissions and exact-file trust approvals are retained.

The exact deleted phase specification is unavailable; the concrete algorithms and UI described here are reconstructed requirements, documented before implementation.
