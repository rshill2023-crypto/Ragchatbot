"""Streamlit UI smoke tests using Streamlit's app test harness."""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src.config import load_config
from src.ingestion.document_loader import find_latest_run

APP_PATH = Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py"


def _has_artifacts() -> bool:
    try:
        find_latest_run(Path(load_config().ingestion.artifacts_dir))
    except Exception:
        return False
    return True


def test_app_renders_disclaimer_and_examples():
    app = AppTest.from_file(str(APP_PATH), default_timeout=20)
    app.run()

    assert not app.exception
    assert app.title[0].value == "Groww Mutual Fund FAQ Assistant"
    assert len(app.button) == 3
    assert app.chat_input[0].placeholder == "Ask a factual mutual fund question..."


@pytest.mark.skipif(not _has_artifacts(), reason="ingestion artifacts are required")
def test_example_click_produces_an_answer():
    app = AppTest.from_file(str(APP_PATH), default_timeout=30)
    app.run()

    app.button[0].click().run()

    assert not app.exception
    messages = app.session_state["messages"]
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[1]["role"] == "assistant"
    assert messages[1]["source_url"].startswith("https://groww.in/")
    assert "http" in messages[1]["text"]
