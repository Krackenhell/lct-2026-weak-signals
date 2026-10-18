"""Стоимость запроса в рублях: по фактически потраченным токенам LLM и числу вызовов decision-модели.

Тарифы ориентировочные и задаются в .env (LLM_RUB_PER_1K_TOKENS, DECISION_RUB_PER_CALL): цены провайдеров меняются,
поэтому в выдаче всегда показано, по какому тарифу посчитано. Открытые источники бесплатны; локальные модели
(Kev, LLM через Ollama) не тарифицируются — их стоимость входит в стоимость сервера.
"""
from urllib.parse import urlparse

from app.config import get_settings

# ₽ за 1000 токенов (запрос + ответ), публичные тарифы для юрлиц на момент подготовки.
LLM_TARIFFS = {
    "GigaChat-2": 0.2, "GigaChat-2-Lite": 0.2, "GigaChat-2-Pro": 1.5, "GigaChat-2-Max": 1.95,
    "GigaChat": 0.2, "GigaChat-Pro": 1.5, "GigaChat-Max": 1.95,
    "yandexgpt-lite/latest": 0.2, "yandexgpt/latest": 1.2,
}
DEFAULT_LLM_TARIFF = 1.0  # неизвестная облачная модель: консервативная оценка
LOCAL_HOSTS = ("localhost", "127.0.0.1", "ollama", "0.0.0.0")


def _is_local_llm() -> bool:
    s = get_settings()
    return s.llm_provider.lower() == "openai" and (urlparse(s.openai_base_url).hostname or "") in LOCAL_HOSTS


def llm_tariff(model: str) -> float:
    s = get_settings()
    if s.llm_rub_per_1k_tokens is not None:
        return s.llm_rub_per_1k_tokens
    if _is_local_llm():
        return 0.0
    return LLM_TARIFFS.get(model, LLM_TARIFFS.get(model.split(":")[0], DEFAULT_LLM_TARIFF))


def estimate(usage: dict[str, dict]) -> dict:
    """usage: провайдер -> {"model", "calls", "tokens"} (собирается при журналировании вызовов)."""
    s = get_settings()
    lines, total = [], 0.0
    for provider, u in sorted(usage.items()):
        if provider in ("jev", "kev"):
            rate = s.decision_rub_per_call if provider == "jev" else 0.0
            rub = u["calls"] * rate
            lines.append({"provider": provider, "model": u["model"], "calls": u["calls"], "tokens": u["tokens"], "rub": round(rub, 2),
                          "tariff": f"{rate:g} ₽ за вызов" if rate else ("локально, без оплаты" if provider == "kev" else "без оплаты по условиям доступа")})
        else:
            rate = llm_tariff(u["model"])
            rub = u["tokens"] / 1000 * rate
            lines.append({"provider": provider, "model": u["model"], "calls": u["calls"], "tokens": u["tokens"], "rub": round(rub, 2),
                          "tariff": f"{rate:g} ₽ за 1000 токенов" if rate else "локальная модель, без оплаты"})
        total += rub
    return {"total_rub": round(total, 2), "lines": lines, "sources": "открытые источники — бесплатно"}
