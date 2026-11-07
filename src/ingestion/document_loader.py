"""Load previously scraped pages from disk into RawDocument objects.

Scraping (`src.ingestion.loader`) writes raw artifacts per run. This stage is
the bridge between scraping and chunking: it reads the latest (or a requested)
run and reconstructs `RawDocument` instances, then persists a `loaded/`
artifact folder for inspection.
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from ..artifacts import ArtifactWriter
from ..config import Settings, load_config
from ..models import RawDocument
from .loader import slug_from_url

LOGGER = logging.getLogger(__name__)


class DocumentLoadError(RuntimeError):
    """Raised when no scraped run can be found or a manifest is invalid."""


@dataclass
class LoadResult:
    run_id: str
    run_dir: Path
    documents: List[RawDocument]
    report: List[Dict[str, Any]]
    manifest_path: Path


def find_latest_run(artifacts_root: Union[str, Path]) -> Path:
    """Return the newest run directory that contains raw/manifest.json."""
    root = Path(artifacts_root)
    if not root.exists():
        raise DocumentLoadError("Artifacts directory does not exist: %s" % root)

    candidates = [
        path
        for path in root.iterdir()
        if path.is_dir() and (path / "raw" / "manifest.json").is_file()
    ]
    if not candidates:
        raise DocumentLoadError(
            "No scraped runs found in %s; run `make scrape` first." % root
        )
    return max(candidates, key=lambda path: path.name)


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if not value:
        return datetime.now(timezone.utc)

    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        LOGGER.warning("Invalid fetched_at %r; using current UTC time", value)
        return datetime.now(timezone.utc)


def _read_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise DocumentLoadError("Cannot read %s: %s" % (path, exc))


def _artifact_paths(run_dir: Path, entry: Dict[str, Any]) -> Tuple[Path, Path]:
    artifacts = entry.get("artifacts") or {}
    html_rel = artifacts.get("html")
    text_rel = artifacts.get("text")

    if html_rel and text_rel:
        return run_dir / html_rel, run_dir / text_rel

    slug = slug_from_url(str(entry.get("source_url", "")))
    return run_dir / "raw" / "html" / (slug + ".html"), run_dir / "raw" / "text" / (
        slug + ".txt"
    )


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def load_run(run_dir: Union[str, Path]) -> Tuple[List[RawDocument], List[Dict[str, Any]]]:
    """Read a single run directory and return documents plus a load report."""
    run_path = Path(run_dir)
    manifest_path = run_path / "raw" / "manifest.json"
    if not manifest_path.is_file():
        raise DocumentLoadError("Missing raw manifest: %s" % manifest_path)

    manifest = _read_json(manifest_path)
    if not isinstance(manifest, list):
        raise DocumentLoadError("raw/manifest.json must be a list: %s" % manifest_path)

    documents: List[RawDocument] = []
    report: List[Dict[str, Any]] = []

    for index, entry in enumerate(manifest):
        if not isinstance(entry, dict):
            report.append(
                {
                    "index": index,
                    "status": "error",
                    "error": "manifest entry is not an object",
                }
            )
            continue

        source_url = entry.get("source_url")
        if not source_url:
            report.append(
                {"index": index, "status": "error", "error": "missing source_url"}
            )
            continue

        if entry.get("status") != "ok":
            report.append(
                {
                    "index": index,
                    "source_url": source_url,
                    "status": "skipped",
                    "reason": "scrape_failed",
                    "error": entry.get("error"),
                }
            )
            continue

        html_path, text_path = _artifact_paths(run_path, entry)
        missing = [str(path) for path in (html_path, text_path) if not path.is_file()]
        if missing:
            report.append(
                {
                    "index": index,
                    "source_url": source_url,
                    "status": "error",
                    "reason": "missing_artifact",
                    "missing": missing,
                }
            )
            LOGGER.error("Missing artifact for %s: %s", source_url, ", ".join(missing))
            continue

        try:
            html = _read_text(html_path)
            text = _read_text(text_path)
        except OSError as exc:
            report.append(
                {
                    "index": index,
                    "source_url": source_url,
                    "status": "error",
                    "reason": "read_error",
                    "error": str(exc),
                }
            )
            continue

        document = RawDocument(
            source_url=str(source_url),
            page_title=str(entry.get("page_title") or ""),
            scheme=str(entry.get("scheme") or ""),
            category=str(entry.get("category") or ""),
            html=html,
            text=text,
            fetched_at=_parse_datetime(entry.get("fetched_at")),
            http_status=int(entry.get("http_status") or 200),
            extraction_warning=entry.get("extraction_warning"),
        )
        documents.append(document)
        report.append(
            {
                "index": index,
                "source_url": document.source_url,
                "scheme": document.scheme,
                "category": document.category,
                "status": "loaded",
                "text_chars": len(document.text),
            }
        )

    return documents, report


def load_documents(
    settings: Settings,
    run_id: Optional[str] = None,
    artifacts_dir: Optional[Union[str, Path]] = None,
    writer: Optional[ArtifactWriter] = None,
) -> LoadResult:
    """Load a scraped run and persist inspectable `loaded/` artifacts."""
    artifacts_root = Path(artifacts_dir or settings.ingestion.artifacts_dir)
    run_dir = artifacts_root / run_id if run_id else find_latest_run(artifacts_root)
    if not run_dir.is_dir():
        raise DocumentLoadError("Run directory does not exist: %s" % run_dir)

    documents, report = load_run(run_dir)

    writer = writer or ArtifactWriter(root=artifacts_root, run_id=run_dir.name)
    payload: List[Dict[str, Any]] = []
    for document in documents:
        record = document.to_dict()
        record["text"] = document.text
        payload.append(record)

    documents_path = writer.save("loaded", "documents", payload, fmt="jsonl")

    loaded = sum(1 for item in report if item["status"] == "loaded")
    load_manifest = {
        "run_id": run_dir.name,
        "source_run": str(run_dir),
        "loaded_at": datetime.now(timezone.utc).isoformat(),
        "document_count": len(documents),
        "entry_count": len(report),
        "loaded": loaded,
        "skipped": sum(1 for item in report if item["status"] == "skipped"),
        "errors": sum(1 for item in report if item["status"] == "error"),
        "documents_artifact": str(documents_path.relative_to(writer.run_dir)),
        "entries": report,
    }
    manifest_path = writer.save("loaded", "load_manifest", load_manifest)

    return LoadResult(
        run_id=run_dir.name,
        run_dir=run_dir,
        documents=documents,
        report=report,
        manifest_path=manifest_path,
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m src.ingestion.document_loader",
        description="Load a scraped run into RawDocument objects",
    )
    parser.add_argument("--run-id", help="run directory name; defaults to latest")
    parser.add_argument(
        "--artifacts-dir",
        help="override the configured artifacts directory",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    settings = load_config()
    try:
        result = load_documents(
            settings,
            run_id=args.run_id,
            artifacts_dir=args.artifacts_dir,
        )
    except DocumentLoadError as exc:
        LOGGER.error("%s", exc)
        return 1

    LOGGER.info(
        "Loaded %d/%d documents from run %s",
        len(result.documents),
        len(result.report),
        result.run_id,
    )
    LOGGER.info("Documents: %s", result.run_dir / "loaded" / "documents.jsonl")
    LOGGER.info("Manifest: %s", result.manifest_path)
    return 0 if len(result.documents) == len(result.report) else 1


if __name__ == "__main__":
    raise SystemExit(main())
