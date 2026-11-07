"""Fetch and clean the configured Groww pages.

Only the URLs listed in `config.ingestion.urls` are fetched. Links found inside
the pages are deliberately ignored. Each page is saved as raw HTML and cleaned
text plus a manifest entry, so the scraping stage is inspectable in the demo.
"""

from __future__ import annotations

import argparse
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from ..artifacts import ArtifactWriter
from ..config import IngestionConfig, Settings, load_config, settings_to_dict
from ..models import RawDocument

LOGGER = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
BACKOFF_BASE_S = 1.0
MIN_TEXT_CHARS = 200

REMOVE_TAGS = (
    "script",
    "style",
    "noscript",
    "nav",
    "footer",
    "aside",
    "form",
    "svg",
    "iframe",
    "template",
)
MIN_CONTENT_CHARS = 1000
CONTENT_SELECTORS = (
    "main",
    "article",
    "[role='main']",
    "#main-content",
    ".main-content",
    ".content",
)

SCHEME_MAP = {
    "hdfc-large-cap-fund-direct-growth": ("HDFC Large Cap Fund", "large_cap"),
    "hdfc-equity-fund-direct-growth": ("HDFC Flexi Cap Fund", "flexi_cap"),
    "hdfc-elss-tax-saver-fund-direct-plan-growth": (
        "HDFC ELSS Tax Saver Fund",
        "elss",
    ),
    "hdfc-mid-cap-fund-direct-growth": ("HDFC Mid Cap Fund", "mid_cap"),
}


