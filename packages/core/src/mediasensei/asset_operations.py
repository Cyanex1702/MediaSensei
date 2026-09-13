from mediasensei.domain.operations import REGISTRY, OperationDefinition, param


def register_asset_operations():
    specs = [
        (
            "image.inspect",
            "Inspect images",
            "image",
            "Pillow",
            {
                "thumbnail": param("Create thumbnail", "boolean", default=True),
                "thumbnail_size": param(
                    "Thumbnail size", "number", default=512, minimum=32, maximum=4096
                ),
            },
        ),
        (
            "image.transform",
            "Resize and convert images",
            "image",
            "Pillow",
            {
                "width": param("Width", "number", default=1024, minimum=1, maximum=20000),
                "height": param("Height", "number", default=1024, minimum=1, maximum=20000),
                "fit": param(
                    "Fit", "enum", choices=["contain", "cover", "pad", "stretch"], default="contain"
                ),
                "format": param("Format", "enum", choices=["JPEG", "PNG", "WEBP"], default="JPEG"),
                "quality": param("Quality", "number", default=90, minimum=1, maximum=100),
                "background": param("Background", "string", default="#ffffff"),
            },
        ),
        (
            "image.ocr",
            "Detect and extract image text",
            "image",
            "Tesseract",
            {
                "action": param(
                    "Action",
                    "enum",
                    choices=["detect_only", "filter", "quarantine", "store_text"],
                    default="detect_only",
                ),
                "language": param("Language", "string", default="eng"),
            },
        ),
        (
            "media.inspect",
            "Inspect video or audio",
            "media",
            "FFmpeg",
            {"preview": param("Create preview", "boolean", default=True)},
        ),
        (
            "media.derive",
            "Transcode video or audio",
            "media",
            "FFmpeg",
            {
                "kind": param(
                    "Derivative",
                    "enum",
                    choices=["transcode", "thumbnail", "waveform"],
                    default="transcode",
                ),
                "media_kind": param(
                    "Media kind", "enum", choices=["video", "audio"], default="video"
                ),
                "format": param(
                    "Format", "enum", choices=["mp4", "webm", "wav", "mp3", "flac"], default="mp4"
                ),
                "width": param("Width", "number", default=960, minimum=16, maximum=7680),
                "height": param("Height", "number", default=540, minimum=16, maximum=4320),
            },
        ),
        (
            "document.index",
            "Index documents for retrieval",
            "document",
            "Local document pipeline",
            {
                "max_words": param("Chunk words", "number", default=420, minimum=50, maximum=10000),
                "overlap_words": param(
                    "Overlap words", "number", default=64, minimum=0, maximum=1000
                ),
            },
        ),
        ("tabular.inspect", "Inspect an imported table", "table", "DuckDB + PyArrow", {}),
    ]
    for identifier, name, modality, backend, schema in specs:
        REGISTRY.register(
            OperationDefinition(
                id=identifier,
                name=name,
                category="Inspect" if identifier.endswith(("inspect", "index")) else "Transform",
                description=f"{name} using the existing local worker. Select compatible assets in Library.",
                parameter_schema=schema,
                version="1.0.0",
                modality=modality,
                backend=backend,
                preview_supported=False,
                deterministic=identifier != "image.ocr",
                cacheable=identifier != "image.ocr",
                input_types=("AssetSelection",),
                output_types=("DerivedAssets", "Report"),
                implementation_reference=identifier,
            )
        )


def enqueue_assets(service, project_id, operation, asset_ids, supplied):
    from mediasensei.domain.jobs import ProcessorSpec, WorkItem
    from mediasensei.infrastructure.jobs import JobQueue
    from mediasensei.operations import parameters

    definition = REGISTRY.get(operation)
    if definition.input_types != ("AssetSelection",):
        raise ValueError("Use the dataset operation endpoint for table transforms.")
    if not isinstance(asset_ids, list) or not asset_ids:
        raise ValueError("Select at least one asset.")
    assets = {a["id"]: a for a in service.catalog.list_assets(project_id)}
    selected = []
    for identifier in asset_ids:
        if identifier not in assets:
            raise ValueError("An asset is outside the selected project.")
        asset = assets[identifier]
        allowed = ["video", "audio"] if definition.modality == "media" else ["tabular" if definition.modality == "table" else definition.modality]
        if asset["media_type"] not in allowed:
            raise ValueError(f"{definition.name} requires {definition.modality} assets.")
        selected.append(asset)
    p = parameters(operation, supplied, [])
    if operation == "audio.transcribe":
        from mediasensei.native_adapters import asr_revisions
        p.update(asr_revisions())
    if operation == "media.derive" and any(a["media_type"] != p["media_kind"] for a in selected):
        raise ValueError("Media kind must match every selected asset.")
    if operation == "document.embed":
        from mediasensei.integrations import IntegrationService
        IntegrationService(service.catalog).embedding(p["model_revision"], require_active=True)
    if operation in ("image.edit", "video.process", "audio.process", "document.prepare", "document.embed", "document.speak", "audio.transcribe"):
        p.update(_asset_ids={str(i): a["id"] for i, a in enumerate(selected)},
                 _project_id=project_id, _operation=operation)
    if operation == "document.index":
        from pathlib import Path

        if p["overlap_words"] >= p["max_words"]:
            raise ValueError("Overlap must be smaller than chunk size.")
        p["asset_ids_by_position"] = {str(i): a["id"] for i, a in enumerate(selected)}
        p["formats_by_position"] = {
            str(i): {"markdown": "md", "htm": "html"}.get(
                Path(a["original_filename"]).suffix[1:].lower(),
                Path(a["original_filename"]).suffix[1:].lower(),
            )
            for i, a in enumerate(selected)
        }
        p["titles_by_position"] = {str(i): a["original_filename"] for i, a in enumerate(selected)}
    if operation == "tabular.inspect":
        from pathlib import Path

        if len(selected) != 1:
            raise ValueError("Inspect one table per operation run.")
        asset = selected[0]
        p.update(
            project_id=project_id,
            asset_id=asset["id"],
            name=Path(asset["original_filename"]).stem,
            source_format=Path(asset["original_filename"]).suffix[1:].lower(),
        )
    if operation.startswith("media."):
        from mediasensei.infrastructure.media import media_processor_spec

        processor = media_processor_spec(operation)
    else:
        processor = ProcessorSpec(
            id=operation,
            version=definition.version,
            deterministic=definition.deterministic,
            cacheable=definition.cacheable,
            model_revision=p.get("model_revision"),
        )
    job = JobQueue(service.catalog).enqueue(
        project_id=project_id,
        kind=operation,
        processor=processor,
        items=[WorkItem(a["sha256"], a["object_key"], i) for i, a in enumerate(selected)],
        parameters=p,
    )
    return {
        "job_id": job.id,
        "operation": operation,
        "inputs": [a["sha256"] for a in selected],
        "parameters": p,
    }
