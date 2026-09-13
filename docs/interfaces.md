# Interfaces quickstart

## REST API

Run `uv run uvicorn apps.api.main:app --host 127.0.0.1 --port 8000` and open `/docs`. Versioned routes begin at `/api/v1`. Errors use a stable `code` and user-safe `message`. Asset uploads are filename-normalized, size-capped, hashed, integrity-verified, deduplicated, and then recorded.

Job endpoints support enqueue, list/detail, structured events, pause, resume, cancel, retry-failed, and cache statistics. Image endpoints enqueue validation, thumbnails, pHash, OCR, and transforms; dataset endpoints create deterministic splits, persist leakage findings, and materialize media + Parquet exports. Media endpoints import and enqueue ffprobe/FFmpeg jobs, list stream metadata and derivatives, and request validation, previews, clips, or transcodes. Document endpoints import and enqueue offline parsing/chunking/embedding, list indexes and ContentUnit chunks, and return exact-cosine retrieval hits with source provenance. Tabular endpoints import and enqueue normalization, then expose schema/profile detail, parameterized queries, frequencies, mappings, and structured exports. The API never executes queued CPU work in its request process.
Dataset-provider endpoints expose capabilities, create policy-gated imports, and inspect import/file checkpoints:

- `GET /api/v1/dataset-providers`
- `GET /api/v1/projects/{project_id}/provider-imports`
- `POST /api/v1/projects/{project_id}/provider-imports`
- `GET /api/v1/provider-imports/{import_id}`

Creation requires an `approved_external` or `unrestricted` project and `allow_remote: true`. Hugging Face branch/tag requests resolve to an exact commit hash; Kaggle imports persist the numeric dataset version. Credentials stay in provider-native environment/configuration and are never returned or stored.

Acquisition endpoints expose capabilities, local planning, separately authorized test/full runs, status and rejection summaries, candidate filtering, human decisions, and pause/resume/cancel:

- `GET /api/v1/acquisition/providers`
- `POST /api/v1/projects/{project_id}/acquisition/requests`
- `POST /api/v1/projects/{project_id}/acquisition/plans`
- `GET /api/v1/acquisition/plans/{plan_id}`
- `POST /api/v1/acquisition/plans/{plan_id}/test`
- `POST /api/v1/acquisition/plans/{plan_id}/start`
- `GET /api/v1/acquisition/runs/{run_id}`
- `GET /api/v1/acquisition/runs/{run_id}/candidates`
- `POST /api/v1/acquisition/candidates/{candidate_id}/decision`
- `POST /api/v1/acquisition/runs/{run_id}/{pause|resume|cancel}`

Planning is network-free. Test/start require `allow_remote: true` plus an external-data project policy; the queued worker performs all discovery and downloads.
Plugin inventory is available at `GET /api/v1/plugins`. It returns Plugin API 1.5, compatible registrations, capability counts, permissions, and isolated safe diagnostics. Plugin entry-point code is never executed by the web workspace; the local Python runtime owns discovery and validation.
## Python SDK

```python
from mediasensei import Catalog, ContentAddressedStore, JobQueue, LocalWorker
from mediasensei.domain import ProcessorSpec, WorkItem

catalog = Catalog("./workspace")
project = catalog.create_project("Example")
stored = ContentAddressedStore("./workspace").import_file("photo.jpg")
queue = JobQueue(catalog)
job = queue.enqueue(
    project_id=str(project.id),
    kind="inspect",
    processor=ProcessorSpec(id="core.identity", version="1.0.0"),
    items=[WorkItem(input_hash=stored.sha256, input_ref=stored.object_key, position=0)],
)
LocalWorker(queue).run_once()
```

## CLI

```bash
mediasensei doctor
mediasensei project create "Example"
mediasensei project list
mediasensei provider list
mediasensei project create "External Dataset" --data-policy approved_external
mediasensei provider import PROJECT_ID huggingface org/dataset --revision main --allow-pattern "*.parquet" --allow-remote
mediasensei provider imports PROJECT_ID
mediasensei provider show IMPORT_ID
mediasensei acquire providers PROJECT_ID
mediasensei acquire prompt PROJECT_ID "Find 500 diverse marine-life images, minimum 1024px"
mediasensei acquire plan PROJECT_ID --topic "marine life" --target 500 --min-width 1024 --min-height 1024
mediasensei acquire test PLAN_ID --count 20 --allow-remote
mediasensei acquire run PLAN_ID --allow-remote
mediasensei acquire status RUN_ID
mediasensei acquire candidates RUN_ID --state rejected --reason low_resolution
mediasensei acquire decide CANDIDATE_ID accept
mediasensei acquire control RUN_ID pause
mediasensei job enqueue-demo PROJECT_ID --count 100
mediasensei job list
mediasensei job pause JOB_ID
mediasensei job resume JOB_ID
mediasensei job retry-failed JOB_ID
mediasensei worker run
mediasensei image import-path PROJECT_ID ./images
mediasensei image analyze PROJECT_ID
mediasensei image ocr PROJECT_ID --action detect_only
mediasensei image transform PROJECT_ID --width 1024 --height 1024 --format WEBP
mediasensei image duplicates PROJECT_ID
mediasensei image split PROJECT_ID --strategy group_aware --seed 42
mediasensei image leakage PROJECT_ID
mediasensei image export PROJECT_ID ./exports/v1
mediasensei media import-path PROJECT_ID ./media
mediasensei media analyze PROJECT_ID --validate-decode
mediasensei media list PROJECT_ID
mediasensei media derive PROJECT_ID --media-kind video --kind transcode --format webm
mediasensei media derive PROJECT_ID --media-kind audio --kind waveform
mediasensei document import-path PROJECT_ID ./documents
mediasensei document index PROJECT_ID --max-words 420 --overlap-words 64
mediasensei worker run --once
mediasensei document list PROJECT_ID
mediasensei document chunks ASSET_ID
mediasensei document search PROJECT_ID "infrared cooldown" --limit 5
mediasensei tabular import-path PROJECT_ID ./observations.csv
mediasensei worker run --once
mediasensei tabular show DATASET_ID
mediasensei tabular query DATASET_ID --filter 'species:eq:"fox"'
mediasensei tabular frequency DATASET_ID species
mediasensei tabular map DATASET_ID '{"species":"annotation.label"}' --metadata-json '{"license":"CC-BY-4.0"}'
mediasensei tabular export DATASET_ID ./exports/observations.xlsx --format xlsx
mediasensei plugin contracts
mediasensei plugin create my-plugin
mediasensei plugin validate ./my_plugin/src/my_plugin/plugin.py
mediasensei plugin list
```
