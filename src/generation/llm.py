"""Provider-agnostic LLM adapters.

Groq is the default and only provider installed by the base requirements. Other
adapters import their SDK lazily so the app still starts when they are absent.
"""

from __future__ import annotations

import logging
import os
from typing import Optional, Protocol

from ..config import LLMConfig

LOGGER = logging.getLogger(__name__)


class LLMError(RuntimeError):
    """Raised when an LLM provider cannot be built or called."""


class LLM(Protocol):
    name: str
    model: str

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        ...


class GroqLLM:
    name = "groq"

    def __init__(self, config: LLMConfig) -> None:
        self.model = config.model
        self.temperature = config.temperature
        api_key = os.getenv("GROQ_API_KEY", "").strip()
        if not api_key:
            raise LLMError("GROQ_API_KEY is not set; using extractive fallback")
        try:
            from groq import Groq
        except ImportError as exc:  # pragma: no cover - install issue
            raise LLMError("groq is not installed; run `make install`") from exc
        self._client = Groq(api_key=api_key, timeout=30.0)

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        response = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=self.temperature,
            max_tokens=350,
        )
        content = response.choices[0].message.content or ""
        if not content.strip():
            raise LLMError("Groq returned an empty response")
        return content.strip()


class OpenAILLM:
    name = "openai"

    def __init__(self, config: LLMConfig) -> None:
        self.model = config.model
        self.temperature = config.temperature
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise LLMError("OPENAI_API_KEY is not set")
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - optional provider
            raise LLMError("openai is not installed") from exc
        self._client = OpenAI(api_key=api_key, timeout=30.0)

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        response = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=self.temperature,
            max_tokens=350,
        )
        return (response.choices[0].message.content or "").strip()


class AnthropicLLM:
    name = "anthropic"

    def __init__(self, config: LLMConfig) -> None:
        self.model = config.model
        self.temperature = config.temperature
        api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
        if not api_key:
            raise LLMError("ANTHROPIC_API_KEY is not set")
        try:
            from anthropic import Anthropic
        except ImportError as exc:  # pragma: no cover - optional provider
            raise LLMError("anthropic is not installed") from exc
        self._client = Anthropic(api_key=api_key, timeout=30.0)

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        response = self._client.messages.create(
            model=self.model,
            max_tokens=350,
            temperature=self.temperature,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        parts = [getattr(block, "text", "") for block in response.content]
        return " ".join(part for part in parts if part).strip()


class MistralLLM:
    name = "mistral"

    def __init__(self, config: LLMConfig) -> None:
        self.model = config.model
        self.temperature = config.temperature
        api_key = os.getenv("MISTRAL_API_KEY", "").strip()
        if not api_key:
            raise LLMError("MISTRAL_API_KEY is not set")
        try:
            from mistralai import Mistral
        except ImportError as exc:  # pragma: no cover - optional provider
            raise LLMError("mistralai is not installed") from exc
        self._client = Mistral(api_key=api_key)

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        response = self._client.chat.complete(
            model=self.model,
            temperature=self.temperature,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return (response.choices[0].message.content or "").strip()


class GeminiLLM:
    name = "gemini"

    def __init__(self, config: LLMConfig) -> None:
        self.model = config.model
        self.temperature = config.temperature
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if not api_key:
            raise LLMError("GEMINI_API_KEY is not set")
        try:
            import google.generativeai as genai
        except ImportError as exc:  # pragma: no cover - optional provider
            raise LLMError("google-generativeai is not installed") from exc
        genai.configure(api_key=api_key)
        self._genai = genai

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        model = self._genai.GenerativeModel(
            self.model, system_instruction=system_prompt
        )
        response = model.generate_content(
            user_prompt,
            generation_config={"temperature": self.temperature, "max_output_tokens": 350},
        )
        return (getattr(response, "text", "") or "").strip()


_PROVIDERS = {
    "groq": GroqLLM,
    "openai": OpenAILLM,
    "anthropic": AnthropicLLM,
    "mistral": MistralLLM,
    "gemini": GeminiLLM,
    "google": GeminiLLM,
}


def build_llm(config: LLMConfig) -> LLM:
    provider = (config.provider or "groq").strip().lower()
    factory = _PROVIDERS.get(provider)
    if factory is None:
        raise LLMError(
            "Unsupported LLM provider %r; expected one of %s"
            % (config.provider, ", ".join(sorted(_PROVIDERS)))
        )
    return factory(config)


def generate_with_retry(
    llm: LLM,
    system_prompt: str,
    user_prompt: str,
    attempts: int = 2,
) -> str:
    last_error: Optional[Exception] = None
    for attempt in range(1, attempts + 1):
        try:
            return llm.generate(system_prompt, user_prompt)
        except Exception as exc:  # provider errors vary by SDK
            last_error = exc
            LOGGER.warning(
                "LLM %s attempt %d/%d failed: %s",
                getattr(llm, "name", "unknown"),
                attempt,
                attempts,
                exc,
            )
    raise LLMError("LLM call failed: %s" % last_error)
