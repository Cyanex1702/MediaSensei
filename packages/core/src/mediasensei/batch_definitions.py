"""Batch 2 asset contracts. Every action runs through the durable worker."""

from mediasensei.domain.operations import REGISTRY, OperationDefinition, param


def definitions():
    number = lambda title, default, low, high: param(
        title, "number", default=default, minimum=low, maximum=high
    )
    choice = lambda title, values, default: param(
        title, "enum", choices=values.split(), default=default
    )
    text = lambda title, default="": param(title, "string", default=default)
    return [
        (
            "image.edit",
            "Image transforms and normalization",
            "image",
            "Pillow",
            {
                "width": number("Width (0 keeps original)", 1024, 0, 16384),
                "height": number("Height (0 keeps original)", 1024, 0, 16384),
                "fit": choice("Fit", "contain cover pad stretch", "contain"),
                "crop": text("Crop left,top,right,bottom (optional)"),
                "rotate": number("Rotate degrees", 0, -360, 360),
                "flip": choice("Flip", "none horizontal vertical both", "none"),
                "mode": choice("Color mode", "RGB grayscale RGBA", "RGB"),
                "format": choice("Format", "JPEG PNG WEBP TIFF BMP", "JPEG"),
                "quality": number("Output quality", 90, 1, 100),
                "background": text("Padding color", "#000000"),
                "brightness": number("Brightness factor", 1, 0, 5),
                "contrast": number("Contrast factor", 1, 0, 5),
                "sharpness": number("Sharpness factor", 1, 0, 5),
                "blur": number("Gaussian blur radius", 0, 0, 50),
                "normalize": param("Normalize contrast", "boolean", default=False),
                "strip_metadata": param("Strip EXIF and GPS", "boolean", default=True),
            },
        ),
        (
            "video.process",
            "Video processing and frame sampling",
            "video",
            "FFmpeg",
            {
                "action": choice(
                    "Action",
                    "inspect thumbnail trim transcode frames contact_sheet scenes extract_audio",
                    "frames",
                ),
                "start": number("Start seconds", 0, 0, 86400),
                "duration": number("Duration seconds (0 to end)", 0, 0, 86400),
                "sampling": choice("Sampling", "count seconds frames scene", "count"),
                "count": number("Frame count / maximum scene frames", 12, 1, 500),
                "interval": number("Every N seconds or frames", 1, 0.01, 100000),
                "scene_threshold": number("Scene change threshold", 0.3, 0.01, 1),
                "width": number("Output width", 960, 64, 4096),
                "height": number("Output height", 540, 64, 4096),
                "fps": number("Output FPS (0 keeps source)", 0, 0, 120),
                "format": choice("Video format", "mp4 webm", "mp4"),
                "audio_format": choice("Extracted audio format", "wav mp3 flac ogg", "wav"),
            },
        ),
        (
            "audio.process",
            "Audio processing and analysis",
            "audio",
            "FFmpeg",
            {
                "action": choice(
                    "Action",
                    "inspect trim convert resample channels normalize silence remove_silence segment waveform spectrogram features",
                    "waveform",
                ),
                "start": number("Start seconds", 0, 0, 86400),
                "duration": number("Duration seconds (0 to end)", 0, 0, 86400),
                "format": choice("Audio format", "wav mp3 flac ogg", "wav"),
                "sample_rate": number("Sample rate", 44100, 8000, 192000),
                "channels": choice("Channels", "1 2", "1"),
                "loudness": number("Target loudness LUFS", -16, -36, -5),
                "silence_db": number("Silence threshold dB", -40, -90, -5),
                "silence_seconds": number("Minimum silence seconds", 0.5, 0.05, 30),
                "segment_seconds": number("Segment length seconds", 30, 0.1, 3600),
            },
        ),
        (
            "document.prepare",
            "Clean, chunk and index documents",
            "document",
            "Local document pipeline",
            {
                "strategy": choice(
                    "Chunk strategy", "token paragraph heading recursive", "heading"
                ),
                "chunk_size": number("Maximum Unicode tokens", 420, 32, 4096),
                "overlap": number("Overlap tokens", 64, 0, 2048),
                "unicode": choice("Unicode normalization", "NFC NFKC NFD NFKD none", "NFKC"),
                "whitespace": param("Clean whitespace", "boolean", default=True),
                "find": text("Find text / regex"),
                "replace": text("Replacement"),
                "regex": param("Use bounded RE2 regex", "boolean", default=False),
            },
        ),
    ]


def register():
    for identifier, name, modality, backend, schema in definitions():
        REGISTRY.register(
            OperationDefinition(
                id=identifier,
                name=name,
                modality=modality,
                backend=backend,
                category="Prepare",
                description=f"{name}; preview first, then save immutable outputs with provenance.",
                parameter_schema=schema,
                version="2.0.0",
                cacheable=False,
                input_types=("AssetSelection",),
                output_types=("DerivedAssets", "Report"),
                implementation_reference="mediasensei.multimodal.BatchService",
            )
        )
