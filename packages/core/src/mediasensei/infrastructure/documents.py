from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import math
import re
import struct
import zipfile
from collections import Counter
from collections.abc import Iterable
from html.parser import HTMLParser
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, cast
from uuid import NAMESPACE_URL, uuid5
from xml.etree import ElementTree

from mediasensei_plugin_sdk import EmbeddingProvider  # type: ignore[import-untyped]

from mediasensei.domain.documents import (
    ChunkEmbedding,
    ChunkingOptions,
    DocumentAnalysis,
    DocumentChunk,
    DocumentFormat,
    ParsedBlock,
    ParsedDocument,
    RetrievalHit,
)
from mediasensei.domain.jobs import ProcessorSpec, ResourceHints, ResourceLevel, WorkItem
from mediasensei.infrastructure.storage import ContentAddressedStore

if TYPE_CHECKING:
    from mediasensei.infrastructure.catalog import Catalog
    from mediasensei.infrastructure.worker import ProcessorRegistry

PARSER_REVISION = "mediasensei-document-parser-v1"
WORD_PATTERN = re.compile(r"[\w']+", re.UNICODE)


class DocumentParseError(ValueError):
    pass


class LocalHashEmbeddingProvider:
    """Deterministic offline embedding using signed feature hashing.

    This compact provider is dependency-free and intended for local retrieval baselines.
    Its exact revision is persisted so a learned embedding adapter can be swapped in later.
    """

    provider_id = "local-hash-embedding"
    model_revision = "mediasensei-hash-embedding-v1"

    def __init__(self, dimensions: int = 384) -> None:
        if not 64 <= dimensions <= 4096:
            raise ValueError("Embedding dimensions must be between 64 and 4096")
        self.dimensions = dimensions

    def embed(self, texts: list[str]) -> list[tuple[float, ...]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> tuple[float, ...]:
        tokens = [token.casefold() for token in WORD_PATTERN.findall(text)]
        features = [*tokens, *(f"{left}::{right}" for left, right in pairwise(tokens))]
        counts = Counter(features)
        vector = [0.0] * self.dimensions
        for feature, count in counts.items():
            digest = hashlib.sha256(feature.encode("utf-8")).digest()
            index = int.from_bytes(digest[:8], "big") % self.dimensions
            sign = 1.0 if digest[8] & 1 else -1.0
            vector[index] += sign * (1.0 + math.log(count))
        norm = math.sqrt(sum(value * value for value in vector))
        if norm:
            vector = [value / norm for value in vector]
        return tuple(vector)


class DocumentParser:
    def parse(
        self,
        path: str | Path,
        *,
        source_sha256: str,
        document_format: DocumentFormat,
        title_hint: str | None = None,
    ) -> ParsedDocument:
        source = Path(path).resolve(strict=True)
        try:
            if document_format == DocumentFormat.TEXT:
                blocks, title, page_count = _parse_text(source, markdown=False)
            elif document_format == DocumentFormat.MARKDOWN:
                blocks, title, page_count = _parse_text(source, markdown=True)
            elif document_format == DocumentFormat.HTML:
                blocks, title, page_count = _parse_html(source)
            elif document_format == DocumentFormat.DOCX:
                blocks, title, page_count = _parse_docx(source)
            elif document_format == DocumentFormat.PDF:
                blocks, title, page_count = _parse_pdf(source)
            else:
                raise DocumentParseError(f"Unsupported document format: {document_format}")
            clean_title = (title or title_hint or source.stem).strip()[:500] or None
            analysis = DocumentAnalysis(
                source_sha256=source_sha256,
                document_format=document_format,
                valid=True,
                title=clean_title,
                page_count=page_count,
                block_count=len(blocks),
                character_count=sum(len(block.text) for block in blocks),
                parser_revision=PARSER_REVISION,
            )
            return ParsedDocument(analysis, tuple(blocks))
        except (DocumentParseError, OSError, ValueError, zipfile.BadZipFile) as error:
            return ParsedDocument(
                DocumentAnalysis(
                    source_sha256=source_sha256,
                    document_format=document_format,
                    valid=False,
                    title=title_hint or source.stem,
                    page_count=None,
                    block_count=0,
                    character_count=0,
                    parser_revision=PARSER_REVISION,
                    error=str(error)[:1000],
                ),
                (),
            )


class StructureAwareChunker:
    def chunk(
        self,
        parsed: ParsedDocument,
        *,
        asset_id: str,
        options: ChunkingOptions,
    ) -> list[DocumentChunk]:
        if not parsed.analysis.valid:
            raise DocumentParseError(parsed.analysis.error or "Document parsing failed")
        groups = _block_groups(parsed.blocks)
        chunks: list[DocumentChunk] = []
        sequence = 0
        for heading, blocks in groups:
            words = WORD_PATTERN.findall("\n".join(block.text for block in blocks))
            if not words:
                continue
            start = 0
            while start < len(words):
                end = min(len(words), start + options.max_words)
                text = " ".join(words[start:end])
                content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
                locator: dict[str, Any] = {
                    "heading": heading,
                    "block_start": blocks[0].index,
                    "block_end": blocks[-1].index,
                    "word_start": start,
                    "word_end": end,
                }
                pages = [block.page for block in blocks if block.page is not None]
                if pages:
                    locator["page_start"] = min(pages)
                    locator["page_end"] = max(pages)
                chunk_id = str(
                    uuid5(
                        NAMESPACE_URL,
                        json.dumps(
                            {
                                "asset_id": asset_id,
                                "source_sha256": parsed.analysis.source_sha256,
                                "sequence": sequence,
                                "content_hash": content_hash,
                                "max_words": options.max_words,
                                "overlap_words": options.overlap_words,
                            },
                            sort_keys=True,
                        ),
                    )
                )
                chunks.append(
                    DocumentChunk(
                        id=chunk_id,
                        asset_id=asset_id,
                        source_sha256=parsed.analysis.source_sha256,
                        sequence=sequence,
                        text=text,
                        word_count=end - start,
                        content_hash=content_hash,
                        locator=locator,
                    )
                )
                sequence += 1
                if end >= len(words):
                    break
                start = max(start + 1, end - options.overlap_words)
        return chunks


class DocumentPipeline:
    def __init__(
        self,
        store: ContentAddressedStore,
        *,
        parser: DocumentParser | None = None,
        chunker: StructureAwareChunker | None = None,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        self.store = store
        self.parser = parser or DocumentParser()
        self.chunker = chunker or StructureAwareChunker()
        self.embedding_provider = embedding_provider or LocalHashEmbeddingProvider()

    def index(
        self,
        path: str | Path,
        *,
        asset_id: str,
        source_sha256: str,
        document_format: DocumentFormat,
        title_hint: str | None = None,
        options: ChunkingOptions | None = None,
    ) -> tuple[ParsedDocument, list[DocumentChunk], list[ChunkEmbedding]]:
        parsed = self.parser.parse(
            path,
            source_sha256=source_sha256,
            document_format=document_format,
            title_hint=title_hint,
        )
        chunks, embeddings = self.embed_chunks(
            parsed,
            asset_id=asset_id,
            options=options,
        )
        return parsed, chunks, embeddings

    def embed_chunks(
        self,
        parsed: ParsedDocument,
        *,
        asset_id: str,
        options: ChunkingOptions | None = None,
    ) -> tuple[list[DocumentChunk], list[ChunkEmbedding]]:
        selected_options = options or ChunkingOptions()
        chunks = self.chunker.chunk(parsed, asset_id=asset_id, options=selected_options)
        if not chunks:
            raise DocumentParseError("Document contains no indexable text")
        vectors = self.embedding_provider.embed([chunk.text for chunk in chunks])
        if len(vectors) != len(chunks):
            raise RuntimeError("Embedding provider returned the wrong number of vectors")
        embeddings = [
            ChunkEmbedding(
                content_unit_id=chunk.id,
                source_sha256=parsed.analysis.source_sha256,
                model_id=self.embedding_provider.provider_id,
                model_revision=self.embedding_provider.model_revision,
                dimensions=self.embedding_provider.dimensions,
                vector=tuple(vector),
            )
            for chunk, vector in zip(chunks, vectors)
        ]
        return chunks, embeddings


class SQLiteVectorIndex:
    provider_id = "sqlite-exact-cosine"

    def __init__(
        self,
        catalog: Catalog,
        *,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        self.catalog = catalog
        self.embedding_provider = embedding_provider or LocalHashEmbeddingProvider()

    def search(
        self,
        project_id: str,
        query: str,
        *,
        limit: int = 5,
        minimum_score: float = 0.0,
        asset_ids: list[str] | None = None,
    ) -> list[RetrievalHit]:
        clean_query = query.strip()
        if not clean_query:
            raise ValueError("Retrieval query cannot be empty")
        bounded_limit = max(1, min(int(limit), 50))
        query_vector = self.embedding_provider.embed([clean_query])[0]
        candidates = self.catalog.embedding_candidates(
            project_id,
            model_id=self.embedding_provider.provider_id,
            model_revision=self.embedding_provider.model_revision,
            asset_ids=asset_ids or [],
        )
        scored: list[RetrievalHit] = []
        for candidate in candidates:
            dimensions = cast(int, candidate["dimensions"])
            vector = unpack_vector(cast(bytes, candidate["vector_blob"]), dimensions)
            if len(vector) != len(query_vector):
                continue
            score = sum(left * right for left, right in zip(query_vector, vector))
            if score < minimum_score:
                continue
            locator_value = candidate.get("locator_json")
            locator = json.loads(str(locator_value)) if locator_value else {}
            scored.append(
                RetrievalHit(
                    content_unit_id=str(candidate["content_unit_id"]),
                    asset_id=str(candidate["asset_id"]),
                    filename=str(candidate["original_filename"]),
                    title=str(candidate["title"]) if candidate.get("title") else None,
                    score=round(max(-1.0, min(1.0, score)), 6),
                    text=str(candidate["text_content"]),
                    locator=locator,
                )
            )
        scored.sort(key=lambda item: (-item.score, item.content_unit_id))
        return scored[:bounded_limit]


def register_document_processors(
    registry: ProcessorRegistry,
    catalog: Catalog,
    *,
    embedding_provider: EmbeddingProvider | None = None,
) -> None:
    provider = embedding_provider or LocalHashEmbeddingProvider()
    pipeline = DocumentPipeline(
        ContentAddressedStore(catalog.workspace), embedding_provider=provider
    )

    def index_processor(item: WorkItem, parameters: dict[str, Any]) -> dict[str, Any]:
        asset_ids = parameters.get("asset_ids_by_position")
        formats = parameters.get("formats_by_position")
        titles = parameters.get("titles_by_position", {})
        if not isinstance(asset_ids, dict) or not isinstance(formats, dict):
            raise TypeError("Document jobs require asset and format provenance maps")
        asset_id = str(asset_ids.get(str(item.position), ""))
        format_value = str(formats.get(str(item.position), ""))
        if not asset_id or not format_value:
            raise ValueError("Document job provenance is incomplete for an input")
        options = ChunkingOptions(
            max_words=int(parameters.get("max_words", 420)),
            overlap_words=int(parameters.get("overlap_words", 64)),
        )
        parsed = pipeline.parser.parse(
            pipeline.store.resolve(item.input_ref),
            source_sha256=item.input_hash,
            document_format=DocumentFormat(format_value),
            title_hint=str(titles.get(str(item.position), ""))
            if isinstance(titles, dict)
            else None,
        )
        catalog.upsert_document_analysis(parsed.analysis)
        chunks, embeddings = pipeline.embed_chunks(
            parsed,
            asset_id=asset_id,
            options=options,
        )
        catalog.replace_document_index(
            asset_id=asset_id,
            analysis=parsed.analysis,
            chunks=chunks,
            embeddings=embeddings,
            options={"max_words": options.max_words, "overlap_words": options.overlap_words},
        )
        return {
            "asset_id": asset_id,
            "chunks": len(chunks),
            "dimensions": provider.dimensions,
            "model_revision": provider.model_revision,
        }

    registry.register("document.index", index_processor)


def document_processor_spec(
    *, embedding_provider: EmbeddingProvider | None = None
) -> ProcessorSpec:
    provider = embedding_provider or LocalHashEmbeddingProvider()
    return ProcessorSpec(
        id="document.index",
        version="1.0.0",
        deterministic=True,
        cacheable=False,
        model_revision=provider.model_revision,
        resource_hints=ResourceHints(
            cpu=ResourceLevel.MEDIUM,
            memory=ResourceLevel.MEDIUM,
            disk=ResourceLevel.LOW,
        ),
    )


def pack_vector(vector: Iterable[float]) -> bytes:
    values = tuple(float(value) for value in vector)
    return struct.pack(f"<{len(values)}f", *values)


def unpack_vector(payload: bytes, dimensions: int) -> tuple[float, ...]:
    if dimensions < 1 or len(payload) != dimensions * 4:
        raise ValueError("Stored embedding has an invalid dimension or byte length")
    return tuple(struct.unpack(f"<{dimensions}f", payload))


def _read_text(path: Path) -> str:
    if path.stat().st_size > 128 * 1024 * 1024:
        raise DocumentParseError("Text document exceeds the 128 MiB parser limit")
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    if "\x00" in text:
        raise DocumentParseError("Text document contains unsupported NUL bytes")
    return text


def _parse_text(path: Path, *, markdown: bool) -> tuple[list[ParsedBlock], str | None, int | None]:
    text = _read_text(path)
    blocks: list[ParsedBlock] = []
    heading: str | None = None
    paragraph: list[str] = []
    start_line = 1
    title: str | None = None

    def flush(end_line: int) -> None:
        nonlocal paragraph
        clean = " ".join(part.strip() for part in paragraph if part.strip())
        if clean:
            blocks.append(
                ParsedBlock(
                    len(blocks),
                    "paragraph",
                    clean,
                    heading=heading,
                    locator={"line_start": start_line, "line_end": end_line},
                )
            )
        paragraph = []

    lines = text.splitlines()
    for line_number, line in enumerate(lines, 1):
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line) if markdown else None
        if match:
            flush(line_number - 1)
            heading = match.group(2).strip()
            title = title or heading
            blocks.append(
                ParsedBlock(
                    len(blocks),
                    f"heading_{len(match.group(1))}",
                    heading,
                    heading=heading,
                    locator={"line_start": line_number, "line_end": line_number},
                )
            )
            start_line = line_number + 1
        elif not line.strip():
            flush(line_number - 1)
            start_line = line_number + 1
        else:
            if not paragraph:
                start_line = line_number
            paragraph.append(line)
    flush(len(lines))
    return blocks, title, None


class _StructuredHTMLParser(HTMLParser):
    block_tags: ClassVar[set[str]] = {
        "p",
        "li",
        "blockquote",
        "pre",
        "td",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[ParsedBlock] = []
        self.title: str | None = None
        self.heading: str | None = None
        self._tag: str | None = None
        self._parts: list[str] = []
        self._suppressed = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._suppressed += 1
            return
        if self._suppressed:
            return
        if tag == "title":
            self._in_title = True
            self._parts = []
        elif tag in self.block_tags:
            self._tag = tag
            self._parts = []

    def handle_data(self, data: str) -> None:
        if not self._suppressed and (self._tag or self._in_title):
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"}:
            self._suppressed = max(0, self._suppressed - 1)
            return
        if self._suppressed:
            return
        clean = re.sub(r"\s+", " ", " ".join(self._parts)).strip()
        if tag == "title" and self._in_title:
            self.title = clean or self.title
            self._in_title = False
            self._parts = []
        elif tag == self._tag:
            if clean:
                kind = f"heading_{tag[1]}" if tag.startswith("h") else tag
                if tag.startswith("h"):
                    self.heading = clean
                    self.title = self.title or clean
                self.blocks.append(
                    ParsedBlock(
                        len(self.blocks),
                        kind,
                        clean,
                        heading=self.heading,
                        locator={"html_tag": tag},
                    )
                )
            self._tag = None
            self._parts = []


def _parse_html(path: Path) -> tuple[list[ParsedBlock], str | None, int | None]:
    parser = _StructuredHTMLParser()
    parser.feed(_read_text(path))
    parser.close()
    return parser.blocks, parser.title, None


def _parse_docx(path: Path) -> tuple[list[ParsedBlock], str | None, int | None]:
    if path.stat().st_size > 512 * 1024 * 1024:
        raise DocumentParseError("DOCX exceeds the 512 MiB parser limit")
    with zipfile.ZipFile(path) as archive:
        try:
            info = archive.getinfo("word/document.xml")
            if info.file_size > 128 * 1024 * 1024:
                raise DocumentParseError("DOCX XML exceeds the 128 MiB expanded limit")
            with archive.open(info) as stream:
                payload = stream.read(128 * 1024 * 1024 + 1)
        except KeyError as error:
            raise DocumentParseError("DOCX is missing word/document.xml") from error
    if len(payload) > 128 * 1024 * 1024:
        raise DocumentParseError("DOCX XML exceeds the 128 MiB expanded limit")
    root = ElementTree.fromstring(payload)
    namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    blocks: list[ParsedBlock] = []
    heading: str | None = None
    title: str | None = None
    page = 1
    for paragraph in root.iter(f"{namespace}p"):
        text = "".join(node.text or "" for node in paragraph.iter(f"{namespace}t")).strip()
        style_node = paragraph.find(f"{namespace}pPr/{namespace}pStyle")
        style = style_node.get(f"{namespace}val", "") if style_node is not None else ""
        is_heading = style.casefold().startswith("heading")
        if text:
            if is_heading:
                heading = text
                title = title or text
            blocks.append(
                ParsedBlock(
                    len(blocks),
                    "heading" if is_heading else "paragraph",
                    text,
                    page=page,
                    heading=heading,
                    locator={"paragraph": len(blocks), "style": style or None},
                )
            )
        page += sum(
            1
            for node in paragraph.iter()
            if node.tag in {f"{namespace}lastRenderedPageBreak", f"{namespace}br"}
            and (
                node.tag.endswith("lastRenderedPageBreak") or node.get(f"{namespace}type") == "page"
            )
        )
    return blocks, title, page


def _parse_pdf(path: Path) -> tuple[list[ParsedBlock], str | None, int | None]:
    if importlib.util.find_spec("pypdf") is None:
        raise DocumentParseError(
            "PDF parsing requires the optional pypdf dependency; install MediaSensei document support and retry"
        )
    pypdf = importlib.import_module("pypdf")
    reader = pypdf.PdfReader(str(path))
    if len(reader.pages) > 10_000:
        raise DocumentParseError("PDF exceeds the 10,000 page parser limit")
    blocks: list[ParsedBlock] = []
    for page_number, page in enumerate(reader.pages, 1):
        page_text = page.extract_text() or ""
        for paragraph in re.split(r"\n\s*\n", page_text):
            clean = re.sub(r"\s+", " ", paragraph).strip()
            if clean:
                blocks.append(
                    ParsedBlock(
                        len(blocks),
                        "paragraph",
                        clean,
                        page=page_number,
                        locator={"page": page_number},
                    )
                )
    metadata = reader.metadata
    title = str(metadata.title).strip() if metadata and metadata.title else None
    return blocks, title, len(reader.pages)


def _block_groups(
    blocks: tuple[ParsedBlock, ...],
) -> list[tuple[str | None, list[ParsedBlock]]]:
    groups: list[tuple[str | None, list[ParsedBlock]]] = []
    for block in blocks:
        if not block.text.strip():
            continue
        if not groups or groups[-1][0] != block.heading:
            groups.append((block.heading, [block]))
        else:
            groups[-1][1].append(block)
    return groups
