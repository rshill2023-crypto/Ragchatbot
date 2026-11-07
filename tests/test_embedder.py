"""Embedding tests (Phase 5): vectors, metadata, and error handling."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from src.artifacts import ArtifactWriter
from src.config import load_config
from src.indexing.embedder import (
    EmbeddingError,
    SentenceTransformerEmbedder,
    build_embedder,
    run_embedding,
)

URL = "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth"
SLUG = "hdfc-large-cap-fund-direct-growth"


class FakeEmbedder:
    model_name = "fake-model"
    dimension = 3
    batch_size = 4
    normalize = True

    def __init__(self, vectors=None) -> None:
        self.vectors = vectors
        self.calls = []

    def encode(self, texts):
        self.calls.append(list(texts))
        if self.vectors is not None:
            return self.vectors
        return [[1.0, float(len(text)), 3.0] for text in texts]


def chunk_record(chunk_id, text, section):
    return {
        "chunk_id": chunk_id,
        "source_url": URL,
        "scheme": "HDFC Large Cap Fund",
        "section": section,
        "text": text,
        "char_count": len(text),
        "token_count": len(text.split()),
    }


def write_run(tmp_path, run_id="run-1", records=None, with_raw_manifest=True):
    run_dir = tmp_path / run_id
    (run_dir / "chunks").mkdir(parents=True)
    if records is None:
        records = [
            chunk_record("c1", "Expense ratio is 0.75%.", "Expense Ratio"),
            chunk_record("c2", "Exit load is 1% within one year.", "Exit Load"),
        ]
    (run_dir / "chunks" / (SLUG + ".jsonl")).write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )
    manifest = {
        "strategy": "heading",
        "per_page": {
            SLUG: {
                "source_url": URL,
                "scheme": "HDFC Large Cap Fund",
                "artifact": "chunks/%s.jsonl" % SLUG,
                "chunks": len(records),
            }
        },
        "total_chunks": len(records),
    }
    (run_dir / "chunks" / "chunk_manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    if with_raw_manifest:
        (run_dir / "raw").mkdir()
        (run_dir / "raw" / "manifest.json").write_text("[]", encoding="utf-8")
    return run_dir


def make_settings(tmp_path):
    settings = load_config()
    return replace(
        settings,
        ingestion=replace(settings.ingestion, artifacts_dir=str(tmp_path)),
    )


def test_run_embedding_writes_vectors_and_metadata(tmp_path):
    run_dir = write_run(tmp_path)
    embedder = FakeEmbedder()
    writer = ArtifactWriter(root=tmp_path, run_id="run-1")

    result = run_embedding(
        make_settings(tmp_path), run_id="run-1", writer=writer, embedder=embedder
    )

    assert result.chunk_count == 2
    assert result.dimension == 3
    assert result.model == "fake-model"
    assert embedder.calls == [["Expense ratio is 0.75%.", "Exit load is 1% within one year."]]

    vectors_path = run_dir / "embeddings" / "vectors.jsonl"
    records = [
        json.loads(line)
        for line in vectors_path.read_text(encoding="utf-8").splitlines()
    ]
    assert [record["chunk_id"] for record in records] == ["c1", "c2"]
    assert all(len(record["vector"]) == 3 for record in records)

    meta = json.loads((run_dir / "embeddings" / "run_meta.json").read_text())
    assert meta["model"] == "fake-model"
    assert meta["dimension"] == 3
    assert meta["chunk_count"] == 2
    assert meta["vector_count"] == 2
    assert meta["vectors_artifact"] == "embeddings/vectors.jsonl"


def test_run_embedding_uses_latest_run(tmp_path):
    write_run(tmp_path, run_id="20261101T100000Z")
    latest = write_run(tmp_path, run_id="20261101T110000Z")

    result = run_embedding(make_settings(tmp_path), embedder=FakeEmbedder())

    assert result.run_id == latest.name
    assert (latest / "embeddings" / "run_meta.json").exists()


def test_missing_chunk_manifest_raises(tmp_path):
    run_dir = tmp_path / "run-1"
    (run_dir / "chunks").mkdir(parents=True)

    with pytest.raises(EmbeddingError):
        run_embedding(make_settings(tmp_path), run_id="run-1", embedder=FakeEmbedder())


def test_empty_chunks_raise(tmp_path):
    write_run(tmp_path, records=[])

    with pytest.raises(EmbeddingError):
        run_embedding(make_settings(tmp_path), run_id="run-1", embedder=FakeEmbedder())


def test_vector_count_mismatch_raises(tmp_path):
    write_run(tmp_path)

    with pytest.raises(EmbeddingError):
        run_embedding(
            make_settings(tmp_path),
            run_id="run-1",
            embedder=FakeEmbedder(vectors=[[1.0, 2.0, 3.0]]),
        )


def test_inconsistent_vector_dimensions_raise(tmp_path):
    write_run(tmp_path)

    with pytest.raises(EmbeddingError):
        run_embedding(
            make_settings(tmp_path),
            run_id="run-1",
            embedder=FakeEmbedder(vectors=[[1.0, 2.0, 3.0], [1.0, 2.0]]),
        )


def test_zero_length_vectors_raise(tmp_path):
    write_run(tmp_path)

    with pytest.raises(EmbeddingError):
        run_embedding(
            make_settings(tmp_path),
            run_id="run-1",
            embedder=FakeEmbedder(vectors=[[], []]),
        )


def test_build_embedder_uses_configured_model_without_loading_it():
    config = load_config().embedding
    embedder = build_embedder(config)

    assert isinstance(embedder, SentenceTransformerEmbedder)
    assert embedder.model_name == config.model
    assert embedder.batch_size == config.batch_size
    assert embedder._model is None


def test_build_embedder_allows_model_override():
    config = load_config().embedding
    embedder = build_embedder(config, model_override="sentence-transformers/all-mpnet-base-v2")
    assert embedder.model_name == "sentence-transformers/all-mpnet-base-v2"
