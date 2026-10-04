# Plugin API 1.5 finalization report

Plugin API 1.5 finalizes `DiscoveryProvider`, `AcquisitionDownloader`, `PromptPlannerProvider`, and `RelevanceEvaluator` with SDK-owned typed records. It also brings analyzer, OCR, embedding, vector-store, dataset-provider, and exporter capabilities under one validated `PluginRegistration` and diagnostic model.

## Evidence

- Discovery is exercised by two independent production adapters—Wikimedia Commons and Openverse—plus direct URLs, an installed entry-point fixture, pagination fixtures, duplicate identity tests, and provider-failure isolation.
- Downloads are exercised by the production HTTPS/public-address bounded downloader and typed plugin adapters with deterministic byte ceilings.
- Planning is exercised by the offline rule planner and a typed third-party planner adapter that returns a serializable validated spec.
- Relevance is exercised by metadata/manual modes and a typed third-party evaluator returning stable decision/reason/evaluator/score fields.
- Compatibility tests cover API ranges, versions, names, permissions, declared-versus-supplied capabilities, structural conformance, duplicate plugin/provider identities, broken imports, secret-safe diagnostics, local validation, generated packages, CLI, and API inventory.

## Stability boundary

The data records, capability identifiers, registration shape, compatibility behavior, and diagnostic codes are stable for Plugin API 1.x. MediaSensei 1.0 includes exact-fingerprint local trust, bounded analyzer subprocesses, hostile-record validation, and explicit runtime generations without changing those contracts. Detached archive signatures and native sandbox packaging profiles are release-layer additions. Authentication handles, marketplace distribution, and additional executable modalities remain post-1.0 work. Additions within 1.x must be backward compatible; incompatible changes require Plugin API 2.0.