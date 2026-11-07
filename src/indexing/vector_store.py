"""Persist embeddings in ChromaDB and expose a small query surface.

Phase 6 writes the vectors produced in Phase 5 into a persistent Chroma
collection. Upserts use deterministic chunk IDs, so re-running the stage does
not duplicate entries. `--rebuild` drops and recreates the collection first.
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

from ..artifacts import ArtifactWriter
from ..config import Settings, VectorDBConfig, load_config
from ..ingestion.document_loader import find_latest_run
from ..models import Retrieved
from .embedder import load_chunks

LOGGER = logging.getLogger(__name__)
DEFAULT_BATCH_SIZE = 500


class VectorStoreError(RuntimeError):
    """Raised when vectors cannot be stored or queried."""


class ChromaVectorStore:
    """Lazy ChromaDB client wrapper with idempotent upserts."""

    def __init__(
        self,
        persist_dir: Union[str, Path],
        collection: str,
        distance: str = "cosine",
    ) -> None:
        self.persist_dir = Path(persist_dir)
        self.collection_name = collection
        self.distance = distance
        self._client = None
        self._collection = None

    def _connect(self, rebuild: bool = False):
        try:
            import chromadb
            from chromadb.config import Settings as ChromaSettings
        except ImportError as exc:  # pragma: no cover - install issue
            raise VectorStoreError(
                "chromadb is not installed; run `make install`"
            ) from exc

        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(
            path=str(self.persist_dir),
            settings=ChromaSettings(anonymized_telemetry=False),
        )

        if rebuild:
            try:
                self._client.delete_collection(name=self.collection_name)
                LOGGER.info("Dropped collection %s", self.collection_name)
            except Exception:  # collection may not exist yet
                LOGGER.debug("Collection %s did not exist", self.collection_name)

        self._collection = self._client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": self.distance},
        )
        return self._collection

    @property
    def collection(self):
        if self._collection is None:
            self._connect()
        return self._collection

    def rebuild(self) -> "ChromaVectorStore":
        self._connect(rebuild=True)
        return self

    def count(self) -> int:
        return int(self.collection.count())

    def upsert(
        self,
        ids: Sequence[str],
        embeddings: Sequence[Sequence[float]],
        documents: Sequence[str],
        metadatas: Sequence[Dict[str, Any]],
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> int:
        if not ids:
            return 0
        if not (len(ids) == len(embeddings) == len(documents) == len(metadatas)):
            raise VectorStoreError(
                "ids, embeddings, documents, and metadatas must have equal length"
            )
        if batch_size < 1:
            raise VectorStoreError("batch_size must be at least 1")

        collection = self.collection
        for start in range(0, len(ids), batch_size):
            stop = start + batch_size
            collection.upsert(
                ids=list(ids[start:stop]),
                embeddings=[list(vector) for vector in embeddings[start:stop]],
                documents=list(documents[start:stop]),
                metadatas=[dict(meta) for meta in metadatas[start:stop]],
            )
        return len(ids)

    def query(
        self,
        query_embedding: Sequence[float],
        top_k: int = 5,
    ) -> List[Retrieved]:
        if top_k < 1:
            raise VectorStoreError("top_k must be at least 1")
        result = self.collection.query(
            query_embeddings=[list(query_embedding)],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )

        ids = (result.get("ids") or [[]])[0]
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]

        hits: List[Retrieved] = []
        for index, chunk_id in enumerate(ids):
            metadata = metadatas[index] or {}
            hits.append(
                Retrieved(
                    chunk_id=str(chunk_id),
                    source_url=str(metadata.get("source_url", "")),
                    scheme=str(metadata.get("scheme", "")),
                    section=str(metadata.get("section", "")),
                    text=str(documents[index] or ""),
                    score=self._score(distances[index]),
                    fetched_at=str(metadata.get("fetched_at", "")),
                )
            )
        return hits

    def _score(self, distance: Any) -> float:
        value = float(distance)
        if self.distance == "cosine":
            return 1.0 - value
        if self.distance == "ip":
            return 1.0 - value
        return 1.0 / (1.0 + max(value, 0.0))


def build_vector_store(
    config: VectorDBConfig,
    persist_dir: Optional[Union[str, Path]] = None,
    collection: Optional[str] = None,
) -> ChromaVectorStore:
    return ChromaVectorStore(
        persist_dir=persist_dir or config.persist_dir,
        collection=collection or config.collection,
        distance=config.distance,
    )


@dataclass
class StoreResult:
    run_id: str
    collection: str
    distance: str
    persist_dir: str
    count: int
    upserted: int
    info_path: Path


def load_vectors(run_dir: Path) -> Dict[str, List[float]]:
    path = run_dir / "embeddings" / "vectors.jsonl"
    if not path.is_file():
        raise VectorStoreError(
            "Missing embedding artifact: %s; run `make embed` first" % path
        )

    vectors: Dict[str, List[float]] = {}
    dimension: Optional[int] = None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise VectorStoreError("Cannot read %s: %s" % (path, exc))

    for line in lines:
        if not line.strip():
            continue
        try:
            record = json.loads(line)
            chunk_id = str(record["chunk_id"])
            vector = [float(value) for value in record["vector"]]
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise VectorStoreError("Invalid vector record in %s: %s" % (path, exc))

        if not vector:
            raise VectorStoreError("Zero-length vector for chunk %s" % chunk_id)
        if dimension is None:
            dimension = len(vector)
        elif len(vector) != dimension:
            raise VectorStoreError(
                "Inconsistent vector dimension for chunk %s: %d != %d"
                % (chunk_id, len(vector), dimension)
            )
        if chunk_id in vectors:
            raise VectorStoreError("Duplicate vector for chunk %s" % chunk_id)
        vectors[chunk_id] = vector

    if not vectors:
        raise VectorStoreError("No vectors found in %s" % path)
    return vectors


def load_fetched_at(run_dir: Path) -> Dict[str, str]:
    """Best-effort map of source URL -> scrape timestamp."""
    mapping: Dict[str, str] = {}

    loaded_path = run_dir / "loaded" / "documents.jsonl"
    if loaded_path.is_file():
        try:
            for line in loaded_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                record = json.loads(line)
                source_url = record.get("source_url")
                fetched_at = record.get("fetched_at")
                if source_url and fetched_at:
                    mapping[str(source_url)] = str(fetched_at)
        except (OSError, json.JSONDecodeError):
            LOGGER.warning("Could not read %s; trying raw manifest", loaded_path)

    if mapping:
        return mapping

    manifest_path = run_dir / "raw" / "manifest.json"
    if not manifest_path.is_file():
        return mapping
    try:
        entries = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        LOGGER.warning("Could not read %s", manifest_path)
        return mapping

    if isinstance(entries, list):
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            source_url = entry.get("source_url")
            fetched_at = entry.get("fetched_at")
            if source_url and fetched_at:
                mapping[str(source_url)] = str(fetched_at)
    return mapping


def prepare_records(run_dir: Path):
    chunks = load_chunks(run_dir)
    if not chunks:
        raise VectorStoreError("No chunks to store in run %s" % run_dir.name)
    vectors = load_vectors(run_dir)
    fetched_at = load_fetched_at(run_dir)

    ids: List[str] = []
    embeddings: List[List[float]] = []
    documents: List[str] = []
    metadatas: List[Dict[str, Any]] = []

    for chunk in chunks:
        vector = vectors.get(chunk.chunk_id)
        if vector is None:
            raise VectorStoreError(
                "Missing vector for chunk %s; re-run `make embed`" % chunk.chunk_id
            )
        ids.append(chunk.chunk_id)
        embeddings.append(vector)
        documents.append(chunk.text)
        metadatas.append(
            {
                "source_url": chunk.source_url,
                "scheme": chunk.scheme,
                "section": chunk.section,
                "fetched_at": fetched_at.get(chunk.source_url, ""),
            }
        )

    missing = set(vectors) - set(ids)
    if missing:
        LOGGER.warning("Ignoring %d embedding(s) without chunks", len(missing))

    return ids, embeddings, documents, metadatas


def run_store(
    settings: Settings,
    run_id: Optional[str] = None,
    artifacts_dir: Optional[Union[str, Path]] = None,
    persist_dir: Optional[Union[str, Path]] = None,
    collection: Optional[str] = None,
    rebuild: bool = False,
    writer: Optional[ArtifactWriter] = None,
    store: Optional[ChromaVectorStore] = None,
) -> StoreResult:
    artifacts_root = Path(artifacts_dir or settings.ingestion.artifacts_dir)
    run_dir = artifacts_root / run_id if run_id else find_latest_run(artifacts_root)
    if not run_dir.is_dir():
        raise VectorStoreError("Run directory does not exist: %s" % run_dir)

    ids, embeddings, documents, metadatas = prepare_records(run_dir)
    active_store = store or build_vector_store(
        settings.vector_db, persist_dir=persist_dir, collection=collection
    )
    if rebuild:
        active_store.rebuild()
        LOGGER.info("Rebuilt collection %s", active_store.collection_name)

    LOGGER.info(
        "Upserting %d vectors into collection %s",
        len(ids),
        active_store.collection_name,
    )
    upserted = active_store.upsert(ids, embeddings, documents, metadatas)
    count = active_store.count()

    embedding_meta = {}
    meta_path = run_dir / "embeddings" / "run_meta.json"
    if meta_path.is_file():
        try:
            embedding_meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            LOGGER.warning("Could not read %s", meta_path)

    writer = writer or ArtifactWriter(root=artifacts_root, run_id=run_dir.name)
    info = {
        "run_id": run_dir.name,
        "provider": settings.vector_db.provider,
        "collection": active_store.collection_name,
        "distance": active_store.distance,
        "count": count,
        "upserted": upserted,
        "rebuilt": rebuild,
        "persist_dir": str(active_store.persist_dir),
        "embedding_model": embedding_meta.get("model"),
        "dimension": embedding_meta.get("dimension"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    info_path = writer.save("vector_store", "collection_info", info)

    return StoreResult(
        run_id=run_dir.name,
        collection=active_store.collection_name,
        distance=active_store.distance,
        persist_dir=str(active_store.persist_dir),
        count=count,
        upserted=upserted,
        info_path=info_path,
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m src.indexing.vector_store",
        description="Persist embeddings in ChromaDB",
    )
    parser.add_argument("--run-id", help="run directory name; defaults to latest")
    parser.add_argument(
        "--artifacts-dir", help="override the configured artifacts directory"
    )
    parser.add_argument(
        "--persist-dir", help="override the configured Chroma persist directory"
    )
    parser.add_argument(
        "--collection", help="override the configured Chroma collection name"
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="drop and recreate the collection before upserting",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    settings = load_config()
    try:
        result = run_store(
            settings,
            run_id=args.run_id,
            artifacts_dir=args.artifacts_dir,
            persist_dir=args.persist_dir,
            collection=args.collection,
            rebuild=args.rebuild,
        )
    except (VectorStoreError, FileNotFoundError) as exc:
        LOGGER.error("%s", exc)
        return 1

    LOGGER.info(
        "Stored %d vectors in %s (%d total)",
        result.upserted,
        result.collection,
        result.count,
    )
    LOGGER.info("Collection info: %s", result.info_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
