# Batch 1 requirements and verification ledger

Scope: phases 1–6 plus four persistent color themes. Existing audit and regression coverage are reused. Phase 7–14 features stay assigned to their agreed batches; no Batch 1 feature is waived.

| Requirement | Implementation | Verification |
|---|---|---|
| Stable typed operation registry and existing processor adapters | Implemented | Passed; see evidence below |
| Immutable working datasets, version comparison, lineage, reproducibility | Implemented | Passed; see evidence below |
| Navigation, Library selections, inspector, jobs and actionable errors | Implemented | Passed; see evidence below |
| Explorer conditions, selection, visibility, query history | Implemented | Passed; see evidence below |
| Exploration/statistics, cleaning, expressions, reshaping, combining | Implemented | Passed; see evidence below |
| Fitted preprocessing, splitting, leakage and quality | Implemented | Passed; see evidence below |
| Reusable interactive chart families, chart persistence and export | Implemented | Passed; see evidence below |
| Function Explorer, global search, contextual docs, recent/favorites | Implemented | Passed; see evidence below |
| Deterministic Guide, independent Guided/Expert preferences | Implemented | Passed; see evidence below |
| Typed workflow composition, checkpoints, recipes, placeholders, import/export | Implemented | Passed; see evidence below |
| Default forest, colorful, charcoal and beige themes | Implemented | Passed; see evidence below |
| Focused tests, batch regression, build and browser acceptance | Completed | Passed |

Verification policy: run focused tests after related changes; run the full regression suite/build at the batch boundary. Re-run only when changed code or failures justify it. Package once after acceptance. Record evidence and remaining gaps here; never mark pending behavior complete solely because an interface exists.


## Acceptance evidence — 2026-09-08

- Full regression: 110 backend tests passed, 1 skipped (FFmpeg unavailable).
- Additional focused checks: cacheability and checkpoint recovery passed (2 tests, including one added test); final search/asset adapter check passed.
- Eight client contract tests, TypeScript, frontend lint, Python Ruff and production build passed.
- `scripts/batch-one-smoke.mjs` passed 20 acceptance checks with no page exceptions: import/worker/adoption/profile/preview/run/version/download, recipe persistence/import/binding, workflow save/run, exact notebook export, operation intent search, heatmap, chart SVG/PNG/visual report exports, version feature differences, Function Explorer, reload and mobile layout.
- Forest, Spectrum, Charcoal and Beige rendered as four distinct palettes. Theme persistence and mobile horizontal bounds passed. Forest screenshot visually reviewed.
- Source packaging verifies version agreement, manifest entries and SHA-256 hashes. Source archives exclude test projects and local runtime environments.

The later three delivery batches remain unchanged. Platform limits and optional toolchain availability are recorded in `docs/2.0-status.md`; no skipped native-media test is reported as passed.

Compatibility browser check also passed project creation, document upload/retrieval, Library, Jobs, System, invalid-upload recovery, API-health isolation, persistence and mobile navigation with no page exceptions. Optional image/ZIP fixture branches were not enabled in this compatibility repeat; archive/image handling retains backend regression coverage.
