"""Local multimodal workbench with immutable outputs and per-asset queue checkpoints."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import mimetypes
import tempfile
import zipfile
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from mediasensei.infrastructure.storage import ContentAddressedStore


def image_edit(path, p, *, preview=False):
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps

    with Image.open(path) as original:
        if original.width * original.height > 64_000_000:
            raise ValueError("Image exceeds the 64 megapixel transform limit.")
        original.load()
        im = ImageOps.exif_transpose(original)
        exif = im.getexif()
        if p["crop"].strip():
            try:
                box = tuple(int(x.strip()) for x in p["crop"].split(","))
            except ValueError as error:
                raise ValueError("Crop must be left,top,right,bottom in pixels.") from error
            if len(box) != 4 or not (
                0 <= box[0] < box[2] <= im.width and 0 <= box[1] < box[3] <= im.height
            ):
                raise ValueError(
                    "Crop coordinates must form a rectangle inside the original image."
                )
            im = im.crop(box)
        if p["rotate"]:
            angle = math.radians(float(p["rotate"]) % 180)
            cosine, sine = round(math.cos(angle), 12), round(math.sin(angle), 12)
            rotated_width = math.ceil(abs(im.width * cosine) + abs(im.height * sine))
            rotated_height = math.ceil(abs(im.height * cosine) + abs(im.width * sine))
            if rotated_width * rotated_height > 64_000_000:
                raise ValueError("Rotated output exceeds the 64 megapixel limit.")
            im = im.rotate(float(p["rotate"]), resample=Image.Resampling.BICUBIC, expand=True)
        if p["flip"] in ("horizontal", "both"):
            im = ImageOps.mirror(im)
        if p["flip"] in ("vertical", "both"):
            im = ImageOps.flip(im)
        width, height = int(p["width"]) or im.width, int(p["height"]) or im.height
        if width * height > 64_000_000:
            raise ValueError("Output exceeds the 64 megapixel limit.")
        size = (width, height)
        if p["fit"] == "cover":
            im = ImageOps.fit(im, size, method=Image.Resampling.LANCZOS)
        elif p["fit"] == "pad":
            im = ImageOps.pad(
                im.convert("RGB"), size, color=p["background"], method=Image.Resampling.LANCZOS
            )
        elif p["fit"] == "stretch":
            im = im.resize(size, Image.Resampling.LANCZOS)
        else:
            im.thumbnail(size, Image.Resampling.LANCZOS)
        mode = "L" if p["mode"] == "grayscale" else p["mode"]
        im = im.convert(mode)
        if p["normalize"]:
            im = ImageOps.autocontrast(im.convert("RGB") if im.mode == "RGBA" else im)
        for key, enhancer in (
            ("brightness", ImageEnhance.Brightness),
            ("contrast", ImageEnhance.Contrast),
            ("sharpness", ImageEnhance.Sharpness),
        ):
            if p[key] != 1:
                im = enhancer(im).enhance(float(p[key]))
        if p["blur"]:
            im = im.filter(ImageFilter.GaussianBlur(float(p["blur"])))
        result = {
            "width": im.width,
            "height": im.height,
            "mode": im.mode,
            "format": p["format"],
            "metadata_stripped": p["strip_metadata"],
        }
        if preview:
            im.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
        if p["format"] == "JPEG" and im.mode not in ("L", "RGB"):
            im = im.convert("RGB")
        buffer = io.BytesIO()
        if p["strip_metadata"]:
            # Pillow can implicitly copy EXIF from im.info even without an exif argument.
            im.info.clear()
        options = {"quality": int(p["quality"])} if p["format"] in ("JPEG", "WEBP") else {}
        if not p["strip_metadata"] and p["format"] in ("JPEG", "PNG", "WEBP", "TIFF"):
            for key in (256, 257, 40962, 40963):
                if key in exif:
                    del exif[key]
            options["exif"] = exif.tobytes()
        im.save(buffer, format="PNG" if preview else p["format"], **({} if preview else options))
        return buffer.getvalue(), result


def image_report(path, sha256):
    from PIL import ExifTags, Image, ImageStat

    with Image.open(path) as im:
        if im.width * im.height > 64_000_000:
            raise ValueError("Image exceeds the 64 megapixel inspection limit.")
        exif = im.getexif()
        metadata = {ExifTags.TAGS.get(k, str(k)): str(v)[:2000] for k, v in exif.items()}
        if 34853 in exif:
            metadata["GPSInfo"] = {
                ExifTags.GPSTAGS.get(k, str(k)): str(v) for k, v in exif.get_ifd(34853).items()
            }
        im.thumbnail((512, 512))
        rgb = im.convert("RGB")
        histogram = rgb.histogram()
        bins = {
            channel: [sum(histogram[offset + i : offset + i + 16]) for i in range(0, 256, 16)]
            for channel, offset in (("red", 0), ("green", 256), ("blue", 512))
        }
        quantized = rgb.quantize(colors=8)
        palette = quantized.getpalette()
        colors = sorted(quantized.getcolors() or [], reverse=True)
        return {
            "sha256": sha256,
            "metadata": metadata,
            "histogram": bins,
            "color_mean": ImageStat.Stat(rgb).mean,
            "colors": [
                {
                    "count": count,
                    "color": "#" + "".join(f"{c:02x}" for c in palette[index * 3 : index * 3 + 3]),
                }
                for count, index in colors
            ],
        }


class BatchService:
    def __init__(self, catalog):
        self.catalog = catalog
        self.store = ContentAddressedStore(catalog.workspace)
        with catalog.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS lab_asset_outputs (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL, asset_id TEXT NOT NULL,
                operation TEXT NOT NULL, result_json TEXT NOT NULL, created_at TEXT NOT NULL)""")
            db.execute(
                "CREATE INDEX IF NOT EXISTS lab_asset_outputs_project ON lab_asset_outputs(project_id, created_at)"
            )

    def asset(self, identifier, project_id=None):
        asset = self.catalog.get_asset(identifier)
        if project_id is not None and asset["project_id"] != project_id:
            raise ValueError("Asset is outside the selected project.")
        return asset

    def preview(self, asset_id, operation, supplied):
        from mediasensei.operations import parameters

        asset = self.asset(asset_id)
        p = parameters(operation, supplied, [])
        modality = operation.split(".")[0]
        if asset["media_type"] != modality:
            raise ValueError("The selected asset is incompatible with this operation.")
        path = self.store.resolve(asset["object_key"])
        if operation == "image.edit":
            payload, report = image_edit(path, p, preview=True)
            mime = "image/png"
            return {
                "parameters": p,
                "report": report,
                "image": f"data:{mime};base64," + base64.b64encode(payload).decode(),
            }
        if operation == "document.prepare":
            from mediasensei.knowledge import document_report

            report, _, _ = document_report(path, asset, p)
        elif operation in ("audio.process", "video.process"):
            from mediasensei.media_workbench import media_plan

            report = media_plan(self.store, path, modality, p)
        else:
            raise ValueError("This operation has no Batch 2 preview.")
        return {"parameters": p, "report": report}

    def execute(self, asset_id, operation, supplied):
        from mediasensei.operations import parameters

        asset = self.asset(asset_id)
        p = parameters(operation, supplied, [])
        if asset["media_type"] != operation.split(".")[0]:
            raise ValueError("The selected asset is incompatible with this operation.")
        source = self.store.resolve(asset["object_key"])
        with tempfile.TemporaryDirectory(prefix="batch2-", dir=self.store.temp_root) as temp:
            directory = Path(temp)
            if operation == "image.edit":
                payload, report = image_edit(source, p)
                file = directory / f"transformed.{p['format'].lower()}"
                file.write_bytes(payload)
                files = [(file, ImageMime[p["format"]])]
            elif operation in ("document.prepare", "document.embed"):
                from mediasensei.knowledge import document_report

                provider = None
                if operation == "document.embed":
                    from mediasensei.integrations import IntegrationService

                    provider = IntegrationService(self.catalog).embedding(
                        p["model_revision"], require_active=True
                    )
                report, parsed, chunks = document_report(
                    source, asset, p, catalog=self.catalog, provider=provider
                )
                file = directory / "prepared.txt"
                file.write_text("\n\n".join(b.text for b in parsed.blocks), encoding="utf-8")
                chunk_file = directory / "chunks.jsonl"
                chunk_file.write_text(
                    "\n".join(json.dumps(asdict(c), ensure_ascii=False) for c in chunks),
                    encoding="utf-8",
                )
                files = [(file, "text/plain"), (chunk_file, "application/x-ndjson")]
            elif operation == "document.speak":
                from mediasensei.native_adapters import speak

                report, files = speak(self.catalog, source, asset, p, directory)
            elif operation == "audio.transcribe":
                from mediasensei.native_adapters import transcribe

                report, files = transcribe(self.store, source, p, directory)
            else:
                from mediasensei.media_workbench import process_media

                report, files = process_media(self.store, source, asset["media_type"], p, directory)
            artifacts = []
            for path, mime in files:
                stored = self.store.import_file(path)
                artifacts.append(
                    {
                        "name": path.name,
                        "sha256": stored.sha256,
                        "object_key": stored.object_key,
                        "bytes": stored.byte_size,
                        "mime": mime
                        or mimetypes.guess_type(path.name)[0]
                        or "application/octet-stream",
                    }
                )
            result = {
                "id": str(uuid4()),
                "asset_id": asset_id,
                "filename": asset["original_filename"],
                "operation": operation,
                "parameters": p,
                "report": report,
                "artifacts": artifacts,
                "provenance": {
                    "source_sha256": asset["sha256"],
                    "operation_version": __import__(
                        "mediasensei.domain.operations", fromlist=["REGISTRY"]
                    )
                    .REGISTRY.get(operation)
                    .version,
                    "tool_revision": report.get("tool_revision", "Pillow / document-pipeline v2"),
                    "created_at": datetime.now(UTC).isoformat(),
                },
            }
            with self.catalog.connect() as db:
                db.execute(
                    "INSERT INTO lab_asset_outputs VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        result["id"],
                        asset["project_id"],
                        asset_id,
                        operation,
                        json.dumps(result),
                        result["provenance"]["created_at"],
                    ),
                )
            return result

    def outputs(self, project_id):
        with self.catalog.connect() as db:
            rows = db.execute(
                "SELECT result_json FROM lab_asset_outputs WHERE project_id=? ORDER BY created_at DESC LIMIT 100",
                (project_id,),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def output(self, output_id):
        with self.catalog.connect() as db:
            row = db.execute(
                "SELECT result_json FROM lab_asset_outputs WHERE id=?", (output_id,)
            ).fetchone()
        if row is None:
            raise KeyError("Output not found")
        return json.loads(row[0])

    def image_details(self, asset_id):
        asset = self.asset(asset_id)
        if asset["media_type"] != "image":
            raise ValueError("Select an image")
        return image_report(self.store.resolve(asset["object_key"]), asset["sha256"])

    def distributions(self, project_id):
        counters = {
            k: Counter()
            for k in ("class", "resolution", "aspect_ratio", "file_size", "format", "quality")
        }
        for asset in self.catalog.list_assets(project_id, media_type="image"):
            a = self.catalog.image_analysis(asset["sha256"]) or {}
            w, h = a.get("width") or 0, a.get("height") or 0
            counters["class"][str(asset.get("metadata", {}).get("label") or "Unlabelled")] += 1
            counters["resolution"][f"{w}x{h}"] += 1
            counters["aspect_ratio"][str(round(w / h, 1)) if h else "unknown"] += 1
            counters["file_size"][
                "<100KB"
                if asset["byte_size"] < 102400
                else "100KB–1MB"
                if asset["byte_size"] < 1048576
                else ">=1MB"
            ] += 1
            counters["format"][a.get("format") or "unknown"] += 1
            counters["quality"][
                "invalid"
                if not a.get("valid")
                else "low resolution"
                if min(w, h) < 512
                else "blur candidate"
                if (a.get("blur_score") or 0) < 50
                else "pass"
            ] += 1
        return {k: dict(v.most_common(50)) for k, v in counters.items()}

    def rag_bundle(self, project_id, destination):
        from mediasensei import __version__
        from mediasensei.infrastructure.documents import unpack_vector

        with self.catalog.connect() as db:
            db.execute("BEGIN")
            assets = [
                dict(row)
                for row in db.execute(
                    "SELECT * FROM assets WHERE project_id=? AND media_type='document' AND state='active' ORDER BY id",
                    (project_id,),
                )
            ]
            if not assets:
                raise ValueError("Import and index documents before exporting a RAG bundle.")
            rows = db.execute(
                """SELECT cu.*, e.model_id, e.model_revision, e.dimensions, e.vector_blob
                FROM content_units cu JOIN assets a ON a.id=cu.asset_id
                JOIN embeddings e ON e.content_unit_id=cu.id
                WHERE a.project_id=? AND a.state='active' AND cu.kind='document_chunk'
                ORDER BY cu.asset_id, json_extract(cu.locator_json, '$.sequence')""",
                (project_id,),
            ).fetchall()
            indexes = [
                dict(r)
                for r in db.execute(
                    """SELECT di.* FROM document_indexes di JOIN assets a ON a.id=di.asset_id
                WHERE a.project_id=? AND a.state='active' ORDER BY di.asset_id""",
                    (project_id,),
                )
            ]
            models = []
            for revision in sorted(
                {row["model_revision"] for row in indexes if row["model_id"] == "learned-tfidf"}
            ):
                model = db.execute(
                    "SELECT * FROM model_revisions WHERE revision=?", (revision,)
                ).fetchone()
                if not model:
                    raise ValueError(
                        "A fitted index model is missing; restore its exact revision before exporting."
                    )
                models.append(dict(model))
        indexed = {i["asset_id"] for i in indexes}
        if any(a["id"] not in indexed for a in assets):
            raise ValueError(
                "Index every active document before exporting; some documents have no index."
            )
        chunks, embeddings = [], []
        for row in rows:
            chunks.append(
                {
                    "id": row["id"],
                    "asset_id": row["asset_id"],
                    "text": row["text_content"],
                    "locator": json.loads(row["locator_json"]),
                }
            )
            embeddings.append(
                {
                    "chunk_id": row["id"],
                    "model_id": row["model_id"],
                    "model_revision": row["model_revision"],
                    "dimensions": row["dimensions"],
                    "vector": unpack_vector(row["vector_blob"], row["dimensions"]),
                }
            )
        manifest = {
            "format": "mediasensei-rag-v1",
            "project_id": project_id,
            "documents": [
                {
                    "id": a["id"],
                    "filename": a["original_filename"],
                    "sha256": a["sha256"],
                    "path": f"documents/{a['id']}{Path(a['original_filename']).suffix.lower()}",
                }
                for a in assets
            ],
            "chunks": len(chunks),
            "created_at": datetime.now(UTC).isoformat(),
        }
        checksums = {}
        with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:

            def write(name, payload):
                data = payload.encode("utf-8") if isinstance(payload, str) else payload
                archive.writestr(name, data)
                checksums[name] = hashlib.sha256(data).hexdigest()

            for asset, entry in zip(assets, manifest["documents"]):
                # Stream original immutable objects, preserving Windows-safe ZIP member names.
                digest = hashlib.sha256()
                with (
                    self.store.resolve(asset["object_key"]).open("rb") as source,
                    archive.open(entry["path"], "w") as target,
                ):
                    for block in iter(lambda: source.read(1024 * 1024), b""):
                        target.write(block)
                        digest.update(block)
                checksums[entry["path"]] = digest.hexdigest()
            write("chunks.jsonl", "\n".join(json.dumps(c, ensure_ascii=False) for c in chunks))
            write("embeddings.jsonl", "\n".join(json.dumps(e) for e in embeddings))
            write("index-metadata.json", json.dumps(indexes, indent=2))
            for model in models:
                payload = self.store.resolve(model["object_key"]).read_bytes()
                if hashlib.sha256(payload).hexdigest() != model["revision"]:
                    raise ValueError("Fitted model checksum mismatch.")
                write(f"models/{model['revision']}.json", payload)
            write("manifest.json", json.dumps(manifest, indent=2))
            write(
                "retrieval-config.json",
                json.dumps(
                    {
                        "metric": "cosine",
                        "providers": [
                            {
                                "id": row["model_id"],
                                "revision": row["model_revision"],
                                "dimensions": row["dimensions"],
                            }
                            for row in indexes
                        ],
                        "top_k": 8,
                        "minimum_score": 0,
                    }
                ),
            )
            write(
                "provenance.json",
                json.dumps(
                    {
                        "sources": manifest["documents"],
                        "indexes": indexes,
                        "app_version": __version__,
                    },
                    indent=2,
                ),
            )
            write(
                "dataset-card.md",
                f"# Local RAG dataset\n\n{len(assets)} documents; {len(chunks)} indexed chunks.\n\nEmbeddings measure lexical similarity using the pinned feature-hash or fitted TF-IDF providers in retrieval-config.json. They do not claim neural semantic understanding. Fitted model artifacts, original documents and source/page/heading provenance are included.\n",
            )
            archive.writestr(
                "checksums.sha256", "\n".join(f"{v}  {k}" for k, v in sorted(checksums.items()))
            )
        return manifest


ImageMime = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
    "TIFF": "image/tiff",
    "BMP": "image/bmp",
}


def register_batch_processors(registry, catalog):
    service = BatchService(catalog)

    def process(item, p):
        asset_id = p["_asset_ids"][str(item.position)]
        asset = service.asset(asset_id, p["_project_id"])
        if asset["sha256"] != item.input_hash or asset["object_key"] != item.input_ref:
            raise ValueError("Queued asset provenance does not match the immutable input.")
        return service.execute(
            asset_id, p["_operation"], {k: v for k, v in p.items() if not k.startswith("_")}
        )

    for operation in (
        "image.edit",
        "video.process",
        "audio.process",
        "document.prepare",
        "document.embed",
        "document.speak",
        "audio.transcribe",
    ):
        registry.register(operation, process)
