"""Pipeline orchestration for ingestion and grounded answering."""

from __future__ import annotations

import argparse
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Sequence

from .artifacts import ArtifactWriter
from .config import Settings, load_config
from .generation.llm import LLM, LLMError, build_llm, generate_with_retry
from .generation.prompt_builder import build_prompt, build_system_prompt
from .generation.validator import validate_answer
from .indexing.vector_store import run_store
from .ingestion.document_loader import find_latest_run
from .models import Answer, Retrieved
from .retrieval.retriever import Retriever, build_retriever
from .safety.intent import (
    ADVICE,
    EMPTY,
    FACTUAL,
    MIXED,
    OFF_TOPIC,
    TOO_LONG,
    classify_intent,
)
from .safety.pii import detect_pii
from .safety.templates import (
    advice_refusal,
    empty_refusal,
    latest_source_date,
    not_found_text,
    off_topic_refusal,
    official_link,
    pii_refusal,
    too_long_refusal,
)

LOGGER = logging.getLogger(__name__)
_SAFE_QUERY_ID = re.compile(r"^[A-Za-z0-9_.-]+$")
_STOPWORDS = {
    "the",
    "and",
    "for",
    "what",
    "when",
    "where",
    "which",
    "how",
    "can",
    "does",
    "with",
    "from",
    "this",
    "that",
    "are",
    "is",
    "of",
    "to",
    "in",
    "on",
    "a",
    "an",
}


def _query_id(value: Optional[str]) -> str:
    result = value or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    if not _SAFE_QUERY_ID.match(result):
        raise ValueError(
            "query_id may contain only letters, numbers, '.', '_', and '-'"
        )
    return result


def _make_writer(settings: Settings) -> ArtifactWriter:
    root = Path(settings.ingestion.artifacts_dir)
    run_dir = find_latest_run(root)
    return ArtifactWriter(root=root, run_id=run_dir.name)


def _save_guardrails(
    writer: ArtifactWriter,
    query_id: str,
    query: str,
    intent: str,
    decision: str,
    reason: str,
    pii_kind: Optional[str] = None,
) -> Path:
    payload = {
        "query_id": query_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "query": "[redacted]" if pii_kind else query,
        "intent": intent,
        "decision": decision,
        "reason": reason,
        "pii_detected": pii_kind is not None,
        "pii_kind": pii_kind,
    }
    return writer.save("guardrails", query_id, payload)


def _relative(path: Optional[Path], root: Path) -> Optional[str]:
    if path is None:
        return None
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


_FACT_TERMS = {
    "aum",
    "benchmark",
    "expense",
    "exit",
    "holding",
    "holdings",
    "load",
    "lock",
    "manager",
    "management",
    "minimum",
    "nav",
    "objective",
    "period",
    "rank",
    "rating",
    "ratio",
    "redeem",
    "redemption",
    "risk",
    "sip",
    "size",
    "stamp",
    "tax",
}


_VALUE_RE = re.compile(
    r"^\s*(?:[₹$€£]\s*)?[\d,.]+"
    r"(?:\s*%|\s*(?:cr|crore|lakh|lakhs))?\s*$",
    re.IGNORECASE,
)


def _value_like(segment: str) -> bool:
    return bool(_VALUE_RE.match(segment))


def _answer_segments(text: str) -> List[str]:
    return [
        segment.strip()
        for segment in re.split(
            r"(?<=[.!?])\s+(?=[A-Z0-9])|\n+", text or ""
        )
        if segment.strip()
    ]


def _segment_tokens(text: str) -> set:
    return set(re.findall(r"[a-z0-9]+", (text or "").lower()))


