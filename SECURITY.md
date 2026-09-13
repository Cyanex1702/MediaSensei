# Security policy

## Supported versions

This workbench is the MediaSensei 2.0 release candidate. Its local acceptance evidence is in docs/batch-4.md. Earlier 1.x and alpha snapshots are historical baselines; no maintenance or security-support promise is implied by their presence in the archive.

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability. Contact the repository owner privately with the affected version, reproduction steps, impact, and any suggested mitigation. Avoid including real credentials, private datasets, or personal information.

## Security boundaries

MediaSensei is local-first, but installed plugins are executable Python. Review source before trusting a plugin. Trust is bound to its exact SHA-256 fingerprint; changed files require fresh approval. Analyzer subprocess isolation reduces impact but is not a substitute for an operating-system security boundary.

Remote acquisition requires explicit authorization and remains subject to project policy, HTTPS/public-address validation, redirect and byte limits, content validation, and immutable storage. Never place secrets in prompts, plugin parameters, project metadata, or issue reports.

Saved provider tokens use an allowlisted native OS keyring. Public connection metadata is separate from credentials; queue payloads reference connection IDs. Revocation disables a connection before deleting its credential and is rechecked before provider downloads. An in-flight request may finish. Provider error messages are redacted before persistence. Unlock the native store and retry if credential removal reports failure.

Playground parses a restricted operation-call syntax and never evaluates arbitrary Python. Existing explicitly trusted plugins remain executable code; Playground restrictions do not turn plugins into a security sandbox. Local ASR executables and companion libraries must come from trusted builds. Model/executable hashes establish revision identity, not code safety. Models are never downloaded implicitly.

Fitted model artifacts contain vocabulary and training-source hashes. RAG exports intentionally contain selected originals. Treat both as dataset material when sharing. A workspace backup contains metadata and source bytes but does not export native keyring credentials.

Keep services bound to loopback. This application is a single-user local tool, without a multi-user authorization boundary. Do not expose its API or frontend to untrusted networks.

Release verification rejects traversal and drive paths, duplicate case-insensitive names, links, malformed manifests and checksum mismatches, with bounded archive reads. SHA256SUMS detects modifications; it does not authenticate a publisher. Release signing and publication require the owner's key and remain separate actions.
