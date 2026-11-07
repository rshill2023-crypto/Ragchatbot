"""Typed configuration loading.

`config.yaml` is the single control surface for models, storage, and prompts.
Secrets live in `.env` and are never read from the YAML file. Environment
variables may override any value that is expected to change between runs.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.yaml"


@dataclass(frozen=True)
class IngestionConfig:
    urls: List[str]
    artifacts_dir: str = "data/artifacts"
    timeout_s: int = 30
    user_agent: str = "groww-mf-faq-demo/1.0"
    rate_limit_rps: float = 1.0


@dataclass(frozen=True)
class ChunkingConfig:
    strategy: str = "auto"
    chunk_size: int = 512
    chunk_overlap: int = 64


@dataclass(frozen=True)
class EmbeddingConfig:
    model: str = "sentence-transformers/all-MiniLM-L6-v2"
    batch_size: int = 32


@dataclass(frozen=True)
class VectorDBConfig:
    provider: str = "chromadb"
    collection: str = "groww_mf_faq"
    persist_dir: str = "data/chroma"
    distance: str = "cosine"


@dataclass(frozen=True)
class RetrievalConfig:
    top_k: int = 5
    candidate_k: int = 50
    min_score: float = 0.2


@dataclass(frozen=True)
class LLMConfig:
    provider: str = "groq"
    model: str = "qwen/qwen3.8-27b"
    temperature: float = 0.1
    max_sentences: int = 3


@dataclass(frozen=True)
class GuardrailsConfig:
    pii_block: bool = True
    advice_classifier: str = "hybrid"


@dataclass(frozen=True)
class SourcesConfig:
    allowlist: List[str] = field(default_factory=list)
    educational_links: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class Settings:
    ingestion: IngestionConfig
    chunking: ChunkingConfig
    embedding: EmbeddingConfig
    vector_db: VectorDBConfig
    retrieval: RetrievalConfig
    llm: LLMConfig
    guardrails: GuardrailsConfig
    sources: SourcesConfig
    config_path: Path = DEFAULT_CONFIG_PATH


def _env_str(name: str, default: str) -> str:
    value = os.getenv(name)
    return value if value not in (None, "") else default


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value not in (None, "") else default


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    return float(value) if value not in (None, "") else default


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _section(data: Dict[str, Any], key: str) -> Dict[str, Any]:
    value = data.get(key) or {}
    if not isinstance(value, dict):
        raise ValueError("config section '%s' must be a mapping" % key)
    return value


def _clean_urls(values: Any) -> List[str]:
    if not values:
        return []
    return [str(value).strip() for value in values if str(value).strip()]


def load_config(path: Optional[Union[str, Path]] = None) -> Settings:
    """Load and validate configuration from YAML plus environment overrides."""
    load_dotenv(PROJECT_ROOT / ".env", override=False)

    config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    if not config_path.is_absolute():
        config_path = (Path.cwd() / config_path).resolve()

    with config_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError("config root must be a mapping")

    ingestion = _section(data, "ingestion")
    chunking = _section(data, "chunking")
    embedding = _section(data, "embedding")
    vector_db = _section(data, "vector_db")
    retrieval = _section(data, "retrieval")
    llm = _section(data, "llm")
    guardrails = _section(data, "guardrails")
    sources = _section(data, "sources")

    settings = Settings(
        ingestion=IngestionConfig(
            urls=_clean_urls(ingestion.get("urls")),
            artifacts_dir=_env_str(
                "RAG_ARTIFACTS_DIR", ingestion.get("artifacts_dir", "data/artifacts")
            ),
            timeout_s=_env_int("RAG_TIMEOUT_S", int(ingestion.get("timeout_s", 30))),
            user_agent=_env_str(
                "RAG_USER_AGENT",
                ingestion.get("user_agent", "groww-mf-faq-demo/1.0"),
            ),
            rate_limit_rps=_env_float(
                "RAG_RATE_LIMIT_RPS", float(ingestion.get("rate_limit_rps", 1.0))
            ),
        ),
        chunking=ChunkingConfig(
            strategy=_env_str("RAG_CHUNK_STRATEGY", chunking.get("strategy", "auto")),
            chunk_size=_env_int("RAG_CHUNK_SIZE", int(chunking.get("chunk_size", 512))),
            chunk_overlap=_env_int(
                "RAG_CHUNK_OVERLAP", int(chunking.get("chunk_overlap", 64))
            ),
        ),
        embedding=EmbeddingConfig(
            model=_env_str(
                "RAG_EMBEDDING_MODEL",
                embedding.get("model", "sentence-transformers/all-MiniLM-L6-v2"),
            ),
            batch_size=_env_int(
                "RAG_EMBEDDING_BATCH_SIZE", int(embedding.get("batch_size", 32))
            ),
        ),
        vector_db=VectorDBConfig(
            provider=_env_str(
                "RAG_VECTOR_DB_PROVIDER", vector_db.get("provider", "chromadb")
            ),
            collection=_env_str(
                "RAG_VECTOR_DB_COLLECTION", vector_db.get("collection", "groww_mf_faq")
            ),
            persist_dir=_env_str(
                "RAG_VECTOR_DB_PERSIST_DIR", vector_db.get("persist_dir", "data/chroma")
            ),
            distance=_env_str(
                "RAG_VECTOR_DB_DISTANCE", vector_db.get("distance", "cosine")
            ),
        ),
        retrieval=RetrievalConfig(
            top_k=_env_int("RAG_RETRIEVAL_TOP_K", int(retrieval.get("top_k", 5))),
            candidate_k=_env_int(
                "RAG_RETRIEVAL_CANDIDATE_K", int(retrieval.get("candidate_k", 50))
            ),
            min_score=_env_float(
                "RAG_RETRIEVAL_MIN_SCORE", float(retrieval.get("min_score", 0.2))
            ),
        ),
        llm=LLMConfig(
            provider=_env_str("RAG_LLM_PROVIDER", llm.get("provider", "groq")),
            model=_env_str("RAG_LLM_MODEL", llm.get("model", "qwen/qwen3.8-27b")),
            temperature=_env_float(
                "RAG_LLM_TEMPERATURE", float(llm.get("temperature", 0.1))
            ),
            max_sentences=_env_int(
                "RAG_LLM_MAX_SENTENCES", int(llm.get("max_sentences", 3))
            ),
        ),
        guardrails=GuardrailsConfig(
            pii_block=_env_bool(
                "RAG_PII_BLOCK", bool(guardrails.get("pii_block", True))
            ),
            advice_classifier=_env_str(
                "RAG_ADVICE_CLASSIFIER",
                guardrails.get("advice_classifier", "hybrid"),
            ),
        ),
        sources=SourcesConfig(
            allowlist=_clean_urls(sources.get("allowlist")),
            educational_links=_clean_urls(sources.get("educational_links")),
        ),
        config_path=config_path,
    )

    _validate(settings)
    return settings


def _validate(settings: Settings) -> None:
    ingestion = settings.ingestion
    chunking = settings.chunking
    retrieval = settings.retrieval
    llm = settings.llm

    if not ingestion.urls:
        raise ValueError("ingestion.urls must contain at least one URL")
    if len(set(ingestion.urls)) != len(ingestion.urls):
        raise ValueError("ingestion.urls contains duplicates")

    allowlist = set(settings.sources.allowlist)
    missing = [url for url in ingestion.urls if url not in allowlist]
    if missing:
        raise ValueError(
            "every ingestion URL must be in sources.allowlist; missing: %s"
            % ", ".join(missing)
        )

    if chunking.chunk_size <= 0:
        raise ValueError("chunking.chunk_size must be positive")
    if chunking.chunk_overlap < 0:
        raise ValueError("chunking.chunk_overlap must be non-negative")
    if chunking.chunk_overlap >= chunking.chunk_size:
        raise ValueError("chunking.chunk_overlap must be smaller than chunk_size")

    if retrieval.top_k < 1:
        raise ValueError("retrieval.top_k must be at least 1")
    if retrieval.candidate_k < retrieval.top_k:
        raise ValueError("retrieval.candidate_k must be at least retrieval.top_k")
    if not 0.0 <= retrieval.min_score <= 1.0:
        raise ValueError("retrieval.min_score must be between 0 and 1")

    if llm.max_sentences < 1:
        raise ValueError("llm.max_sentences must be at least 1")


def settings_to_dict(settings: Settings) -> Dict[str, Any]:
    """Return a JSON-friendly snapshot suitable for run metadata."""
    snapshot = asdict(settings)
    snapshot["config_path"] = str(settings.config_path)
    return snapshot
