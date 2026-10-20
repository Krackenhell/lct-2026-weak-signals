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

Z_CLIP = 3.0


@dataclass
class SignalModel:
    features: list[str]
    mean: list[float]
    scale: list[float]
    coef: list[float]
    intercept: float
    meta: dict
    # Калибровка температурой: на обучающей выборке классы разделяются почти идеально, и сырая регрессия выдаёт
    # «99,99%». Логит делится на T, подобранную по прогнозам кросс-валидации (на примерах, которых модель не видела),
    # так что 80% означает «из таких кандидатов сигналами оказываются около 80%». Порядок и порог 0,5 не меняются.
    temperature: float = 1.0

    @classmethod
    def load(cls, path: Path | None = None) -> "SignalModel | None":
        path = path or get_settings().model_dir / "signal_model.json"
        if not path.exists():
            return None
        d = json.loads(path.read_text(encoding="utf-8"))
        return cls(d["features"], d["mean"], d["scale"], d["coef"], d["intercept"], d.get("meta", {}), float(d.get("temperature", 1.0)))

    def save(self, path: Path | None = None) -> None:
        path = path or get_settings().model_dir / "signal_model.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.__dict__, ensure_ascii=False, indent=1), encoding="utf-8")

    def _z(self, x: dict[str, float]) -> list[float]:
        # Отклонение ограничено ±Z_CLIP: значение далеко за пределами обучающей выборки (другая decision-модель,
        # сбой источника) не должно в одиночку давать вероятность «100%».
        return [max(-Z_CLIP, min(Z_CLIP, (x.get(f, m) - m) / (s or 1.0))) for f, m, s in zip(self.features, self.mean, self.scale, strict=False)]

    def logit(self, x: dict[str, float]) -> float:
        """Откалиброванный логит: сумма вкладов признаков, делённая на температуру."""
        return (self.intercept + sum(c * v for c, v in zip(self.coef, self._z(x), strict=False))) / self.temperature

    def predict(self, x: dict[str, float]) -> float:
        return 1.0 / (1.0 + math.exp(-max(min(self.logit(x), 30), -30)))

    def outside(self, x: dict[str, float]) -> list[str]:
        """Признаки, значение которых дальше Z_CLIP стандартных отклонений от обучающей выборки:
        на таких кандидатах модель не проверялась, и её процент — экстраполяция."""
        return [FEATURE_RU.get(f, f) for f, m, s in zip(self.features, self.mean, self.scale, strict=False)
                if abs((x.get(f, m) - m) / (s or 1.0)) > Z_CLIP]

    def explain(self, x: dict[str, float]) -> list[dict]:
        """Вклады признаков в логит, отсортированные по модулю."""
        z = self._z(x)
        rows = [
            {
                "feature": f,
                "label": FEATURE_RU.get(f, f),
                "value": round(x.get(f, m), 3),
                "contribution": round(c * v / self.temperature, 3),  # в тех же единицах, что и итоговая вероятность
                "level": "высокое" if v > 0.25 else "низкое" if v < -0.25 else "среднее",
            }
            for f, m, c, v in zip(self.features, self.mean, self.coef, z, strict=False)
        ]
        return sorted(rows, key=lambda r: -abs(r["contribution"]))


def default_features() -> list[str]:
    return list(FEATURES)
