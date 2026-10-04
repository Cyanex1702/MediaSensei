# ADR 015: Reproducible, verified, deliberately published releases

- Status: Accepted
- Date: 2026-09-02

## Decision

MediaSensei 1.0 ships as platform-specific portable source archives and standard Python distributions. Archives normalize ordering, timestamps, ownership, and executable modes; embed a complete SHA-256 file manifest; and are verified immediately after creation. Release metadata, Python/web versions, and an optional version tag must agree. Full-stack smoke testing starts the real API and web runtime before artifacts are approved.

Publication is never triggered by a source push. Read-only CI verifies tags and manual release candidates without uploading them. A release owner may create a detached SHA-256/OpenSSL signature using a private key held outside the repository; consumers verify with the published public key.

## Consequences

Builds are repeatable from the same commit and epoch, corrupted or path-traversing archives fail verification, and signing credentials never enter source control or release bundles. Desktop bundles still require Python 3.12+ and Node.js 22.13+; the existing one-click launchers install application dependencies and start services.