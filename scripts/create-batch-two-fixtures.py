"""Create synthetic local browser fixtures without contacting discovery providers."""

import json
import os
import subprocess
from pathlib import Path

from mediasensei.domain.acquisition import (
    AcquisitionDecision,
    AcquisitionDecisionKind,
    AcquisitionModality,
    AcquisitionReason,
    AcquisitionSpec,
    DiscoveryCandidate,
    DiscoveryPage,
    TargetSpec,
)
from mediasensei.infrastructure.acquisition import AcquisitionService
from mediasensei.infrastructure.catalog import Catalog
from mediasensei.infrastructure.storage import ContentAddressedStore
from PIL import Image, ImageDraw, ImageFont

root = Path(".audit/batch2-fixtures")
root.mkdir(parents=True, exist_ok=True)
im = Image.new("RGB", (800, 180), "white")
d = ImageDraw.Draw(im)
d.text(
    (30, 45),
    "MediaSensei OCR test 123",
    font=(
        ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 48)
        if os.name == "nt"
        else ImageFont.load_default(size=48)
    ),
    fill="black",
)
im.save(root / "sample.png")
(root / "notes.md").write_text(
    "# Field notes\n\nThe red fox lives in snowy forests. It hunts mice and rests in sheltered dens.\n\n## Habitat\n\n"
    + ("Forests provide shelter, food, and safe habitat for foxes. " * 50),
    encoding="utf-8",
)
from mediasensei.infrastructure.media import FFmpegToolchain

ffmpeg = FFmpegToolchain().ffmpeg
if not ffmpeg:
    raise RuntimeError("Configure FFmpeg before creating browser fixtures")
for name, args in [
    ("sample.wav", ["-f", "lavfi", "-i", "sine=frequency=440:duration=3", "-c:a", "pcm_s16le"]),
    (
        "sample.mp4",
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=160x120:rate=12:duration=3",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=3",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
        ],
    ),
]:
    subprocess.run(
        [ffmpeg, "-nostdin", "-v", "error", *args, "-threads", "1", "-y", str(root / name)],
        check=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
catalog = Catalog(os.environ.get("MEDIASENSEI_WORKSPACE", ".audit/batch2-workspace"))
store = ContentAddressedStore(catalog.workspace)
project = str(
    catalog.create_project("Batch 2 browser acceptance", data_policy="approved_external").id
)
stored = store.import_file(root / "sample.png")
asset = catalog.record_asset(
    project_id=project,
    sha256=stored.sha256,
    object_key=stored.object_key,
    byte_size=stored.byte_size,
    media_type="image",
    original_filename="review-fixture.png",
)
service = AcquisitionService(catalog)
_, plan = service.create_plan(
    project,
    AcquisitionSpec(AcquisitionModality.IMAGE, "Synthetic QA candidate", TargetSpec(count=2)),
)
run = service.repository.create_run(plan)
q = service.repository.runnable_queries(run)[0]
service.repository.record_discovery(
    q["id"],
    DiscoveryPage(
        (
            DiscoveryCandidate(
                "wikimedia-commons",
                "synthetic-1",
                "https://example.org/fixture.png",
                title="Synthetic review fixture",
                width=800,
                height=180,
                license="CC0",
            ),
        )
    ),
)
candidate = service.repository.list_candidates(run)[0]
service.repository.record_candidate_decision(
    candidate["id"],
    AcquisitionDecision(
        AcquisitionDecisionKind.REVIEW,
        AcquisitionReason.NEEDS_REVIEW,
        "local-qa",
        "1",
        {"quality_score": 85, "relevance_score": 0.8},
    ),
    asset_id=asset,
    sha256=stored.sha256,
)
(root / "context.json").write_text(json.dumps({"project": project, "run": run, "asset": asset}))
print("Local browser fixtures created; no network acquisition performed.")
