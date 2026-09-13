# MediaSensei 2.0.0

A local-first workspace for importing images, documents, audio/video, and structured data; processing them with persistent jobs; and exporting datasets or searching indexed documents.

## Delivered scope

The first grouped delivery (phases 1–6) adds 35 executable table operations, immutable versions and detailed comparisons, DuckDB filtering and selection, reusable charts and visual reports, training-only preprocessing, installed Function Explorer, parameterized recipes, resumable workflows and exact Python/notebook/replay exports. The original dark green theme is restored as the default, alongside Spectrum, Charcoal and Beige palettes.

Batch 2 adds parameterized image transforms, video/audio processing, OCR, document preparation and RAG bundles, and editable acquisition with consent and candidate review. Batch 3 adds Model Hub with fitted lexical retrieval and supervised language models, native credential connections, a restricted operation-script Playground, Windows voice personalities and opt-in local whisper.cpp transcription. See [integration guide](docs/integrations.md). Batch 4 closes the local release boundary with 186 passing backend tests, production browser acceptance and deterministic source packages. See [certification ledger](docs/batch-4.md). Native macOS/Linux certification remains unexecuted. See [release status](docs/2.0-status.md), [Batch 1 requirements and verification](docs/batch-1.md), and [architecture](docs/adr-0002-batch-one.md).

Table pages are bounded to 200 rows; transforms support up to 200,000 rows and 256 MiB Parquet. Preview sampling is explicit. Create a split before choosing Fit training preprocessing to fit statistics and category vocabulary exclusively on training rows.

## Quick start

Install **Python 3.12+** and **Node.js 22.13+** (Node 24 LTS recommended), then extract or clone this repository into a writable directory with at least 5 GB free. Initial setup requires internet access. Leave at least 2 GB free on the workspace drive for processing.

- **Windows:** double-click `start.bat` (or `MediaSensei-Windows.bat`).
- **macOS/Linux:** run `sh start.sh`. On macOS, `MediaSensei-macOS.command` also works after allowing it to open.

The launcher creates `.venv`, installs locked dependencies, initializes `.env`, builds the web application, starts FastAPI, the worker, and the built frontend, checks their health, and opens **http://127.0.0.1:3000**. Logs are in `.mediasensei-launcher/logs/`.

To prepare dependencies without starting, run `setup.bat` or `sh setup.sh`. For development with hot reload, run `start-dev.bat` or `sh start-dev.sh`. Stop with `Stop-MediaSensei-Windows.bat` or `python3 scripts/mediasensei_launcher.py stop`. Windows also accepts `python scripts/mediasensei_launcher.py stop`.

## Workflow

1. Create a project.
2. Use **Files or ZIP** or **Folder** to import local files. Multi-file selection uploads sequentially to bound memory and network use.
3. Check **Jobs** for processing progress and errors. Select a job to pause, resume, cancel, retry failures, or inspect events.
4. Browse originals and thumbnails in **Library**. Quarantine/reactivate assets as needed.
5. Use the dedicated **Data Lab**, **Image Lab**, **Video Lab**, **Audio Lab**, **Knowledge Lab**, and **Quality** areas.

A successful upload means bytes were accepted and jobs queued. Processing can subsequently fail for malformed content or missing optional tools; the failure is retained in Jobs. ZIP results report skipped entries rather than silently treating them as imported.

## Supported formats

| Type | Extensions | Requirements |
|---|---|---|
| Images | JPG/JPEG, PNG, WebP, BMP, TIF/TIFF, GIF | Pillow installed by launcher; transforms output JPEG/PNG/WebP |
| Documents | TXT, MD, Markdown, PDF, DOCX, HTML/HTM | Local parsing and indexing; scanned PDFs require an external OCR workflow |
| Audio/video | WAV, MP3, FLAC, M4A, OGG, AAC; MP4, MOV, MKV, WebM, AVI, M4V | Install FFmpeg **and ffprobe** on PATH |
| Tables | CSV, TSV, JSON, JSONL/NDJSON, Parquet, XLSX, SQLite/SQLite3/DB, DuckDB | Data extras installed by launcher |
| Archives | ZIP | Nested folders supported; nested ZIPs and unsupported files are skipped |

Image OCR uses configured **Tesseract**, with Windows inbox OCR as a fallback when the requested language is installed. These native tools are optional and are not bundled or installed silently. The **System** screen reports availability. Hugging Face/Kaggle adapters are optional: install `.[providers]` and configure the relevant service credentials to use their API/CLI workflows. Remote acquisition requires explicit project policy and `allow_remote`; it is not an automatic part of local imports.