class FetchError(RuntimeError):
    """Raised when a page cannot be fetched or parsed."""

    def __init__(self, message: str, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass
class ScrapeResult:
    documents: List[RawDocument]
    manifest: List[Dict[str, Any]]
    run_id: str
    artifacts_dir: Path
    manifest_path: Path


def slug_from_url(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    slug = path.split("/")[-1].lower()
    slug = re.sub(r"[^a-z0-9-]+", "-", slug).strip("-")
    return slug or "page"


def _page_identity(url: str) -> Tuple[str, str]:
    """Return (scheme, category) for a configured page."""
    path = urlparse(url).path.rstrip("/")
    slug = path.split("/")[-1]

    if "/amc/" in path:
        return "HDFC Mutual Fund", "amc"
    if slug in SCHEME_MAP:
        return SCHEME_MAP[slug]

    scheme = re.sub(r"\s+", " ", slug.replace("-", " ")).strip().title()
    if "elss" in slug:
        category = "elss"
    elif "large-cap" in slug:
        category = "large_cap"
    elif "mid-cap" in slug:
        category = "mid_cap"
    elif "flexi" in slug or "equity-fund" in slug:
        category = "flexi_cap"
    else:
        category = "other"
    return scheme or "Unknown scheme", category


def _make_soup(html: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:  # pragma: no cover - lxml is in requirements
        return BeautifulSoup(html, "html.parser")


def _clean_title(raw: str) -> str:
    title = re.sub(r"\s+", " ", raw or "").strip()
    title = re.sub(r"\s*[|\-–]\s*Groww\s*$", "", title, flags=re.IGNORECASE).strip()
    return title


def _normalise_text(raw: str) -> str:
    lines: List[str] = []
    for line in raw.splitlines():
        cleaned = re.sub(r"\s+", " ", line).strip()
        if cleaned:
            lines.append(cleaned)
    return "\n".join(lines).strip()


def _select_content(soup: BeautifulSoup):
    for selector in CONTENT_SELECTORS:
        candidate = soup.select_one(selector)
        if candidate is not None and len(candidate.get_text(strip=True)) >= MIN_TEXT_CHARS:
            return candidate

    # Groww has no <main>. Climb from the page heading to the smallest ancestor
    # that contains the full scheme content, instead of falling back to <body>
    # (which includes the site-wide mega menu).
    heading = soup.find("h1") or soup.find("h2")
    if heading is not None:
        node = heading
        while node.parent is not None:
            node = node.parent
            if len(node.get_text(strip=True)) >= MIN_CONTENT_CHARS:
                return node

    return soup.body or soup


def extract_document(
    url: str,
    html: str,
    fetched_at: Optional[datetime] = None,
    http_status: int = 200,
) -> RawDocument:
    """Turn fetched HTML into a RawDocument with cleaned visible text."""
    soup = _make_soup(html)

    page_title = ""
    if soup.title and soup.title.string:
        page_title = _clean_title(soup.title.string)
    if not page_title:
        heading = soup.find("h1")
        page_title = _clean_title(heading.get_text(" ", strip=True) if heading else "")
    if not page_title:
        page_title = _page_identity(url)[0]

    content = _select_content(soup)
    for tag in content.find_all(REMOVE_TAGS):
        tag.decompose()

    text = _normalise_text(content.get_text(separator="\n"))

    warning = None
    if len(text) < MIN_TEXT_CHARS:
        warning = "low_text_content"
        LOGGER.warning("Low text extracted for %s (%d chars)", url, len(text))

    scheme, category = _page_identity(url)
    return RawDocument(
        source_url=url,
        page_title=page_title,
        scheme=scheme,
        category=category,
        html=html,
        text=text,
        fetched_at=fetched_at or datetime.now(timezone.utc),
        http_status=http_status,
        extraction_warning=warning,
    )


class GrowwLoader:
    """Fetch the configured pages with retries and polite rate limiting."""

    def __init__(
        self,
        config: IngestionConfig,
        session: Optional[requests.Session] = None,
        sleep: Any = time.sleep,
        clock: Any = time.monotonic,
    ) -> None:
        self.config = config
        self.session = session or requests.Session()
        self._sleep = sleep
        self._clock = clock
        self._last_request_at: Optional[float] = None

    def _throttle(self) -> None:
        if self.config.rate_limit_rps <= 0:
            return
        if self._last_request_at is not None:
            elapsed = self._clock() - self._last_request_at
            delay = (1.0 / self.config.rate_limit_rps) - elapsed
            if delay > 0:
                self._sleep(delay)
        self._last_request_at = self._clock()

    def _backoff(self, attempt: int) -> float:
        return BACKOFF_BASE_S * (2 ** (attempt - 1))

    def _get(self, url: str) -> requests.Response:
        last_error: Optional[Exception] = None

        for attempt in range(1, MAX_ATTEMPTS + 1):
            self._throttle()
            try:
                response = self.session.get(
                    url,
                    headers={"User-Agent": self.config.user_agent},
                    timeout=self.config.timeout_s,
                    allow_redirects=False,
                )
            except requests.RequestException as exc:
                last_error = exc
                if attempt < MAX_ATTEMPTS:
                    self._sleep(self._backoff(attempt))
                    continue
                break

            status = response.status_code
            if status == 429 or 500 <= status <= 599:
                last_error = FetchError("HTTP %d for %s" % (status, url), status)
                if attempt < MAX_ATTEMPTS:
                    retry_after = None
                    headers = getattr(response, "headers", None) or {}
                    try:
                        retry_after = float(headers.get("Retry-After", ""))
                    except (TypeError, ValueError):
                        retry_after = None
                    self._sleep(
                        retry_after
                        if retry_after is not None
                        else self._backoff(attempt)
                    )
                    continue
                break

            if 300 <= status < 400:
                headers = getattr(response, "headers", None) or {}
                location = headers.get("Location", "<unknown>")
                raise FetchError(
                    "Redirect not followed (%d) for %s -> %s"
                    % (status, url, location),
                    status,
                )

            if status >= 400:
                raise FetchError("HTTP %d for %s" % (status, url), status)

            return response

        if isinstance(last_error, FetchError):
            raise last_error
        raise FetchError("Failed to fetch %s: %s" % (url, last_error))

    def fetch(self, url: str) -> RawDocument:
        response = self._get(url)
        return extract_document(
            url,
            response.text,
            fetched_at=datetime.now(timezone.utc),
            http_status=response.status_code,
        )

    def fetch_all(self) -> Tuple[List[RawDocument], List[Dict[str, Any]]]:
        documents: List[RawDocument] = []
        manifest: List[Dict[str, Any]] = []

        for url in self.config.urls:
            try:
                document = self.fetch(url)
            except FetchError as exc:
                LOGGER.error("Skipping %s: %s", url, exc)
                manifest.append(
                    {
                        "source_url": url,
                        "scheme": _page_identity(url)[0],
                        "category": _page_identity(url)[1],
                        "status": "failed",
                        "http_status": exc.status_code,
                        "error": str(exc),
                        "fetched_at": datetime.now(timezone.utc).isoformat(),
                    }
                )
                continue

            documents.append(document)
            entry = document.to_dict()
            entry.update({"status": "ok", "artifacts": {}})
            manifest.append(entry)

        return documents, manifest


def scrape(
    settings: Settings,
    writer: Optional[ArtifactWriter] = None,
    session: Optional[requests.Session] = None,
) -> ScrapeResult:
    """Fetch all configured pages and persist raw artifacts + manifest."""
    writer = writer or ArtifactWriter(settings.ingestion.artifacts_dir)
    writer.write_run_meta(settings_to_dict(settings))

    loader = GrowwLoader(settings.ingestion, session=session)
    documents, manifest = loader.fetch_all()
    documents_by_url = {document.source_url: document for document in documents}

    used_slugs: Set[str] = set()
    for entry in manifest:
        document = documents_by_url.get(entry["source_url"])
        if document is None:
            continue

        slug = slug_from_url(document.source_url)
        if slug in used_slugs:
            suffix = 2
            while "%s-%d" % (slug, suffix) in used_slugs:
                suffix += 1
            slug = "%s-%d" % (slug, suffix)
        used_slugs.add(slug)

        html_path = writer.save("raw/html", slug, document.html, fmt="html")
        text_path = writer.save("raw/text", slug, document.text, fmt="text")
        entry["artifacts"] = {
            "html": str(html_path.relative_to(writer.run_dir)),
            "text": str(text_path.relative_to(writer.run_dir)),
        }

    manifest_path = writer.save("raw", "manifest", manifest)
    return ScrapeResult(
        documents=documents,
        manifest=manifest,
        run_id=writer.run_id,
        artifacts_dir=writer.run_dir,
        manifest_path=manifest_path,
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m src.ingestion.loader",
        description="Scrape the configured Groww pages into raw artifacts",
    )
    parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    settings = load_config()
    result = scrape(settings)

    ok = sum(1 for entry in result.manifest if entry["status"] == "ok")
    LOGGER.info(
        "Scraped %d/%d pages into %s",
        ok,
        len(result.manifest),
        result.artifacts_dir,
    )
    LOGGER.info("Manifest: %s", result.manifest_path)
    return 0 if ok == len(result.manifest) else 1


if __name__ == "__main__":
    raise SystemExit(main())
