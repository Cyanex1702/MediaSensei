from __future__ import annotations

import json
import os
import platform
import shutil
import sqlite3
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, cast

import typer
from dotenv import load_dotenv

from mediasensei import __version__
from mediasensei.domain.acquisition import (
    AcquisitionBudget,
    AcquisitionDecisionKind,
    AcquisitionModality,
    AcquisitionRunState,
    AcquisitionSpec,
    TargetSpec,
    TargetUnit,
)
from mediasensei.domain.documents import DocumentFormat
from mediasensei.domain.images import DatasetSample, FitMode, OCRAction, SplitStrategy
from mediasensei.domain.jobs import (
    ProcessorSpec,
    ResourceHints,
    ResourceLevel,
    RuntimeProfile,
    WorkItem,
)
from mediasensei.domain.media import MediaDerivativeKind, MediaKind
from mediasensei.domain.providers import ProviderImportOptions
from mediasensei.domain.tabular import (
    FilterOperator,
    TabularFilter,
    TabularFormat,
    TabularQuery,
)
from mediasensei.infrastructure.acquisition import (
    AcquisitionService,
    acquisition_processor_spec,
    acquisition_request_hash,
)
from mediasensei.infrastructure.acquisition_planning import (
    DiscoveryRegistry,
    spec_from_dict,
)
from mediasensei.infrastructure.catalog import Catalog
from mediasensei.infrastructure.datasets import (
    DatasetSplitter,
    DuplicateDetector,
    LeakageDetector,
    MediaParquetExporter,
)
from mediasensei.infrastructure.documents import SQLiteVectorIndex, document_processor_spec
from mediasensei.infrastructure.jobs import JobQueue
from mediasensei.infrastructure.media import FFmpegToolchain, media_processor_spec
from mediasensei.infrastructure.plugins import (
    PluginRuntime,
    PluginSubprocessExecutor,
    PluginTrustStore,
    validate_plugin_file,
)
from mediasensei.infrastructure.providers import (
    DatasetProviderRegistry,
    provider_processor_spec,
    provider_request_hash,
)
from mediasensei.infrastructure.scheduler import AdaptiveScheduler, HardwareProfile
from mediasensei.infrastructure.storage import ContentAddressedStore
from mediasensei.infrastructure.tabular import TabularEngine, tabular_processor_spec
from mediasensei.infrastructure.worker import LocalWorker

load_dotenv(Path.cwd() / ".env")

app = typer.Typer(help="MediaSensei local-first data engineering CLI.")
project_app = typer.Typer(help="Create and inspect projects.")
plugin_app = typer.Typer(help="Inspect and scaffold plugins.")
job_app = typer.Typer(help="Enqueue and control persistent jobs.")
worker_app = typer.Typer(help="Run the separate local worker process.")
image_app = typer.Typer(help="Import, analyze, split, validate, and export images.")
document_app = typer.Typer(help="Import, chunk, embed, inspect, and search documents locally.")
media_app = typer.Typer(help="Import, inspect, preview, clip, and transcode video or audio.")
tabular_app = typer.Typer(help="Import, inspect, query, map, and export structured data.")
provider_app = typer.Typer(help="Import revision-pinned Hugging Face and Kaggle datasets.")
acquire_app = typer.Typer(help="Plan, test, run, and inspect Intelligent Acquisition.")
app.add_typer(project_app, name="project")
app.add_typer(plugin_app, name="plugin")
app.add_typer(job_app, name="job")
app.add_typer(worker_app, name="worker")
app.add_typer(image_app, name="image")
app.add_typer(document_app, name="document")
app.add_typer(media_app, name="media")
app.add_typer(tabular_app, name="tabular")
app.add_typer(provider_app, name="provider")
app.add_typer(acquire_app, name="acquire")


def workspace_path() -> Path:
    return Path(os.environ.get("MEDIASENSEI_WORKSPACE", ".mediasensei-workspace")).resolve()


def local_queue() -> JobQueue:
    return JobQueue(Catalog(workspace_path()))


provider_registry = DatasetProviderRegistry.defaults()
acquisition_discovery_registry = DiscoveryRegistry.defaults()
acquisition_downloader = None


@app.command()
def doctor() -> None:
    """Inspect the local runtime without changing project data."""
    workspace = workspace_path()
    catalog = Catalog(workspace)
    queue = JobQueue(catalog)
    hardware = HardwareProfile.detect(workspace)
    decision = AdaptiveScheduler().decide(
        hardware,
        RuntimeProfile.BALANCED,
        ResourceHints(cpu=ResourceLevel.MEDIUM, memory=ResourceLevel.MEDIUM),
    )
    report = {
        "mediasensei": __version__,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "cpu_threads": hardware.cpu_threads,
        "total_memory_bytes": hardware.total_memory_bytes,
        "available_memory_bytes": hardware.available_memory_bytes,
        "database": str(catalog.database_path),
        "sqlite": sqlite3.sqlite_version,
        "storage": str(workspace),
        "free_bytes": hardware.free_disk_bytes,
        "ffmpeg": shutil.which("ffmpeg"),
        "ffprobe": shutil.which("ffprobe"),
        "runtime_profile": decision.profile.value,
        "recommended_concurrency": decision.max_concurrency,
        "backpressure_paused": decision.paused_for_pressure,
        "warnings": list(decision.warnings),
        "cache": queue.cache_stats(),
    }
    typer.echo(json.dumps(report, indent=2))


@project_app.command("create")
def project_create(
    name: str,
    description: str = "",
    data_policy: str = typer.Option("local_only", "--data-policy"),
) -> None:
    if data_policy not in {"local_only", "approved_external", "unrestricted"}:
        raise typer.BadParameter(
            "data-policy must be local_only, approved_external, or unrestricted"
        )
    project = Catalog(workspace_path()).create_project(name, description, data_policy)
    typer.echo(f"Created {project.name} ({project.id})")


@project_app.command("list")
def project_list() -> None:
    for project in Catalog(workspace_path()).list_projects():
        typer.echo(f"{project['id']}  {project['name']}")


@acquire_app.command("providers")
def acquire_providers(project_id: str | None = None) -> None:
    service = AcquisitionService(
        Catalog(workspace_path()),
        discovery=acquisition_discovery_registry,
    )
    typer.echo(json.dumps(service.capabilities(project_id), indent=2))


