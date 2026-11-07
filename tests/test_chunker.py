"""Chunking tests (Phase 4): strategies, IDs, manifest, and artifacts."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.artifacts import ArtifactWriter
from src.config import ChunkingConfig, load_config
from src.ingestion.chunker import (
    AutoChunker,
    BaseChunker,
    ChunkingError,
    FixedChunker,
    HeadingChunker,
    chunk_documents,
    heading_boundaries,
    make_chunk_id,
    run_chunking,
)
from src.models import RawDocument

LARGE_CAP_URL = "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth"
ELSS_URL = "https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth"
LARGE_CAP_SLUG = "hdfc-large-cap-fund-direct-growth"
ELSS_SLUG = "hdfc-elss-tax-saver-fund-direct-plan-growth"

HTML = """
<html><body>
  <h1>HDFC Large Cap Fund Direct Growth</h1>
  <h2>Expense Ratio</h2>
  <h2>Exit Load</h2>
  <h2>Minimum SIP</h2>
  <h2>Benchmark</h2>
</body></html>
"""

TEXT = "\n".join(
    [
        "HDFC Large Cap Fund Direct Growth",
        "Expense Ratio",
        "The expense ratio is 0.75% for the direct plan.",
        "Exit Load",
        "Exit load is 1% if redeemed within one year.",
        "Minimum SIP",
        "The minimum SIP amount is Rs 500 per month.",
        "Benchmark",
        "The benchmark index is NIFTY 100 Total Return Index.",
    ]
)


def make_document(
    text: str = TEXT,
    html: str = HTML,
    url: str = LARGE_CAP_URL,
    scheme: str = "HDFC Large Cap Fund",
) -> RawDocument:
    return RawDocument(
        source_url=url,
        page_title="HDFC Large Cap Fund Direct Growth",
        scheme=scheme,
        category="large_cap",
        html=html,
        text=text,
        fetched_at=datetime(2026, 11, 1, tzinfo=timezone.utc),
    )


def tokens(count: int) -> str:
    return " ".join("word%d" % index for index in range(count))


def test_fixed_chunker_respects_size_and_overlap() -> None:
    document = make_document(text=tokens(25))
    chunks = FixedChunker(chunk_size=10, chunk_overlap=2).chunk(document)

    assert len(chunks) == 3
    assert all(chunk.token_count <= 10 for chunk in chunks)
    assert chunks[0].text.split()[0] == "word0"
    assert chunks[1].text.split()[0] == "word8"
    assert chunks[1].text.split()[-1] == "word17"
    assert chunks[2].text.split()[-1] == "word24"


def test_heading_chunker_preserves_sections() -> None:
    document = make_document()
    chunks = HeadingChunker(chunk_size=100, chunk_overlap=0).chunk(document)

    sections = {chunk.section for chunk in chunks}
    assert "Expense Ratio" in sections
    assert "Exit Load" in sections
    assert "Minimum SIP" in sections
    assert "Benchmark" in sections

    expense = [chunk for chunk in chunks if chunk.section == "Expense Ratio"][0]
    assert "0.75%" in expense.text

    exit_load = [chunk for chunk in chunks if chunk.section == "Exit Load"][0]
    assert "1%" in exit_load.text


def test_heading_boundaries_are_ordered() -> None:
    boundaries = heading_boundaries(make_document())
    positions = [position for position, _ in boundaries]
    assert positions == sorted(positions)
    assert len(boundaries) >= 4


def test_auto_chunker_prefers_heading_when_sections_exist() -> None:
    chunker = AutoChunker(chunk_size=100, chunk_overlap=0)
    chosen, rationale = chunker.choose(make_document())

    assert chosen.name == "heading"
    assert "section headings" in rationale
    assert chunker.chunk(make_document())


def test_auto_chunker_falls_back_to_fixed_without_headings() -> None:
    document = make_document(text=tokens(40), html="", url=ELSS_URL)
    chunker = AutoChunker(chunk_size=10, chunk_overlap=2)
    chosen, rationale = chunker.choose(document)

    assert chosen.name == "fixed"
    assert "fixed token windows" in rationale
    assert all(chunk.token_count <= 10 for chunk in chunker.chunk(document))


def test_chunk_ids_are_deterministic_and_unique() -> None:
    document = make_document()
    first = HeadingChunker(100, 0).chunk(document)
    second = HeadingChunker(100, 0).chunk(document)

    assert [chunk.chunk_id for chunk in first] == [chunk.chunk_id for chunk in second]
    assert len({chunk.chunk_id for chunk in first}) == len(first)
    assert make_chunk_id(LARGE_CAP_URL, "Expense Ratio", 0) != make_chunk_id(
        ELSS_URL, "Expense Ratio", 0
    )


def test_empty_document_produces_no_chunks() -> None:
    document = make_document(text="   \n  ", html="")
    assert HeadingChunker(100, 0).chunk(document) == []
    assert FixedChunker(100, 0).chunk(document) == []


def test_invalid_chunking_config_is_rejected() -> None:
    with pytest.raises(ChunkingError):
        BaseChunker(0, 0)
    with pytest.raises(ChunkingError):
        BaseChunker(10, 10)
    with pytest.raises(ChunkingError):
        BaseChunker(10, -1)


def test_unknown_strategy_is_rejected() -> None:
    config = ChunkingConfig(strategy="auto", chunk_size=100, chunk_overlap=10)
    with pytest.raises(ChunkingError):
        chunk_documents([make_document()], config, strategy="semantic")


def test_chunk_manifest_counts_match_chunks() -> None:
    config = ChunkingConfig(strategy="auto", chunk_size=100, chunk_overlap=0)
    documents = [
        make_document(),
        make_document(text=tokens(30), html="", url=ELSS_URL, scheme="ELSS"),
    ]

    chunks, manifest = chunk_documents(documents, config)

    assert manifest["requested_strategy"] == "auto"
    assert manifest["strategy"] == "mixed"
    assert manifest["total_chunks"] == len(chunks)
    assert sum(page["chunks"] for page in manifest["per_page"].values()) == len(chunks)
    assert set(manifest["per_page"]) == {LARGE_CAP_SLUG, ELSS_SLUG}
    assert manifest["per_page"][LARGE_CAP_SLUG]["strategy"] == "heading"
    assert manifest["per_page"][ELSS_SLUG]["strategy"] == "fixed"


def write_run(tmp_path: Path) -> Path:
    run_dir = tmp_path / "run-1"
    (run_dir / "raw" / "html").mkdir(parents=True)
    (run_dir / "raw" / "text").mkdir(parents=True)
    (run_dir / "raw" / "html" / (LARGE_CAP_SLUG + ".html")).write_text(
        HTML, encoding="utf-8"
    )
    (run_dir / "raw" / "text" / (LARGE_CAP_SLUG + ".txt")).write_text(
        TEXT, encoding="utf-8"
    )
    manifest = [
        {
            "source_url": LARGE_CAP_URL,
            "page_title": "HDFC Large Cap Fund Direct Growth",
            "scheme": "HDFC Large Cap Fund",
            "category": "large_cap",
            "fetched_at": "2026-11-01T12:00:00+00:00",
            "http_status": 200,
            "extraction_warning": None,
            "status": "ok",
            "artifacts": {
                "html": "raw/html/%s.html" % LARGE_CAP_SLUG,
                "text": "raw/text/%s.txt" % LARGE_CAP_SLUG,
            },
        }
    ]
    (run_dir / "raw" / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return run_dir


def test_run_chunking_writes_artifacts(tmp_path) -> None:
    run_dir = write_run(tmp_path)
    settings = load_config()
    settings = replace(
        settings,
        ingestion=replace(settings.ingestion, artifacts_dir=str(tmp_path)),
        chunking=ChunkingConfig(strategy="heading", chunk_size=100, chunk_overlap=0),
    )
    writer = ArtifactWriter(root=tmp_path, run_id="run-1")

    result = run_chunking(settings, run_id="run-1", writer=writer)

    assert result.manifest["total_chunks"] > 0
    assert result.manifest_path == run_dir / "chunks" / "chunk_manifest.json"
    assert result.manifest_path.exists()

    chunk_file = run_dir / "chunks" / (LARGE_CAP_SLUG + ".jsonl")
    assert chunk_file.exists()
    records = [
        json.loads(line)
        for line in chunk_file.read_text(encoding="utf-8").splitlines()
    ]
    assert len(records) == result.manifest["total_chunks"]
    assert all(record["source_url"] == LARGE_CAP_URL for record in records)

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["per_page"][LARGE_CAP_SLUG]["artifact"] == (
        "chunks/%s.jsonl" % LARGE_CAP_SLUG
    )


def test_run_chunking_requires_documents(tmp_path) -> None:
    run_dir = tmp_path / "run-empty"
    (run_dir / "raw").mkdir(parents=True)
    (run_dir / "raw" / "manifest.json").write_text("[]", encoding="utf-8")
    settings = load_config()
    settings = replace(
        settings,
        ingestion=replace(settings.ingestion, artifacts_dir=str(tmp_path)),
    )

    with pytest.raises(ChunkingError):
        run_chunking(settings, run_id="run-empty")
