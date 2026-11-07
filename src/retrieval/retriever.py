"""Query retrieval over the Chroma vector store.

Phase 7 embeds the question with the same model used during ingestion, asks
Chroma for the top-k nearest chunks, drops results below `min_score`, and
writes an inspectable trace to `retrieval/<query_id>.json`.
"""

from __future__ import annotations

import argparse
import logging
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from ..artifacts import ArtifactWriter
from ..config import Settings, load_config
from ..indexing.embedder import Embedder, build_embedder
from ..indexing.vector_store import ChromaVectorStore, build_vector_store
from ..ingestion.document_loader import find_latest_run
from ..models import Retrieved

LOGGER = logging.getLogger(__name__)
_SAFE_QUERY_ID = re.compile(r"^[A-Za-z0-9_.-]+$")
_WORD = re.compile(r"[a-z0-9]+")

_STOPWORDS = {
    "about",
    "an",
    "and",
    "are",
    "at",
    "be",
    "by",
    "can",
    "could",
    "did",
    "do",
    "does",
    "for",
    "from",
    "fund",
    "funds",
    "hdfc",
    "how",
    "i",
    "in",
    "is",
    "it",
    "me",
    "mutual",
    "my",
    "of",
    "on",
    "or",
    "please",
    "scheme",
    "should",
    "tell",
    "that",
    "the",
    "their",
    "there",
    "these",
    "this",
    "those",
    "to",
    "was",
    "were",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "will",
    "with",
    "would",
    "you",
    "your",
}

_ASPECT_TERMS = {
    "aum",
    "benchmark",
    "capital",
    "category",
    "duty",
    "email",
    "exit",
    "expense",
    "gain",
    "gains",
    "holding",
    "holdings",
    "incorporation",
    "inception",
    "launch",
    "load",
    "lock",
    "lump",
    "manager",
    "management",
    "min",
    "minimum",
    "nav",
    "objective",
    "period",
    "phone",
    "rank",
    "rating",
    "ratio",
    "redeem",
    "redemption",
    "risk",
    "sip",
    "size",
    "stamp",
    "statement",
    "sum",
    "tax",
    "website",
}

_SCHEME_STOPWORDS = {
    "and",
    "direct",
    "fund",
    "funds",
    "growth",
    "hdfc",
    "mutual",
    "plan",
    "saver",
    "tax",
    "the",
}


def _tokens(text: str) -> List[str]:
    return _WORD.findall((text or "").lower())


def _content_terms(text: str) -> List[str]:
    return [
        token
        for token in _tokens(text)
        if len(token) > 2 and token not in _STOPWORDS
    ]


def _haystack(hit: Retrieved) -> str:
    return " ".join(
        value for value in (hit.scheme, hit.section, hit.text) if value
    ).lower()


def _select_target_scheme(
    query: str, candidates: Sequence[Retrieved]
) -> Optional[str]:
    query_tokens = set(_tokens(query))
    scores: Dict[str, int] = {}
    for hit in candidates:
        scheme = (hit.scheme or "").strip()
        if not scheme:
            continue
        distinctive = {
            token
            for token in _tokens(scheme)
            if len(token) > 2 and token not in _SCHEME_STOPWORDS
        }
        score = len(distinctive & query_tokens)
        if score:
            scores[scheme] = max(scores.get(scheme, 0), score)

    if not scores:
        return None
    best_score = max(scores.values())
    best = [scheme for scheme, score in scores.items() if score == best_score]
    return best[0] if len(best) == 1 else None


def _rank_candidates(
    query: str,
    candidates: Sequence[Retrieved],
    scheme_filter: Optional[str],
) -> "tuple[List[Retrieved], List[str]]":
    pool = [
        hit
        for hit in candidates
        if scheme_filter is None or hit.scheme == scheme_filter
    ]
    if not pool:
        pool = list(candidates)

    terms = list(dict.fromkeys(_content_terms(query)))
    focused = [term for term in terms if term in _ASPECT_TERMS]
    if focused:
        terms = focused
    if not terms:
        return sorted(pool, key=lambda hit: hit.score, reverse=True), []

    token_sets = {id(hit): set(_tokens(_haystack(hit))) for hit in pool}
    document_frequency = {
        term: sum(1 for hit in pool if term in token_sets[id(hit)])
        for term in terms
    }
    idf = {
        term: math.log((len(pool) + 1) / (document_frequency[term] + 1)) + 1.0
        for term in terms
    }

    def rank_score(hit: Retrieved) -> float:
        tokens = token_sets[id(hit)]
        lexical = sum(idf[term] for term in terms if term in tokens)
        return hit.score + 0.15 * lexical

    return sorted(pool, key=rank_score, reverse=True), terms


