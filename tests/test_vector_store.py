"""Vector-store tests (Phase 6): upsert, metadata, query, idempotency."""

from __future__ import annotations

import json
import uuid
from dataclasses import replace
from pathlib import Path

import pytest

from src.artifacts import ArtifactWriter
from src.config import load_config
from src.indexing.vector_store import (
    ChromaVectorStore,
    VectorStoreError,
    build_vector_store,
    load_fetched_at,
    load_vectors,
    prepare_records,
    run_store,
)

URL = "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth"
SLUG = "hdfc-large-cap-fund-direct-growth"
FETCHED_AT = "2026-11-01T17:33:01.353216+00:00"


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


def default_chunks():
    return [
        chunk_record("c1", "Expense ratio is 0.75%.", "Expense Ratio"),
        chunk_record("c2", "Exit load is 1% within one year.", "Exit Load"),
    ]


def write_run(
    tmp_path,
    run_id="run-1",
    chunks=None,
    vectors=None,
    with_embeddings=True,
):
    run_dir = tmp_path / run_id
    (run_dir / "chunks").mkdir(parents=True)
    chunks = default_chunks() if chunks is None else chunks
    (run_dir / "chunks" / (SLUG + ".jsonl")).write_text(
        "\n".join(json.dumps(record) for record in chunks) + "\n",
        encoding="utf-8",
    )
    (run_dir / "chunks" / "chunk_manifest.json").write_text(
        json.dumps(
            {
                "strategy": "heading",
                "per_page": {
                    SLUG: {
                        "source_url": URL,
                        "scheme": "HDFC Large Cap Fund",
                        "artifact": "chunks/%s.jsonl" % SLUG,
                        "chunks": len(chunks),
                    }
                },
                "total_chunks": len(chunks),
            }
        ),
        encoding="utf-8",
    )

    (run_dir / "loaded").mkdir()
    (run_dir / "loaded" / "documents.jsonl").write_text(
        json.dumps(
            {
                "source_url": URL,
                "scheme": "HDFC Large Cap Fund",
                "fetched_at": FETCHED_AT,
                "text": "full page text",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    if with_embeddings:
        (run_dir / "embeddings").mkdir()
        if vectors is None:
            vectors = [
                {"chunk_id": "c1", "vector": [1.0, 0.0, 0.0]},
                {"chunk_id": "c2", "vector": [0.0, 1.0, 0.0]},
            ]
        (run_dir / "embeddings" / "vectors.jsonl").write_text(
            "\n".join(json.dumps(record) for record in vectors) + "\n",
            encoding="utf-8",
        )
        (run_dir / "embeddings" / "run_meta.json").write_text(
            json.dumps(
                {
                    "model": "sentence-transformers/all-MiniLM-L6-v2",
                    "dimension": 3,
                    "chunk_count": len(vectors),
                }
            ),
            encoding="utf-8",
        )

    return run_dir


def make_settings(tmp_path):
    settings = load_config()
    return replace(
        settings,
        ingestion=replace(settings.ingestion, artifacts_dir=str(tmp_path)),
    )


class FakeStore:
    def __init__(self) -> None:
        self.collection_name = "fake_collection"
        self.distance = "cosine"
        self.persist_dir = Path("/tmp/fake-chroma")
        self.rows = {}
        self.rebuilt = False
        self.upsert_calls = []

    def rebuild(self):
        self.rebuilt = True
        self.rows.clear()
        return self

    def upsert(self, ids, embeddings, documents, metadatas, batch_size=500):
        self.upsert_calls.append(
            (list(ids), list(embeddings), list(documents), list(metadatas))
        )
        for index, chunk_id in enumerate(ids):
            self.rows[chunk_id] = {
                "embedding": embeddings[index],
                "document": documents[index],
                "metadata": metadatas[index],
            }
        return len(ids)

    def count(self):
        return len(self.rows)


def test_prepare_records_pairs_chunks_and_vectors(tmp_path):
    run_dir = write_run(tmp_path)

    ids, embeddings, documents, metadatas = prepare_records(run_dir)

    assert ids == ["c1", "c2"]
    assert embeddings == [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
    assert documents == ["Expense ratio is 0.75%.", "Exit load is 1% within one year."]
    assert metadatas[0] == {
        "source_url": URL,
        "scheme": "HDFC Large Cap Fund",
        "section": "Expense Ratio",
        "fetched_at": FETCHED_AT,
    }


def test_run_store_writes_collection_info(tmp_path):
    run_dir = write_run(tmp_path)
    store = FakeStore()
    writer = ArtifactWriter(root=tmp_path, run_id="run-1")

    result = run_store(
        make_settings(tmp_path),
        run_id="run-1",
        store=store,
        writer=writer,
    )

    assert result.upserted == 2
    assert result.count == 2
    assert result.collection == "fake_collection"
    assert store.rebuilt is False
    assert set(store.rows) == {"c1", "c2"}

    info = json.loads((run_dir / "vector_store" / "collection_info.json").read_text())
    assert info["collection"] == "fake_collection"
    assert info["count"] == 2
    assert info["upserted"] == 2
    assert info["distance"] == "cosine"
    assert info["embedding_model"] == "sentence-transformers/all-MiniLM-L6-v2"
    assert info["dimension"] == 3


def test_run_store_is_idempotent(tmp_path):
    write_run(tmp_path)
    store = FakeStore()

    first = run_store(make_settings(tmp_path), run_id="run-1", store=store)
    second = run_store(make_settings(tmp_path), run_id="run-1", store=store)

    assert first.count == 2
    assert second.count == 2
    assert len(store.rows) == 2


def test_rebuild_clears_collection(tmp_path):
    write_run(tmp_path)
    store = FakeStore()
    run_store(make_settings(tmp_path), run_id="run-1", store=store)

    result = run_store(
        make_settings(tmp_path), run_id="run-1", store=store, rebuild=True
    )

    assert store.rebuilt is True
    assert result.count == 2


def test_missing_embeddings_raise(tmp_path):
    write_run(tmp_path, with_embeddings=False)

    with pytest.raises(VectorStoreError):
        run_store(make_settings(tmp_path), run_id="run-1", store=FakeStore())


def test_missing_vector_for_chunk_raises(tmp_path):
    write_run(tmp_path, vectors=[{"chunk_id": "c1", "vector": [1.0, 0.0, 0.0]}])

    with pytest.raises(VectorStoreError):
        run_store(make_settings(tmp_path), run_id="run-1", store=FakeStore())


def test_inconsistent_vector_dimensions_raise(tmp_path):
    write_run(
        tmp_path,
        vectors=[
            {"chunk_id": "c1", "vector": [1.0, 0.0, 0.0]},
            {"chunk_id": "c2", "vector": [0.0, 1.0]},
        ],
    )

    with pytest.raises(VectorStoreError):
        load_vectors(tmp_path / "run-1")


def test_duplicate_vector_id_raises(tmp_path):
    write_run(
        tmp_path,
        vectors=[
            {"chunk_id": "c1", "vector": [1.0, 0.0, 0.0]},
            {"chunk_id": "c1", "vector": [0.0, 1.0, 0.0]},
        ],
    )

    with pytest.raises(VectorStoreError):
        load_vectors(tmp_path / "run-1")


def test_fetched_at_falls_back_to_raw_manifest(tmp_path):
    run_dir = tmp_path / "run-raw"
    (run_dir / "raw").mkdir(parents=True)
    (run_dir / "raw" / "manifest.json").write_text(
        json.dumps([{"source_url": URL, "fetched_at": FETCHED_AT}]),
        encoding="utf-8",
    )

    assert load_fetched_at(run_dir) == {URL: FETCHED_AT}


def test_build_vector_store_uses_config_without_connecting():
    config = load_config().vector_db
    store = build_vector_store(
        config, persist_dir="/tmp/test-chroma", collection="test_collection"
    )

    assert isinstance(store, ChromaVectorStore)
    assert store.collection_name == "test_collection"
    assert store.distance == config.distance
    assert store.persist_dir == Path("/tmp/test-chroma")
    assert store._collection is None


def test_chroma_roundtrip_query_and_idempotency(tmp_path):
    pytest.importorskip("chromadb")
    store = build_vector_store(
        load_config().vector_db,
        persist_dir=tmp_path / "chroma",
        collection="roundtrip_%s" % uuid.uuid4().hex,
    )
    ids = ["a", "b", "c"]
    embeddings = [[1.0, 0.0, 0.0], [0.8, 0.6, 0.0], [0.0, 0.0, 1.0]]
    documents = ["alpha", "beta", "gamma"]
    metadatas = [
        {
            "source_url": URL,
            "scheme": "HDFC Large Cap Fund",
            "section": section,
            "fetched_at": FETCHED_AT,
        }
        for section in ("A", "B", "C")
    ]

    assert store.upsert(ids, embeddings, documents, metadatas) == 3
    assert store.count() == 3
    assert store.upsert(ids, embeddings, documents, metadatas) == 3
    assert store.count() == 3

    hits = store.query([1.0, 0.0, 0.0], top_k=2)
    assert [hit.chunk_id for hit in hits] == ["a", "b"]
    assert hits[0].text == "alpha"
    assert hits[0].source_url == URL
    assert hits[0].score > hits[1].score

    store.rebuild()
    assert store.count() == 0
