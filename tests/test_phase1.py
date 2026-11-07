"""Configuration and artifact writer tests for Phase 1."""

from __future__ import annotations

import json

import pytest

from src.artifacts import ArtifactWriter
from src.config import load_config, settings_to_dict
from src.models import Answer, Chunk, RawDocument


def test_config_loads_five_urls() -> None:
    config = load_config()
    assert len(config.ingestion.urls) == 5


def test_ingestion_urls_are_allowlisted() -> None:
    config = load_config()
    allowlist = set(config.sources.allowlist)
    assert all(url in allowlist for url in config.ingestion.urls)


def test_chunk_overlap_is_smaller_than_chunk_size() -> None:
    config = load_config()
    assert config.chunking.chunk_overlap < config.chunking.chunk_size


def test_settings_snapshot_is_json_friendly() -> None:
    snapshot = settings_to_dict(load_config())
    encoded = json.dumps(snapshot)
    assert '"llm"' in encoded
    assert '"embedding"' in encoded


def test_invalid_config_is_rejected(tmp_path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "\n".join(
            [
                "ingestion:",
                "  urls: [https://example.com/a]",
                "chunking: { chunk_size: 100, chunk_overlap: 100 }",
                "sources: { allowlist: [https://example.com/a] }",
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_config(bad)


def test_artifact_writer_creates_run_layout(tmp_path) -> None:
    writer = ArtifactWriter(root=tmp_path, run_id="test-run")
    manifest = writer.save("raw", "manifest", {"pages": 5})
    assert manifest == tmp_path / "test-run" / "raw" / "manifest.json"
    assert json.loads(manifest.read_text(encoding="utf-8"))["pages"] == 5

    chunks = writer.save("chunks", "sample", [{"chunk_id": "a"}], fmt="jsonl")
    assert chunks.read_text(encoding="utf-8").strip() == '{"chunk_id": "a"}'

    meta = writer.write_run_meta({"llm": {"provider": "groq"}})
    assert json.loads(meta.read_text(encoding="utf-8"))["run_id"] == "test-run"


def test_artifact_writer_blocks_path_traversal(tmp_path) -> None:
    writer = ArtifactWriter(root=tmp_path, run_id="test-run")
    with pytest.raises(ValueError):
        writer.save("raw", "../escape", {"x": 1})
    with pytest.raises(ValueError):
        writer.save("/absolute", "manifest", {"x": 1})


def test_models_serialize_to_dicts() -> None:
    from datetime import datetime, timezone

    doc = RawDocument(
        source_url="https://example.com",
        page_title="Example",
        scheme="Example Fund",
        category="large_cap",
        html="<p>hi</p>",
        text="hi",
        fetched_at=datetime(2026, 11, 1, tzinfo=timezone.utc),
    )
    assert doc.to_dict()["char_count"] == 2

    chunk = Chunk("c1", doc.source_url, doc.scheme, "Intro", "hi", 2, 1)
    assert chunk.to_dict()["chunk_id"] == "c1"

    answer = Answer("Fact.", doc.source_url, "2026-11-01")
    assert answer.to_dict()["refused"] is False
