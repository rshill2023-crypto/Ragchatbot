"""Rule-based intent routing for factual vs advice vs off-topic queries."""

from __future__ import annotations

import re
from dataclasses import dataclass

FACTUAL = "factual"
ADVICE = "advice"
OFF_TOPIC = "off_topic"
MIXED = "mixed"
EMPTY = "empty"
TOO_LONG = "too_long"

MAX_QUERY_CHARS = 500

_DOMAIN_TERMS = (
    "mutual fund",
    "mutual-fund",
    "fund",
    "scheme",
    "amc",
    "hdfc",
    "sip",
    "elss",
    "nav",
    "aum",
    "expense ratio",
    "expense",
    "exit load",
    "lock-in",
    "lock in",
    "riskometer",
    "risk",
    "benchmark",
    "large cap",
    "mid cap",
    "flexi cap",
    "small cap",
    "statement",
    "capital gain",
    "redemption",
    "folio",
    "minimum investment",
    "minimum sip",
)

_FACTUAL_HINTS = (
    "what is",
    "what are",
    "how to",
    "how do",
    "how can",
    "how much",
    "when is",
    "where can",
    "expense ratio",
    "exit load",
    "lock-in",
    "lock in",
    "minimum sip",
    "minimum investment",
    "riskometer",
    "benchmark",
    "nav",
    "aum",
    "statement",
    "capital gain",
    "redemption",
)

_ADVICE_PATTERNS = (
    r"\bshould\s+(?:i|we|you)\b",
    r"\bbuy\s+or\s+sell\b",
    r"\bsell\s+or\s+buy\b",
    r"\bwhich\s+(?:fund|scheme|one)\b.*\b(?:better|best|choose|pick)\b",
    r"\bwhich\s+is\s+better\b",
    r"\bbetter\s+(?:fund|scheme|option)\b",
    r"\bbest\s+(?:fund|scheme|option)\b",
    r"\brecommend\b",
    r"\bsuggest\s+(?:a\s+)?(?:fund|scheme|investment)\b",
    r"\bwill\s+(?:this|it|the\s+fund)\b.*\b(?:give|generate|produce|earn)\b",
    r"\bgood\s+returns?\b",
    r"\bguaranteed\s+returns?\b",
    r"\bworth\s+(?:investing|buying)\b",
    r"\bcompare\s+(?:returns?|funds?|schemes?)\b",
    r"\b(?:invest|put\s+money)\s+in\b",
    r"\bportfolio\b",
    r"\bmultibagger\b",
    r"\bhow\s+much\s+should\s+i\s+invest\b",
    r"\bis\s+it\s+good\s+to\s+invest\b",
)

_INJECTION_PATTERNS = (
    r"ignore\s+(?:all|any|the)?\s*rules",
    r"ignore\s+(?:all|any|the)?\s*instructions",
    r"system\s+prompt",
    r"jailbreak",
    r"act\s+as\s+(?:a|an)\s+",
    r"give\s+me\s+(?:investment\s+)?advice",
)


@dataclass(frozen=True)
class Intent:
    label: str
    reason: str


def _matches(text: str, patterns) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def _contains_any(text: str, terms) -> bool:
    return any(term in text for term in terms)


def classify_intent(query: str) -> Intent:
    text = (query or "").strip()
    lowered = text.lower()

    if not text:
        return Intent(EMPTY, "empty query")
    if len(text) > MAX_QUERY_CHARS:
        return Intent(TOO_LONG, "query exceeds %d characters" % MAX_QUERY_CHARS)
    if _matches(text, _INJECTION_PATTERNS):
        return Intent(ADVICE, "prompt injection or advice request")

    has_domain = _contains_any(lowered, _DOMAIN_TERMS)
    has_factual_hint = _contains_any(lowered, _FACTUAL_HINTS)
    has_advice = _matches(text, _ADVICE_PATTERNS)

    if has_advice and has_factual_hint and has_domain:
        return Intent(MIXED, "factual question combined with an advice request")
    if has_advice:
        return Intent(ADVICE, "advice or performance request")
    if not has_domain:
        return Intent(OFF_TOPIC, "no mutual fund scope term found")
    return Intent(FACTUAL, "factual mutual fund query")
