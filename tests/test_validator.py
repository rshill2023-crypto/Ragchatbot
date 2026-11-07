"""Validator tests: sentence limit, citations, updated line, performance blocks."""

from __future__ import annotations

from src.config import load_config
from src.generation.validator import count_factual_sentences, validate, validate_answer

DATE = "2026-11-01T17:33:01.353216+00:00"


def make_settings():
    return load_config()


def fallback():
    settings = make_settings()
    return settings, settings.sources.allowlist[0]


def test_more_than_three_sentences_truncated():
    settings, url = fallback()
    out = validate("One. Two. Three. Four.", settings, fallback_url=url, fallback_date=DATE)

    assert count_factual_sentences(out.text) <= settings.llm.max_sentences
    assert "Four" not in out.text


def test_missing_citation_injected():
    settings, url = fallback()
    out = validate(
        "Expense ratio is 0.75%.", settings, fallback_url=url, fallback_date=DATE
    )

    assert url in out.text
    assert out.text.count("http") == 1
    assert "Last updated from sources: 2026-11-01" in out.text


def test_invalid_url_replaced():
    settings, url = fallback()
    out = validate(
        "Info. Source: https://evil.example.com",
        settings,
        fallback_url=url,
        fallback_date=DATE,
    )

    assert "evil.example.com" not in out.text
    assert url in out.text


def test_multiple_links_keep_one_allowlisted():
    settings, url = fallback()
    out = validate(
        "Info https://evil.example.com and %s" % url,
        settings,
        fallback_url=url,
        fallback_date=DATE,
    )

    assert out.text.count("http") == 1
    assert url in out.text
    assert "evil.example.com" not in out.text


def test_performance_sentence_blocked():
    settings, url = fallback()
    out = validate(
        "This fund gives 20% CAGR. Expense ratio is 0.75%.",
        settings,
        fallback_url=url,
        fallback_date=DATE,
    )

    assert "CAGR" not in out.text
    assert "Expense ratio is 0.75%" in out.text


def test_only_performance_content_gets_safe_body():
    settings, url = fallback()
    out = validate(
        "This fund returned 20% CAGR.",
        settings,
        fallback_url=url,
        fallback_date=DATE,
    )

    assert "CAGR" not in out.text
    assert "could not find a factual answer" in out.text.lower()
    assert out.text.count("http") == 1


def test_extra_note_counts_toward_sentence_limit():
    settings, url = fallback()
    out = validate_answer(
        "One. Two. Three. Four.",
        settings,
        fallback_url=url,
        fallback_date=DATE,
        extra_note="I cannot provide investment advice.",
    )

    assert "I cannot provide investment advice." in out.text
    assert count_factual_sentences(out.text) <= settings.llm.max_sentences


def test_last_updated_line_is_normalized_once():
    settings, url = fallback()
    out = validate(
        "Expense ratio is 0.75%.\nLast updated from sources: old date",
        settings,
        fallback_url=url,
        fallback_date=DATE,
    )

    assert out.text.count("Last updated from sources:") == 1
    assert "2026-11-01" in out.text
