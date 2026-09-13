"""Typed Batch 3 operation definitions."""

from mediasensei.domain.operations import REGISTRY, OperationDefinition, param


def register():
    document_schema = dict(REGISTRY.get("document.prepare").parameter_schema)
    document_schema["model_revision"] = param("Exact learned model revision", "string", default="")
    specs = [
        (
            "document.embed",
            "Index with a fitted model",
            "document",
            document_schema,
            ("AssetSelection",),
        ),
        (
            "document.speak",
            "Generate local speech",
            "document",
            {"personality": param("Saved voice personality", "string", default="")},
            ("AssetSelection",),
        ),
        (
            "audio.transcribe",
            "Transcribe with local whisper.cpp",
            "audio",
            {
                "language": param(
                    "Language",
                    "enum",
                    choices=["auto", "en", "ur", "de", "fr", "es", "ar", "ja", "zh"],
                    default="auto",
                ),
                "duration": param("Maximum seconds", "number", default=60, minimum=1, maximum=600),
                "model_revision": param("Pinned local model SHA-256", "string", default=""),
                "tool_revision": param("Pinned local executable SHA-256", "string", default=""),
            },
            ("AssetSelection",),
        ),
        ("model.train", "Train a fitted local model", "document", {}, ("TrainingSnapshot",)),
        (
            "connection.import",
            "Import using a saved connection",
            "document",
            {},
            ("ProviderRequest",),
        ),
    ]
    for identifier, name, modality, schema, inputs in specs:
        REGISTRY.register(
            OperationDefinition(
                id=identifier,
                name=name,
                modality=modality,
                category="Integrations",
                description=name + "; explicit execution with pinned provenance and durable jobs.",
                parameter_schema=schema,
                version="1.0.0",
                cacheable=False,
                input_types=inputs,
                output_types=("DerivedAssets", "Report"),
                preview_supported=False,
                implementation_reference="mediasensei.integrations.IntegrationService",
            )
        )