class RetrievalError(RuntimeError):
    """Raised when a query cannot be retrieved."""


@dataclass
class RetrievalResult:
    query_id: str
    query: str
    results: List[Retrieved]
    candidates: List[Retrieved]
    trace_path: Path


class Retriever:
    """Embed a query, retrieve top-k chunks, and filter by score."""

    def __init__(
        self,
        settings: Settings,
        embedder: Optional[Embedder] = None,
        store: Optional[ChromaVectorStore] = None,
        writer: Optional[ArtifactWriter] = None,
    ) -> None:
        self.settings = settings
        self.embedder = embedder or build_embedder(settings.embedding)
        self.store = store or build_vector_store(settings.vector_db)
        self.writer = writer

    def _writer_for_trace(self) -> ArtifactWriter:
        if self.writer is not None:
            return self.writer
        artifacts_root = Path(self.settings.ingestion.artifacts_dir)
        run_dir = find_latest_run(artifacts_root)
        return ArtifactWriter(root=artifacts_root, run_id=run_dir.name)

    def retrieve(
        self,
        query: str,
        query_id: Optional[str] = None,
    ) -> RetrievalResult:
        text = (query or "").strip()
        if not text:
            raise RetrievalError("Query must not be empty")

        active_query_id = query_id or datetime.now(timezone.utc).strftime(
            "%Y%m%dT%H%M%S%fZ"
        )
        if not _SAFE_QUERY_ID.match(active_query_id):
            raise RetrievalError(
                "query_id may contain only letters, numbers, '.', '_', and '-'"
            )

        vectors = self.embedder.encode([text])
        if len(vectors) != 1:
            raise RetrievalError(
                "Embedder returned %d vectors for one query" % len(vectors)
            )

        top_k = self.settings.retrieval.top_k
        candidate_k = max(top_k, self.settings.retrieval.candidate_k)
        min_score = self.settings.retrieval.min_score
        candidates = self.store.query(vectors[0], top_k=candidate_k)
        candidates = sorted(candidates, key=lambda hit: hit.score, reverse=True)
        scheme_filter = _select_target_scheme(text, candidates)
        ranked, aspect_terms = _rank_candidates(text, candidates, scheme_filter)
        results = [hit for hit in ranked if hit.score >= min_score][:top_k]

        writer = self._writer_for_trace()
        trace = {
            "query_id": active_query_id,
            "query": text,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "model": self.embedder.model_name,
            "collection": self.store.collection_name,
            "distance": self.store.distance,
            "top_k": top_k,
            "candidate_k": candidate_k,
            "min_score": min_score,
            "scheme_filter": scheme_filter,
            "aspect_terms": aspect_terms,
            "candidate_count": len(candidates),
            "result_count": len(results),
            "candidates": [self._hit_dict(hit) for hit in candidates],
            "results": [self._hit_dict(hit) for hit in results],
        }
        trace_path = writer.save("retrieval", active_query_id, trace)

        LOGGER.info(
            "Query %s: %d candidates, %d above min_score %.3f",
            active_query_id,
            len(candidates),
            len(results),
            min_score,
        )
        return RetrievalResult(
            query_id=active_query_id,
            query=text,
            results=results,
            candidates=candidates,
            trace_path=trace_path,
        )

    @staticmethod
    def _hit_dict(hit: Retrieved):
        return {
            "chunk_id": hit.chunk_id,
            "score": hit.score,
            "source_url": hit.source_url,
            "scheme": hit.scheme,
            "section": hit.section,
            "fetched_at": hit.fetched_at,
        }


def build_retriever(
    settings: Settings,
    embedder: Optional[Embedder] = None,
    store: Optional[ChromaVectorStore] = None,
    writer: Optional[ArtifactWriter] = None,
) -> Retriever:
    return Retriever(
        settings=settings,
        embedder=embedder,
        store=store,
        writer=writer,
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m src.retrieval.retriever",
        description="Retrieve top-k chunks for a factual question",
    )
    parser.add_argument("query", help="factual question")
    parser.add_argument("--query-id", help="deterministic trace id")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    try:
        result = build_retriever(load_config()).retrieve(
            args.query, query_id=args.query_id
        )
    except (RetrievalError, FileNotFoundError) as exc:
        LOGGER.error("%s", exc)
        return 1

    print("Query: %s" % result.query)
    print("Results: %d" % len(result.results))
    for hit in result.results:
        print(
            "  %.4f | %s | %s | %s"
            % (hit.score, hit.scheme, hit.section, hit.source_url)
        )
    print("Trace: %s" % result.trace_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
