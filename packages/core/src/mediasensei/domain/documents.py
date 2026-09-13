from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class DocumentFormat(StrEnum):
    TEXT = "txt"
    MARKDOWN = "md"
    HTML = "html"
    PDF = "pdf"
    DOCX = "docx"

    @classmethod
    def from_filename(cls, filename: str) -> DocumentFormat:
        suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
        aliases = {"text": cls.TEXT, "markdown": cls.MARKDOWN, "htm": cls.HTML}
        try:
            return aliases[suffix] if suffix in aliases else cls(suffix)
        except ValueError as error:
            raise ValueError(f"Unsupported document format: {suffix or 'unknown'}") from error


@dataclass(frozen=True, slots=True)
class ParsedBlock:
    index: int
    kind: str
    text: str
    page: int | None = None
    heading: str | None = None
    locator: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DocumentAnalysis:
    source_sha256: str
    document_format: DocumentFormat
    valid: bool
    title: str | None
    page_count: int | None
    block_count: int
    character_count: int
    parser_revision: str
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    analysis: DocumentAnalysis
    blocks: tuple[ParsedBlock, ...]


@dataclass(frozen=True, slots=True)
class ChunkingOptions:
    max_words: int = 420
    overlap_words: int = 64

    def __post_init__(self) -> None:
        if not 32 <= self.max_words <= 4096:
            raise ValueError("Chunk size must be between 32 and 4096 words")
        if not 0 <= self.overlap_words < self.max_words:
            raise ValueError("Chunk overlap must be non-negative and smaller than chunk size")


@dataclass(frozen=True, slots=True)
class DocumentChunk:
    id: str
    asset_id: str
    source_sha256: str
    sequence: int
    text: str
    word_count: int
    content_hash: str
    locator: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ChunkEmbedding:
    content_unit_id: str
    source_sha256: str
    model_id: str
    model_revision: str
    dimensions: int
    vector: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class RetrievalHit:
    content_unit_id: str
    asset_id: str
    filename: str
    title: str | None
    score: float
    text: str
    locator: dict[str, Any]
