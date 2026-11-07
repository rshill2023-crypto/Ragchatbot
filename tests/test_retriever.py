"""Retrieval tests (Phase 7): embedding query, filtering, trace artifacts."""

from __future__ import annotations

import json
import re
from dataclasses import replace

import pytest

from src.artifacts import ArtifactWriter
from src.config import load_config
from src.models import Retrieved
from src.retrieval.retriever import RetrievalError, Retriever, build_retriever

URL = "https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth"


def make_hit(chunk_id, score, section="ELSS"):
    return Retrieved(
        chunk_id=chunk_id,
        source_url=URL,
        scheme="HDFC ELSS Tax Saver Fund",
        section=section,
        text="ELSS has a 3-year lock-in.",
        score=score,
    )


def make_scheme_hit(chunk_id, score, scheme, section, text):
    return Retrieved(
        chunk_id=chunk_id,
        source_url=URL,
        scheme=scheme,
        section=section,
        text=text,
        score=score,
    )


class FakeEmbedder:
    model_name = "fake-embedder"

    def __init__(self):
        self.calls = []

    def encode(self, texts):
        self.calls.append(list(texts))
        return [[1.0, 0.0, 0.0] for _ in texts]


class FakeStore:
    collection_name = "fake_collection"
    distance = "cosine"

    def __init__(self, hits):
        self.hits = list(hits)
        self.calls = []

    def query(self, query_embedding, top_k=5):
        self.calls.append((list(query_embedding), top_k))
        return self.hits[:top_k]


def make_settings(tmp_path, top_k=5, min_score=0.2):
    settings = load_config()
    return replace(
        settings,
        ingestion=replace(settings.ingestion, artifacts_dir=str(tmp_path)),
        retrieval=replace(
            settings.retrieval, top_k=top_k, min_score=min_score
        ),
    )


def test_retrieve_filters_scores_sorts_and_writes_trace(tmp_path):
    hits = [
        make_hit("weak", 0.10),
        make_hit("strong", 0.90),
        make_hit("medium", 0.50),
    ]
    embedder = FakeEmbedder()
    store = FakeStore(hits)
    writer = ArtifactWriter(root=tmp_path, run_id="run-1")
    retriever = Retriever(
        make_settings(tmp_path, top_k=3, min_score=0.2),
        embedder=embedder,
        store=store,
        writer=writer,
    )

    result = retriever.retrieve("What is the ELSS lock-in period?", "q1")

    assert embedder.calls == [["What is the ELSS lock-in period?"]]
    assert store.calls == [([1.0, 0.0, 0.0], 50)]
    assert [hit.chunk_id for hit in result.results] == ["strong", "medium"]
    assert [hit.chunk_id for hit in result.candidates] == ["strong", "medium", "weak"]

    trace_path = tmp_path / "run-1" / "retrieval" / "q1.json"
    assert result.trace_path == trace_path
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    assert trace["query_id"] == "q1"
    assert trace["query"] == "What is the ELSS lock-in period?"
    assert trace["model"] == "fake-embedder"
    assert trace["collection"] == "fake_collection"
    assert trace["top_k"] == 3
    assert trace["min_score"] == 0.2
    assert trace["candidate_count"] == 3
    assert trace["result_count"] == 2
    assert [item["chunk_id"] for item in trace["results"]] == ["strong", "medium"]
    assert trace["results"][0]["source_url"] == URL


