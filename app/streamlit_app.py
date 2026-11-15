"""Streamlit UI for the facts-only Groww MF FAQ assistant."""

from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import streamlit as st

from src.config import load_config
from src.ingestion.document_loader import find_latest_run
from src.pipeline import answer
from src.safety.pii import detect_pii
from src.safety.templates import latest_source_date

DISCLAIMER = "Facts-only. No investment advice."
EXAMPLES = (
    "What is the expense ratio of HDFC Flexi Cap?",
    "What is the ELSS lock-in period?",
    "What is the minimum SIP amount?",
)
FUND_LIBRARY = (
    ("HDFC Flexi Cap", "Equity · Direct Growth", "Selected"),
    ("HDFC ELSS Tax Saver", "Tax saver · Direct Plan", "3Y lock-in"),
    ("HDFC Large Cap", "Equity · Direct Growth", "Large cap"),
    ("HDFC Mid Cap", "Equity · Direct Growth", "Mid cap"),
    ("HDFC Mutual Funds", "AMC overview", "Directory"),
)

GROWW_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

:root {
    --gw-mint: #00D09C;
    --gw-mint-deep: #00B386;
    --gw-mint-accent: #04B488;
    --gw-mint-soft: #E0F8EE;
    --gw-ink: #44475B;
    --gw-border: #F0F0F2;
    --gw-white: #FFFFFF;
    --gw-shadow: 0 2px 8px rgba(68, 71, 91, 0.04);
    --gw-shadow-lg: 0 8px 24px rgba(68, 71, 91, 0.08);
}

html, body, [class*="css"] {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
}

.stApp {
    background: var(--gw-white);
    color: var(--gw-ink);
}

header[data-testid="stHeader"],
#MainMenu,
footer,
[data-testid="stToolbar"] {
    display: none;
}

.block-container {
    max-width: 1240px;
    padding: 0 24px 56px;
}

.gw-header {
    position: sticky;
    top: 0;
    z-index: 50;
    margin: 0 -24px 24px;
    background: rgba(255, 255, 255, 0.96);
    border-bottom: 1px solid var(--gw-border);
    backdrop-filter: blur(12px);
}

.gw-header-inner {
    max-width: 1192px;
    margin: 0 auto;
    padding: 14px 24px;
    display: flex;
    align-items: center;
    gap: 24px;
}

.gw-brand {
    display: flex;
    align-items: center;
    gap: 10px;
    color: var(--gw-ink);
    font-size: 16px;
    font-weight: 600;
    letter-spacing: -0.01em;
    white-space: nowrap;
}

.gw-brand-dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background: var(--gw-mint);
    box-shadow: 0 0 0 4px var(--gw-mint-soft);
}

.gw-nav {
    display: flex;
    gap: 6px;
}

.gw-nav a {
    padding: 8px 12px;
    border-radius: 8px;
    color: rgba(68, 71, 91, 0.65);
    font-size: 14px;
    font-weight: 500;
    text-decoration: none;
}

.gw-nav a:hover {
    color: var(--gw-ink);
    background: var(--gw-mint-soft);
}

.gw-nav a.active {
    color: var(--gw-mint-deep);
    background: var(--gw-mint-soft);
}

.gw-header-actions {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-left: auto;
}

.gw-pill {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 5px 10px;
    border-radius: 999px;
    background: var(--gw-mint-soft);
    color: var(--gw-mint-deep);
    font-size: 12px;
    font-weight: 500;
    white-space: nowrap;
}

.gw-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--gw-mint);
}

.gw-new-chat {
    padding: 9px 14px;
    border-radius: 10px;
    background: var(--gw-mint);
    color: var(--gw-white) !important;
    font-size: 14px;
    font-weight: 600;
    text-decoration: none;
    white-space: nowrap;
}

.gw-new-chat:hover {
    background: var(--gw-mint-deep);
}

.gw-panel {
    margin-bottom: 16px;
    padding: 18px;
    border: 1px solid var(--gw-border);
    border-radius: 16px;
    background: var(--gw-white);
    box-shadow: var(--gw-shadow);
}

.gw-panel-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    margin-bottom: 12px;
}

.gw-eyebrow {
    color: rgba(68, 71, 91, 0.55);
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.06em;
    text-transform: uppercase;
}