Empty files and missing/unsupported extensions are rejected. Corrupt content with a supported extension is diagnosed during processing. Password-protected ZIPs and unsupported compression are rejected. ZIP traversal, drive paths, alternate data streams, symlinks, duplicate archive paths, and expansion limits are checked before catalog writes. Duplicate basenames in different folders are retained; immutable bytes use content-addressed storage.

## Configuration

Copy `.env.example` to `.env` if starting services manually. The launcher does this automatically. Existing process environment variables override the file.

| Variable | Default | Purpose |
|---|---|---|
| `MEDIASENSEI_WORKSPACE` | `.mediasensei-workspace` | SQLite metadata, original objects, derivatives, jobs, exports |
| `MEDIASENSEI_API_PORT` | `8000` | API port used by launcher |
| `MEDIASENSEI_WEB_PORT` | `3000` | Browser port used by launcher |
| `MEDIASENSEI_STARTUP_TIMEOUT_SECONDS` | `180` | Startup readiness allowance (10-1800 seconds) |
| `NEXT_PUBLIC_CORE_API_URL` | derived from API port by launcher | Full browser API base, including `/api/v1`; rebuild after changes |
| `MEDIASENSEI_CORS_ORIGINS` | `[]` | JSON array of additional approved browser origins; loopback origins allowed by default |
| `MEDIASENSEI_MAX_UPLOAD_BYTES` | `2147483648` | Per-file/upload limit (2 GiB) |
| `MEDIASENSEI_ZIP_MAX_FILES` | `20000` | ZIP entry limit |
| `MEDIASENSEI_ZIP_MAX_TOTAL_BYTES` | `21474836480` | Expanded supported content limit (20 GiB) |

Limits are ceilings, not recommended dataset sizes. Large tabular/document processing may need considerably more memory than the source file. Choose limits appropriate for your machine. Temporary multipart data also requires disk space on the OS temporary drive; `TEMP`/`TMP` (Windows) or `TMPDIR` (Unix) can place it on another drive.

Health: `GET http://127.0.0.1:8000/health` (also `/api/v1/health`). OpenAPI: `/docs` and `/openapi.json`. File uploads use multipart field `file`; ZIP imports use `/api/v1/projects/{id}/imports/archive`.

## Development and testing

After setup, install test tools into the private environment:

```powershell
# Windows
.venv\Scripts\python -m pip install -e ".[dev,image,data]" -c requirements-lock.txt
npm test
npm run lint
.venv\Scripts\python -m ruff check apps packages scripts tests
npm run build
npx playwright install chromium
npm run test:e2e
```

```sh
# macOS/Linux
.venv/bin/python -m pip install -e '.[dev,image,data]' -c requirements-lock.txt
npm test
npm run lint
.venv/bin/python -m ruff check apps packages scripts tests
npm run build
npx playwright install chromium
npm run test:e2e
```

On Linux, `npx playwright install --with-deps chromium` installs required browser system libraries. Tests exercise startup, API contracts, real processing, malformed uploads, ZIP limits/traversal/CRC errors, original/derived downloads, persistence, and browser error recovery. FFmpeg integration is skipped when its binaries are unavailable. CI is configured for Windows, Linux, and macOS; local verification does not imply those remote jobs have run.

To start services individually, activate `.venv`, then run these in separate terminals from the repository root:

```sh
python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8000
python -m mediasensei.cli worker run
npm run dev
```

## Release and deployment

```sh
npm run release:check
npm run release:bundle
node scripts/run-python.mjs scripts/release.py verify release/MediaSensei-1.0.2-windows.zip
node scripts/run-python.mjs scripts/release.py checksums
```

Bundles include source, tests, configuration example, CI, and launchers. Dependencies, user data, logs, local environment files, and generated frontend output are excluded. The launcher installs/builds from the source bundle. Python constraints capture the tested dependency set; npm uses `package-lock.json`.

**Deployment scope: a trusted, single-user local workstation.** The API has no user authentication and intentionally binds to loopback. Do not expose it directly to the internet. A shared/server deployment needs authentication, TLS, a reverse proxy with appropriate request limits/timeouts, backups, and a separately supervised worker. The retained `.openai/hosting.json`, `db/`, and `drizzle/` files describe the historical Sites frontend; they do not host the Python worker or replace its SQLite catalog. This release does not publish or change the linked Site.

## Troubleshooting

