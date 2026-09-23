"""Классификатор слабых сигналов: логистическая регрессия на стандартизованных признаках.

Хранится в JSON (средние, масштабы, веса) — модель полностью прозрачна и не требует
pickle. Вклад признака в решение = вес × стандартизованное значение.
"""
import json
import math
from dataclasses import dataclass
from pathlib import Path

from app.config import get_settings
from app.pipeline.features import FEATURE_RU, FEATURES


@dataclass
class SignalModel:
    features: list[str]
    mean: list[float]
    scale: list[float]
    coef: list[float]
    intercept: float
    meta: dict

    @classmethod
    def load(cls, path: Path | None = None) -> "SignalModel | None":
        path = path or get_settings().model_dir / "signal_model.json"
        if not path.exists():
            return None
        d = json.loads(path.read_text(encoding="utf-8"))
        return cls(d["features"], d["mean"], d["scale"], d["coef"], d["intercept"], d.get("meta", {}))

    def save(self, path: Path | None = None) -> None:
        path = path or get_settings().model_dir / "signal_model.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.__dict__, ensure_ascii=False, indent=1), encoding="utf-8")

    def _z(self, x: dict[str, float]) -> list[float]:
        return [(x.get(f, m) - m) / (s or 1.0) for f, m, s in zip(self.features, self.mean, self.scale)]

    def predict(self, x: dict[str, float]) -> float:
        z = self._z(x)
        logit = self.intercept + sum(c * v for c, v in zip(self.coef, z))
        return 1.0 / (1.0 + math.exp(-max(min(logit, 30), -30)))

    def explain(self, x: dict[str, float]) -> list[dict]:
        """Вклады признаков в логит, отсортированные по модулю."""
        z = self._z(x)
        rows = [
            {
                "feature": f,
                "label": FEATURE_RU.get(f, f),
                "value": round(x.get(f, m), 3),
                "contribution": round(c * v, 3),
                "level": "высокое" if v > 0.25 else "низкое" if v < -0.25 else "среднее",
            }
            for f, m, c, v in zip(self.features, self.mean, self.coef, z)
        ]
        return sorted(rows, key=lambda r: -abs(r["contribution"]))


def default_features() -> list[str]:
    return list(FEATURES)
