"""Safe refusal and limitation templates.

Refusals never include user PII and always include exactly one official link.
"""

from __future__ import annotations

from ..config import Settings
from ..models import Answer


def official_link(settings: Settings) -> str:
    sources = settings.sources
    if sources.educational_links:
        return sources.educational_links[0]
    if sources.allowlist:
        return sources.allowlist[0]
    return ""


def _answer(text: str, settings: Settings, trace_id: str = "") -> Answer:
    link = official_link(settings)
    body = text.strip()
    if link and link not in body:
        body = "%s %s" % (body, link)
    return Answer(
        text=body,
        source_url=link,
        last_updated="",
        refused=True,
        trace_id=trace_id,
    )


def advice_refusal(settings: Settings, trace_id: str = "") -> Answer:
    return _answer(
        "I can only answer factual questions from official Groww pages and "
        "cannot provide investment advice. For educational information, see",
        settings,
        trace_id,
    )


def off_topic_refusal(settings: Settings, trace_id: str = "") -> Answer:
    return _answer(
        "I can only answer factual questions about the configured HDFC mutual "
        "fund pages. You can explore the official AMC overview at",
        settings,
        trace_id,
    )


def pii_refusal(settings: Settings, trace_id: str = "") -> Answer:
    return _answer(
        "I cannot process messages containing PAN, Aadhaar, account, OTP, email, "
        "or phone details. Please remove the sensitive information and ask a "
        "factual mutual fund question; for general information, see",
        settings,
        trace_id,
    )


def empty_refusal(settings: Settings, trace_id: str = "") -> Answer:
    return _answer(
        "Please ask a factual mutual fund question, such as expense ratio, exit "
        "load, minimum SIP, or ELSS lock-in. You can start from",
        settings,
        trace_id,
    )


def too_long_refusal(settings: Settings, trace_id: str = "") -> Answer:
    return _answer(
        "Please shorten your question to under 500 characters and ask one "
        "factual mutual fund question. For official details, see",
        settings,
        trace_id,
    )


def not_found_text() -> str:
    return "I could not find this in the provided sources."


def refusal_from_decision(decision: str, settings: Settings, trace_id: str = "") -> Answer:
    if decision == "pii":
        return pii_refusal(settings, trace_id)
    if decision == "advice":
        return advice_refusal(settings, trace_id)
    if decision == "empty":
        return empty_refusal(settings, trace_id)
    if decision == "too_long":
        return too_long_refusal(settings, trace_id)
    return off_topic_refusal(settings, trace_id)


def with_note(text: str, note: str) -> str:
    """Append a sentence inside the factual body, before citation metadata."""
    marker = "\n\nSource:"
    if marker in text:
        body, rest = text.split(marker, 1)
        return "%s %s%s" % (body.rstrip(), note, marker + rest)
    return "%s %s" % (text.rstrip(), note)


def latest_source_date(settings: Settings) -> str:
    """Return a best-effort date from the latest loaded run, if available."""
    try:
        import json
        from pathlib import Path

        from ..ingestion.document_loader import find_latest_run

        run_dir = find_latest_run(Path(settings.ingestion.artifacts_dir))
        loaded = run_dir / "loaded" / "documents.jsonl"
        if not loaded.is_file():
            return ""
        for line in loaded.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            value = record.get("fetched_at")
            if value:
                return str(value)
    except Exception:
        return ""
    return ""

