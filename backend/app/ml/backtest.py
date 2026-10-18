"""«Машина времени»: ретроспективная проверка без утечки будущего.

Система смотрит на технологии «глазами» даты среза (по умолчанию 1 января 2021): годовые ряды публикаций
обрезаются на срезе, препринты arXiv и обсуждения Hacker News берутся только до среза, репозитории GitHub —
созданные за год до среза, просмотры Википедии — за год до среза. Затем сравниваем оценку модели с тем,
что произошло к 2026 году.

Разметка «стало трендом к 2026» — экспертная, сделана командой и открыта ниже вместе с критериями, чтобы её можно
было оспорить:
  1 — к 2026 году стало массовой практикой или рынком: продукты у многих вендоров, тысячи работ в год;
  0 — к 2026 году осталось нишевым или заглохло после всплеска интереса.
В список вошли только темы, которые на дату среза уже существовали, но ещё не были мейнстримом.

Используется модель на наблюдаемых показателях (без ответов decision-модели: тексты 2020 года для неё
пришлось бы собирать заново). Сравнение — с двумя простыми базовыми правилами.

Запуск: python -m app.ml.backtest [--cutoff 2021-01-01]   → data/model/backtest.json
"""
import argparse
import asyncio
import json
import logging
import math
from datetime import date, datetime, timedelta, timezone

import numpy as np
from sklearn.metrics import roc_auc_score

from app.collectors import arxiv, github, hackernews, openalex, wikipedia
from app.collectors.base import RawDoc
from app.collectors.http import HttpClient
from app.config import get_settings
from app.pipeline.evidence import Evidence, _safe
from app.pipeline.features import NUMERIC, numeric_features

log = logging.getLogger("backtest")
MIN_COMPLETE = 20  # меньше полных тем — метрики не публикуем: слишком мало для вывода

# (поисковая фраза, 1 — стало трендом к 2026 / 0 — осталось нишей или заглохло, пояснение)
CASES = [
    ("retrieval-augmented generation", 1, "статья 2020 г.; к 2024–2026 — стандартная архитектура корпоративных LLM"),
    ("diffusion model", 1, "DDPM 2020; к 2023 — основа генерации изображений и видео"),
    ("vision transformer", 1, "ViT, октябрь 2020; к 2026 — базовая архитектура компьютерного зрения"),
    ("neural radiance fields", 1, "NeRF 2020; к 2026 — массовая технология 3D-реконструкции"),
    ("large language model", 1, "в 2020 термин редкий; к 2026 — массовый рынок"),
    ("prompt engineering", 1, "в 2020 почти не встречалось; к 2026 — профессия и практика"),
    ("vector database", 1, "в 2020 — единичные проекты; к 2026 — отдельный рынок"),
    ("self-supervised learning", 1, "к 2026 — стандарт предобучения"),
    ("zero trust architecture", 1, "NIST SP 800-207 (2020); к 2026 — массовая практика ИБ"),
    ("confidential computing", 1, "консорциум 2019; к 2026 — во всех крупных облаках"),
    ("chiplet", 1, "к 2026 — основной подход в производстве процессоров"),
    ("stablecoin", 1, "к 2026 — регулируемый платёжный инструмент в ряде юрисдикций"),
    ("central bank digital currency", 1, "к 2026 — пилоты и запуски в десятках стран, включая цифровой рубль"),
    ("edge AI", 1, "к 2026 — NPU в массовых смартфонах и ноутбуках"),
    ("deepfake detection", 1, "к 2026 — массовая задача банков и платформ"),
    ("capsule network", 0, "всплеск 2017–2019, к 2026 практически не используется"),
    ("blockchain voting", 0, "к 2026 так и не вышло за пилоты"),
    ("initial coin offering", 0, "пик 2018, к 2026 — почти исчезло"),
    ("4D printing", 0, "интерес с 2014, к 2026 — лабораторная ниша"),
    ("hyperloop", 0, "громкие анонсы, к 2026 проекты закрыты"),
    ("blockchain supply chain", 0, "волна пилотов 2018–2020, к 2026 — единичные внедрения"),
    ("drone delivery", 0, "к 2026 — ограниченные пилоты, не массовый сервис"),
    ("voice commerce", 0, "ожидания 2018, к 2026 — ниша"),
    ("DNA data storage", 0, "к 2026 — лабораторные демонстрации"),
    ("neuromorphic computing", 0, "к 2026 — исследовательская ниша"),
    ("biometric payment card", 0, "пилоты 2018–2020, к 2026 не стало массовым"),
    ("liquid neural network", 0, "к 2026 — нишевое направление"),
    ("holographic display", 0, "к 2026 — нишевые продукты"),
    ("smart contact lens", 0, "к 2026 проекты свёрнуты или в лабораториях"),
    ("quantum supremacy", 0, "к 2026 нет массового прикладного эффекта"),
]