.gw-chip {
    padding: 3px 8px;
    border-radius: 999px;
    background: var(--gw-mint-soft);
    color: var(--gw-mint-deep);
    font-size: 11px;
    font-weight: 500;
    white-space: nowrap;
}

.gw-panel-title {
    margin: 0;
    color: var(--gw-ink);
    font-size: 15px;
    font-weight: 600;
}

.gw-fund-list {
    display: flex;
    flex-direction: column;
    gap: 6px;
}

.gw-fund-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    padding: 11px 12px;
    border-left: 3px solid transparent;
    border-radius: 12px;
}

.gw-fund-row.selected {
    border-left-color: var(--gw-mint-deep);
    background: var(--gw-mint-soft);
}

.gw-fund-name {
    color: var(--gw-ink);
    font-size: 13px;
    font-weight: 600;
}

.gw-fund-meta {
    margin-top: 2px;
    color: rgba(68, 71, 91, 0.55);
    font-size: 11px;
}

.gw-fund-right {
    color: rgba(68, 71, 91, 0.45);
    font-size: 10px;
    white-space: nowrap;
}

.gw-panel-foot {
    margin-top: 16px;
    padding-top: 14px;
    border-top: 1px solid var(--gw-border);
}

.gw-verified {
    display: flex;
    align-items: center;
    gap: 6px;
    color: var(--gw-mint-deep);
    font-size: 12px;
    font-weight: 600;
}

.gw-muted {
    color: rgba(68, 71, 91, 0.55);
    font-size: 11px;
    line-height: 17px;
}

.gw-stat {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 5px 0;
    font-size: 12px;
}

.gw-stat span {
    color: rgba(68, 71, 91, 0.55);
}

.gw-stat strong {
    color: var(--gw-ink);
    font-weight: 600;
    text-align: right;
}

.gw-pills {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-top: 10px;
}

.gw-disclaimer {
    border-color: rgba(0, 208, 156, 0.24);
    background: var(--gw-mint-soft);
}

.gw-disclaimer h3 {
    margin: 0 0 6px;
    color: var(--gw-mint-deep);
    font-size: 14px;
    font-weight: 600;
}

.gw-disclaimer p {
    margin: 0;
    color: rgba(68, 71, 91, 0.62);
    font-size: 11px;
    line-height: 17px;
}

h1 {
    margin: 0 0 6px !important;
    padding: 0 !important;
    color: var(--gw-ink) !important;
    font-size: 22px !important;
    font-weight: 600 !important;
    letter-spacing: -0.015em !important;
    line-height: 30px !important;
}

.gw-subtitle {
    margin: 0 0 14px;
    color: rgba(68, 71, 91, 0.6);
    font-size: 13px;
    line-height: 20px;
}

.gw-example-label {
    margin: 2px 0 8px;
    color: rgba(68, 71, 91, 0.45);
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.06em;
    text-transform: uppercase;
}

.stButton > button {
    width: 100%;
    min-height: 40px;
    padding: 8px 12px;
    border: 1px solid var(--gw-border);
    border-radius: 999px;
    background: var(--gw-white);
    box-shadow: none;
    color: var(--gw-ink);
    font-size: 12px;
    font-weight: 500;
    line-height: 16px;
    white-space: normal;
}

.stButton > button:hover {
    border-color: var(--gw-mint);
    background: var(--gw-mint-soft);
    color: var(--gw-mint-deep);
}

.stButton > button:focus:not(:active) {
    border-color: var(--gw-mint);
    box-shadow: 0 0 0 2px rgba(0, 208, 156, 0.16);
}

.gw-user-row {
    display: flex;
    justify-content: flex-end;
    margin: 12px 0;
}

.gw-user-bubble {
    max-width: 82%;
    padding: 12px 14px;
    border: 1px solid var(--gw-border);
    border-radius: 16px 16px 4px 16px;
    background: var(--gw-mint-soft);
    box-shadow: var(--gw-shadow);
    color: var(--gw-ink);
    font-size: 14px;
    line-height: 20px;
}

.gw-card {
    margin: 0 0 14px;
    padding: 18px;
    border: 1px solid var(--gw-border);
    border-radius: 16px;
    background: var(--gw-white);
    box-shadow: var(--gw-shadow);
}

