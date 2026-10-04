# ADR 0005 — certify the local release boundary

Status: accepted.

Batch 3 alpha.4 is preserved before final certification. The final package is 2.0.0-rc.1 because native macOS/Linux execution is unavailable on the current Windows host. The implemented feature scope is complete; the release-candidate label records the remaining platform qualification boundary.

Use the existing source archive builder and embedded SHA-256 manifest. Reject duplicate archive entries, traversal/drive paths, links and malformed manifests, and compare two builds made from the same source and timestamp. Packages exclude environments, private workspaces, native binaries and credentials. Checksums establish integrity, not publisher identity; signing requires the owner's release key and is a separate publication action.

Test additive integration schema initialization against an existing catalog, repeat initialization, and reopen in a separate interpreter. Test queued jobs across API and worker restarts. Install the built wheel in a clean Python environment and verify imports and execution from that installed path, outside the checkout. The desktop UI remains in the full platform source distributions.

Retain a Windows/Linux/macOS CI matrix and document exact local execution, skipped optional dependencies and unsupported native adapters. Do not publish a repository, hosted site or release as a side effect of certification.