@acquire_app.command("prompt")
def acquire_prompt(
    project_id: str,
    prompt: str,
) -> None:
    service = AcquisitionService(
        Catalog(workspace_path()),
        discovery=acquisition_discovery_registry,
    )
    request_id, plan_id = service.from_prompt(project_id, prompt)
    typer.echo(
        json.dumps(
            {"request_id": request_id, "plan": service.repository.plan(plan_id)},
            indent=2,
        )
    )


@acquire_app.command("plan")
def acquire_plan(
    project_id: str,
    topic: str = typer.Option(..., "--topic"),
    target: int = typer.Option(100, "--target", min=1, max=100_000),
    min_width: int = typer.Option(512, "--min-width", min=1, max=100_000),
    min_height: int = typer.Option(512, "--min-height", min=1, max=100_000),
    category: Annotated[list[str] | None, typer.Option("--category")] = None,
    query: Annotated[list[str] | None, typer.Option("--query")] = None,
    provider: Annotated[list[str] | None, typer.Option("--provider")] = None,
    max_candidates: int = typer.Option(1500, "--max-candidates", min=1, max=1_000_000),
    max_download_mib: int = typer.Option(25_600, "--max-download-mib", min=1),
    max_storage_mib: int = typer.Option(20_480, "--max-storage-mib", min=1),
    max_requests: int = typer.Option(2_000, "--max-requests", min=1),
    reject_exact_duplicates: bool = typer.Option(True, "--reject-exact/--allow-exact-duplicates"),
    near_duplicate_threshold: int = typer.Option(8, "--near-duplicate-threshold", min=0, max=64),
    replenish_until_target: bool = typer.Option(True, "--replenish/--single-batch"),
    relevance: str = typer.Option("auto", "--relevance"),
) -> None:
    provider_ids = tuple(provider or ["wikimedia-commons", "openverse"])
    for provider_id in provider_ids:
        try:
            acquisition_discovery_registry.get(provider_id)
        except LookupError as error:
            raise typer.BadParameter(str(error), param_hint="--provider") from error
    try:
        spec = AcquisitionSpec(
            AcquisitionModality.IMAGE,
            topic,
            TargetSpec(TargetUnit.ACCEPTED_ASSETS, target),
            categories=tuple(category or []),
            queries=tuple(query or []),
            provider_ids=provider_ids,
            min_width=min_width,
            min_height=min_height,
            reject_exact_duplicates=reject_exact_duplicates,
            near_duplicate_threshold=near_duplicate_threshold,
            relevance_strategy=relevance,
            replenish_until_target=replenish_until_target,
            budget=AcquisitionBudget(
                max_candidates=max_candidates,
                max_download_bytes=max_download_mib * 1024**2,
                max_storage_bytes=max_storage_mib * 1024**2,
                max_requests=max_requests,
            ),
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    service = AcquisitionService(
        Catalog(workspace_path()),
        discovery=acquisition_discovery_registry,
    )
    request_id, plan_id = service.create_plan(project_id, spec)
    typer.echo(
        json.dumps(
            {"request_id": request_id, "plan": service.repository.plan(plan_id)},
            indent=2,
        )
    )


@acquire_app.command("run")
def acquire_run(
    plan_id: str,
    allow_remote: bool = typer.Option(False, "--allow-remote"),
) -> None:
    typer.echo(json.dumps(_queue_acquisition(plan_id, allow_remote), indent=2))


@acquire_app.command("test")
def acquire_test(
    plan_id: str,
    count: int = typer.Option(20, "--count", min=1, max=100),
    allow_remote: bool = typer.Option(False, "--allow-remote"),
) -> None:
    typer.echo(
        json.dumps(
            _queue_acquisition(plan_id, allow_remote, dry_run_count=count),
            indent=2,
        )
    )


@acquire_app.command("status")
def acquire_status(run_id: str) -> None:
    service = AcquisitionService(Catalog(workspace_path()))
    typer.echo(
        json.dumps(
            {
                **service.repository.run(run_id),
                "rejections": service.repository.rejection_summary(run_id),
            },
            indent=2,
        )
    )


@acquire_app.command("candidates")
def acquire_candidates(
    run_id: str,
    state: str | None = typer.Option(None, "--state"),
    reason: str | None = typer.Option(None, "--reason"),
) -> None:
    service = AcquisitionService(Catalog(workspace_path()))
    typer.echo(
        json.dumps(
            {"items": service.repository.list_candidates(run_id, state=state, reason=reason)},
            indent=2,
        )
    )


@acquire_app.command("decide")
def acquire_decide(candidate_id: str, decision: str) -> None:
    try:
        selected = AcquisitionDecisionKind(decision)
    except ValueError as error:
        raise typer.BadParameter("decision must be accept, reject, or review") from error
    service = AcquisitionService(Catalog(workspace_path()))
    typer.echo(json.dumps(service.human_decision(candidate_id, selected), indent=2))


@acquire_app.command("control")
def acquire_control(run_id: str, action: str) -> None:
    catalog = Catalog(workspace_path())
    service = AcquisitionService(catalog)
    run = service.repository.run(run_id)
    job_id = str(run.get("job_id") or "")
    queue = JobQueue(catalog)
    if action == "pause":
        service.repository.set_run_state(run_id, AcquisitionRunState.PAUSED)
        if job_id:
            queue.pause(job_id)
    elif action == "resume":
        service.repository.set_run_state(run_id, AcquisitionRunState.REPLENISHING)
        if job_id:
            queue.retry_failed(job_id)
            queue.resume(job_id)
    elif action == "cancel":
        service.repository.set_run_state(run_id, AcquisitionRunState.CANCELLED)
        if job_id:
            queue.cancel(job_id)
    else:
        raise typer.BadParameter("action must be pause, resume, or cancel")
    typer.echo(json.dumps(service.repository.run(run_id), indent=2))


def _queue_acquisition(
    plan_id: str,
    allow_remote: bool,
    *,
    dry_run_count: int | None = None,
) -> dict[str, object]:
    if not allow_remote:
        raise typer.BadParameter("Pass --allow-remote to authorize network acquisition")
    catalog = Catalog(workspace_path())
    service = AcquisitionService(
        catalog,
        discovery=acquisition_discovery_registry,
        downloader=acquisition_downloader,
    )
    plan = service.repository.plan(plan_id)
    if service.repository.project_policy(str(plan["project_id"])) == "local_only":
        raise typer.BadParameter(
            "The project is local-only; use an approved_external or unrestricted project"
        )
    run_id = service.repository.create_run(plan_id, dry_run_count=dry_run_count)
    spec = spec_from_dict(cast(dict[str, object], plan["spec"]))
    job = JobQueue(catalog).enqueue(
        project_id=str(plan["project_id"]),
        kind="intelligent-acquisition",
        processor=acquisition_processor_spec(),
        items=[WorkItem(acquisition_request_hash(run_id, spec), run_id, 0)],
        parameters={"run_id": run_id},
        profile=RuntimeProfile.BALANCED,
    )
    service.repository.attach_job(run_id, job.id)
    return {"run": service.repository.run(run_id), "job": _job_dict(job)}


@provider_app.command("list")
def provider_list() -> None:
    typer.echo(json.dumps({"items": provider_registry.capabilities()}, indent=2))


@provider_app.command("imports")
def provider_imports(project_id: str) -> None:
    catalog = Catalog(workspace_path())
    catalog.get_project(project_id)
    typer.echo(json.dumps({"items": catalog.list_provider_imports(project_id)}, indent=2))


@provider_app.command("show")
def provider_show(import_id: str) -> None:
    catalog = Catalog(workspace_path())
    typer.echo(
        json.dumps(
            {
                **catalog.provider_import(import_id),
                "files": catalog.provider_import_files(import_id),
            },
            indent=2,
        )
    )


@provider_app.command("import")
def provider_import_dataset(
    project_id: str,
    provider_id: str,
    dataset_id: str,
    revision: str | None = typer.Option(None, "--revision"),
    allow_pattern: Annotated[list[str] | None, typer.Option("--allow-pattern")] = None,
    ignore_pattern: Annotated[list[str] | None, typer.Option("--ignore-pattern")] = None,
    max_files: int = typer.Option(10_000, min=1, max=100_000),
    max_file_mib: int = typer.Option(2048, min=1, max=102_400),
    max_total_mib: int = typer.Option(20_480, min=1, max=1_048_576),
    allow_remote: bool = typer.Option(False, "--allow-remote"),
) -> None:
    if not allow_remote:
        raise typer.BadParameter("Pass --allow-remote to authorize network access")
    catalog = Catalog(workspace_path())
    project = catalog.get_project(project_id)
    if project["data_policy"] == "local_only":
        raise typer.BadParameter(
            "The project is local-only; use an approved_external or unrestricted project"
        )
    try:
        provider = provider_registry.get(provider_id)
    except LookupError as error:
        raise typer.BadParameter(str(error)) from error
    if not provider.available():
        raise typer.BadParameter(
            "Provider unavailable; install with: pip install 'mediasensei[providers]'"
        )
    options = ProviderImportOptions(
        allow_patterns=tuple(allow_pattern or []),
        ignore_patterns=tuple(ignore_pattern or []),
        max_files=max_files,
        max_file_bytes=max_file_mib * 1024**2,
        max_total_bytes=max_total_mib * 1024**2,
    )
    clean_revision = revision.strip() if revision else None
    import_id = catalog.create_provider_import(
        project_id=project_id,
        provider_id=provider.provider_id,
        dataset_id=dataset_id,
        requested_revision=clean_revision,
        allow_patterns=options.allow_patterns,
        ignore_patterns=options.ignore_patterns,
        max_files=options.max_files,
        max_file_bytes=options.max_file_bytes,
        max_total_bytes=options.max_total_bytes,
    )
    queue = JobQueue(catalog)
    job = queue.enqueue(
        project_id=project_id,
        kind="dataset-provider-import",
        processor=provider_processor_spec(),
        items=[
            WorkItem(
                provider_request_hash(provider.provider_id, dataset_id, clean_revision, options),
                import_id,
                0,
            )
        ],
        parameters={"import_id": import_id},
        profile=RuntimeProfile.BALANCED,
    )
    typer.echo(
        json.dumps(
            {"import": catalog.provider_import(import_id), "job": _job_dict(job)},
            indent=2,
        )
    )


@job_app.command("list")
def job_list(project_id: str | None = None, limit: int = 50) -> None:
    jobs = local_queue().list_jobs(project_id, limit=limit)
    if not jobs:
        typer.echo("No jobs found.")
        return
    for job in jobs:
        typer.echo(
            f"{job.id}  {job.state.value:22}  {job.progress:3}%  "
            f"{job.cached_count} cached  {job.failed_count} failed  {job.kind}"
        )


@job_app.command("show")
def job_show(job_id: str) -> None:
    job = local_queue().get(job_id)
    typer.echo(json.dumps(_job_dict(job), indent=2))


@job_app.command("enqueue-demo")
def job_enqueue_demo(
    project_id: str,
    count: int = typer.Option(10, min=1, max=10_000),
    profile: RuntimeProfile = RuntimeProfile.BALANCED,
) -> None:
    processor = ProcessorSpec(
        id="core.identity",
        version="1.0.0",
        resource_hints=ResourceHints(
            cpu=ResourceLevel.LOW,
            memory=ResourceLevel.LOW,
        ),
    )
    job = local_queue().enqueue(
        project_id=project_id,
        kind="demo-inspection",
        processor=processor,
        items=[
            WorkItem(
                input_hash=f"{index:064x}",
                input_ref=f"demo:{index}",
                position=index,
            )
            for index in range(count)
        ],
        parameters={"source": "cli-demo"},
        profile=profile,
    )
    typer.echo(f"Queued {job.id} with {job.total_items} items")


@job_app.command("pause")
def job_pause(job_id: str) -> None:
    typer.echo(f"{job_id} -> {local_queue().pause(job_id).state.value}")


@job_app.command("resume")
def job_resume(job_id: str) -> None:
    typer.echo(f"{job_id} -> {local_queue().resume(job_id).state.value}")


@job_app.command("cancel")
def job_cancel(job_id: str) -> None:
    typer.echo(f"{job_id} -> {local_queue().cancel(job_id).state.value}")


@job_app.command("retry-failed")
def job_retry_failed(job_id: str) -> None:
    typer.echo(f"{job_id} -> {local_queue().retry_failed(job_id).state.value}")


@worker_app.command("run")
def worker_run(
    once: bool = typer.Option(False, "--once", help="Process at most one queued job."),
    poll_interval: float = typer.Option(0.5, min=0.05, max=5.0),
) -> None:
    """Run the restart-safe local worker outside the API process."""
    worker = LocalWorker(local_queue())
    if once:
        job = worker.run_once()
        typer.echo("No queued jobs." if job is None else json.dumps(_job_dict(job), indent=2))
        return
    typer.echo(f"Worker {worker.worker_id} is running. Press Ctrl+C to stop.")
    try:
        worker.run_forever(poll_interval=poll_interval)
    except KeyboardInterrupt:
        typer.echo("Worker stopped; active work will recover from its lease/checkpoint.")


@image_app.command("import-path")
def image_import_path(
    project_id: str,
    source: Path,
    recursive: bool = typer.Option(True, "--recursive/--no-recursive"),
) -> None:
    """Import image files immutably and enqueue content analysis."""
    catalog = Catalog(workspace_path())
    store = ContentAddressedStore(workspace_path())
    queue = JobQueue(catalog)
    source_path = source.expanduser().resolve(strict=True)
    candidates = (
        [source_path]
        if source_path.is_file()
        else list(source_path.rglob("*") if recursive else source_path.glob("*"))
    )
    extensions = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif"}
    imported: list[tuple[str, str]] = []
    for candidate in sorted(path for path in candidates if path.is_file()):
        if candidate.suffix.lower() not in extensions:
            continue
        stored = store.import_file(candidate)
        asset_id = catalog.record_asset(
            project_id=project_id,
            sha256=stored.sha256,
            original_filename=candidate.name,
            media_type="image",
            object_key=stored.object_key,
            byte_size=stored.byte_size,
            metadata={"source_path": str(candidate)},
        )
        imported.append((asset_id, stored.sha256))
    if not imported:
        raise typer.BadParameter("No supported image files were found")
    assets = [catalog.get_asset(asset_id) for asset_id, _ in imported]
    job = _enqueue_image_job(queue, project_id, assets, "image.inspect", "image-inspection")
    typer.echo(f"Imported {len(imported)} images and queued {job.id}")


@image_app.command("analyze")
def image_analyze(project_id: str) -> None:
    catalog = Catalog(workspace_path())
    assets = catalog.list_assets(project_id, media_type="image", state=None)
    job = _enqueue_image_job(
        JobQueue(catalog), project_id, assets, "image.inspect", "image-inspection"
    )
    typer.echo(f"Queued {job.id} for {job.total_items} images")


@image_app.command("ocr")
def image_ocr(
    project_id: str,
    action: OCRAction = OCRAction.DETECT_ONLY,
    language: str | None = None,
) -> None:
    catalog = Catalog(workspace_path())
    assets = catalog.list_assets(project_id, media_type="image", state="active")
    job = _enqueue_image_job(
        JobQueue(catalog),
        project_id,
        assets,
        "image.ocr",
        "image-ocr",
        parameters={"action": action.value, "language": language},
        deterministic=False,
    )
    typer.echo(f"Queued OCR job {job.id} for {job.total_items} images")


@image_app.command("transform")
def image_transform(
    project_id: str,
    width: int = typer.Option(1024, min=1, max=16384),
    height: int = typer.Option(1024, min=1, max=16384),
    fit: FitMode = FitMode.CONTAIN,
    format: str = typer.Option("JPEG"),
    quality: int = typer.Option(90, min=1, max=100),
) -> None:
    catalog = Catalog(workspace_path())
    assets = catalog.list_assets(project_id, media_type="image", state="active")
    parameters: dict[str, object] = {
        "width": width,
        "height": height,
        "fit": fit.value,
        "format": format.upper(),
        "quality": quality,
    }
    job = _enqueue_image_job(
        JobQueue(catalog),
        project_id,
        assets,
        "image.transform",
        "image-transform",
        parameters=parameters,
    )
    typer.echo(f"Queued transform job {job.id} for {job.total_items} images")


@image_app.command("duplicates")
def image_duplicates(project_id: str, threshold: int = typer.Option(8, min=0, max=64)) -> None:
    catalog = Catalog(workspace_path())
    groups = DuplicateDetector().groups(
        _project_image_samples(catalog, project_id), perceptual_threshold=threshold
    )
    catalog.replace_duplicate_groups(project_id, groups)
    typer.echo(json.dumps({"groups": groups, "count": len(groups)}, indent=2))


@image_app.command("split")
def image_split(
    project_id: str,
    strategy: SplitStrategy = SplitStrategy.RANDOM,
    seed: int = 42,
    train: float = 0.8,
    validation: float = 0.1,
    test: float = 0.1,
) -> None:
    catalog = Catalog(workspace_path())
    assigned = DatasetSplitter().assign(
        _project_image_samples(catalog, project_id),
        strategy=strategy,
        seed=seed,
        ratios={"train": train, "validation": validation, "test": test},
    )
    catalog.replace_dataset_samples(project_id, assigned, seed=seed, strategy=strategy.value)
    counts: dict[str, int] = {}
    for sample in assigned:
        counts[sample.split or "unassigned"] = counts.get(sample.split or "unassigned", 0) + 1
    typer.echo(json.dumps({"seed": seed, "strategy": strategy.value, "counts": counts}, indent=2))


@image_app.command("leakage")
def image_leakage(project_id: str, threshold: int = typer.Option(8, min=0, max=64)) -> None:
    catalog = Catalog(workspace_path())
    samples = catalog.dataset_samples(project_id)
    issues = LeakageDetector().detect(samples, perceptual_threshold=threshold)
    catalog.replace_leakage_issues(project_id, issues)
    typer.echo(
        json.dumps({"issues": [asdict(issue) for issue in issues], "count": len(issues)}, indent=2)
    )


@image_app.command("export")
def image_export(project_id: str, destination: Path) -> None:
    catalog = Catalog(workspace_path())
    samples = catalog.dataset_samples(project_id)
    result = MediaParquetExporter(ContentAddressedStore(workspace_path())).export(
        samples,
        destination,
        project_name=project_id,
        split_seed=42,
    )
    catalog.record_export(project_id, result)
    typer.echo(json.dumps(asdict(result), indent=2))


@document_app.command("import-path")
def document_import_path(
    project_id: str,
    source: Path,
    recursive: bool = typer.Option(True, "--recursive/--no-recursive"),
    max_words: int = typer.Option(420, min=32, max=4096),
    overlap_words: int = typer.Option(64, min=0, max=1024),
) -> None:
    """Import documents immutably and queue local chunking plus embeddings."""
    if overlap_words >= max_words:
        raise typer.BadParameter("Overlap must be smaller than chunk size")
    catalog = Catalog(workspace_path())
    store = ContentAddressedStore(workspace_path())
    source_path = source.expanduser().resolve(strict=True)
    candidates = (
        [source_path]
        if source_path.is_file()
        else list(source_path.rglob("*") if recursive else source_path.glob("*"))
    )
    assets: list[dict[str, object]] = []
    for candidate in sorted(path for path in candidates if path.is_file()):
        try:
            document_format = DocumentFormat.from_filename(candidate.name)
        except ValueError:
            continue
        stored = store.import_file(candidate)
        asset_id = catalog.record_asset(
            project_id=project_id,
            sha256=stored.sha256,
            original_filename=candidate.name,
            media_type="document",
            object_key=stored.object_key,
            byte_size=stored.byte_size,
            metadata={"source_path": str(candidate), "format": document_format.value},
        )
        assets.append(catalog.get_asset(asset_id))
    if not assets:
        raise typer.BadParameter("No supported TXT, Markdown, HTML, PDF, or DOCX files were found")
    job = _enqueue_document_job(
        JobQueue(catalog),
        project_id,
        assets,
        max_words=max_words,
        overlap_words=overlap_words,
    )
    typer.echo(f"Imported {len(assets)} documents and queued {job.id}")


@document_app.command("list")
def document_list(project_id: str) -> None:
    catalog = Catalog(workspace_path())
    typer.echo(
        json.dumps(
            {
                "items": catalog.list_document_indexes(project_id),
                "stats": catalog.document_stats(project_id),
            },
            indent=2,
        )
    )


@document_app.command("index")
def document_index(
    project_id: str,
    max_words: int = typer.Option(420, min=32, max=4096),
    overlap_words: int = typer.Option(64, min=0, max=1024),
) -> None:
    if overlap_words >= max_words:
        raise typer.BadParameter("Overlap must be smaller than chunk size")
    catalog = Catalog(workspace_path())
    assets = catalog.list_assets(project_id, media_type="document", state="active")
    job = _enqueue_document_job(
        JobQueue(catalog),
        project_id,
        assets,
        max_words=max_words,
        overlap_words=overlap_words,
    )
    typer.echo(f"Queued {job.id} for {job.total_items} documents")


@document_app.command("chunks")
def document_chunks(asset_id: str, limit: int = typer.Option(200, min=1, max=1000)) -> None:
    typer.echo(
        json.dumps(Catalog(workspace_path()).document_chunks(asset_id, limit=limit), indent=2)
    )


@document_app.command("search")
def document_search(
    project_id: str,
    query: str,
    limit: int = typer.Option(5, min=1, max=50),
    minimum_score: float = typer.Option(0.0, min=-1.0, max=1.0),
) -> None:
    catalog = Catalog(workspace_path())
    hits = SQLiteVectorIndex(catalog).search(
        project_id,
        query,
        limit=limit,
        minimum_score=minimum_score,
    )
    typer.echo(
        json.dumps(
            {"query": query, "items": [asdict(hit) for hit in hits]},
            indent=2,
        )
    )


@media_app.command("import-path")
def media_import_path(
    project_id: str,
    source: Path,
    recursive: bool = typer.Option(True, "--recursive/--no-recursive"),
) -> None:
    """Import video/audio immutably and queue FFmpeg metadata plus previews."""
    catalog = Catalog(workspace_path())
    store = ContentAddressedStore(workspace_path())
    source_path = source.expanduser().resolve(strict=True)
    candidates = (
        [source_path]
        if source_path.is_file()
        else list(source_path.rglob("*") if recursive else source_path.glob("*"))
    )
    video_extensions = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
    audio_extensions = {".wav", ".mp3", ".flac", ".m4a", ".ogg", ".aac"}
    assets: list[dict[str, object]] = []
    for candidate in sorted(path for path in candidates if path.is_file()):
        extension = candidate.suffix.lower()
        if extension not in video_extensions | audio_extensions:
            continue
        media_kind = MediaKind.VIDEO if extension in video_extensions else MediaKind.AUDIO
        stored = store.import_file(candidate)
        asset_id = catalog.record_asset(
            project_id=project_id,
            sha256=stored.sha256,
            original_filename=candidate.name,
            media_type=media_kind.value,
            object_key=stored.object_key,
            byte_size=stored.byte_size,
            metadata={"source_path": str(candidate)},
        )
        assets.append(catalog.get_asset(asset_id))
    if not assets:
        raise typer.BadParameter("No supported video or audio files were found")
    job = _enqueue_media_job(
        JobQueue(catalog),
        project_id,
        assets,
        "media.inspect",
        "media-inspection",
        {"preview": True},
    )
    typer.echo(f"Imported {len(assets)} media assets and queued {job.id}")


@media_app.command("list")
def media_list(project_id: str) -> None:
    catalog = Catalog(workspace_path())
    items: list[dict[str, object]] = []
    for asset in _project_media_assets(catalog, project_id, state=None):
        sha256 = str(asset["sha256"])
        items.append(
            {
                **asset,
                "analysis": catalog.media_analysis(sha256),
                "derivatives": catalog.derived_media(sha256),
            }
        )
    typer.echo(json.dumps(items, indent=2))


@media_app.command("analyze")
def media_analyze(
    project_id: str,
    validate_decode: bool = typer.Option(False, "--validate-decode/--probe-only"),
    preview: bool = typer.Option(True, "--preview/--no-preview"),
) -> None:
    catalog = Catalog(workspace_path())
    assets = _project_media_assets(catalog, project_id)
    job = _enqueue_media_job(
        JobQueue(catalog),
        project_id,
        assets,
        "media.inspect",
        "media-inspection",
        {"validate_decode": validate_decode, "preview": preview},
    )
    typer.echo(f"Queued {job.id} for {job.total_items} media assets")


@media_app.command("derive")
def media_derive(
    project_id: str,
    media_kind: MediaKind = MediaKind.VIDEO,
    kind: MediaDerivativeKind = MediaDerivativeKind.TRANSCODE,
    format: str = typer.Option("mp4", "--format"),
    start_seconds: float | None = typer.Option(None, min=0, max=86400),
    duration_seconds: float | None = typer.Option(None, min=0.001, max=86400),
    width: int | None = typer.Option(None, min=64, max=7680),
    height: int | None = typer.Option(None, min=64, max=4320),
) -> None:
    catalog = Catalog(workspace_path())
    assets = catalog.list_assets(project_id, media_type=media_kind.value, state="active")
    parameters: dict[str, object] = {
        "kind": kind.value,
        "media_kind": media_kind.value,
        "format": format.lower(),
        "start_seconds": start_seconds,
        "duration_seconds": duration_seconds,
        "width": width,
        "height": height,
    }
    job = _enqueue_media_job(
        JobQueue(catalog),
        project_id,
        assets,
        "media.derive",
        "media-derivative",
        parameters,
    )
    typer.echo(f"Queued {kind.value} job {job.id} for {job.total_items} {media_kind.value} assets")


@tabular_app.command("import-path")
def tabular_import_path(
    project_id: str,
    source: Path,
    source_format: Annotated[TabularFormat | None, typer.Option("--format")] = None,
    sheet: str | None = None,
    table: str | None = None,
) -> None:
    """Import a structured file immutably and queue normalization/profiling."""
    source_path = source.expanduser().resolve(strict=True)
    if not source_path.is_file():
        raise typer.BadParameter("Tabular imports must be regular files")
    catalog = Catalog(workspace_path())
    store = ContentAddressedStore(workspace_path())
    selected_format = source_format or TabularFormat.from_filename(source_path.name)
    stored = store.import_file(source_path)
    asset_id = catalog.record_asset(
        project_id=project_id,
        sha256=stored.sha256,
        original_filename=source_path.name,
        media_type="tabular",
        object_key=stored.object_key,
        byte_size=stored.byte_size,
        metadata={"source_path": str(source_path), "format": selected_format.value},
    )
    options = {key: value for key, value in {"sheet": sheet, "table": table}.items() if value}
    analysis_key = TabularEngine.analysis_key(stored.sha256, selected_format, options)
    dataset_id = catalog.record_tabular_dataset(
        project_id=project_id,
        asset_id=asset_id,
        analysis_key=analysis_key,
        name=source_path.stem,
    )
    job = JobQueue(catalog).enqueue(
        project_id=project_id,
        kind="tabular-inspection",
        processor=tabular_processor_spec(),
        items=[WorkItem(stored.sha256, stored.object_key, 0)],
        parameters={"source_format": selected_format.value, **options},
    )
    typer.echo(
        json.dumps({"dataset_id": dataset_id, "asset_id": asset_id, "job_id": job.id}, indent=2)
    )


@tabular_app.command("list")
def tabular_list(project_id: str) -> None:
    typer.echo(json.dumps(Catalog(workspace_path()).list_tabular_datasets(project_id), indent=2))


@tabular_app.command("show")
def tabular_show(dataset_id: str) -> None:
    typer.echo(json.dumps(Catalog(workspace_path()).get_tabular_dataset(dataset_id), indent=2))


@tabular_app.command("query")
def tabular_query(
    dataset_id: str,
    filter: Annotated[
        list[str] | None, typer.Option("--filter", help="column:operator:JSON-value")
    ] = None,
    search: str | None = None,
    sort_by: str | None = None,
    descending: bool = False,
    limit: int = typer.Option(100, min=1, max=1000),
    offset: int = typer.Option(0, min=0),
) -> None:
    catalog = Catalog(workspace_path())
    dataset = catalog.get_tabular_dataset(dataset_id)
    request = TabularQuery(
        filters=tuple(_parse_filter(value) for value in (filter or [])),
        search=search,
        sort_by=sort_by,
        descending=descending,
        limit=limit,
        offset=offset,
    )
    started = time.perf_counter()
    result = TabularEngine(ContentAddressedStore(workspace_path())).query(
        str(dataset["normalized_object_key"]), request
    )
    duration_ms = (time.perf_counter() - started) * 1000
    catalog.record_tabular_query(dataset_id, asdict(request), int(result["total"]), duration_ms)
    typer.echo(json.dumps({**result, "duration_ms": round(duration_ms, 3)}, indent=2))


@tabular_app.command("frequency")
def tabular_frequency(
    dataset_id: str, column: str, limit: int = typer.Option(20, min=1, max=100)
) -> None:
    dataset = Catalog(workspace_path()).get_tabular_dataset(dataset_id)
    result = TabularEngine(ContentAddressedStore(workspace_path())).frequency(
        str(dataset["normalized_object_key"]), column, limit=limit
    )
    typer.echo(json.dumps({"column": column, "items": result}, indent=2))


@tabular_app.command("map")
def tabular_map(dataset_id: str, mapping_json: str, metadata_json: str = "{}") -> None:
    try:
        mapping = json.loads(mapping_json)
        metadata = json.loads(metadata_json)
    except json.JSONDecodeError as error:
        raise typer.BadParameter(f"Mapping and metadata must be JSON objects: {error}") from error
    if not isinstance(mapping, dict) or not isinstance(metadata, dict):
        raise typer.BadParameter("Mapping and metadata must be JSON objects")
    result = Catalog(workspace_path()).update_tabular_mapping(
        dataset_id, schema_mapping=mapping, custom_metadata=metadata
    )
    typer.echo(json.dumps(result, indent=2))


@tabular_app.command("export")
def tabular_export(
    dataset_id: str,
    destination: Path,
    format: Annotated[TabularFormat, typer.Option("--format")],
) -> None:
    catalog = Catalog(workspace_path())
    dataset = catalog.get_tabular_dataset(dataset_id)
    result = TabularEngine(ContentAddressedStore(workspace_path())).export(
        str(dataset["normalized_object_key"]), destination, format
    )
    export_id = catalog.record_tabular_export(dataset_id, result)
    typer.echo(json.dumps({"id": export_id, **asdict(result)}, indent=2, default=str))


def _enqueue_document_job(
    queue: JobQueue,
    project_id: str,
    assets: list[dict[str, object]],
    *,
    max_words: int,
    overlap_words: int,
):
    if not assets:
        raise typer.BadParameter("The project has no active documents")
    asset_ids: dict[str, str] = {}
    formats: dict[str, str] = {}
    titles: dict[str, str] = {}
    items: list[WorkItem] = []
    for position, asset in enumerate(assets):
        metadata_value = asset.get("metadata")
        metadata = (
            cast(dict[str, object], metadata_value) if isinstance(metadata_value, dict) else {}
        )
        format_value = str(metadata.get("format", ""))
        if not format_value:
            format_value = DocumentFormat.from_filename(str(asset["original_filename"])).value
        key = str(position)
        asset_ids[key] = str(asset["id"])
        formats[key] = format_value
        titles[key] = Path(str(asset["original_filename"])).stem
        items.append(
            WorkItem(
                input_hash=str(asset["sha256"]),
                input_ref=str(asset["object_key"]),
                position=position,
            )
        )
    return queue.enqueue(
        project_id=project_id,
        kind="document-index",
        processor=document_processor_spec(),
        items=items,
        parameters={
            "asset_ids_by_position": asset_ids,
            "formats_by_position": formats,
            "titles_by_position": titles,
            "max_words": max_words,
            "overlap_words": overlap_words,
        },
        profile=RuntimeProfile.BALANCED,
    )


def _project_media_assets(
    catalog: Catalog, project_id: str, *, state: str | None = "active"
) -> list[dict[str, object]]:
    return [
        *catalog.list_assets(project_id, media_type=MediaKind.VIDEO.value, state=state),
        *catalog.list_assets(project_id, media_type=MediaKind.AUDIO.value, state=state),
    ]


def _enqueue_media_job(
    queue: JobQueue,
    project_id: str,
    assets: list[dict[str, object]],
    processor_id: str,
    kind: str,
    parameters: dict[str, object],
):
    if not assets:
        raise typer.BadParameter("The project has no matching video or audio assets")
    return queue.enqueue(
        project_id=project_id,
        kind=kind,
        processor=media_processor_spec(processor_id, toolchain=FFmpegToolchain()),
        items=[
            WorkItem(
                input_hash=str(asset["sha256"]),
                input_ref=str(asset["object_key"]),
                position=position,
            )
            for position, asset in enumerate(assets)
        ],
        parameters=parameters,
        profile=RuntimeProfile.BALANCED,
    )


def _parse_filter(value: str) -> TabularFilter:
    parts = value.split(":", 2)
    if len(parts) != 3:
        raise typer.BadParameter("Filters use column:operator:JSON-value")
    column, operator, raw = parts
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = raw
    try:
        return TabularFilter(column, FilterOperator(operator), parsed)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error


def _enqueue_image_job(
    queue: JobQueue,
    project_id: str,
    assets: list[dict[str, object]],
    processor_id: str,
    kind: str,
    *,
    parameters: dict[str, object] | None = None,
    deterministic: bool = True,
):
    if not assets:
        raise typer.BadParameter("The project has no matching images")
    processor = ProcessorSpec(
        id=processor_id,
        version="1.0.0",
        deterministic=deterministic,
        cacheable=deterministic,
        resource_hints=ResourceHints(cpu=ResourceLevel.MEDIUM, memory=ResourceLevel.MEDIUM),
    )
    return queue.enqueue(
        project_id=project_id,
        kind=kind,
        processor=processor,
        items=[
            WorkItem(
                input_hash=str(asset["sha256"]),
                input_ref=str(asset["object_key"]),
                position=position,
            )
            for position, asset in enumerate(assets)
        ],
        parameters=parameters or {},
        profile=RuntimeProfile.BALANCED,
    )


def _project_image_samples(catalog: Catalog, project_id: str) -> list[DatasetSample]:
    samples: list[DatasetSample] = []
    for asset in catalog.list_assets(project_id, media_type="image", state="active"):
        analysis = catalog.image_analysis(str(asset["sha256"])) or {}
        metadata = (
            cast(dict[str, object], asset["metadata"])
            if isinstance(asset.get("metadata"), dict)
            else {}
        )
        samples.append(
            DatasetSample(
                asset_id=str(asset["id"]),
                sha256=str(asset["sha256"]),
                object_key=str(asset["object_key"]),
                filename=str(asset["original_filename"]),
                label=str(metadata.get("label", "unlabeled")),
                source_key=str(asset.get("source_id")) if asset.get("source_id") else None,
                group_key=str(asset["sha256"]),
                perceptual_hash=(
                    str(analysis["perceptual_hash"]) if analysis.get("perceptual_hash") else None
                ),
            )
        )
    return samples


@plugin_app.command("list")
def plugin_list() -> None:
    """List compatible plugins and isolated discovery diagnostics."""
    typer.echo(json.dumps(PluginRuntime.discover().inventory(), indent=2))


@plugin_app.command("contracts")
def plugin_contracts() -> None:
    """Show the finalized Plugin API version and capability identifiers."""
    from mediasensei_plugin_sdk import CAPABILITIES, PLUGIN_API_VERSION

    typer.echo(
        json.dumps(
            {"api_version": PLUGIN_API_VERSION, "capabilities": sorted(CAPABILITIES)},
            indent=2,
        )
    )


@plugin_app.command("validate")
def plugin_validate(path: Path) -> None:
    """Load and validate a local plugin entry-point file with safe errors."""
    try:
        typer.echo(json.dumps(validate_plugin_file(path), indent=2))
    except ValueError as error:
        raise typer.BadParameter(str(error), param_hint="path") from error


@plugin_app.command("trust")
def plugin_trust(path: Path) -> None:
    """Approve the exact SHA-256 fingerprint of a local plugin file."""
    try:
        typer.echo(json.dumps(PluginTrustStore.default(workspace_path()).approve(path), indent=2))
    except ValueError as error:
        raise typer.BadParameter(str(error), param_hint="path") from error


@plugin_app.command("trusted")
def plugin_trusted() -> None:
    """List locally approved plugin fingerprints."""
    typer.echo(
        json.dumps({"items": PluginTrustStore.default(workspace_path()).entries()}, indent=2)
    )


@plugin_app.command("revoke")
def plugin_revoke(name: str) -> None:
    """Remove a plugin fingerprint from the local trust policy."""
    removed = PluginTrustStore.default(workspace_path()).revoke(name)
    typer.echo(json.dumps({"name": name.strip().lower(), "revoked": removed}, indent=2))


@plugin_app.command("analyze")
def plugin_analyze(
    path: Path,
    object_key: str,
    parameters: str = typer.Option("{}", "--parameters"),
    timeout: float = typer.Option(15.0, "--timeout", min=0.1, max=300.0),
) -> None:
    """Run a trusted local analyzer in an isolated, timeout-bound subprocess."""
    try:
        values = json.loads(parameters)
        if not isinstance(values, dict):
            raise TypeError("parameters must be a JSON object")
        result = PluginSubprocessExecutor(
            PluginTrustStore.default(workspace_path()), timeout_seconds=timeout
        ).analyze(path, object_key, values)
        typer.echo(json.dumps(result, indent=2))
    except (TypeError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        raise typer.BadParameter(str(error)) from error


@plugin_app.command("create")
def plugin_create(
    name: str,
    destination: Path = Path("."),
    capability: str = typer.Option("analyzer", "--capability"),
) -> None:
    """Create an installable analyzer or discovery-provider Plugin API 1.5 template."""
    slug = name.strip().lower().replace("-", "_").replace(" ", "_")
    distribution = slug.replace("_", "-")
    if not slug or not all(character.isalnum() or character == "_" for character in slug):
        raise typer.BadParameter("Plugin names may contain letters, numbers, spaces, or hyphens")
    if capability not in {"analyzer", "discovery-provider"}:
        raise typer.BadParameter("capability must be analyzer or discovery-provider")
    target = (destination / slug).resolve()
    if target.exists():
        raise typer.BadParameter(f"Destination already exists: {target}")
    package = target / "src" / slug
    tests = target / "tests"
    package.mkdir(parents=True)
    tests.mkdir()
    (target / "pyproject.toml").write_text(
        "[build-system]\nrequires = ['hatchling>=1.27']\nbuild-backend = 'hatchling.build'\n\n"
        "[project]\n"
        f"name = '{distribution}'\nversion = '0.1.0'\nrequires-python = '>=3.12'\n"
        "dependencies = ['mediasensei>=0.10,<1']\n\n"
        f"[project.entry-points.\"mediasensei.plugins\"]\n{distribution} = '{slug}.plugin:PLUGIN'\n\n"
        "[tool.hatch.build.targets.wheel]\n"
        f"packages = ['src/{slug}']\n\n[tool.pytest.ini_options]\npythonpath = ['src']\n",
        encoding="utf-8",
    )
    (package / "__init__.py").write_text(
        "from .plugin import PLUGIN\n\n__all__ = ['PLUGIN']\n", encoding="utf-8"
    )
    if capability == "analyzer":
        source = (
            "from mediasensei_plugin_sdk import PluginManifest, PluginRegistration\n\n"
            f"MANIFEST = PluginManifest(name='{distribution}', version='0.1.0', "
            "api='>=1.5,<2', capabilities=('analyzer',), permissions=('read_asset_metadata',))\n\n"
            "class MetadataAnalyzer:\n    manifest = MANIFEST\n\n"
            "    def analyze(self, object_key: str, parameters: dict[str, object]) -> dict[str, object]:\n"
            "        return {'object_key': object_key, 'parameters': parameters}\n\n"
            "PLUGIN = PluginRegistration(manifest=MANIFEST, analyzers=(MetadataAnalyzer(),))\n"
        )
    else:
        source = (
            "from mediasensei_plugin_sdk import (DiscoveryCandidate, DiscoveryPage, DiscoveryRequest, PluginManifest, PluginRegistration)\n\n"
            f"MANIFEST = PluginManifest(name='{distribution}', version='0.1.0', "
            "api='>=1.5,<2', capabilities=('discovery_provider',), permissions=('network.discovery',))\n\n"
            "class DiscoveryProvider:\n"
            f"    provider_id = '{distribution}-search'\n    version = '0.1.0'\n\n"
            "    def available(self) -> bool:\n        return True\n\n"
            "    def capabilities(self) -> dict[str, object]:\n        return {'modalities': ['image'], 'supports_pagination': False}\n\n"
            "    def search(self, request: DiscoveryRequest) -> DiscoveryPage:\n"
            "        candidate = DiscoveryCandidate(self.provider_id, 'example', 'https://example.com/image.jpg', title=request.query)\n"
            "        return DiscoveryPage((candidate,))\n\n"
            "PLUGIN = PluginRegistration(manifest=MANIFEST, discovery_providers=(DiscoveryProvider(),))\n"
        )
    (package / "plugin.py").write_text(source, encoding="utf-8")
    (tests / "test_plugin.py").write_text(
        f"from {slug}.plugin import PLUGIN\nfrom mediasensei_plugin_sdk import validate_registration\n\n"
        "def test_registration_is_compatible() -> None:\n    assert validate_registration(PLUGIN) is PLUGIN\n",
        encoding="utf-8",
    )
    (target / "README.md").write_text(
        f"# {distribution}\n\nMediaSensei Plugin API 1.5 {capability} template.\n\n"
        "Install in editable mode, inspect with `mediasensei plugin list`, and explicitly trust local analyzer files before execution.\n",
        encoding="utf-8",
    )
    typer.echo(f"Created installable {capability} plugin template at {target}")


def _job_dict(job) -> dict[str, object]:
    return {
        "id": job.id,
        "state": job.state.value,
        "kind": job.kind,
        "profile": job.profile.value,
        "progress": job.progress,
        "processed": job.processed_count,
        "cached": job.cached_count,
        "failed": job.failed_count,
        "skipped": job.skipped_count,
        "checkpoint": job.checkpoint,
    }


operation_app = typer.Typer(help="Discover and run reproducible dataset operations.")
app.add_typer(operation_app, name="operation")


@operation_app.command("search")
def operation_search(query: Annotated[str, typer.Argument()] = "") -> None:
    from mediasensei.domain.operations import REGISTRY

    for operation in REGISTRY.search(query):
        typer.echo(f"{operation.id}: {operation.name} — {operation.description}")


@operation_app.command("run")
def operation_run(
    dataset_id: str,
    operation_id: str,
    parameters: str = "{}",
    workspace: Path = Path(".mediasensei-workspace"),
) -> None:
    from mediasensei.operations import Workbench

    service = Workbench(workspace)
    try:
        params = json.loads(parameters)
        if not isinstance(params, dict):
            raise TypeError("Parameters must be a JSON object.")
        dataset = service.dataset(dataset_id)
        result = service.enqueue(
            dataset_id, [{"operation": operation_id, "parameters": params}], dataset["revision"]
        )
        typer.echo(json.dumps(result))
        typer.echo("Queued. Start the worker to execute this operation.")
    except (KeyError, ValueError, TypeError) as error:
        raise typer.BadParameter(str(error)) from error


recipe_app = typer.Typer(help="List and execute parameterized recipes through the shared core.")
app.add_typer(recipe_app, name="recipe")


@recipe_app.command("list")
def recipe_list(workspace: Path = Path(".mediasensei-workspace")):
    from mediasensei.operations import Workbench

    typer.echo(json.dumps(Workbench(workspace).recipes(), indent=2))


@recipe_app.command("run")
def recipe_run(
    recipe_id: str,
    dataset_id: str,
    bindings: str = "{}",
    workspace: Path = Path(".mediasensei-workspace"),
):
    from mediasensei.operations import Workbench
    from mediasensei.workflows import resolve_parameters

    service = Workbench(workspace)
    recipe = next((r for r in service.recipes() if r["id"] == recipe_id), None)
    if recipe is None:
        raise typer.BadParameter("Recipe not found.")
    try:
        steps = resolve_parameters(recipe["steps"], json.loads(bindings))
        typer.echo(
            json.dumps(service.enqueue(dataset_id, steps, service.dataset(dataset_id)["revision"]))
        )
    except (ValueError, KeyError, TypeError) as error:
        raise typer.BadParameter(str(error)) from error


if __name__ == "__main__":
    app()
