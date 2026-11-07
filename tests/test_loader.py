"""Scraping tests for Phase 2 (no network access required)."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone

import pytest
import requests

from src.artifacts import ArtifactWriter
from src.config import IngestionConfig, load_config
from src.ingestion.loader import (
    FetchError,
    GrowwLoader,
    extract_document,
    scrape,
)

LARGE_CAP_URL = (
    "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth"
)
ELSS_URL = (
    "https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth"
)
AMC_URL = "https://groww.in/mutual-funds/amc/hdfc-mutual-funds"

LARGE_CAP_HTML = """
<html>
  <head><title>HDFC Large Cap Fund - Groww</title></head>
  <body>
    <nav>Menu Link</nav>
    <header>Site header</header>
    <main>
      <h1>HDFC Large Cap Fund Direct Growth</h1>
      <h2>Expense Ratio</h2>
      <p>The expense ratio is 0.75% for the direct plan.</p>
      <h2>Exit Load</h2>
      <p>Exit load is 1% if redeemed within one year.</p>
      <h2>Minimum SIP</h2>
      <p>The minimum SIP amount is Rs 500 per month.</p>
      <h2>Riskometer</h2>
      <p>The riskometer level is Very High for this scheme.</p>
      <h2>Benchmark</h2>
      <p>The benchmark index is NIFTY 100 Total Return Index.</p>
      <p><a href="/mutual-funds/other-fund">An internal link we must not follow</a></p>
    </main>
    <script>var tracking = "should be removed";</script>
    <footer>Footer junk</footer>
  </body>
