"""Провайдеры LLM из разрешённого ТЗ списка. Выбор — явный, через LLM_PROVIDER; каждый вызов журналируется.

LLM используется только для работы с найденными текстами: расширение запроса,
извлечение названий технологий из документов, русские резюме и досье.
Решение «сигнал / не сигнал» LLM не принимает.
"""
import asyncio
import json
import re
import time
import uuid
from dataclasses import dataclass, field

import httpx

from app.config import get_settings


@dataclass
class LLMResult:
    text: str
    provider: str
    model: str
    latency_ms: int
    ok: bool = True
    error: str = ""
    usage: dict = field(default_factory=dict)  # {"prompt", "completion", "total"} — токены для расчёта стоимости


def _usage(prompt, completion, total=None) -> dict:
    p, c = int(prompt or 0), int(completion or 0)
    return {"prompt": p, "completion": c, "total": int(total or p + c)}


class BaseLLM:
    provider = "none"
    model = "none"

    def __init__(self, concurrency: int = 4) -> None:
        self._sem = asyncio.Semaphore(concurrency)

    async def _complete(self, system: str, user: str, temperature: float, max_tokens: int) -> str | tuple[str, dict]:
        """Текст ответа или (текст, токены)."""
        raise NotImplementedError

    async def complete(self, system: str, user: str, temperature: float = 0.2, max_tokens: int = 1500) -> LLMResult:
        t = time.perf_counter()
        async with self._sem:
            last = ""
            for attempt in range(3):
                try:
                    out = await self._complete(system, user, temperature, max_tokens)
                    text, usage = out if isinstance(out, tuple) else (out, {})
                    return LLMResult(text, self.provider, self.model, int((time.perf_counter() - t) * 1000), usage=usage)
                except (httpx.HTTPError, KeyError, ValueError) as exc:
                    last = str(exc)
                    rate_limited = isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429
                    await asyncio.sleep((6 if rate_limited else 2) * (attempt + 1))
        return LLMResult("", self.provider, self.model, int((time.perf_counter() - t) * 1000), ok=False, error=last)


class GigaChat(BaseLLM):
    provider = "gigachat"

    def __init__(self) -> None:
        s = get_settings()
        super().__init__(concurrency=max(1, s.gigachat_concurrency))  # бесплатный тариф — 1 поток, корпоративный — больше
        self.model = s.gigachat_model
        self._auth_key = s.gigachat_auth_key
        self._scope = s.gigachat_scope
        # Соединение и токен — быстро (10 с), генерация длинного ответа — до 90 с.
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(90, connect=10), verify=s.gigachat_verify_ssl)
        self._token = ""
        self._token_exp = 0.0
        self._lock = asyncio.Lock()

    async def _get_token(self) -> str:
        async with self._lock:
            if self._token and time.time() < self._token_exp - 60:
                return self._token
            r = await self._client.post(
                "https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
                headers={"Authorization": f"Basic {self._auth_key}", "RqUID": str(uuid.uuid4()), "Content-Type": "application/x-www-form-urlencoded"},
                data={"scope": self._scope},
            )
            r.raise_for_status()
            d = r.json()
            self._token = d["access_token"]
            self._token_exp = d.get("expires_at", 0) / 1000 or time.time() + 1500
            return self._token

    async def _complete(self, system, user, temperature, max_tokens):
        token = await self._get_token()
        r = await self._client.post(
            "https://gigachat.devices.sberbank.ru/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {token}"},
            json={"model": self.model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}], "temperature": temperature, "max_tokens": max_tokens},
        )
        r.raise_for_status()
        d = r.json()
        u = d.get("usage") or {}
        return d["choices"][0]["message"]["content"], _usage(u.get("prompt_tokens"), u.get("completion_tokens"), u.get("total_tokens"))


class YandexGPT(BaseLLM):
    provider = "yandexgpt"

    def __init__(self) -> None:
        super().__init__(concurrency=4)
        s = get_settings()
        self.model = s.yandex_model
        self._uri = f"gpt://{s.yandex_folder_id}/{s.yandex_model}"
        self._client = httpx.AsyncClient(timeout=120, headers={"Authorization": f"Api-Key {s.yandex_api_key}"})

    async def _complete(self, system, user, temperature, max_tokens):
        r = await self._client.post(
            "https://llm.api.cloud.yandex.net/foundationModels/v1/completion",
            json={
                "modelUri": self._uri,
                "completionOptions": {"temperature": temperature, "maxTokens": str(max_tokens)},
                "messages": [{"role": "system", "text": system}, {"role": "user", "text": user}],
            },
        )
        r.raise_for_status()
        d = r.json()["result"]
        u = d.get("usage") or {}
        return d["alternatives"][0]["message"]["text"], _usage(u.get("inputTextTokens"), u.get("completionTokens"), u.get("totalTokens"))


class OpenAICompatible(BaseLLM):
    """gpt-4.1 / gpt-5.6-luna или Qwen3 через OpenAI-совместимый endpoint."""

    provider = "openai"

    def __init__(self) -> None:
        super().__init__(concurrency=6)
        s = get_settings()
        self.model = s.openai_model
        self._url = s.openai_base_url.rstrip("/") + "/chat/completions"
        self._client = httpx.AsyncClient(timeout=120, headers={"Authorization": f"Bearer {s.openai_api_key}"})

    async def _complete(self, system, user, temperature, max_tokens):
        r = await self._client.post(
            self._url,
            json={"model": self.model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}], "temperature": temperature, "max_tokens": max_tokens},
        )
        r.raise_for_status()
        d = r.json()
        u = d.get("usage") or {}
        return d["choices"][0]["message"]["content"], _usage(u.get("prompt_tokens"), u.get("completion_tokens"), u.get("total_tokens"))


class NoLLM(BaseLLM):
    provider = "none"
    model = "template"

    async def complete(self, system, user, temperature=0.2, max_tokens=1500) -> LLMResult:
        return LLMResult("", self.provider, self.model, 0, ok=False, error="LLM отключена")


def get_llm(provider: str | None = None) -> BaseLLM:
    s = get_settings()
    provider = (provider or s.llm_provider).lower()
    if provider == "gigachat" and s.gigachat_auth_key:
        return GigaChat()
    if provider == "yandexgpt" and s.yandex_api_key:
        return YandexGPT()
    if provider == "openai" and s.openai_api_key:
        return OpenAICompatible()
    return NoLLM()


def parse_json(text: str):
    """Достаёт JSON из ответа LLM (в т.ч. из блока ```json ... ```)."""
    if not text:
        return None
    m = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.S)
    raw = m.group(1) if m else text
    start = min([i for i in (raw.find("{"), raw.find("[")) if i >= 0], default=-1)
    if start < 0:
        return None
    end = max(raw.rfind("}"), raw.rfind("]"))
    try:
        return json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None