def test_scheme_filter_and_aspect_terms_promote_the_fact_chunk(tmp_path):
    hits = [
        make_scheme_hit(
            "flexi-title",
            0.70,
            "HDFC Flexi Cap Fund",
            "HDFC Flexi Cap Direct Plan Growth",
            "HDFC Flexi Cap Direct Plan Growth\nEquity\nFlexi Cap",
        ),
        make_scheme_hit(
            "flexi-expense",
            0.45,
            "HDFC Flexi Cap Fund",
            "Expense ratio",
            "Expense ratio\n0.75%\nRating\n5",
        ),
        make_scheme_hit(
            "large-expense",
            0.55,
            "HDFC Large Cap Fund",
            "Expense ratio",
            "Expense ratio\n1.02%",
        ),
    ]
    retriever = Retriever(
        make_settings(tmp_path, top_k=2, min_score=0.2),
        embedder=FakeEmbedder(),
        store=FakeStore(hits),
        writer=ArtifactWriter(root=tmp_path, run_id="run-1"),
    )

    result = retriever.retrieve(
        "What is the expense ratio of HDFC Flexi Cap?", "rerank"
    )

    assert [hit.chunk_id for hit in result.results] == [
        "flexi-expense",
        "flexi-title",
    ]
    assert all(hit.scheme == "HDFC Flexi Cap Fund" for hit in result.results)
    trace = json.loads(result.trace_path.read_text(encoding="utf-8"))
    assert trace["scheme_filter"] == "HDFC Flexi Cap Fund"
    assert "expense" in trace["aspect_terms"]


def test_all_candidates_below_min_score(tmp_path):
    retriever = Retriever(
        make_settings(tmp_path, min_score=0.8),
        embedder=FakeEmbedder(),
        store=FakeStore([make_hit("a", 0.7), make_hit("b", 0.6)]),
        writer=ArtifactWriter(root=tmp_path, run_id="run-1"),
    )

    result = retriever.retrieve("expense ratio", "low-scores")

    assert result.results == []
    assert len(result.candidates) == 2
    trace = json.loads(result.trace_path.read_text(encoding="utf-8"))
    assert trace["result_count"] == 0
    assert trace["candidate_count"] == 2


def test_empty_query_raises_before_embedding(tmp_path):
    embedder = FakeEmbedder()
    retriever = Retriever(
        make_settings(tmp_path),
        embedder=embedder,
        store=FakeStore([]),
        writer=ArtifactWriter(root=tmp_path, run_id="run-1"),
    )

    with pytest.raises(RetrievalError):
        retriever.retrieve("   ", "empty")
    assert embedder.calls == []


def test_invalid_query_id_raises(tmp_path):
    retriever = Retriever(
        make_settings(tmp_path),
        embedder=FakeEmbedder(),
        store=FakeStore([]),
        writer=ArtifactWriter(root=tmp_path, run_id="run-1"),
    )

    with pytest.raises(RetrievalError):
        retriever.retrieve("expense ratio", "../../escape")


def test_default_query_id_is_generated(tmp_path):
    retriever = Retriever(
        make_settings(tmp_path),
        embedder=FakeEmbedder(),
        store=FakeStore([make_hit("a", 0.9)]),
        writer=ArtifactWriter(root=tmp_path, run_id="run-1"),
    )

    result = retriever.retrieve("expense ratio")

    assert re.match(r"^[A-Za-z0-9_.-]+$", result.query_id)
    assert result.trace_path.name == result.query_id + ".json"
    assert result.trace_path.is_file()


def test_trace_uses_latest_run_when_writer_not_given(tmp_path):
    for run_id in ("20261101T100000Z", "20261101T110000Z"):
        (tmp_path / run_id / "raw").mkdir(parents=True)
        (tmp_path / run_id / "raw" / "manifest.json").write_text("[]")

    retriever = Retriever(
        make_settings(tmp_path),
        embedder=FakeEmbedder(),
        store=FakeStore([make_hit("a", 0.9)]),
    )

    result = retriever.retrieve("expense ratio", "latest-run-test")

    assert result.trace_path == (
        tmp_path / "20261101T110000Z" / "retrieval" / "latest-run-test.json"
    )


def test_build_retriever_uses_supplied_components(tmp_path):
    embedder = FakeEmbedder()
    store = FakeStore([])
    retriever = build_retriever(make_settings(tmp_path), embedder=embedder, store=store)

    assert retriever.embedder is embedder
    assert retriever.store is store
