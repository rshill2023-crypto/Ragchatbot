"""Loading stage tests (Phase 3): read scraped artifacts into RawDocument."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import timezone

import pytest

from src.config import load_config
from src.ingestion.document_loader import (
    DocumentLoadError,
    find_latest_run,
    load_documents,
    load_run,
)

LARGE_CAP_URL = "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth"
ELSS_URL = "https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth"
LARGE_CAP_SLUG = "hdfc-large-cap-fund-direct-growth"
ELSS_SLUG = "hdfc-elss-tax-saver-fund-direct-plan-growth"


def make_settings(artifacts_dir):
    settings = load_config()
    return replace(
        settings,
        ingestion=replace(settings.ingestion, artifacts_dir=str(artifacts_dir)),
    )


def write_page(run_dir, slug, text="The expense ratio is 0.75%."):
    (run_dir / "raw" / "html").mkdir(parents=True, exist_ok=True)
    (run_dir / "raw" / "text").mkdir(parents=True, exist_ok=True)
    (run_dir / "raw" / "html" / (slug + ".html")).write_text(
        "<html><body><main>%s</main></body></html>" % text, encoding="utf-8"
    )
    (run_dir / "raw" / "text" / (slug + ".txt")).write_text(text, encoding="utf-8")


def write_manifest(run_dir, entries):
    (run_dir / "raw").mkdir(parents=True, exist_ok=True)
    (run_dir / "raw" / "manifest.json").write_text(
        json.dumps(entries), encoding="utf-8"
    )


def ok_entry(url, slug, title, category="large_cap", scheme="HDFC Large Cap Fund"):
    return {
        "source_url": url,
        "page_title": title,
        "scheme": scheme,
        "category": category,
        "fetched_at": "2026-11-01T12:00:00+00:00",
        "http_status": 200,
        "char_count": 31,
        "extraction_warning": None,
        "status": "ok",
        "artifacts": {
            "html": "raw/html/%s.html" % slug,
            "text": "raw/text/%s.txt" % slug,
        },
    }


def test_load_documents_reads_artifacts_and_writes_loaded_output(tmp_path):
    run_dir = tmp_path / "run-1"
    write_page(run_dir, LARGE_CAP_SLUG)
    write_manifest(run_dir, [ok_entry(LARGE_CAP_URL, LARGE_CAP_SLUG, "Large Cap")])

    result = load_documents(make_settings(tmp_path), run_id="run-1")

    assert result.run_id == "run-1"
    assert len(result.documents) == 1
    document = result.documents[0]
    assert document.source_url == LARGE_CAP_URL
    assert document.page_title == "Large Cap"
    assert document.scheme == "HDFC Large Cap Fund"
    assert document.category == "large_cap"
    assert "0.75%" in document.text
    assert "<main>" in document.html
    assert document.fetched_at.tzinfo == timezone.utc

    documents_path = run_dir / "loaded" / "documents.jsonl"
    assert documents_path.exists()
    records = [
        json.loads(line)
        for line in documents_path.read_text(encoding="utf-8").splitlines()
    ]
    assert records[0]["source_url"] == LARGE_CAP_URL
    assert "text" in records[0]

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["document_count"] == 1
    assert manifest["loaded"] == 1
    assert manifest["errors"] == 0


def test_find_latest_run_and_load_default(tmp_path):
    first = tmp_path / "20261101T100000Z"
    second = tmp_path / "20261101T110000Z"
    write_page(first, LARGE_CAP_SLUG)
    write_manifest(first, [ok_entry(LARGE_CAP_URL, LARGE_CAP_SLUG, "Old")])
    write_page(second, ELSS_SLUG, "ELSS has a 3 year lock-in.")
    write_manifest(
        second,
        [
            ok_entry(
                ELSS_URL,
                ELSS_SLUG,
                "New",
                category="elss",
                scheme="HDFC ELSS Tax Saver Fund",
            )
        ],
    )

    assert find_latest_run(tmp_path) == second

    result = load_documents(make_settings(tmp_path))
    assert result.run_id == second.name
    assert result.documents[0].page_title == "New"


def test_artifact_paths_fallback_when_mapping_absent(tmp_path):
    run_dir = tmp_path / "run-1"
    write_page(run_dir, LARGE_CAP_SLUG)
    entry = ok_entry(LARGE_CAP_URL, LARGE_CAP_SLUG, "Large Cap")
    entry.pop("artifacts")
    write_manifest(run_dir, [entry])

    result = load_documents(make_settings(tmp_path), run_id="run-1")
    assert len(result.documents) == 1


def test_missing_artifact_is_reported(tmp_path):
    run_dir = tmp_path / "run-1"
    write_manifest(run_dir, [ok_entry(LARGE_CAP_URL, LARGE_CAP_SLUG, "Large Cap")])

    result = load_documents(make_settings(tmp_path), run_id="run-1")

    assert result.documents == []
    assert result.report[0]["status"] == "error"
    assert result.report[0]["reason"] == "missing_artifact"
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["errors"] == 1


def test_failed_scrape_entry_is_skipped(tmp_path):
    run_dir = tmp_path / "run-1"
    write_manifest(
        run_dir,
        [
            {
                "source_url": LARGE_CAP_URL,
                "status": "failed",
                "http_status": 404,
                "error": "HTTP 404",
                "fetched_at": "2026-11-01T12:00:00+00:00",
            }
        ],
    )

    result = load_documents(make_settings(tmp_path), run_id="run-1")

    assert result.documents == []
    assert result.report[0]["status"] == "skipped"
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["skipped"] == 1


def test_invalid_manifest_entries_are_reported(tmp_path):
    run_dir = tmp_path / "run-1"
    write_manifest(run_dir, ["not-an-object", {"status": "ok"}])

    result = load_documents(make_settings(tmp_path), run_id="run-1")

    assert result.documents == []
    statuses = [entry["status"] for entry in result.report]
    assert statuses == ["error", "error"]
    assert result.report[0]["error"] == "manifest entry is not an object"
    assert result.report[1]["error"] == "missing source_url"


def test_z_timestamp_is_parsed(tmp_path):
    run_dir = tmp_path / "run-1"
    write_page(run_dir, LARGE_CAP_SLUG)
    entry = ok_entry(LARGE_CAP_URL, LARGE_CAP_SLUG, "Large Cap")
    entry["fetched_at"] = "2026-11-01T12:00:00Z"
    write_manifest(run_dir, [entry])

    documents, _ = load_run(run_dir)
    assert documents[0].fetched_at.tzinfo is not None


def test_missing_run_or_manifest_raises(tmp_path):
    with pytest.raises(DocumentLoadError):
        find_latest_run(tmp_path / "missing")

    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(DocumentLoadError):
        find_latest_run(empty)

    with pytest.raises(DocumentLoadError):
        load_run(tmp_path / "no-run")
