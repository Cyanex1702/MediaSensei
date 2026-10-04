# MediaSensei independent QA and repair report

30 September 2026 · Windows · Python 3.13 · Node 24.21 · Microsoft Edge / Playwright

**Assessment: a repaired, working local alpha with a production frontend build. The full dataset engine described in the supplied master prompt is not complete or production-certified.**

The original ZIP and prompt were left untouched. Repairs are in this extracted copy. The old prompt was used as a requirements reference; its instructions to create a new repository were not treated as a request to replace the application. Earlier certification documents describe prior claims, not evidence from this pass.

## Reproduced problems and repairs

| Priority | Problem | Repair and verification |
|---|---|---|
| High | Nested JSON/Parquet lists and objects crash Data Lab profiling with `unhashable type: list/numpy.ndarray`. | Compare normalized, hashable values for profiling, duplicate removal and canonical selection while retaining original nested cells. Added direct and API/worker regression tests. |
| High | Infinity/NaN in numeric tables produces JSON serialization failures. Aggregate overflow can also produce infinity. | Convert non-finite response values to JSON null and guard profile statistics. Stored originals are unchanged. Tested Parquet import, overview and rows. |
| High | A malformed or wrong-shape favorites/recents preference crashes rendering or reports an already queued operation as failed. Blocked/full browser storage can also break startup. | Centralized safe preference reads/writes and validated string lists. Tested corrupt and blocked storage in the real browser and client tests. |
| High | Updating a running Windows instance locks npm files; the update path also recreated an existing virtual environment. | Stop this launcher's own services before dependency installation and retain the existing venv. Added launcher regression coverage. |
| Medium | Every ordinary start rebuilds the frontend. | Fingerprint source/configuration/API origin and reuse a successful unchanged build. A source/origin change or missing output triggers a rebuild; failed builds invalidate the stamp. |
| Medium | API timeout ends after headers, allowing response body consumption to hang. Validation messages lose field details. | Deadline now includes body reading; distinguish timeout, cancellation, network and validation errors. Added client tests. |
| Medium | Filtering Data Lab from page 2 can show no rows even when matches exist. Dataset switches temporarily display the previous dataset's rows, versions and charts. | Reset pagination on query changes, clear obsolete dataset state, discard stale chart responses and prevent switching during an operation. Browser regression covers page-2 filtering. |
| Medium | Large libraries render every card, while bulk quarantine/reactivation launches an unbounded request burst. | Render at most 100 assets per Library page; constrain bulk updates to four concurrent requests and report partial failures. Tested 205 synthetic assets and bounded request concurrency. The catalog API itself still returns the full project; see scale limitations below. |
| Medium | Navigating back to Data Lab can leave a different tab selected. Modality-only empty Library results lack an empty state. | Correct navigation and empty states; add grouped navigation, a workflow guide, dismissible notices and backend startup guidance. |
| Medium | Uncaught view errors leave the app unusable. | Added a recovery boundary with Reload workspace and error details. It does not delete projects or reset stored data. |
| Medium | The main end-to-end script still clicks the removed `Index documents` button. | Updated it to prepare/index documents through the current Knowledge Lab and wait for real jobs. The production end-to-end harness passes. |
| Dependency | npm initially reports 8 vulnerabilities: 7 high, 1 moderate. | Updated compatible Cloudflare runtime/tooling/types and transitive fixes; final npm audit reports zero known findings. This is a dependency audit result, not a complete security certification. |

Also added validation for malformed filter objects/column lists and fixed the native fixture script's Windows-only process flag on other platforms.

## Executed verification

- Full Python regression: **164 passed, 27 skipped**. Skips are native-media cases where optional FFmpeg/ffprobe tooling was unavailable. Two upstream test-client deprecation warnings remain.
- Client contract/preference tests: **15 passed**.
- TypeScript, frontend lint, Python Ruff and `pip check`: passed.
- Production frontend build and Windows launcher readiness: passed (API, worker and web).
- Production end-to-end harness: passed, including multi-file/ZIP imports, persistent processing, Library, document retrieval, invalid uploads and API error recovery.
- Data Lab browser suite: 20 checks, including transformations, previews, version restore/export, charts/SVG/PNG/report export, recipes, typed bindings, saved workflows, themes, mobile layout and reload persistence; no page errors.
- Image/document/acquisition browser suite: 11 checks, including transform preview, worker output, ZIP download, adoption, Windows OCR, document preparation/chunks, retrieval, RAG export and local candidate review; no page errors. Native video/audio portions were explicitly skipped.
- Integration browser suite: 8 checks covering fitted lexical models, pinned indexing, model import/export, Playground, credential save/revoke, Windows speech and persistence; no page errors. Provider gates used synthetic data, not authenticated remote downloads.
- New browser regressions: all 19 navigation pages, corrupt/blocked browser storage, Library pagination, query pagination reset, preview/enqueue and mobile overflow.
- Restart verification: 8 checks covering persisted imports, transformations, jobs, output hashes, model revisions and Playground source.
- Python wheel and source distribution build and metadata checks: passed. This pass did not repeat clean-venv installed-wheel execution.
- Source ZIP: generated with the repository release tool and verified against its embedded SHA-256 manifest.

