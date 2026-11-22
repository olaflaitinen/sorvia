"""Language-model clients.

  OpenAICompatibleClient  any /chat/completions endpoint (hosted APIs, vLLM, Ollama, LM Studio)
  StaticClient            replays question -> SQL pairs from a JSONL file; used for tests,
                          for the oracle upper bound in experiments, and for offline demos
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx

from sorvia.config import Settings
from sorvia.nl2sql.embeddings import normalize


@dataclass(frozen=True)
class Message:
    role: str  # "user" | "assistant"
    content: str


@dataclass(frozen=True)
class Completion:
    text: str
    model: str
    latency_ms: int
    input_tokens: int | None = None
    output_tokens: int | None = None


class LLMError(RuntimeError):
    pass


class LLMClient(Protocol):
    provider: str
    model: str

    def complete(self, system: str, messages: list[Message]) -> Completion: ...


class _HttpClient:
    def __init__(self, timeout_s: float, retries: int = 2) -> None:
        self._client = httpx.Client(timeout=timeout_s)
        self._retries = retries

    def _post(self, url: str, headers: dict[str, str], body: dict[str, object]) -> dict[str, object]:
        last: Exception | None = None
        for attempt in range(self._retries + 1):
            try:
                response = self._client.post(url, headers=headers, json=body)
                if response.status_code in (429, 500, 502, 503, 504, 529) and attempt < self._retries:
                    time.sleep(min(2**attempt, 8))
                    continue
                response.raise_for_status()
                result: dict[str, object] = response.json()
                return result
            except httpx.HTTPError as exc:
                last = exc
                if attempt < self._retries:
                    time.sleep(min(2**attempt, 8))
        raise LLMError(f"Language model request failed: {last}")


class OpenAICompatibleClient(_HttpClient):
    provider = "openai"

    def __init__(self, base_url: str, model: str, api_key: str | None, max_tokens: int, timeout_s: float) -> None:
        super().__init__(timeout_s)
        self.model = model
        self._max_tokens = max_tokens
        self._url = f"{base_url.rstrip('/')}/chat/completions"
        self._headers = {"content-type": "application/json"}
        if api_key:
            self._headers["authorization"] = f"Bearer {api_key}"

    def complete(self, system: str, messages: list[Message]) -> Completion:
        start = time.perf_counter()
        data = self._post(self._url, self._headers, {
            "model": self.model,
            "max_tokens": self._max_tokens,
            "temperature": 0,
            "messages": [{"role": "system", "content": system}]
            + [{"role": m.role, "content": m.content} for m in messages],
        })
        choices = data.get("choices") or []
        text = choices[0]["message"]["content"] if choices else ""  # type: ignore[index]
        usage = data.get("usage") or {}
        return Completion(
            text=str(text),
            model=str(data.get("model", self.model)),
            latency_ms=int((time.perf_counter() - start) * 1000),
            input_tokens=usage.get("prompt_tokens") if isinstance(usage, dict) else None,
            output_tokens=usage.get("completion_tokens") if isinstance(usage, dict) else None,
        )


def _question_key(text: str) -> str:
    return " ".join(normalize(text).split())


class StaticClient:
    """Answers from a JSONL file of {"question": ..., "sql": ...} records.

    The question is located in the last user message after the "Question:" marker.
    """

    provider = "static"

    def __init__(self, pairs: dict[str, str], model: str = "static") -> None:
        self.model = model
        self._pairs = {_question_key(q): s for q, s in pairs.items()}

    @classmethod
    def from_jsonl(cls, path: Path, question_field: str = "question", sql_field: str = "sql") -> StaticClient:
        pairs: dict[str, str] = {}
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    record = json.loads(line)
                    pairs[record[question_field]] = record[sql_field]
                    if "question_en" in record:
                        pairs[record["question_en"]] = record[sql_field]
        return cls(pairs)

    def complete(self, system: str, messages: list[Message]) -> Completion:
        last = messages[-1].content
        question = last.rsplit("Question:", 1)[-1].strip() if "Question:" in last else last.strip()
        sql = self._pairs.get(_question_key(question))
        text = f"```sql\n{sql}\n```" if sql else "-- CANNOT_ANSWER: sual statik cavablar siyahısında yoxdur"
        return Completion(text=text, model=self.model, latency_ms=0)


def build_client(settings: Settings) -> LLMClient:
    if settings.llm_provider == "static":
        if settings.static_sql_path is None:
            raise ValueError("SORVIA_STATIC_SQL_PATH is required for the static provider")
        return StaticClient.from_jsonl(settings.static_sql_path)
    api_key = settings.llm_api_key.get_secret_value() if settings.llm_api_key else None
    if not settings.llm_base_url or not settings.llm_model:
        raise ValueError("SORVIA_LLM_BASE_URL and SORVIA_LLM_MODEL are required for the openai provider")
    return OpenAICompatibleClient(settings.llm_base_url, settings.llm_model, api_key,
                                  settings.llm_max_tokens, settings.llm_timeout_s)
