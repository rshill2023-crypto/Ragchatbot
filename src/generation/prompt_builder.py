"""Grounded prompt construction for the facts-only answer contract."""

from __future__ import annotations

from typing import Sequence

from ..config import Settings
from ..models import Retrieved


def _date(value: str) -> str:
    text = (value or "").strip()
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]
    return text or "date unavailable"


def build_system_prompt(settings: Settings) -> str:
    max_sentences = settings.llm.max_sentences
    return (
        "You are a facts-only mutual fund FAQ assistant. "
        "Use ONLY the provided context. Never use outside knowledge. "
        "If the answer is not in the context, say you cannot find it in the "
        "provided sources and cite the closest official source.\n"
        "Rules:\n"
        "- Answer in at most %d sentences of factual content.\n"
        "- Include exactly ONE source link, copied from the context.\n"
        "- Never give investment advice, recommendations, opinions, predictions, "
        "or return/performance claims.\n"
        "- Do not mention CAGR, returns, annualised performance, or fund rankings.\n"
        "- End with exactly: Last updated from sources: <date>, using the date "
        "shown in the context.\n"
    ) % max_sentences


def build_prompt(
    query: str,
    chunks: Sequence[Retrieved],
    settings: Settings,
) -> str:
    lines = [
        "Question: %s" % (query or "").strip(),
        "",
        "Context:",
    ]
    for index, chunk in enumerate(chunks, start=1):
        text = " ".join((chunk.text or "").split())
        lines.extend(
            [
                "[%d] Scheme: %s" % (index, chunk.scheme),
                "Section: %s" % chunk.section,
                "Source: %s" % chunk.source_url,
                "Last updated: %s" % _date(chunk.fetched_at),
                "Text: %s" % text,
                "",
            ]
        )
    lines.append(
        "Return at most %d factual sentences, one official link from the context, "
        "and the Last updated line." % settings.llm.max_sentences
    )
    return "\n".join(lines).strip()


def build_messages(query: str, chunks: Sequence[Retrieved], settings: Settings):
    return [
        {"role": "system", "content": build_system_prompt(settings)},
        {"role": "user", "content": build_prompt(query, chunks, settings)},
    ]