- **API unavailable:** inspect `api.log`; check Python setup, API port and `/health`. Changing API ports requires restarting/rebuilding the frontend. A 422 upload error is not an offline error.
- **Jobs stay queued:** make sure the worker is running and uses the same workspace as FastAPI. Check `worker.log`.
- **Jobs paused:** inspect job events for memory/disk pressure, free space, then use Resume. The scheduler pauses under 2 GiB of free workspace disk or 512 MiB available RAM.
- **Missing FFmpeg/Tesseract:** install the binary, ensure it is on PATH, restart services, and retry failed jobs.
- **Port already in use:** stop the old MediaSensei instance or choose ports in `.env`. Development startup uses a strict port and does not silently move the frontend.
- **Setup fails:** check disk space on both the project and temporary/cache drives, internet access, and Python/Node versions. Re-run setup after correcting the cause.
- **Moved the repository:** recreate `.venv` in the new location; Python virtual environments are not portable.
- **Untrusted plugins:** installing, validating, or approving a Python plugin can execute its code. Use only code you trust. The subprocess boundary is not an OS security sandbox.

## Architecture

`components/mediasensei-app.tsx` â†’ `lib/core-api.ts` â†’ FastAPI in `apps/api/` â†’ core services in `packages/core/` â†’ SQLite catalog/content-addressed files â†’ a separate leased worker â†’ UI polling.

The domain and processing adapters remain independent of React. Upload storage/extraction and validated API configuration now have separate modules. SQLite WAL, immutable originals, deterministic cache keys, and persistent jobs suit a local MVP. Large-scale multi-user processing, paginated catalog queries, and splitting the remaining large UI/API adapters are future work; see [engineering report](AUDIT_REPORT.md) and `docs/architecture/`.

License: Apache-2.0.

If the browser does not open, check `.mediasensei-launcher/logs/launcher.log` and `.mediasensei-launcher/startup-status.json`. They preserve the launcher result and each service's readiness error. The web log retains npm output on Windows. A failed readiness check stops the services; run `start.bat` / `sh start.sh` again after addressing the reported error. When readiness succeeds, open http://127.0.0.1:3000 manually if the browser association fails.

## Data Lab workflow

1. Import a CSV, Excel or Parquet file from Overview and wait for its inspection job.
2. Open Data Lab, refresh imports, then choose **Create from import**.
3. Inspect rows; click a column header for its profile. Use the inspector to choose an operation and parameters.
4. Preview a sample, then Run. Follow progress in the job drawer and inspect operation history.
5. Add configured operations to Workflows; dry run, reorder and save a reusable recipe.
6. Create a named snapshot in Versions. Export its Parquet or reproducibility bundle, including the original normalized input and exact executable workflow.

Snapshots store references, not copies of unchanged data. Concurrent stale-head updates fail rather than overwriting newer changes. Restoring a version also restores its lineage. Working revisions are additive; no imported asset is overwritten.

## Shared SDK and CLI

```python
from mediasensei.operations import Workbench
workbench = Workbench(".mediasensei-workspace")
datasets = workbench.datasets("PROJECT_ID")
dataset = workbench.dataset("DATASET_ID")
preview = workbench.preview(dataset["id"], "fill_missing", {"columns": ["income"], "strategy": "median"})
job = workbench.enqueue(dataset["id"], [{"operation": "fill_missing", "parameters": {"columns": ["income"], "strategy": "median"}}], dataset["revision"])
```

Run `mediasensei operation search "heat map"` or `mediasensei operation run DATASET_ID profile` after activating the installed environment. Operation execution uses the existing worker. Generated Python calls the same public `execute_frame` implementation; it requires the recorded MediaSensei and library versions.

New API routes are documented under `/docs`, tag **Operation workbench**. New tests: `pytest tests/test_operations.py`. With the app running on ports 8010/3010, `node scripts/workbench-smoke.mjs` exercises the full Data Lab browser flow; ports can be overridden with `NEXT_PUBLIC_CORE_API_URL` and `MEDIASENSEI_SMOKE_WEB_URL`.

## Replaying an exported workflow

Replay uses the exact public MediaSensei core, so install the matching source release before running workflow.py. From the release root, run `.venv/Scripts/python.exe -m pip install -e ".[image,data]" -c requirements-lock.txt` on Windows (use `.venv/bin/python` on macOS/Linux), then use that same absolute Python executable to run workflow.py in the extracted bundle directory. Do not use an unrelated older MediaSensei installation. The launcher already installs the correct workbench package. See docs/media-workbench.md for native media setup.
"# MediaSensei" 