def extractive_answer(chunks: Sequence[Retrieved], query: str) -> str:
    """Build a grounded fallback answer when no LLM key/provider is available."""
    if not chunks:
        return not_found_text()

    terms = list(
        dict.fromkeys(
            term
            for term in re.findall(r"[a-z0-9]+", (query or "").lower())
            if len(term) > 2 and term not in _STOPWORDS
        )
    )
    focused = [term for term in terms if term in _FACT_TERMS]
    if focused:
        terms = focused
    if not terms:
        terms = ["fact"]

    source = chunks[0].source_url
    source_chunks = [chunk for chunk in chunks if chunk.source_url == source]
    scored = []
    for chunk_rank, chunk in enumerate(source_chunks or chunks):
        segments = _answer_segments(chunk.text)
        for index, segment in enumerate(segments):
            segment_tokens = _segment_tokens(segment)
            score = sum(1 for term in terms if term in segment_tokens)
            if not score:
                continue
            fact = segment
            if (
                index + 1 < len(segments)
                and not _value_like(segment)
                and _value_like(segments[index + 1])
            ):
                fact = segment + " " + segments[index + 1]
                score += 1
            if re.search(r"\d", fact):
                score += 1
            fact = re.sub(
                r"^Min\.\s+for\s+SIP\b", "Minimum SIP", fact, flags=re.IGNORECASE
            )
            section = " ".join((chunk.section or "").split())
            if (
                not re.search(r"\d", fact)
                and fact.casefold() == section.casefold()
            ):
                continue
            scored.append((score, chunk_rank, index, fact))

    scored.sort(key=lambda item: (-item[0], item[1], item[2]))
    chosen: List[str] = []
    for _, _, _, fact in scored:
        value = " ".join(fact.split())
        if not value or any(value.casefold() in existing.casefold() for existing in chosen):
            continue
        chosen.append(value)
        if len(chosen) == 2:
            break

    if not chosen:
        fallback = _answer_segments(chunks[0].text or "")[:3]
        chosen = [" ".join(segment.split()) for segment in fallback]
    if not chosen:
        return not_found_text()

    body = " ".join(chosen[:3])
    if body and body[-1] not in ".!?":
        body += "."
    return body


