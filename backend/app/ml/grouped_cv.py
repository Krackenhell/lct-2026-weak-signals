"""Кросс-валидация с группировкой синонимов: близкие формулировки одной технологии всегда в одном фолде.

Вопрос технического эксперта: «не утекает ли ответ, если "solid-state battery" в обучении, а "all-solid-state batteries"
в проверке?». Обычная StratifiedKFold такие пары разводит. Здесь строки, у которых поисковые фразы делят больше половины
значимых слов, склеиваются в группу (объединение по цепочке), и проверка идёт StratifiedGroupKFold.
Модель не переобучается — считается только оценка; результат дописывается в data/model/metrics.json → cv5_grouped.

    python -m app.ml.grouped_cv
"""
import json
import re

import numpy as np
from sklearn.model_selection import StratifiedGroupKFold

from app.config import get_settings
from app.ml import train

STOP = {"and", "for", "the", "with", "based", "of", "in", "on", "to", "using", "system", "systems", "technology", "technologies"}


def _words(r: dict) -> set[str]:
    text = " ".join([r.get("phrase") or "", *(r.get("alt_terms") or [])]).lower()
    ws = {w[:-1] if len(w) > 4 and w.endswith("s") else w for w in re.findall(r"[a-z0-9]{3,}", text)}
    return ws - STOP


def synonym_groups(rows: list[dict], overlap: float = 0.5) -> list[int]:
    """Номер группы для каждой строки: строки с пересечением слов > overlap (от меньшего набора) — одна группа."""
    parent = list(range(len(rows)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    sets = [_words(r) for r in rows]
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            a, b = sets[i], sets[j]
            if a and b and len(a & b) / min(len(a), len(b)) > overlap:
                parent[find(i)] = find(j)
    return [find(i) for i in range(len(rows))]


def grouped_oof(X, y, groups, C=0.5, seed=42):
    oof = np.zeros(len(y))
    for tr, te in StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=seed).split(X, y, groups):
        sc, clf = train._fit(X[tr], y[tr], C)
        z = np.clip(sc.transform(X[te]), -train.Z_CLIP, train.Z_CLIP)
        oof[te] = train._sigmoid(z @ clf.coef_[0] + clf.intercept_[0])
    return oof


def evaluate(rows: list[dict]) -> dict:
    rows = [r for r in rows if not r.get("incomplete") and train.has_evidence(r)]
    feats = [f for f in train._usable(rows, train.FEATURES) if f not in train.MODEL_EXCLUDE]
    X, y = train._matrix(rows, feats)
    groups = synonym_groups(rows)
    plain = train._metrics(y, train._oof(X, y))
    grouped = train._metrics(y, grouped_oof(X, y, groups))
    sizes = {}
    for g in groups:
        sizes[g] = sizes.get(g, 0) + 1
    multi = [g for g, n in sizes.items() if n > 1]
    examples = [[rows[i]["phrase"] for i in range(len(rows)) if groups[i] == g][:4] for g in multi[:6]]
    return {"n": len(rows), "groups": len(sizes), "rows_in_shared_groups": sum(sizes[g] for g in multi),
            "plain_cv5": plain, "grouped_cv5": grouped, "f1_delta": round(grouped["f1"] - plain["f1"], 3), "examples": examples,
            "method": "StratifiedGroupKFold(5), группы — поисковые фразы с пересечением значимых слов > 50%"}


def main() -> None:
    d = get_settings().model_dir
    rows = json.loads((d / "training_rows.json").read_text(encoding="utf-8"))
    res = evaluate(rows)
    path = d / "metrics.json"
    metrics = json.loads(path.read_text(encoding="utf-8"))
    metrics["cv5_grouped"] = res
    path.write_text(json.dumps(metrics, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k != "examples"}, ensure_ascii=False, indent=1))
    print("примеры групп:", res["examples"])


if __name__ == "__main__":
    main()
