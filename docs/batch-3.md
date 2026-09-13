# Batch 3 â€” extensibility and integrations

Status: delivered as 2.0.0-alpha.4. Batch 2 was closed before this work; Batch 4 is release certification.

## Recovered requirements

The continuation document and repository call for Model Hub/revision management, learned adapters, saved connections and credentials, a controlled Playground, broader integrations, language detection/ASR where appropriate, and voice personalities. The original Phase 11â€“14 wording was not recovered.

## Reconstructed delivery decisions

- Model Hub trains bounded local TF-IDF retrieval models and supervised language classifiers from indexed project documents. Learned means fitted vocabulary/weights; these are not neural semantic models. Revisions are SHA-256-addressed JSON with training-source provenance, verification, export/import and archival. Indexing and inference pin an exact revision.
- Existing EmbeddingProvider and SQLite retrieval interfaces accept the fitted retrieval adapter. RAG exports include fitted model artifacts and revision-aware configuration.
- Connections use the native OS credential store; SQLite holds public connection metadata only. Revocation is checked again when a queued connection-backed provider import starts. Hugging Face uses the existing provider import engine with secrets resolved only inside the worker.
- Playground accepts a bounded Python operation-call subset and compiles it to the existing table workflow engine. Imports, arbitrary attributes, loops, filesystem/network access and general Python execution are rejected. This is deliberately not an unrestricted Python sandbox.
- Voice personalities save a local system voice and speaking rate. Explicit speech generation uses the existing worker and produces an immutable WAV on Windows. ASR uses an explicitly configured local whisper.cpp executable/model; no automatic model downloads or provider calls.
- Existing plugin trust, API compatibility, reload and inventory remain the integration boundary. New operations are discoverable in the shared registry; no parallel queue is introduced.

## Acceptance ledger

- [x] Model training, revision verification/import/export/archive and pinned indexing/retrieval
- [x] Supervised language classification and source/model provenance
- [x] Credentials excluded from catalog, jobs, logs and exports; revoked connections rejected
- [x] Controlled Playground compilation, saved scripts and real worker execution
- [x] Voice personality persistence and native speech output; ASR availability boundary
- [x] API contracts, backend regression, lint/type/build and browser acceptance
- [x] Updated documentation, synchronized alpha.4 versions and verified packages

Resource budgets: 1,000 training chunks, 2 MiB training text, 512 vocabulary terms, 32 labels, 30 Playground steps, and existing table/media limits. Actions require explicit user execution. Native/provider claims depend on executed evidence.


## Acceptance evidence — 2026-09-10

- Focused integrations: 19 passed, zero skips, including actual Windows speech and local whisper.cpp transcription of synthetic English speech.
- Full backend regression: 175 passed, zero skips; two upstream FastAPI/Starlette deprecation warnings.
- Browser: 8 checks, zero page errors, on development and production servers. Trained retrieval, model import/export/archive, real Playground dataset changes, native OS credential save/revoke, speech playback/download, reload and mobile layout were exercised.
- Ruff, TypeScript, frontend lint, 8 client contracts and production build passed.
- Exact versions synchronized to alpha.4; platform source archives contain verified embedded manifests.

## Changes and limitations

Added learned.py, integrations.py, playground.py, integration_definitions.py, native_adapters.py/native_speech.ps1, API routes, integration UI and browser/backend tests. Extended existing worker, operation, asset, knowledge and provider boundaries; added keyring as a runtime dependency. See ADR 0004 and integrations.md.

The original deleted Phase 11–14 text remains unrecovered. This delivery implements the documented reconstructed scope. Native Windows evidence does not certify macOS/Linux keyrings or speech. No authenticated remote dataset was downloaded; provider failure/redaction and revocation were tested with controlled adapters. Whisper testing used b4938 and tiny.en on one short English fixture; it does not establish accuracy across languages. General Python and neural semantic models are outside this reconstructed scope.