def answer(
    config: Settings,
    question: str,
    query_id: Optional[str] = None,
    llm: Optional[LLM] = None,
    retriever: Optional[Retriever] = None,
    writer: Optional[ArtifactWriter] = None,
) -> Answer:
    """Guard, retrieve, generate, validate, and persist a grounded answer."""
    raw_question = question or ""
    text = raw_question.strip()
    active_query_id = _query_id(query_id)
    active_writer = writer or _make_writer(config)

    if not text:
        result = empty_refusal(config, active_query_id)
        _save_guardrails(
            active_writer, active_query_id, "", EMPTY, "refuse", "empty query"
        )
        return result

    if config.guardrails.pii_block:
        pii = detect_pii(text)
        if pii is not None:
            result = pii_refusal(config, active_query_id)
            _save_guardrails(
                active_writer,
                active_query_id,
                text,
                "pii",
                "refuse",
                "sensitive information detected",
                pii_kind=pii.kind,
            )
            return result

    intent = classify_intent(text)
    if intent.label == TOO_LONG:
        result = too_long_refusal(config, active_query_id)
        _save_guardrails(
            active_writer,
            active_query_id,
            text,
            TOO_LONG,
            "refuse",
            intent.reason,
        )
        return result
    if intent.label == ADVICE:
        result = advice_refusal(config, active_query_id)
        _save_guardrails(
            active_writer, active_query_id, text, ADVICE, "refuse", intent.reason
        )
        return result
    if intent.label == OFF_TOPIC:
        result = off_topic_refusal(config, active_query_id)
        _save_guardrails(
            active_writer, active_query_id, text, OFF_TOPIC, "refuse", intent.reason
        )
        return result
    if intent.label not in (FACTUAL, MIXED):
        result = empty_refusal(config, active_query_id)
        _save_guardrails(
            active_writer, active_query_id, text, EMPTY, "refuse", intent.reason
        )
        return result

    active_retriever = retriever or build_retriever(config, writer=active_writer)
    retrieval = active_retriever.retrieve(text, query_id=active_query_id)
    top = retrieval.results[0] if retrieval.results else None
    fallback_date = top.fetched_at if top is not None else latest_source_date(config)

    if top is None:
        result = validate_answer(
            not_found_text(),
            config,
            fallback_url=official_link(config),
            fallback_date=fallback_date,
            trace_id=active_query_id,
        )
        active_writer.save(
            "responses",
            active_query_id,
            {
                "query_id": active_query_id,
                "query": text,
                "intent": intent.label,
                "provider": "none",
                "model": "",
                "latency_ms": 0,
                "raw_answer": not_found_text(),
                "answer": result.to_dict(),
                "error": None,
                "retrieval_trace": _relative(
                    getattr(retrieval, "trace_path", None), active_writer.run_dir
                ),
                "prompt_artifact": None,
            },
        )
        _save_guardrails(
            active_writer,
            active_query_id,
            text,
            intent.label,
            "not_found",
            "no chunks above min_score",
        )
        return result

    prompt = build_prompt(text, retrieval.results, config)
    prompt_path = active_writer.save(
        "prompts", active_query_id, prompt, fmt="text"
    )

    provider = "extractive"
    model = ""
    error: Optional[str] = None
    raw_answer: Optional[str] = None
    started = time.perf_counter()

    active_llm = llm
    if active_llm is None:
        try:
            active_llm = build_llm(config.llm)
        except LLMError as exc:
            error = str(exc)
            LOGGER.warning("LLM unavailable: %s", exc)

    if active_llm is not None:
        try:
            raw_answer = generate_with_retry(
                active_llm,
                build_system_prompt(config),
                prompt,
            )
            provider = getattr(active_llm, "name", "unknown")
            model = getattr(active_llm, "model", "")
        except Exception as exc:
            error = str(exc)
            LOGGER.warning("LLM failed; using extractive fallback: %s", exc)

    if raw_answer is None:
        raw_answer = extractive_answer(retrieval.results, text)

    latency_ms = int((time.perf_counter() - started) * 1000)
    extra_note = "I cannot provide investment advice." if intent.label == MIXED else None
    result = validate_answer(
        raw_answer,
        config,
        fallback_url=top.source_url,
        fallback_date=top.fetched_at,
        trace_id=active_query_id,
        extra_note=extra_note,
    )

    active_writer.save(
        "responses",
        active_query_id,
        {
            "query_id": active_query_id,
            "query": text,
            "intent": intent.label,
            "provider": provider,
            "model": model,
            "latency_ms": latency_ms,
            "raw_answer": raw_answer,
            "answer": result.to_dict(),
            "error": error,
            "retrieval_trace": _relative(
                getattr(retrieval, "trace_path", None), active_writer.run_dir
            ),
            "prompt_artifact": _relative(prompt_path, active_writer.run_dir),
        },
    )
    _save_guardrails(
        active_writer,
        active_query_id,
        text,
        intent.label,
        "answer_factual_refuse_advice" if intent.label == MIXED else "answer",
        intent.reason,
    )
    return result


def ingest(config: Settings) -> str:
    """Run the full offline pipeline: scrape -> load -> chunk -> embed -> store."""
    from .indexing.embedder import run_embedding
    from .ingestion.chunker import run_chunking
    from .ingestion.document_loader import load_documents
    from .ingestion.loader import scrape

    scrape_result = scrape(config)
    run_id = scrape_result.run_id
    LOGGER.info("Scraped run %s", run_id)

    load_documents(config, run_id=run_id)
    run_chunking(config, run_id=run_id)
    run_embedding(config, run_id=run_id)
    run_store(config, run_id=run_id, rebuild=True)
    LOGGER.info("Ingestion complete for run %s", run_id)
    return run_id


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m src.pipeline",
        description="Groww MF FAQ assistant pipeline",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("ingest", help="run the offline ingestion pipeline")

    ask_parser = subparsers.add_parser("ask", help="ask a factual question")
    ask_parser.add_argument("question", help="question text")
    ask_parser.add_argument("--query-id", help="deterministic trace id")

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    settings = load_config()

    if args.command == "ingest":
        run_id = ingest(settings)
        print("Ingested run: %s" % run_id)
        return 0

    result = answer(settings, args.question, query_id=args.query_id)
    print(result.text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