.gw-refusal {
    border-left: 3px solid var(--gw-ink);
    background: var(--gw-white);
}

.gw-card-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 12px;
    padding-bottom: 10px;
    border-bottom: 1px solid var(--gw-border);
}

.gw-bot {
    display: flex;
    align-items: center;
    gap: 8px;
    color: var(--gw-ink);
    font-size: 14px;
    font-weight: 600;
}

.gw-bot-dot {
    width: 9px;
    height: 9px;
    border-radius: 50%;
    background: var(--gw-mint);
}

.gw-badge {
    padding: 3px 8px;
    border-radius: 999px;
    background: var(--gw-mint-soft);
    color: var(--gw-mint-deep);
    font-size: 10px;
    font-weight: 500;
    white-space: nowrap;
}

.gw-source {
    color: rgba(68, 71, 91, 0.58);
    font-size: 11px;
    font-weight: 500;
    text-decoration: none;
    white-space: nowrap;
}

.gw-source:hover {
    color: var(--gw-mint-deep);
}

.gw-answer {
    color: var(--gw-ink);
    font-size: 14px;
    line-height: 22px;
}

.gw-trace {
    margin-top: 14px;
    overflow: hidden;
    border: 1px solid var(--gw-border);
    border-radius: 12px;
    background: var(--gw-white);
}

.gw-trace summary {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 10px 12px;
    background: rgba(240, 240, 242, 0.55);
    color: var(--gw-ink);
    font-size: 12px;
    font-weight: 500;
    list-style: none;
    cursor: pointer;
}

.gw-trace summary::-webkit-details-marker {
    display: none;
}

.gw-trace-body {
    padding: 12px;
    border-top: 1px solid var(--gw-border);
    color: rgba(68, 71, 91, 0.62);
    font-size: 11px;
    line-height: 17px;
}

.gw-chunk {
    padding: 8px 0;
    border-bottom: 1px solid var(--gw-border);
}

.gw-chunk:last-child {
    border-bottom: 0;
    padding-bottom: 0;
}

.gw-chunk strong {
    color: var(--gw-ink);
    font-weight: 600;
}

.gw-empty {
    padding: 16px 0 4px;
    color: rgba(68, 71, 91, 0.55);
    font-size: 12px;
}

[data-testid="stChatInput"] {
    padding: 4px;
    border: 1px solid var(--gw-border);
    border-radius: 16px;
    background: var(--gw-white);
    box-shadow: var(--gw-shadow);
}

[data-testid="stChatInput"]:focus-within {
    border-color: var(--gw-mint);
    box-shadow: 0 0 0 2px rgba(0, 208, 156, 0.14);
}

[data-testid="stChatInput"] textarea {
    color: var(--gw-ink);
    font-size: 14px;
}

[data-testid="stChatInput"] button {
    border-radius: 10px !important;
    background: var(--gw-mint) !important;
    color: var(--gw-white) !important;
}

[data-testid="stChatInput"] button:hover {
    background: var(--gw-mint-deep) !important;
}

[data-testid="stAlert"] {
    border: 1px solid var(--gw-border);
    border-radius: 12px;
    background: var(--gw-white);
    color: var(--gw-ink);
}

[data-testid="stAlert"] p {
    color: var(--gw-ink);
    font-size: 12px;
}

