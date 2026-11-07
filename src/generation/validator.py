"""Answer validation: sentence limit, one allowlisted citation, updated line.

The validator is deliberately conservative: it strips all URLs from the model
output, keeps at most one allowlisted source, removes performance sentences, and
rebuilds the final display text with exactly one citation and one updated line.
"""

from __future__ import annotations

import re
from typing import List, Optional, Sequence

from ..config import Settings
from ..models import Answer

_URL_RE = re.compile(r"https?://[^\s<>\"')\]]+")
_META_LINE_RE = re.compile(
    r"(?im)^\s*(?:source|last updated from sources)\s*:.*$"
)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_PERFORMANCE_RE = re.compile(
    r"\b(?:cagr|returns?|annuali[sz]ed|outperform\w*|multibagger|profit|"
    r"gains?|performance)\b",
    re.IGNORECASE,
)


def split_sentences(text: str) -> List[str]:
    value = re.sub(r"\s+", " ", (text or "").strip())
    if not value:
        return []
    return [part.strip() for part in _SENTENCE_SPLIT_RE.split(value) if part.strip()]


def _clean_text(raw: str) -> str:
    text = _META_LINE_RE.sub(" ", raw or "")
    text = _URL_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _normalise_date(value: str) -> str:
    text = (value or "").strip()
    match = re.search(r"\d{4}-\d{2}-\d{2}", text)
    if match:
        return match.group(0)
    return text or "date unavailable"


def _choose_source(
    raw: str,
    settings: Settings,
    fallback_url: Optional[str],
) -> str:
    allowlist = list(settings.sources.allowlist)
    allowed = set(allowlist)
    found = [match.rstrip(".,;:") for match in _URL_RE.findall(raw or "")]
    for url in found:
        if url in allowed:
            return url
    if fallback_url and fallback_url in allowed:
        return fallback_url
    return allowlist[0] if allowlist else (fallback_url or "")


def _limit_sentences(sentences: Sequence[str], limit: int) -> List[str]:
    if limit < 0:
        limit = 0
    return list(sentences[:limit])


def validate_answer(
    raw_answer: str,
    settings: Settings,
    fallback_url: Optional[str] = None,
    fallback_date: str = "",
    trace_id: str = "",
    extra_note: Optional[str] = None,
) -> Answer:
    source_url = _choose_source(raw_answer, settings, fallback_url)
    last_updated = _normalise_date(fallback_date)

    cleaned = _clean_text(raw_answer)
    sentences = [
        sentence
        for sentence in split_sentences(cleaned)
        if not _PERFORMANCE_RE.search(sentence)
    ]

    limit = settings.llm.max_sentences
    if extra_note:
        limit = max(limit - 1, 0)
    sentences = _limit_sentences(sentences, limit)
    if extra_note:
        sentences.append(extra_note)

    body = " ".join(sentence.strip() for sentence in sentences if sentence.strip())
    if not body:
        body = (
            "I could not find a factual answer without performance claims in the "
            "provided sources."
        )

    parts = [body]
    if source_url:
        parts.append("Source: %s" % source_url)
    parts.append("Last updated from sources: %s" % last_updated)
    text = "\n\n".join(parts)

    return Answer(
        text=text,
        source_url=source_url,
        last_updated=last_updated,
        refused=False,
        trace_id=trace_id,
    )


def validate(
    raw_answer: str,
    settings: Settings,
    fallback_url: Optional[str] = None,
    fallback_date: str = "",
) -> Answer:
    return validate_answer(
        raw_answer,
        settings,
        fallback_url=fallback_url,
        fallback_date=fallback_date,
    )


def count_factual_sentences(text: str) -> int:
    body = text.split("\n\nSource:", 1)[0]
    return len(split_sentences(body))
