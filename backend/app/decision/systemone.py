"""Клиент System One API. Один и тот же код обслуживает Jev (api.typesafe.ai) и локальный Kev (совместимый API)."""
import asyncio

import httpx

from app.decision.base import DecisionResult, Timer, normalize_answer


class SystemOneClient:
    def __init__(self, provider: str, base_url: str, model: str, api_key: str = "", timeout: float = 60.0, concurrency: int = 4):
        self.provider = provider
        self.model = model
        self._url = base_url.rstrip("/") + "/v1/systemone"
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.AsyncClient(timeout=timeout, headers=headers)
        self._sem = asyncio.Semaphore(concurrency)

    async def ask(self, state: str, questions: dict) -> DecisionResult:
        body = {"state": state, "model": self.model, "questions": questions}
        async with self._sem:
            last = ""
            for attempt in range(3):
                with Timer() as t:
                    try:
                        resp = await self._client.post(self._url, json=body)
                        if resp.status_code == 429 or resp.status_code >= 500:
                            raise httpx.HTTPStatusError(f"HTTP {resp.status_code}", request=resp.request, response=resp)
                        resp.raise_for_status()
                        data = resp.json()
                    except (httpx.HTTPError, ValueError) as exc:
                        last = f"{type(exc).__name__}: {exc}"  # у таймаутов httpx str(exc) пустой
                        await asyncio.sleep(1.5 * (attempt + 1))
                        continue
                answers = {qid: normalize_answer(a) for qid, a in (data.get("answers") or {}).items()}
                return DecisionResult(answers, self.provider, data.get("model", self.model), t.ms, data.get("usage") or {})
        return DecisionResult({}, self.provider, self.model, 0, ok=False, error=last)

    async def close(self) -> None:
        await self._client.aclose()