@media (max-width: 900px) {
    .gw-header {
        margin: 0 -14px 18px;
    }

    .gw-header-inner {
        gap: 12px;
        padding: 12px 14px;
    }

    .gw-nav,
    .gw-pill {
        display: none;
    }

    .gw-new-chat {
        padding: 8px 11px;
        font-size: 13px;
    }

    .block-container {
        padding: 0 14px 40px;
    }

    h1 {
        font-size: 20px !important;
        line-height: 28px !important;
    }

    .gw-panel {
        padding: 15px;
    }

    .gw-card {
        padding: 15px;
    }
}
</style>
"""


def _format_source_date(value: str) -> str:
    if not value:
        return "Not available"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.strftime("%d %b %Y")
    except ValueError:
        return value[:10]


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _header_html() -> str:
    return """
    <div class="gw-header">
      <div class="gw-header-inner">
        <div class="gw-brand">
          <span class="gw-brand-dot"></span>
          <span>Groww MF FAQ</span>
        </div>
        <nav class="gw-nav" aria-label="Primary">
          <a class="active" href="#ask">Ask</a>
          <a href="#fund-library">Fund library</a>
          <a href="#sources">Sources</a>
        </nav>
        <div class="gw-header-actions">
          <span class="gw-pill"><span class="gw-dot"></span>Facts only</span>
          <a class="gw-new-chat" href="?new_chat=1">New chat</a>
        </div>
      </div>
    </div>
    """


def _fund_library_html() -> str:
    rows = []
    for name, meta, right in FUND_LIBRARY:
        selected = " selected" if right == "Selected" else ""
        rows.append(
            """
            <div class="gw-fund-row%s">
              <div>
                <div class="gw-fund-name">%s</div>
                <div class="gw-fund-meta">%s</div>
              </div>
              <span class="gw-fund-right">%s</span>
            </div>
            """
            % (selected, html.escape(name), html.escape(meta), html.escape(right))
        )
    return """
    <div id="fund-library" class="gw-panel">
      <div class="gw-panel-head">
        <span class="gw-eyebrow">Fund library</span>
        <span class="gw-chip">HDFC AMC</span>
      </div>
      <div class="gw-fund-list">%s</div>
      <div class="gw-panel-foot">
        <div class="gw-verified">✓ Official sources only</div>
        <div class="gw-muted">Verified SID / KIM corpus</div>
      </div>
    </div>
    """ % "".join(rows)


def _context_html(config: Any) -> str:
    source_count = len(config.ingestion.urls)
    source_date = _format_source_date(latest_source_date(config))
    return """
    <div id="sources" class="gw-panel">
      <div class="gw-panel-head">
        <span class="gw-eyebrow">Corpus scope</span>
        <span class="gw-dot"></span>
      </div>
      <h2 class="gw-panel-title">HDFC mutual funds</h2>
      <p class="gw-muted">AMC overview + four direct plans</p>
      <div style="margin-top:12px;padding-top:10px;border-top:1px solid var(--gw-border);">
        <div class="gw-stat"><span>Audit source</span><strong>%s verified pages</strong></div>
        <div class="gw-stat"><span>Last validated</span><strong>%s</strong></div>
      </div>
      <div class="gw-pills">
        <span class="gw-chip">Facts only</span>
        <span class="gw-chip">Official filings</span>
        <span class="gw-chip">No advice</span>
      </div>
    </div>
    <div class="gw-panel gw-disclaimer">
      <h3>Facts-only. No advice.</h3>
      <p>
        All answers are grounded in official Groww fund pages.
        Mutual fund investments are subject to market risks.
      </p>
    </div>
    <div class="gw-panel">
      <div class="gw-eyebrow">Answer contract</div>
      <div style="margin-top:8px;">
        <div class="gw-stat"><span>Citations</span><strong>Exactly one</strong></div>
        <div class="gw-stat"><span>Length</span><strong>Maximum 3 sentences</strong></div>
        <div class="gw-stat"><span>Advice</span><strong>Never</strong></div>
      </div>
    </div>
    """ % (source_count, html.escape(source_date))


def _trace_html(query_id: Optional[str], config: Any) -> str:
    if not query_id:
        return ""
    try:
        run_dir = find_latest_run(Path(config.ingestion.artifacts_dir))
    except Exception as exc:
        return """
        <details class="gw-trace">
          <summary><span>How this answer was found</span><span>Trace unavailable</span></summary>
          <div class="gw-trace-body">%s</div>
        </details>
        """ % html.escape(str(exc))

    retrieval = _load_json(run_dir / "retrieval" / ("%s.json" % query_id)) or {}
    results = retrieval.get("results", [])[:3]
    chunks = []
    for result in results:
        source = str(result.get("source_url", ""))
        score = result.get("score")
        section = str(result.get("section", "Fund facts"))
        score_text = "%.3f" % score if isinstance(score, (int, float)) else "n/a"
        chunks.append(
            """
            <div class="gw-chunk">
              <strong>%s</strong><br/>
              %s · score %s
            </div>
            """
            % (
                html.escape(section),
                html.escape(source.rsplit("/", 1)[-1]),
                html.escape(score_text),
            )
        )
    body = "".join(chunks) or '<div class="gw-muted">No retrieval rows stored.</div>'
    return """
    <details class="gw-trace">
      <summary>
        <span>How this answer was found</span>
        <span>%s chunk(s)</span>
      </summary>
      <div class="gw-trace-body">
        <div style="margin-bottom:6px;">Run: %s</div>
        %s
      </div>
    </details>
    """ % (len(results), html.escape(run_dir.name), body)


def _assistant_card_html(message: Dict[str, Any], config: Any) -> str:
    refused = bool(message.get("refused"))
    source_url = str(message.get("source_url") or "")
    allowed = set(config.sources.allowlist)
    if source_url in allowed:
        source = """
        <a class="gw-source" href="%s" target="_blank" rel="noopener noreferrer">
          groww.in ↗
        </a>
        """ % html.escape(source_url, quote=True)
    else:
        source = '<span class="gw-source">Official source</span>'

    badge = "Scope notice" if refused else "Official source"
    card_class = "gw-card gw-refusal" if refused else "gw-card"
    answer_html = html.escape(str(message.get("text", ""))).replace("\n", "<br/>")
    trace = _trace_html(message.get("query_id"), config)
    return """
    <article class="%s">
      <div class="gw-card-head">
        <div class="gw-bot">
          <span class="gw-bot-dot"></span>
          <span>Groww MF Bot</span>
          <span class="gw-badge">%s</span>
        </div>
        %s
      </div>
      <div class="gw-answer">%s</div>
      %s
    </article>
    """ % (card_class, html.escape(badge), source, answer_html, trace)


def _render_message(message: Dict[str, Any], config: Any) -> None:
    if message["role"] == "user":
        st.html(
            '<div class="gw-user-row"><div class="gw-user-bubble">%s</div></div>'
            % html.escape(str(message["text"]))
        )
        return
    st.html(_assistant_card_html(message, config))


st.set_page_config(
    page_title="Groww MF FAQ Assistant",
    page_icon=":bar_chart:",
    layout="wide",
)

st.html(GROWW_CSS)

if "messages" not in st.session_state:
    st.session_state.messages = []

if st.query_params.get("new_chat"):
    st.session_state.messages = []
    st.query_params.clear()
    st.rerun()

try:
    config = load_config()
except Exception as exc:  # pragma: no cover - configuration failure in UI
    st.error("Configuration error: %s" % exc)
    st.stop()

st.html(_header_html())

left, center, right = st.columns([0.92, 2.36, 1.02], gap="large")

with left:
    st.html(_fund_library_html())

with right:
    st.html(_context_html(config))

with center:
    st.html('<div id="ask"></div>')
    st.title("Ask a factual question about HDFC mutual funds")
    st.html(
        '<p class="gw-subtitle">Answers come only from official Groww fund pages. No advice.</p>'
    )
    st.html('<div class="gw-example-label">Example questions</div>')

    example_columns = st.columns(3)
    clicked_example = None
    for column, example in zip(example_columns, EXAMPLES):
        if column.button(example, use_container_width=True):
            clicked_example = example

    if st.session_state.messages:
        for message in st.session_state.messages:
            _render_message(message, config)
    else:
        st.html(
            '<div class="gw-empty">'
            "Start with an example above or ask your own factual question."
            "</div>"
        )

    typed_question = st.chat_input("Ask a factual mutual fund question...")
    question = typed_question or clicked_example

    if question:
        pii = detect_pii(question)
        display_question = (
            "[redacted: sensitive information]" if pii is not None else question
        )
        st.session_state.messages.append(
            {"role": "user", "text": display_question}
        )

        try:
            with st.spinner("Retrieving from official sources and drafting an answer..."):
                result = answer(config, question)
            st.session_state.messages.append(
                {
                    "role": "assistant",
                    "text": result.text,
                    "refused": result.refused,
                    "source_url": result.source_url,
                    "query_id": result.trace_id,
                }
            )
        except Exception as exc:  # pragma: no cover - surfaced to the user in UI
            st.error(
                "I could not answer that right now. Make sure ingestion completed "
                "with `make ingest`. Details: %s" % exc
            )

        st.rerun()
