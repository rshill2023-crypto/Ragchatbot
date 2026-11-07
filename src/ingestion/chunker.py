"""Chunk cleaned documents for retrieval.

Three strategies are supported:

- `heading`: split at section headings, then window long sections;
- `fixed`: fixed token windows with overlap;
- `auto`: inspect each page's structure and choose `heading` or `fixed`.

Every chunk keeps source metadata and is persisted with a manifest describing
the selected strategy and rationale.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

from bs4 import BeautifulSoup

from ..artifacts import ArtifactWriter
from ..config import ChunkingConfig, Settings, load_config
from ..models import Chunk, RawDocument
from .document_loader import find_latest_run, load_run
from .loader import slug_from_url

LOGGER = logging.getLogger(__name__)

TOKEN_RE = re.compile(r"\S+")
HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")

KEYWORD_HEADINGS = (
    "expense ratio",
    "exit load",
    "exit load, stamp duty and tax",
    "stamp duty",
    "tax implication",
    "minimum sip",
    "minimum investments",
    "lock-in",
    "lock in",
    "riskometer",
    "fund benchmark",
    "benchmark",
    "investment objective",
    "fund house",
    "scheme information",
    "fund details",
    "fund management",
    "returns and rankings",
    "annualised returns",
    "absolute returns",
    "holdings",
)


class ChunkingError(RuntimeError):
    """Raised when chunking configuration or input is invalid."""


@dataclass
class ChunkResult:
    run_id: str
    run_dir: Path
    chunks: List[Chunk]
    manifest: Dict[str, Any]
    manifest_path: Path


def token_spans(text: str) -> List[Tuple[int, int]]:
    return [(match.start(), match.end()) for match in TOKEN_RE.finditer(text)]


def count_tokens(text: str) -> int:
    return len(TOKEN_RE.findall(text))


def make_chunk_id(source_url: str, section: str, index: int) -> str:
    raw = "%s|%s|%d" % (source_url, section, index)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _normalise_heading(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _looks_like_heading(value: str) -> bool:
    heading = _normalise_heading(value)
    if not heading or len(heading) > 100:
        return False
    if not any(character.isalpha() for character in heading):
        return False
    if len(heading.split()) > 12:
        return False
    return True


def _keyword_heading(line: str) -> bool:
    value = _normalise_heading(line).lower()
    if not value or len(value) > 80:
        return False
    if value.endswith((".", ";", "!", "?")):
        return False
    if len(value.split()) > 8:
        return False
    return any(value == keyword or value.startswith(keyword) for keyword in KEYWORD_HEADINGS)


def _html_headings(html: str) -> List[str]:
    if not html:
        return []
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:  # pragma: no cover - lxml is in requirements
        soup = BeautifulSoup(html, "html.parser")

    headings: List[str] = []
    for tag in soup.find_all(HEADING_TAGS):
        text = _normalise_heading(tag.get_text(" ", strip=True))
        if _looks_like_heading(text):
            headings.append(text)
    return headings


def _line_offsets(text: str) -> Iterable[Tuple[int, str]]:
    offset = 0
    for line in text.splitlines():
        yield offset, line
        offset += len(line) + 1


def heading_boundaries(document: RawDocument) -> List[Tuple[int, str]]:
    """Return (position, heading) pairs in the cleaned text."""
    text = document.text
    if not text.strip():
        return []

    lowered = text.lower()
    boundaries: List[Tuple[int, str]] = []

    cursor = 0
    for heading in _html_headings(document.html):
        found = lowered.find(heading.lower(), cursor)
        if found < 0:
            continue
        boundaries.append((found, heading))
        cursor = found + len(heading)

    for offset, line in _line_offsets(text):
        if _keyword_heading(line):
            heading = _normalise_heading(line)
            if heading:
                boundaries.append((offset, heading))

    merged: List[Tuple[int, str]] = []
    for position, heading in sorted(boundaries, key=lambda item: item[0]):
        if merged and position - merged[-1][0] <= 2:
            continue
        merged.append((position, heading))
    return merged


def _sections_from_text(document: RawDocument) -> List[Tuple[str, str]]:
    text = document.text
    if not text.strip():
        return []

    boundaries = heading_boundaries(document)
    if not boundaries:
        return [("content", text)]

    sections: List[Tuple[str, str]] = []
    first_position = boundaries[0][0]
    intro = text[:first_position].strip()
    if intro:
        sections.append(("Introduction", intro))

    for index, (position, heading) in enumerate(boundaries):
        end = boundaries[index + 1][0] if index + 1 < len(boundaries) else len(text)
        body = text[position:end].strip()
        if body:
            sections.append((heading, body))
    return sections


class BaseChunker:
    name = "base"

    def __init__(self, chunk_size: int, chunk_overlap: int) -> None:
        if chunk_size <= 0:
            raise ChunkingError("chunk_size must be positive")
        if chunk_overlap < 0:
            raise ChunkingError("chunk_overlap must be non-negative")
        if chunk_overlap >= chunk_size:
            raise ChunkingError("chunk_overlap must be smaller than chunk_size")
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def sections(self, document: RawDocument) -> List[Tuple[str, str]]:
        raise NotImplementedError

    def split_text(self, text: str) -> List[str]:
        spans = token_spans(text)
        if not spans:
            return []
        if len(spans) <= self.chunk_size:
            return [text[spans[0][0] : spans[-1][1]].strip()]

        step = self.chunk_size - self.chunk_overlap
        pieces: List[str] = []
        start = 0
        while start < len(spans):
            end = min(start + self.chunk_size, len(spans))
            piece = text[spans[start][0] : spans[end - 1][1]].strip()
            if piece:
                pieces.append(piece)
            if end >= len(spans):
                break
            start += step
        return pieces

    def chunk(self, document: RawDocument) -> List[Chunk]:
        chunks: List[Chunk] = []
        index = 0
        for section, section_text in self.sections(document):
            for piece in self.split_text(section_text):
                chunk = Chunk(
                    chunk_id=make_chunk_id(document.source_url, section, index),
                    source_url=document.source_url,
                    scheme=document.scheme,
                    section=section,
                    text=piece,
                    char_count=len(piece),
                    token_count=count_tokens(piece),
                )
                chunks.append(chunk)
                index += 1
        return chunks


class FixedChunker(BaseChunker):
    name = "fixed"

    def sections(self, document: RawDocument) -> List[Tuple[str, str]]:
        if not document.text.strip():
            return []
        return [("content", document.text)]


class HeadingChunker(BaseChunker):
    name = "heading"

    def sections(self, document: RawDocument) -> List[Tuple[str, str]]:
        return _sections_from_text(document)


class AutoChunker(BaseChunker):
    name = "auto"

    def choose(self, document: RawDocument) -> Tuple[BaseChunker, str]:
        boundaries = heading_boundaries(document)
        if len(boundaries) >= 3:
            rationale = (
                "Detected %d section headings; heading chunking keeps facts with "
                "their section labels." % len(boundaries)
            )
            return HeadingChunker(self.chunk_size, self.chunk_overlap), rationale
        rationale = (
            "Found %d reliable section headings; using fixed token windows."
            % len(boundaries)
        )
        return FixedChunker(self.chunk_size, self.chunk_overlap), rationale

    def sections(self, document: RawDocument) -> List[Tuple[str, str]]:
        return []

    def chunk(self, document: RawDocument) -> List[Chunk]:
        chunker, _ = self.choose(document)
        return chunker.chunk(document)


def _build_chunker(strategy: str, config: ChunkingConfig) -> BaseChunker:
    normalized = (strategy or config.strategy or "auto").lower()
    if normalized == "heading":
        return HeadingChunker(config.chunk_size, config.chunk_overlap)
    if normalized == "fixed":
        return FixedChunker(config.chunk_size, config.chunk_overlap)
    if normalized == "auto":
        return AutoChunker(config.chunk_size, config.chunk_overlap)
    raise ChunkingError(
        "unsupported chunking strategy %r; expected auto, heading, or fixed"
        % strategy
    )


def chunk_documents(
    documents: Sequence[RawDocument],
    config: ChunkingConfig,
    strategy: Optional[str] = None,
) -> Tuple[List[Chunk], Dict[str, Any]]:
    """Chunk documents and return chunks plus a strategy manifest."""
    requested = (strategy or config.strategy or "auto").lower()
    all_chunks: List[Chunk] = []
    per_page: Dict[str, Any] = {}
    strategies_used: List[str] = []

    for document in documents:
        chunker = _build_chunker(requested, config)
        if isinstance(chunker, AutoChunker):
            chosen, rationale = chunker.choose(document)
            chunker = chosen
        else:
            rationale = "Strategy explicitly requested."

        chunks = chunker.chunk(document)
        all_chunks.extend(chunks)

        slug = slug_from_url(document.source_url)
        per_page[slug] = {
            "source_url": document.source_url,
            "scheme": document.scheme,
            "strategy": chunker.name,
            "rationale": rationale,
            "chunks": len(chunks),
        }
        if chunker.name not in strategies_used:
            strategies_used.append(chunker.name)

    manifest: Dict[str, Any] = {
        "requested_strategy": requested,
        "strategy": strategies_used[0] if len(strategies_used) == 1 else "mixed",
        "strategies_used": strategies_used,
        "rationale": (
            "Per-page selection based on detected headings."
            if requested == "auto"
            else "Strategy explicitly requested."
        ),
        "params": {
            "chunk_size": config.chunk_size,
            "chunk_overlap": config.chunk_overlap,
        },
        "per_page": per_page,
        "total_chunks": len(all_chunks),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    return all_chunks, manifest


def run_chunking(
    settings: Settings,
    run_id: Optional[str] = None,
    artifacts_dir: Optional[Union[str, Path]] = None,
    writer: Optional[ArtifactWriter] = None,
    strategy: Optional[str] = None,
) -> ChunkResult:
    """Load a scraped run, chunk it, and persist chunk artifacts."""
    artifacts_root = Path(artifacts_dir or settings.ingestion.artifacts_dir)
    run_dir = artifacts_root / run_id if run_id else find_latest_run(artifacts_root)
    if not run_dir.is_dir():
        raise ChunkingError("Run directory does not exist: %s" % run_dir)

    documents, _ = load_run(run_dir)
    if not documents:
        raise ChunkingError("No documents to chunk in run %s" % run_dir.name)

    chunks, manifest = chunk_documents(documents, settings.chunking, strategy)

    writer = writer or ArtifactWriter(root=artifacts_root, run_id=run_dir.name)
    grouped: Dict[str, List[Chunk]] = {}
    for chunk in chunks:
        grouped.setdefault(chunk.source_url, []).append(chunk)

    for page in manifest["per_page"].values():
        page["artifact"] = "chunks/%s.jsonl" % slug_from_url(page["source_url"])

    for source_url, page_chunks in grouped.items():
        slug = slug_from_url(source_url)
        writer.save(
            "chunks",
            slug,
            [chunk.to_dict() for chunk in page_chunks],
            fmt="jsonl",
        )

    manifest_path = writer.save("chunks", "chunk_manifest", manifest)
    return ChunkResult(
        run_id=run_dir.name,
        run_dir=run_dir,
        chunks=chunks,
        manifest=manifest,
        manifest_path=manifest_path,
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m src.ingestion.chunker",
        description="Chunk loaded documents and persist chunk artifacts",
    )
    parser.add_argument("--run-id", help="run directory name; defaults to latest")
    parser.add_argument(
        "--artifacts-dir", help="override the configured artifacts directory"
    )
    parser.add_argument(
        "--strategy",
        choices=("auto", "heading", "fixed"),
        help="override the configured chunking strategy",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    settings = load_config()
    try:
        result = run_chunking(
            settings,
            run_id=args.run_id,
            artifacts_dir=args.artifacts_dir,
            strategy=args.strategy,
        )
    except (ChunkingError, FileNotFoundError) as exc:
        LOGGER.error("%s", exc)
        return 1

    LOGGER.info(
        "Created %d chunks from run %s using %s",
        len(result.chunks),
        result.run_id,
        result.manifest["strategy"],
    )
    LOGGER.info("Manifest: %s", result.manifest_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
