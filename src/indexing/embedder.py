"""Embed chunks with a configurable sentence-transformers model.

The default model is `sentence-transformers/all-MiniLM-L6-v2`. Embeddings are
written to `embeddings/vectors.jsonl` and run metadata to
`embeddings/run_meta.json` so the stage is inspectable.
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Sequence, Tuple, Union

from ..artifacts import ArtifactWriter
from ..config import EmbeddingConfig, Settings, load_config
from ..ingestion.document_loader import find_latest_run
from ..models import Chunk

LOGGER = logging.getLogger(__name__)


class EmbeddingError(RuntimeError):
    """Raised when chunks cannot be embedded."""


class Embedder(Protocol):
    model_name: str
    dimension: int

    def encode(self, texts: List[str]) -> List[List[float]]:
        ...


class SentenceTransformerEmbedder:
    """Lazy wrapper around sentence-transformers."""

    def __init__(
        self,
        model_name: str,
        batch_size: int = 32,
        normalize: bool = True,
    ) -> None:
        self.model_name = model_name
        self.batch_size = batch_size
        self.normalize = normalize
        self._model = None

    def _load(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:  # pragma: no cover - install issue
                raise EmbeddingError(
                    "sentence-transformers is not installed; run `make install`"
                ) from exc
            LOGGER.info("Loading embedding model %s", self.model_name)
            self._model = SentenceTransformer(self.model_name)
        return self._model

    @property
    def dimension(self) -> int:
        model = self._load()
        dimensions = model.get_sentence_embedding_dimension()
        if dimensions is None:
            raise EmbeddingError(
                "Model %s does not report an embedding dimension" % self.model_name
            )
        return int(dimensions)

    def encode(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        model = self._load()
        embeddings = model.encode(
            texts,
            batch_size=self.batch_size,
            normalize_embeddings=self.normalize,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return [[float(value) for value in row] for row in embeddings]


def build_embedder(
    config: EmbeddingConfig,
    model_override: Optional[str] = None,
) -> SentenceTransformerEmbedder:
    return SentenceTransformerEmbedder(
        model_name=model_override or config.model,
        batch_size=config.batch_size,
    )


@dataclass
class EmbeddingResult:
    run_id: str
    run_dir: Path
    chunk_count: int
    dimension: int
    model: str
    vectors_path: Path
    meta_path: Path


def _chunk_from_record(record: Dict[str, Any]) -> Chunk:
    return Chunk(
        chunk_id=str(record["chunk_id"]),
        source_url=str(record["source_url"]),
        scheme=str(record.get("scheme", "")),
        section=str(record.get("section", "")),
        text=str(record["text"]),
        char_count=int(record.get("char_count", len(str(record["text"])))),
        token_count=int(record.get("token_count", 0)),
    )


def load_chunks(run_dir: Path) -> List[Chunk]:
    manifest_path = run_dir / "chunks" / "chunk_manifest.json"
    if not manifest_path.is_file():
        raise EmbeddingError(
            "Missing chunk manifest: %s; run `make chunk` first" % manifest_path
        )

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EmbeddingError("Cannot read %s: %s" % (manifest_path, exc))

    per_page = manifest.get("per_page") or {}
    if not isinstance(per_page, dict) or not per_page:
        raise EmbeddingError("Chunk manifest has no per_page entries: %s" % manifest_path)

    chunks: List[Chunk] = []
    for slug, page in per_page.items():
        relative = (page or {}).get("artifact") or "chunks/%s.jsonl" % slug
        path = run_dir / relative
        if not path.is_file():
            raise EmbeddingError("Missing chunk artifact: %s" % path)
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise EmbeddingError("Cannot read %s: %s" % (path, exc))

        for line in lines:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                chunks.append(_chunk_from_record(record))
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                raise EmbeddingError("Invalid chunk record in %s: %s" % (path, exc))

    return chunks


def _validate_vectors(
    chunks: Sequence[Chunk], vectors: List[List[float]]
) -> Tuple[List[Chunk], List[List[float]]]:
    if len(vectors) != len(chunks):
        raise EmbeddingError(
            "Embedder returned %d vectors for %d chunks" % (len(vectors), len(chunks))
        )
    if not vectors:
        return [], []

    dimension = len(vectors[0])
    if dimension == 0:
        raise EmbeddingError("Embedder returned zero-length vectors")
    for index, vector in enumerate(vectors):
        if len(vector) != dimension:
            raise EmbeddingError(
                "Inconsistent embedding dimension at index %d: %d != %d"
                % (index, len(vector), dimension)
            )
    return list(chunks), vectors


def run_embedding(
    settings: Settings,
    run_id: Optional[str] = None,
    artifacts_dir: Optional[Union[str, Path]] = None,
    writer: Optional[ArtifactWriter] = None,
    embedder: Optional[Embedder] = None,
    model_override: Optional[str] = None,
) -> EmbeddingResult:
    """Embed all chunks in a run and persist vectors + run metadata."""
    artifacts_root = Path(artifacts_dir or settings.ingestion.artifacts_dir)
    run_dir = artifacts_root / run_id if run_id else find_latest_run(artifacts_root)
    if not run_dir.is_dir():
        raise EmbeddingError("Run directory does not exist: %s" % run_dir)

    chunks = load_chunks(run_dir)
    if not chunks:
        raise EmbeddingError("No chunks to embed in run %s" % run_dir.name)

    active_embedder = embedder or build_embedder(settings.embedding, model_override)
    LOGGER.info(
        "Embedding %d chunks with %s", len(chunks), active_embedder.model_name
    )
    vectors = active_embedder.encode([chunk.text for chunk in chunks])
    chunks, vectors = _validate_vectors(chunks, vectors)
    dimension = len(vectors[0])

    writer = writer or ArtifactWriter(root=artifacts_root, run_id=run_dir.name)
    payload = [
        {"chunk_id": chunk.chunk_id, "vector": vector}
        for chunk, vector in zip(chunks, vectors)
    ]
    vectors_path = writer.save("embeddings", "vectors", payload, fmt="jsonl")

    meta = {
        "run_id": run_dir.name,
        "model": active_embedder.model_name,
        "dimension": dimension,
        "chunk_count": len(chunks),
        "vector_count": len(vectors),
        "batch_size": getattr(active_embedder, "batch_size", None),
        "normalize": getattr(active_embedder, "normalize", None),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "vectors_artifact": str(vectors_path.relative_to(writer.run_dir)),
    }
    meta_path = writer.save("embeddings", "run_meta", meta)

    return EmbeddingResult(
        run_id=run_dir.name,
        run_dir=run_dir,
        chunk_count=len(chunks),
        dimension=dimension,
        model=active_embedder.model_name,
        vectors_path=vectors_path,
        meta_path=meta_path,
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m src.indexing.embedder",
        description="Embed chunks and persist vectors + run metadata",
    )
    parser.add_argument("--run-id", help="run directory name; defaults to latest")
    parser.add_argument(
        "--artifacts-dir", help="override the configured artifacts directory"
    )
    parser.add_argument(
        "--model", help="override the configured sentence-transformers model"
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    settings = load_config()
    try:
        result = run_embedding(
            settings,
            run_id=args.run_id,
            artifacts_dir=args.artifacts_dir,
            model_override=args.model,
        )
    except (EmbeddingError, FileNotFoundError) as exc:
        LOGGER.error("%s", exc)
        return 1

    LOGGER.info(
        "Embedded %d chunks into %d dimensions using %s",
        result.chunk_count,
        result.dimension,
        result.model,
    )
    LOGGER.info("Vectors: %s", result.vectors_path)
    LOGGER.info("Metadata: %s", result.meta_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
