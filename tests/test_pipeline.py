"""Generation and pipeline tests (Phase 7/8) using fake LLM and retriever."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from src.artifacts import ArtifactWriter
from src.config import load_config
from src.generation.llm import LLMError, build_llm
from src.generation.prompt_builder import build_prompt, build_system_prompt
from src.models import Retrieved
from src.pipeline import answer, extractive_answer
from src.retrieval.retriever import RetrievalResult

DATE = "2026-11-01T17:33:03.530416+00:00"


def make_settings(tmp_path):
    settings = load_config()
    return replace(
        settings,
        ingestion=replace(settings.ingestion, artifacts_dir=str(tmp_path)),
    )


def make_writer(tmp_path):
    run_dir = tmp_path / "run-1"
    (run_dir / "raw").mkdir(parents=True)
    (run_dir / "raw" / "manifest.json").write_text("[]", encoding="utf-8")
    return ArtifactWriter(root=tmp_path, run_id="run-1")


def make_hit(text="The ELSS lock-in period is three years.", section="ELSS"):
    settings = load_config()
    return Retrieved(
        chunk_id="chunk-1",
        source_url=settings.sources.allowlist[3],
        scheme="HDFC ELSS Tax Saver Fund",
        section=section,
        text=text,
        score=0.9,
        fetched_at=DATE,
    )


class FakeLLM:
    name = "fake"
    model = "fake-model"

    def __init__(self, output=None, fail=False):
        self.output = output
        self.fail = fail
        self.calls = []

    def generate(self, system_prompt, user_prompt):
        self.calls.append((system_prompt, user_prompt))
        if self.fail:
            raise RuntimeError("provider unavailable")
        return self.output


class FakeRetriever:
    def __init__(self, results, trace_path=None):
        self.results = list(results)
        self.trace_path = trace_path
        self.calls = []

    def retrieve(self, query, query_id=None):
        self.calls.append((query, query_id))
        return RetrievalResult(
            query_id=query_id or "generated",
            query=query,
            results=self.results,
            candidates=self.results,
            trace_path=self.trace_path or Path("/tmp/retrieval.json"),
        )


def test_factual_answer_is_grounded_and_artifacts_written(tmp_path):
    hit = make_hit()
    raw = "The ELSS lock-in period is three years. Source: %s" % hit.source_url
    llm = FakeLLM(raw)
    retriever = FakeRetriever([hit])
    writer = make_writer(tmp_path)

    result = answer(
        make_settings(tmp_path),
        "What is the ELSS lock-in period?",
        query_id="q1",
        llm=llm,
        retriever=retriever,
        writer=writer,
    )

    assert result.refused is False
    assert "three years" in result.text
    assert result.text.count("http") == 1
    assert "Last updated from sources: 2026-11-01" in result.text
    assert result.source_url == hit.source_url
    assert len(llm.calls) == 1
    assert retriever.calls == [("What is the ELSS lock-in period?", "q1")]

    run_dir = tmp_path / "run-1"
    assert (run_dir / "prompts" / "q1.txt").is_file()
    response = json.loads((run_dir / "responses" / "q1.json").read_text())
    assert response["provider"] == "fake"
    assert response["intent"] == "factual"
    guardrails = json.loads((run_dir / "guardrails" / "q1.json").read_text())
    assert guardrails["decision"] == "answer"


def test_llm_failure_uses_extractive_fallback(tmp_path):
    hit = make_hit()
    llm = FakeLLM(fail=True)
    writer = make_writer(tmp_path)

    result = answer(
        make_settings(tmp_path),
        "What is the ELSS lock-in period?",
        query_id="fallback",
        llm=llm,
        retriever=FakeRetriever([hit]),
        writer=writer,
    )

    assert "lock-in" in result.text.lower()
    response = json.loads(
        (tmp_path / "run-1" / "responses" / "fallback.json").read_text()
    )
    assert response["provider"] == "extractive"
    assert response["error"]


def test_advice_query_is_refused_without_retrieval(tmp_path):
    retriever = FakeRetriever([make_hit()])
    result = answer(
        make_settings(tmp_path),
        "Should I buy HDFC Flexi Cap?",
        query_id="advice",
        retriever=retriever,
        writer=make_writer(tmp_path),
    )

    assert result.refused is True
    assert "advice" in result.text.lower() or "factual" in result.text.lower()
    assert result.text.count("http") == 1
    assert retriever.calls == []


def test_pii_is_rejected_and_never_written(tmp_path):
    pii_value = "ABCDE1234F"
    retriever = FakeRetriever([make_hit()])
    result = answer(
        make_settings(tmp_path),
        "My PAN is %s, what is the expense ratio?" % pii_value,
        query_id="pii",
        retriever=retriever,
        writer=make_writer(tmp_path),
    )

    assert result.refused is True
    assert pii_value not in result.text
    assert retriever.calls == []
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert pii_value not in path.read_text(encoding="utf-8", errors="ignore")


def test_off_topic_is_refused(tmp_path):
    retriever = FakeRetriever([make_hit()])
    result = answer(
        make_settings(tmp_path),
        "What's the weather today?",
        query_id="off-topic",
        retriever=retriever,
        writer=make_writer(tmp_path),
    )

    assert result.refused is True
    assert "mutual fund" in result.text.lower()
    assert retriever.calls == []


def test_empty_query_is_refused(tmp_path):
    retriever = FakeRetriever([make_hit()])
    result = answer(
        make_settings(tmp_path),
        "   ",
        query_id="empty",
        retriever=retriever,
        writer=make_writer(tmp_path),
    )

    assert result.refused is True
    assert retriever.calls == []


def test_mixed_query_answers_fact_and_refuses_advice(tmp_path):
    hit = make_hit("The exit load is 1% within one year.", "Exit Load")
    llm = FakeLLM("The exit load is 1% within one year.")
    result = answer(
        make_settings(tmp_path),
        "What is the exit load? Also should I buy?",
        query_id="mixed",
        llm=llm,
        retriever=FakeRetriever([hit]),
        writer=make_writer(tmp_path),
    )

    assert result.refused is False
    assert "exit load" in result.text.lower()
    assert "cannot provide investment advice" in result.text.lower()


def test_no_retrieved_chunks_returns_limited_answer(tmp_path):
    result = answer(
        make_settings(tmp_path),
        "What is the expense ratio of HDFC Small Cap?",
        query_id="not-found",
        retriever=FakeRetriever([]),
        writer=make_writer(tmp_path),
    )

    assert result.refused is False
    assert "could not find" in result.text.lower()
    assert result.text.count("http") == 1
    assert "Last updated from sources:" in result.text


def test_extractive_answer_prefers_query_terms():
    hit = make_hit(
        "HDFC ELSS Tax Saver Fund\nELSS • 3Y Lock-in\nEquity\nVery High Risk"
    )
    output = extractive_answer([hit], "What is the ELSS lock-in period?")
    assert "lock-in" in output.lower()


def test_prompt_contains_rules_and_numbered_context():
    settings = load_config()
    hit = make_hit()
    system_prompt = build_system_prompt(settings)
    user_prompt = build_prompt("ELSS lock-in?", [hit], settings)

    assert "exactly ONE source link" in system_prompt
    assert "Never give investment advice" in system_prompt
    assert "Last updated from sources:" in system_prompt
    assert "[1] Scheme: HDFC ELSS Tax Saver Fund" in user_prompt
    assert hit.source_url in user_prompt
    assert "2026-11-01" in user_prompt


def test_build_llm_requires_groq_key(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(LLMError):
        build_llm(load_config().llm)


def test_build_llm_rejects_unknown_provider():
    settings = load_config()
    with pytest.raises(LLMError):
        build_llm(replace(settings.llm, provider="unknown"))
