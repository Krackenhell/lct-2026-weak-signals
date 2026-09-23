"""Decision-модели (System One API): Jev (TypeSafe, облако), Kev (локально), эвристика (офлайн-запасной вариант).

Модель не решает, является ли технология слабым сигналом. Она отвечает на атомарные
вопросы о тексте доказательств, а ответы становятся признаками нашего классификатора.
"""
import time
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class DecisionResult:
    answers: dict  # id вопроса -> {"type", "value", ...}
    provider: str
    model: str
    latency_ms: int
    usage: dict = field(default_factory=dict)
    ok: bool = True
    error: str = ""


class DecisionModel(Protocol):
    provider: str
    model: str

    async def ask(self, state: str, questions: dict) -> DecisionResult: ...


def normalize_answer(raw: dict) -> dict:
    """Приводит ответ System One к виду {'type', 'value' ∈ [0,1], ...}."""
    t = raw.get("type")
    if t == "noul":
        return {"type": "noul", "value": float(raw.get("noul", 0.5))}
    if t == "score":
        probs = raw.get("probabilities") or {}
        levels = max(len(probs) - 1, 1)
        return {
            "type": "score",
            "value": float(raw.get("score", 0.0)) / levels,
            "level": float(raw.get("score", 0.0)),
            "confidence": raw.get("confidence"),
            "probabilities": probs,
        }
    if t == "choice":
        return {
            "type": "choice",
            "choice": raw.get("choice"),
            "confidence": raw.get("confidence"),
            "probabilities": raw.get("probabilities") or {},
        }
    return {"type": t or "unknown", "value": 0.5}


class Timer:
    def __enter__(self):
        self.t = time.perf_counter()
        return self

    def __exit__(self, *exc):
        self.ms = int((time.perf_counter() - self.t) * 1000)
