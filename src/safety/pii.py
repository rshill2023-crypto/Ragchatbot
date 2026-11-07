"""PII detection for the pre-retrieval guardrail.

Only a coarse match is returned; callers must never log or persist the matched
value itself. The pipeline stores only the PII category in guardrail traces.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class PIIMatch:
    kind: str
    start: int
    end: int


_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_PAN = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b", re.IGNORECASE)
_AADHAAR_CONTEXT = re.compile(
    r"\b(?:aadhaar|aadhar|uidai)\b[^\d]{0,30}(\d{4}[\s-]?\d{4}[\s-]?\d{4})\b",
    re.IGNORECASE,
)
_AADHAAR = re.compile(r"(?<!\d)\d{4}[\s-]?\d{4}[\s-]?\d{4}(?!\d)")
_ACCOUNT = re.compile(
    r"\b(?:account|a/c|acct)\b[^\d]{0,30}(\d{9,18})(?!\d)",
    re.IGNORECASE,
)
_OTP = re.compile(
    r"\b(?:otp|one[\s-]?time\s+(?:password|code)|verification\s+code)\b"
    r"[^\d]{0,20}(\d{4,8})\b",
    re.IGNORECASE,
)
_PHONE = re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{9}(?!\d)")


def detect_pii(text: str) -> Optional[PIIMatch]:
    """Return the first PII match, or None. The value is never returned."""
    value = text or ""

    for kind, pattern in (
        ("email", _EMAIL),
        ("pan", _PAN),
        ("aadhaar", _AADHAAR_CONTEXT),
        ("account", _ACCOUNT),
        ("otp", _OTP),
        ("phone", _PHONE),
        ("aadhaar", _AADHAAR),
    ):
        match = pattern.search(value)
        if match is not None:
            start, end = match.span(1) if match.lastindex else match.span()
            return PIIMatch(kind=kind, start=start, end=end)

    return None


def contains_pii(text: str) -> bool:
    return detect_pii(text) is not None
