"""Structure-preserving document preparation, Unicode-token chunking and RAG exports."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter
from dataclasses import asdict, replace
from uuid import NAMESPACE_URL, uuid5

from mediasensei.domain.documents import ChunkEmbedding, DocumentChunk, DocumentFormat
from mediasensei.infrastructure.documents import DocumentParser, LocalHashEmbeddingProvider

TOKENS = re.compile(r"\w+|[^\w\s]", re.UNICODE)


def prepare_document(path, asset, p):
    parsed = DocumentParser().parse(
        path,
        source_sha256=asset["sha256"],
        document_format=DocumentFormat.from_filename(asset["original_filename"]),
        title_hint=asset["original_filename"],
    )
    if not parsed.analysis.valid:
        raise ValueError(parsed.analysis.error)
    if sum(len(b.text) for b in parsed.blocks) > 5_000_000:
        raise ValueError("Document exceeds the 5 million character preparation limit.")
    blocks = []
    for b in parsed.blocks:
        value = b.text
        if p["unicode"] != "none":
            value = unicodedata.normalize(p["unicode"], value)
        if p["find"]:
            if p["regex"]:
                import pyarrow as pa
                import pyarrow.compute as pc

                try:
                    value = pc.replace_substring_regex(
                        pa.array([value]), pattern=p["find"], replacement=p["replace"]
                    )[0].as_py()
                except (pa.ArrowInvalid, pa.ArrowNotImplementedError) as error:
                    raise ValueError(f"Invalid RE2 expression: {error}") from error
            else:
                value = value.replace(p["find"], p["replace"])
        if p["whitespace"]:
            value = re.sub(r"[^\S\n]+", " ", value)
            value = re.sub(r"\n{3,}", "\n\n", value).strip()
        if value.strip():
            blocks.append(replace(b, text=value))
    if not blocks:
        raise ValueError("Document contains no text after cleaning.")
    parsed = replace(
        parsed,
        blocks=tuple(blocks),
        analysis=replace(
            parsed.analysis,
            block_count=len(blocks),
            character_count=sum(len(b.text) for b in blocks),
            parser_revision=parsed.analysis.parser_revision + "+prepare-v2",
        ),
    )
    return parsed


def chunk_document(parsed, asset_id, p):
    size, overlap = int(p["chunk_size"]), int(p["overlap"])
    if overlap >= size:
        raise ValueError("Overlap must be smaller than chunk size.")
    strategy = p["strategy"]
    groups = []
    for b in parsed.blocks:
        if (
            strategy == "token"
            and groups
            or strategy == "heading"
            and groups
            and groups[-1][-1].heading == b.heading
        ):
            groups[-1].append(b)
        else:
            groups.append([b])
    if strategy == "recursive":
        # Pack paragraphs into token-bounded units; split long units below on sentence boundaries.
        packed = []
        for group in groups:
            if packed and sum(len(TOKENS.findall(b.text)) for b in [*packed[-1], *group]) <= size:
                packed[-1].extend(group)
            else:
                packed.append(group)
        groups = packed
    chunks = []
    for group in groups:
        text = "\n\n".join(b.text for b in group)
        spans = list(TOKENS.finditer(text))
        offsets, cursor = [], 0
        for b in group:
            offsets.append((cursor, cursor + len(b.text), b))
            cursor += len(b.text) + 2
        start = 0
        while start < len(spans):
            end = min(start + size, len(spans))
            if strategy == "recursive" and end < len(spans):
                for i in range(end - 1, start + max(overlap, size // 2), -1):
                    if spans[i].group() in ".!?":
                        end = i + 1
                        break
            lo, hi = spans[start].start(), spans[end - 1].end()
            value = text[lo:hi]
            used = [b for left, right, b in offsets if right > lo and left < hi]
            pages = [b.page for b in used if b.page is not None]
            digest = hashlib.sha256(value.encode()).hexdigest()
            locator = {
                "heading": used[0].heading,
                "block_start": used[0].index,
                "block_end": used[-1].index,
                "page_start": min(pages) if pages else None,
                "page_end": max(pages) if pages else None,
                "token_count": end - start,
                "tokenizer": "Unicode words and punctuation v1",
                "strategy": strategy,
                "character_start": lo,
                "character_end": hi,
            }
            identifier = str(
                uuid5(
                    NAMESPACE_URL,
                    json.dumps(
                        [asset_id, parsed.analysis.source_sha256, p, len(chunks), digest],
                        sort_keys=True,
                    ),
                )
            )
            chunks.append(
                DocumentChunk(
                    identifier,
                    asset_id,
                    parsed.analysis.source_sha256,
                    len(chunks),
                    value,
                    len(value.split()),
                    digest,
                    locator,
                )
            )
            if len(chunks) > 20000:
                raise ValueError("Preparation exceeds the 20,000 chunk limit; increase chunk size.")
            if end == len(spans):
                break
            start = end - overlap
    return chunks


def quality(parsed, chunks):
    text = "\n".join(b.text for b in parsed.blocks)
    words = {w.casefold() for w in re.findall(r"\w+", text)}
    # A transparent baseline; avoid presenting a heuristic as a learned detector.
    markers = {
        "en": "the and is are with this for of to in",
        "es": "el la los las de que una para con",
        "fr": "le la les une des pour avec est dans",
        "de": "der die das und ist mit ein eine",
    }
    scores = {k: len(words & set(v.split())) for k, v in markers.items()}
    best = max(scores, key=scores.get)
    language = best if scores[best] >= 3 else "und"
    counts = Counter(
        hashlib.sha256(b.text.casefold().strip().encode()).hexdigest() for b in parsed.blocks
    )
    return {
        "characters": len(text),
        "words": len(text.split()),
        "tokens": len(TOKENS.findall(text)),
        "tokenizer": "Unicode words and punctuation v1 (not model-specific)",
        "language": language,
        "language_method": "stopword heuristic; und means uncertain",
        "duplicate_blocks": sum(n - 1 for n in counts.values()),
        "chunks": len(chunks),
        "empty_blocks": sum(not b.text.strip() for b in parsed.blocks),
        "chunk_tokens": [c.locator["token_count"] for c in chunks],
    }


def index_prepared(catalog, asset, parsed, chunks, p, provider=None):
    provider = provider or LocalHashEmbeddingProvider()
    vectors = provider.embed([c.text for c in chunks])
    embeddings = [
        ChunkEmbedding(
            c.id,
            asset["sha256"],
            provider.provider_id,
            provider.model_revision,
            provider.dimensions,
            v,
        )
        for c, v in zip(chunks, vectors)
    ]
    catalog.replace_document_index(
        asset_id=asset["id"],
        analysis=parsed.analysis,
        chunks=chunks,
        embeddings=embeddings,
        options={**p, "tokenizer": "unicode-v1"},
    )
    return {
        "model_id": provider.provider_id,
        "model_revision": provider.model_revision,
        "dimensions": provider.dimensions,
        "chunks": len(chunks),
    }


def document_report(path, asset, p, *, catalog=None, provider=None):
    parsed = prepare_document(path, asset, p)
    chunks = chunk_document(parsed, asset["id"], p)
    report = {
        "analysis": asdict(parsed.analysis),
        "quality": quality(parsed, chunks),
        "blocks": [asdict(b) for b in parsed.blocks[:200]],
        "chunks": [asdict(c) for c in chunks[:200]],
        "preview_limit": 200,
        "comparison": {
            s: quality(parsed, chunk_document(parsed, asset["id"], {**p, "strategy": s}))
            for s in ("token", "paragraph", "heading", "recursive")
        },
    }
    if catalog is not None:
        report["index"] = index_prepared(catalog, asset, parsed, chunks, p, provider=provider)
    return report, parsed, chunks