</html>
"""


class FakeResponse:
    def __init__(self, text: str, status_code: int = 200, headers=None) -> None:
        self.text = text
        self.status_code = status_code
        self.headers = headers or {}


class FakeSession:
    def __init__(self, responses) -> None:
        self.responses = responses
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        value = self.responses[url]
        if isinstance(value, list):
            value = value.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


def make_config(urls):
    return IngestionConfig(
        urls=urls,
        artifacts_dir="data/artifacts",
        timeout_s=5,
        rate_limit_rps=0,
    )


def make_loader(session):
    return GrowwLoader(make_config([LARGE_CAP_URL, ELSS_URL]), session=session, sleep=lambda _: None)


def test_extract_document_keeps_main_content_only() -> None:
    document = extract_document(LARGE_CAP_URL, LARGE_CAP_HTML)

    assert document.page_title == "HDFC Large Cap Fund"
    assert document.scheme == "HDFC Large Cap Fund"
    assert document.category == "large_cap"
    assert "expense ratio is 0.75%" in document.text
    assert "minimum SIP amount is Rs 500" in document.text
    assert "tracking" not in document.text
    assert "Footer junk" not in document.text
    assert "Menu Link" not in document.text
    assert "Site header" not in document.text
    assert document.extraction_warning is None
    assert document.http_status == 200


def test_page_identity_for_amc_and_elss() -> None:
    amc = extract_document(AMC_URL, "<html><body><main>HDFC Mutual Fund</main></body></html>")
    elss = extract_document(ELSS_URL, "<html><body><main>ELSS</main></body></html>")

    assert (amc.scheme, amc.category) == ("HDFC Mutual Fund", "amc")
    assert (elss.scheme, elss.category) == ("HDFC ELSS Tax Saver Fund", "elss")


def test_low_text_content_sets_warning() -> None:
    document = extract_document(
        LARGE_CAP_URL, "<html><body><main><p>Too short</p></main></body></html>"
    )
    assert document.extraction_warning == "low_text_content"


def test_fetch_all_only_requests_configured_urls() -> None:
    session = FakeSession(
        {
            LARGE_CAP_URL: FakeResponse(LARGE_CAP_HTML),
            ELSS_URL: FakeResponse(LARGE_CAP_HTML.replace("Large Cap", "ELSS")),
        }
    )

    documents, manifest = make_loader(session).fetch_all()

    assert len(documents) == 2
    assert session.calls == [LARGE_CAP_URL, ELSS_URL]
    assert all(entry["status"] == "ok" for entry in manifest)


def test_redirects_are_not_followed() -> None:
    session = FakeSession(
        {
            LARGE_CAP_URL: FakeResponse(
                "", status_code=301, headers={"Location": "https://groww.in/other"}
            ),
            ELSS_URL: FakeResponse(LARGE_CAP_HTML),
        }
    )

    documents, manifest = make_loader(session).fetch_all()

    assert len(documents) == 1
    failure = next(entry for entry in manifest if entry["status"] == "failed")
    assert failure["http_status"] == 301
    assert "Redirect not followed" in failure["error"]
    assert session.calls == [LARGE_CAP_URL, ELSS_URL]


def test_fetch_all_continues_after_failure() -> None:
    session = FakeSession(
        {
            LARGE_CAP_URL: FakeResponse(LARGE_CAP_HTML),
            ELSS_URL: FakeResponse("not found", status_code=404),
        }
    )

    documents, manifest = make_loader(session).fetch_all()

    assert len(documents) == 1
    assert len(manifest) == 2
    failed = [entry for entry in manifest if entry["status"] == "failed"]
    assert len(failed) == 1
    assert failed[0]["source_url"] == ELSS_URL
    assert failed[0]["http_status"] == 404


def test_fetch_retries_transient_errors() -> None:
    session = FakeSession(
        {
            LARGE_CAP_URL: [
                FakeResponse("busy", status_code=503),
                FakeResponse("busy", status_code=503),
                FakeResponse(LARGE_CAP_HTML),
            ],
            ELSS_URL: FakeResponse(LARGE_CAP_HTML),
        }
    )
    loader_instance = GrowwLoader(
        make_config([LARGE_CAP_URL]),
        session=session,
        sleep=lambda _: None,
    )

    document = loader_instance.fetch(LARGE_CAP_URL)

    assert document.source_url == LARGE_CAP_URL
    assert len(session.calls) == 3


def test_fetch_raises_after_retry_exhaustion() -> None:
    session = FakeSession(
        {
            LARGE_CAP_URL: [
                FakeResponse("busy", status_code=500),
                FakeResponse("busy", status_code=500),
                FakeResponse("busy", status_code=500),
            ],
            ELSS_URL: FakeResponse(LARGE_CAP_HTML),
        }
    )
    loader_instance = GrowwLoader(
        make_config([LARGE_CAP_URL]),
        session=session,
        sleep=lambda _: None,
    )

    with pytest.raises(FetchError):
        loader_instance.fetch(LARGE_CAP_URL)


def test_network_exception_is_reported_in_manifest() -> None:
    session = FakeSession(
        {
            LARGE_CAP_URL: requests.ConnectionError("offline"),
            ELSS_URL: FakeResponse(LARGE_CAP_HTML),
        }
    )
    loader_instance = GrowwLoader(
        make_config([LARGE_CAP_URL, ELSS_URL]),
        session=session,
        sleep=lambda _: None,
    )

    documents, manifest = loader_instance.fetch_all()

    assert len(documents) == 1
    failure = [entry for entry in manifest if entry["status"] == "failed"][0]
    assert "offline" in failure["error"]
    assert failure["http_status"] is None


def test_scrape_writes_raw_artifacts_and_manifest(tmp_path) -> None:
    settings = load_config()
    settings = replace(
        settings,
        ingestion=replace(
            settings.ingestion,
            urls=[LARGE_CAP_URL, ELSS_URL],
            artifacts_dir=str(tmp_path),
            rate_limit_rps=0,
        ),
    )
    writer = ArtifactWriter(root=tmp_path, run_id="run-1")
    session = FakeSession(
        {
            LARGE_CAP_URL: FakeResponse(LARGE_CAP_HTML),
            ELSS_URL: FakeResponse(LARGE_CAP_HTML.replace("Large Cap", "ELSS")),
        }
    )

    result = scrape(settings, writer=writer, session=session)

    assert result.run_id == "run-1"
    assert result.manifest_path == tmp_path / "run-1" / "raw" / "manifest.json"
    assert (tmp_path / "run-1" / "run_meta.json").exists()

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert len(manifest) == 2
    for entry in manifest:
        assert entry["status"] == "ok"
        assert (tmp_path / "run-1" / entry["artifacts"]["html"]).exists()
        assert (tmp_path / "run-1" / entry["artifacts"]["text"]).exists()

    html_files = sorted((tmp_path / "run-1" / "raw" / "html").glob("*.html"))
    assert len(html_files) == 2


def test_extract_uses_heading_when_title_missing() -> None:
    document = extract_document(
        LARGE_CAP_URL,
        "<html><body><main><h1>Fallback Heading</h1>%s</main></body></html>"
        % ("<p>Fact goes here.</p>" * 30),
    )
    assert document.page_title == "Fallback Heading"


def test_fetched_at_defaults_to_utc() -> None:
    document = extract_document(LARGE_CAP_URL, LARGE_CAP_HTML)
    assert document.fetched_at.tzinfo is not None
    assert abs((datetime.now(timezone.utc) - document.fetched_at).total_seconds()) < 5
