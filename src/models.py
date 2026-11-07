"""Dataclasses shared across the ingestion, retrieval, and generation stages."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass
class RawDocument:
    source_url: str
    page_title: str
    scheme: str
    category: str
    html: str
    text: str
    fetched_at: datetime
    http_status: int = 200
    extraction_warning: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_url": self.source_url,
            "page_title": self.page_title,
            "scheme": self.scheme,
            "category": self.category,
            "char_count": len(self.text),
            "fetched_at": self.fetched_at.isoformat(),
            "http_status": self.http_status,
            "extraction_warning": self.extraction_warning,
        }


@dataclass
class Chunk:
    chunk_id: str
    source_url: str
    scheme: str
    section: str
    text: str
    char_count: int
    token_count: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "source_url": self.source_url,
            "scheme": self.scheme,
            "section": self.section,
            "text": self.text,
            "char_count": self.char_count,
            "token_count": self.token_count,
        }


@dataclass
class Retrieved:
    chunk_id: str
    source_url: str
    scheme: str
    section: str
    text: str
    score: float
    fetched_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "source_url": self.source_url,
            "scheme": self.scheme,
            "section": self.section,
            "text": self.text,
            "score": self.score,
            "fetched_at": self.fetched_at,
        }


@dataclass
class Answer:
    text: str
    source_url: str
    last_updated: str
    refused: bool = False
    trace_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "source_url": self.source_url,
            "last_updated": self.last_updated,
            "refused": self.refused,
            "trace_id": self.trace_id,
        }