async def as_of(http: HttpClient, phrase: str, cutoff: date) -> tuple[dict, Evidence]:
    """Числовые признаки технологии в том виде, в каком их можно было посчитать на дату среза."""
    year_before = cutoff - timedelta(days=365)
    ts_from = int(datetime.combine(year_before, datetime.min.time(), tzinfo=timezone.utc).timestamp())
    ts_to = int(datetime.combine(cutoff, datetime.min.time(), tzinfo=timezone.utc).timestamp())
    failed: list[str] = []
    years = await _safe("openalex", openalex.yearly_counts(http, phrase), {}, failed)
    ev = Evidence(phrase=phrase, today=(cutoff - timedelta(days=1)).isoformat(), failed=failed)
    ev.yearly = {y: n for y, n in years.items() if y < cutoff.year}  # будущее отрезано
    docs: list[RawDoc] = await _safe("arxiv", arxiv.search_before(http, phrase, cutoff, 15), [], failed)
    hn_docs, ev.hn_12m = await _safe("hackernews", hackernews.search(http, phrase, ts_from, 10, until_ts=ts_to), ([], None), failed)
    ev.gh_repos_12m = await _safe("github", github.count_created(http, phrase, year_before.isoformat(), cutoff.isoformat()), None, failed)
    ev.wiki = await _safe("wikipedia", wikipedia.lookup(http, phrase, as_of=cutoff), {}, failed)
    ev.docs = docs + hn_docs
    return numeric_features(ev), ev


def _numeric_model(rows: list[dict], min_docs: int = 3):
    """Модель на наблюдаемых показателях, обученная на той же выборке, что и основная (примеры с доказательствами)."""
    from app.ml.train import _fit, _matrix

    rows = [r for r in rows if r.get("n_docs", 0) >= min_docs]
    X, y = _matrix(rows, NUMERIC)
    return _fit(X, y)


def evaluate(results: list[dict]) -> dict:
    y = np.array([r["label"] for r in results])
    out = {"n": len(results), "n_trend": int(y.sum())}
    scorers = {
        "model": [r["p"] for r in results],
        "baseline_more_works": [r["features"]["log_total_works"] for r in results],  # «больше публикаций — перспективнее»
        "baseline_growth": [r["features"]["growth"] for r in results],  # «быстрее рост — перспективнее»
    }
    k = max(1, int(y.sum()))
    for name, s in scorers.items():
        s = np.array(s, dtype=float)
        top = np.argsort(-s)[:k]
        out[name] = {
            "roc_auc": round(float(roc_auc_score(y, s)), 3) if 0 < y.sum() < len(y) else None,
            f"precision_at_{k}": round(float(y[top].mean()), 3),
        }
    return out


async def run(cutoff: date) -> dict:
    s = get_settings()
    rows = json.loads((s.model_dir / "training_rows.json").read_text(encoding="utf-8"))
    sc, clf = _numeric_model(rows)
    http = HttpClient(patient=True)  # пакетная задача: ждём источники, а не пропускаем их
    results = []
    for phrase, label, note in CASES:
        feats, ev = await as_of(http, phrase, cutoff)
        x = np.array([[feats[f] for f in NUMERIC]])
        p = float(clf.predict_proba(sc.transform(x))[0, 1])
        works = int(round(math.expm1(feats["log_total_works"])))
        results.append({"phrase": phrase, "label": label, "note": note, "p": round(p, 3), "works_at_cutoff": works,
                        "features": {k: round(v, 3) for k, v in feats.items()}, "failed_sources": sorted(set(ev.failed))})
        log.info("%-34s label=%d p=%.3f works=%d failed=%s", phrase, label, p, works, ev.failed)
    await http.close()
    # Без годовых рядов OpenAlex признаки публикаций нулевые, и модель видела бы «нет данных» вместо истории темы.
    # Такие темы в метрики не входят; если полных тем мало — метрики не считаются вовсе.
    complete = [r for r in results if "openalex" not in r["failed_sources"]]
    labels = {r["label"] for r in complete}
    ok = len(complete) >= MIN_COMPLETE and labels == {0, 1}
    report = {"cutoff": cutoff.isoformat(), "model": "логистическая регрессия на наблюдаемых показателях (без decision-модели)",
              "labels_note": __doc__.split("Разметка", 1)[1].split("Используется", 1)[0].strip(),
              "status": "ok" if ok else "incomplete",
              "metrics": evaluate(complete) if ok else None,
              "results": sorted(results, key=lambda r: -r["p"]),
              "incomplete": len(results) - len(complete)}
    (s.model_dir / "backtest.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return report


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    ap = argparse.ArgumentParser()
    ap.add_argument("--cutoff", default="2021-01-01")
    rep = asyncio.run(run(date.fromisoformat(ap.parse_args().cutoff)))
    if rep["status"] == "ok":
        print(json.dumps(rep["metrics"], ensure_ascii=False, indent=1))
    else:
        print(f"Результат неполный: у {rep['incomplete']} из {len(rep['results'])} тем нет рядов OpenAlex — метрики не считаются. Задайте OPENALEX_API_KEY и запустите снова.")


if __name__ == "__main__":
    main()