Tests used synthetic disposable workspaces. They did not process your personal dataset. Screenshots and machine-readable browser reports are in `qa-evidence/` beside this report in the delivered folder.

## What the master prompt still asks for

| Area | Current implementation and gap |
|---|---|
| Tabular dataset engine | Real import, DuckDB queries, working revisions, operations, recipes, versions and export exist. Transforms are bounded to 200,000 rows, 256 MiB Parquet and a decoded memory allowance. Import/profiling paths can materialize data; this is not a demonstrated out-of-core engine for arbitrary large datasets. |
| Large media libraries | Card rendering is now bounded, but `/projects/{id}/assets` still loads/enriches the full catalog and the UI refreshes it periodically. True API pagination, incremental updates and a measured large-catalog acceptance test remain necessary. No 10,000-asset interruption/resume certification was performed. |
| Unified multimodal datasets | Table versions/workflows and media outputs are implemented through different services. The full cross-modality Sample/Annotation/Feature/Dataset model and a unified version/restore experience are incomplete. Global Versions/Exports currently target Data Lab; image exports are in Image Lab and RAG exports in Knowledge Lab. |
| Saved Smart Collections | Query history and recipes exist. No complete saved, project-wide Smart Collection workflow was found. |
| Storage management | Content-addressed storage and immutable originals exist. No complete Storage Manager with reference-aware garbage collection and an explicit deletion workflow was found. |
| Semantic models | Built-in retrieval uses signed feature hashing or fitted TF-IDF, with supervised lexical language classification. These are lexical baselines, not a neural semantic embedding/model-download platform. |
| Video/audio | Implementation exists, but FFmpeg/ffprobe were not available for this pass. A bounded attempt to obtain FFmpeg timed out; no partial binary was installed. Native processing is unverified here. Windows OCR and speech were executed successfully. |
| Remote providers | Hugging Face/Kaggle adapters, consent gates and provenance code exist. Live authenticated imports were not verified. Remote access remains opt-in and project-policy dependent. |
| Notebook portability | Workflow Python/notebook exports exist. The requested dedicated Quickstart/Colab/Kaggle notebook files are absent from this archive. |
| Release/architecture | Windows was executed. Native macOS/Linux, performance under sustained large workloads, shared-server authentication and remote provider qualification remain unverified. Several large UI/API/service modules remain. The deployed scope is a trusted single-user local workstation. |

The original end-to-end scenario is therefore **partially demonstrated**, not fully closed: local image/document/table workflows work in the tested cases, while provider qualification, general multimodal versions and large-scale acceptance still need work. Post-MVP items in the prompt, such as a full annotation studio and distributed workers, were not silently added to this repair scope.

## Running the repaired copy

Double-click `start.bat` in this folder. Normal defaults are API port 8000 and browser port 3000. Use `Stop-MediaSensei-Windows.bat` to stop it. The first setup of a freshly extracted source ZIP installs dependencies and builds; subsequent unchanged starts reuse the build.

Use the extracted source folder, not the ZIP viewer. Keep the folder in a writable location. Python 3.12+ and Node 22.13+ are required. Do not copy the generated `.venv` to another machine or location; a newly extracted source ZIP creates its own environment.

For audio/video, configure FFmpeg and ffprobe using the media setup guide. FFmpeg's official download page lists Windows build providers: https://ffmpeg.org/download.html . Those tools are not bundled in the source ZIP.

The most useful next engineering work is API pagination/incremental refresh, a unified multimodal version/export workflow, then measured native-media and large-dataset acceptance. The older roadmap's blanket completion statement should not be used as a release gate.
