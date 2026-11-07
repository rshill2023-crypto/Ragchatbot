"""Streamlit UI for the facts-only Groww MF FAQ assistant."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

import streamlit as st

from src.config import load_config
from src.ingestion.document_loader import find_latest_run
from src.pipeline import answer
from src.safety.pii import detect_pii

DISCLAIMER = "Facts-only. No investment advice."
EXAMPLES = (
    "What is the expense ratio of HDFC Flexi Cap?",
    "What is the ELSS lock-in period?",
    "What is the minimum SIP amount?",
)

st.set_page_config(
    page_title="Groww MF FAQ Assistant",
    page_icon=":bar_chart:",
    layout="centered",
)

st.title("Groww Mutual Fund FAQ Assistant")
st.caption(
    "Ask factual questions about the five configured HDFC fund pages. "
    "Every answer cites one official Groww source."
)
st.info(DISCLAIMER)

try:
    config = load_config()
except Exception as exc:  # pragma: no cover - configuration failure in UI
    st.error("Configuration error: %s" % exc)
    st.stop()

with st.sidebar:
    st.subheader("Scope")
    st.write("AMC overview + four HDFC schemes:")
    for url in config.ingestion.urls:
        st.markdown("- [%s](%s)" % (url.rsplit("/", 1)[-1], url))
    st.divider()
    st.caption(
        "This demo answers only from the saved Groww pages. "
        "It does not browse internal links or the live web."
    )

if "messages" not in st.session_state:
    st.session_state.messages = []


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _render_trace(query_id: str) -> None:
    try:
        run_dir = find_latest_run(Path(config.ingestion.artifacts_dir))
    except Exception as exc:
        st.caption("Trace unavailable: %s" % exc)
        return

    retrieval_path = run_dir / "retrieval" / ("%s.json" % query_id)
    prompt_path = run_dir / "prompts" / ("%s.txt" % query_id)
    response_path = run_dir / "responses" / ("%s.json" % query_id)
    guardrail_path = run_dir / "guardrails" / ("%s.json" % query_id)

    st.caption("Run: `%s`" % run_dir.name)
    for label, path in (
        ("Retrieval trace", retrieval_path),
        ("Prompt", prompt_path),
        ("Response trace", response_path),
        ("Guardrail trace", guardrail_path),
    ):
        st.write("%s: `%s`" % (label, path.relative_to(run_dir)))

    retrieval = _load_json(retrieval_path)
    if retrieval:
        st.markdown("**Retrieved chunks**")
        st.json(retrieval.get("results", []))

    if prompt_path.is_file():
        with st.expander("Prompt sent to the model"):
            st.code(prompt_path.read_text(encoding="utf-8"))

    response = _load_json(response_path)
    if response:
        with st.expander("Raw generation metadata"):
            st.json(
                {
                    "provider": response.get("provider"),
                    "model": response.get("model"),
                    "latency_ms": response.get("latency_ms"),
                    "error": response.get("error"),
                }
            )


def _render_message(message: Dict[str, Any]) -> None:
    role = message["role"]
    with st.chat_message(role):
        if role == "user":
            st.markdown(message["text"])
            return

        if message.get("refused"):
            st.warning(message["text"])
        else:
            st.markdown(message["text"])

        source_url = message.get("source_url")
        if source_url:
            st.link_button("Open official source", source_url)

        with st.expander("Show RAG trace"):
            _render_trace(message["query_id"])


for message in st.session_state.messages:
    _render_message(message)

example_columns = st.columns(3)
clicked_example = None
for column, example in zip(example_columns, EXAMPLES):
    if column.button(example, use_container_width=True):
        clicked_example = example

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
