from app.config import get_settings
from app.decision.base import DecisionModel
from app.decision.heuristic import HeuristicDecision
from app.decision.systemone import SystemOneClient


def get_decision_model(provider: str | None = None) -> DecisionModel:
    """Маршрутизация decision-модели задаётся явно в настройках (DECISION_PROVIDER) и пишется в журнал."""
    s = get_settings()
    provider = (provider or s.decision_provider).lower()
    if provider == "jev":
        if not s.typesafe_api_key:
            return HeuristicDecision()  # ключ ещё не задан — работаем на офлайн-правилах, это видно в журнале
        return SystemOneClient("jev", s.typesafe_base_url, s.jev_model, s.typesafe_api_key, concurrency=8)
    if provider == "kev":
        return SystemOneClient("kev", s.kev_base_url, s.kev_model, concurrency=2, timeout=180)
    return HeuristicDecision()
