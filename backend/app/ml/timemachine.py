"""Машина времени 2.0: много дат среза, исторические признаки и честная проверка «вне времени».

Что изменилось по сравнению с backtest.py (один срез, 30 тем, модель обучена на данных 2026 года):
1. База расширена: ~120 тем с датами среза 2016, 2018, 2020, 2021, 2022. Для каждой — что стало к 2026 году.
2. Признаки считаются строго на 1 января года среза: публикации OpenAlex до среза, гранты NIH до среза,
   стартапы Y Combinator из наборов до среза, репозитории GitHub и обсуждения Hacker News за год до среза,
   статья Википедии на дату среза.
3. Отдельная «историческая» модель обучается на этих признаках. Проверка — «вне времени»: модель учится на темах
   одних лет среза и предсказывает темы другого года, которого не видела (leave-one-cutoff-out). Так мы проверяем
   ровно то, что нужно банку: угадывание будущего по прошлому.

Разметка (1 — к 2026 году стало массовой практикой или рынком; 0 — осталось нишей или заглохло) — экспертная,
сделана командой по открытым фактам и записана ниже вместе с пояснениями, чтобы её можно было оспорить.
Ограничения, о которых говорим прямо:
- темы выбраны задним числом (известные успехи и провалы), поэтому реальная задача сложнее этой проверки;
- описание стартапа YC — текущее, а не на момент набора; поэтому метрики публикуются и без признаков YC;
- фраза поиска одна на тему: синонимы (например, «LLM» для «large language model») не учитываются.

Запуск: python -m app.ml.timemachine   → data/model/timemachine.json
"""
import argparse
import asyncio
import json
import logging
import math
from datetime import date, datetime, timedelta, timezone

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.preprocessing import StandardScaler

from app.collectors import github, grants, hackernews, openalex, wikipedia, yc
from app.collectors.http import HttpClient
from app.config import get_settings
from app.ml.backtest import CASES as CASES_2021
from app.pipeline.evidence import _safe

log = logging.getLogger("timemachine")

# (поисковая фраза, год среза, 1/0, пояснение). Фразы уникальны: одна тема — один срез, иначе проверка
# «вне времени» видела бы ту же тему в обучении.
CASES: list[tuple[str, int, int, str]] = [
    # ── Срез 2016 ──
    ("generative adversarial network", 2016, 1, "статья 2014 г.; к 2019–2026 — основа генеративных моделей и синтеза данных"),
    ("serverless computing", 2016, 1, "AWS Lambda 2014; к 2026 — во всех облаках, массовая практика"),
    ("neural machine translation", 2016, 1, "к 2017 перевели Google Translate, к 2026 — стандарт отрасли"),
    ("attention mechanism", 2016, 1, "2014–2015; к 2026 — основа трансформеров"),
    ("graph neural network", 2016, 1, "к 2026 — массовый инструмент (рекомендации, антифрод, химия)"),
    ("edge computing", 2016, 1, "к 2026 — отдельный рынок и стандартная архитектура"),
    ("robotic process automation", 2016, 1, "к 2020 — многомиллиардный рынок, стандарт банков"),
    ("open banking", 2016, 1, "PSD2 2015; к 2026 — регуляторная норма в ЕС, Великобритании, России"),
    ("differential privacy", 2016, 1, "Apple 2016, перепись США 2020; к 2026 — стандарт защиты данных"),
    ("WebAssembly", 2016, 1, "анонс 2015; к 2026 — во всех браузерах и в серверных платформах"),
    ("mRNA vaccine", 2016, 1, "к 2020–2021 — массовая вакцинация, рынок"),
    ("deep reinforcement learning", 2016, 1, "DQN/AlphaGo; к 2026 — стандарт в робототехнике и RLHF"),
    ("smart contract", 2016, 1, "Ethereum 2015; к 2026 — основа DeFi и токенизации"),
    ("microservices", 2016, 1, "к 2020 — стандартная архитектура"),
    ("container orchestration", 2016, 1, "к 2020 — Kubernetes де-факто стандарт"),
    ("Li-Fi", 2016, 0, "громкие ожидания 2015–2016; к 2026 — ниша"),
    ("smart dust", 2016, 0, "к 2026 не вышло из лабораторий"),
    ("DNA computing", 2016, 0, "к 2026 — лабораторные демонстрации"),
    ("memristor", 2016, 0, "к 2026 — исследовательская ниша, нет массовой памяти"),
    ("graphene transistor", 2016, 0, "к 2026 — нет массовых продуктов"),
    ("flying car", 2016, 0, "к 2026 — нет массового сервиса"),
    ("blockchain land registry", 2016, 0, "пилоты 2016–2018, к 2026 — единичные внедрения"),
    ("spintronics", 2016, 0, "к 2026 — нишевые применения"),
    ("telepresence robot", 2016, 0, "к 2026 — ниша"),
    ("magnetic refrigeration", 2016, 0, "к 2026 — лабораторная ниша"),
    ("carbon nanotube transistor", 2016, 0, "к 2026 — исследования, нет массового производства"),
    ("swarm robotics", 2016, 0, "к 2026 — исследования и шоу дронов, не массовая практика"),
    # ── Срез 2018 ──
    ("federated learning", 2018, 1, "термин 2016–2017; к 2026 — стандарт приватного ML (смартфоны, банки, медицина)"),
    ("self-attention", 2018, 1, "Transformer 2017; к 2026 — основа всех LLM"),
    ("explainable artificial intelligence", 2018, 1, "к 2026 — требование регуляторов (AI Act), отдельный рынок"),
    ("automated machine learning", 2018, 1, "к 2026 — во всех облачных ML-платформах"),
    ("contrastive learning", 2018, 1, "к 2026 — стандарт предобучения (CLIP, SimCLR)"),
    ("knowledge distillation", 2018, 1, "к 2026 — стандарт сжатия моделей"),
    ("MLOps", 2018, 1, "к 2026 — профессия и рынок инструментов"),
    ("digital twin", 2018, 1, "к 2026 — массовая практика в промышленности"),
    ("decentralized finance", 2018, 1, "к 2026 — десятки млрд долларов в протоколах, регулирование"),
    ("synthetic data", 2018, 1, "к 2026 — массовая практика обучения моделей"),
    ("RISC-V", 2018, 1, "к 2026 — миллиарды ядер, поддержка крупными вендорами"),
    ("eBPF", 2018, 1, "к 2026 — стандарт наблюдаемости и безопасности в Linux"),
    ("GraphQL", 2018, 1, "к 2026 — массовый API-стандарт"),
    ("zero-knowledge proof", 2018, 1, "к 2026 — zk-rollups и цифровые удостоверения в продакшне"),
    ("buy now pay later", 2018, 1, "к 2026 — массовый платёжный продукт, регулирование"),
    ("neobank", 2018, 1, "к 2026 — десятки банков с миллионами клиентов"),
    ("liquid biopsy", 2018, 1, "к 2026 — коммерческие тесты в клиниках"),
    ("computational pathology", 2018, 1, "к 2026 — одобренные регуляторами продукты"),
    ("non-fungible token", 2018, 0, "пик интереса в 2021, к 2026 обороты рынка сократились в разы"),
    ("security token offering", 2018, 0, "волна 2018–2019, к 2026 почти исчезло"),
    ("blockchain identity", 2018, 0, "к 2026 — единичные пилоты"),
    ("spiking neural network", 2018, 0, "к 2026 — исследовательская ниша"),
    ("optical neural network", 2018, 0, "к 2026 — лабораторные демонстрации"),
    ("quantum internet", 2018, 0, "к 2026 — эксперименты"),
    ("air taxi", 2018, 0, "к 2026 нет массового коммерческого сервиса"),
    ("autonomous delivery robot", 2018, 0, "к 2026 — ограниченные пилоты"),
    ("graphene supercapacitor", 2018, 0, "к 2026 — нишевые продукты"),
    ("self-healing material", 2018, 0, "к 2026 — исследования"),
    ("electronic skin", 2018, 0, "к 2026 — лабораторные прототипы"),
    ("molecular communication", 2018, 0, "к 2026 — теория и лаборатории"),
    ("quantum machine learning", 2018, 0, "к 2026 нет практического преимущества"),
    # ── Срез 2020 ──
    ("vision-language model", 2020, 1, "к 2026 — массовые мультимодальные модели"),
    ("data mesh", 2020, 1, "термин 2019; к 2026 — распространённая архитектура данных"),
    ("feature store", 2020, 1, "к 2026 — стандартный компонент ML-платформ"),
    ("low-code", 2020, 1, "к 2026 — многомиллиардный рынок"),
    ("embedded finance", 2020, 1, "к 2026 — массовая модель распространения финуслуг"),
    ("sodium-ion battery", 2020, 1, "CATL 2021–2023; к 2026 — серийное производство"),
    ("remote patient monitoring", 2020, 1, "к 2026 — массовая услуга, оплачивается страховщиками"),
    ("contact tracing app", 2020, 0, "всплеск 2020, к 2026 приложения закрыты"),
    ("quantum annealing", 2020, 0, "к 2026 нет массового прикладного эффекта"),
    ("yield farming", 2020, 0, "бум 2020–2021, к 2026 — ниша"),
    ("metaverse", 2020, 0, "пик ожиданий 2021–2022, к 2026 проекты свёрнуты или урезаны"),
    ("play-to-earn", 2020, 0, "бум 2021, к 2026 почти исчезло"),
    ("neuro-symbolic AI", 2020, 0, "к 2026 — исследовательская ниша"),
    ("hydrogen fuel cell vehicle", 2020, 0, "к 2026 — продажи падают, станции закрываются"),
    ("space-based solar power", 2020, 0, "к 2026 — демонстрации"),
    ("cultured meat", 2020, 0, "к 2026 — единичные разрешения, нет массового рынка"),
    ("vertical farming", 2020, 0, "к 2026 — волна банкротств, ниша"),
    ("electronic nose", 2020, 0, "к 2026 — ниша"),
    # ── Срез 2022 ──
    ("instruction tuning", 2022, 1, "к 2026 — стандартный этап обучения LLM"),
    ("reinforcement learning from human feedback", 2022, 1, "к 2026 — стандарт выравнивания LLM"),
    ("chain-of-thought", 2022, 1, "к 2026 — стандарт рассуждающих моделей"),
    ("low-rank adaptation", 2022, 1, "LoRA 2021; к 2026 — стандарт дообучения"),
    ("text-to-image", 2022, 1, "к 2026 — массовые продукты"),
    ("passkey", 2022, 1, "FIDO 2022; к 2026 — во всех крупных платформах и банках"),
    ("mixture of experts", 2022, 1, "к 2026 — архитектура ведущих LLM"),
    ("WebGPU", 2022, 1, "к 2026 — во всех основных браузерах"),
    ("NFT marketplace", 2022, 0, "к 2026 обороты упали в разы"),
    ("move-to-earn", 2022, 0, "бум 2022, к 2026 исчезло"),
    ("GameFi", 2022, 0, "к 2026 — ниша"),
    ("holographic telepresence", 2022, 0, "к 2026 — демонстрации"),
] + [(p, 2021, lab, note) for p, lab, note in CASES_2021]

TM_FEATURES = ["log_works_total", "log_works_recent2", "growth2", "accel", "recent_share3", "age_years",
               "log_nih_recent3", "nih_growth", "log_yc_total", "log_yc_recent2", "log_gh_repos_12m", "log_hn_12m", "wiki_exists"]
NO_YC = [f for f in TM_FEATURES if not f.startswith("log_yc")]
FEATURE_RU = {
    "log_works_total": "Научные работы до среза (лог)", "log_works_recent2": "Работы за 2 года до среза (лог)",
    "growth2": "Рост работ: 2 года до среза к 2 предыдущим", "accel": "Ускорение роста работ", "recent_share3": "Доля работ за 3 года",
    "age_years": "Возраст темы в литературе", "log_nih_recent3": "Гранты NIH за 3 года до среза (лог)", "nih_growth": "Рост грантов NIH",
    "log_yc_total": "Стартапы YC до среза (лог)", "log_yc_recent2": "Стартапы YC в 2 последних набора (лог)",
    "log_gh_repos_12m": "Репозитории GitHub за год до среза (лог)", "log_hn_12m": "Обсуждения Hacker News за год до среза (лог)",
    "wiki_exists": "Статья в Википедии на дату среза",
}


def series_features(yearly: dict[int, int], c: int) -> dict[str, float]:
    """Признаки годового ряда публикаций на 1 января года c (годы ≥ c не используются)."""
    s = {y: n for y, n in yearly.items() if y < c}
    total = sum(s.values())
    r2 = s.get(c - 1, 0) + s.get(c - 2, 0)
    p2 = s.get(c - 3, 0) + s.get(c - 4, 0)
    first = next((y for y in sorted(s) if s[y] >= 3), None)
    g_last = math.log1p(s.get(c - 1, 0)) - math.log1p(s.get(c - 2, 0))
    g_prev = math.log1p(s.get(c - 2, 0)) - math.log1p(s.get(c - 3, 0))
    return {
        "log_works_total": math.log1p(total), "log_works_recent2": math.log1p(r2),
        "growth2": math.log1p(r2 / 2) - math.log1p(p2 / 2), "accel": g_last - g_prev,
        "recent_share3": (r2 + s.get(c - 3, 0)) / total if total else 0.0,
        "age_years": float(min(c - first, 40)) if first else 0.0,
    }


def yc_features(companies: list[dict], phrase: str, c: int) -> dict[str, float]:
    years = [int(yc.batch_date(x.get("batch"))[:4]) for x in yc.find(companies, phrase) if yc.batch_date(x.get("batch"))]
    before = [y for y in years if y < c]
    return {"log_yc_total": math.log1p(len(before)), "log_yc_recent2": math.log1p(sum(1 for y in before if y >= c - 2))}


async def as_of(http: HttpClient, phrase: str, c: int, companies: list[dict]) -> tuple[dict[str, float], list[str]]:
    cutoff = date(c, 1, 1)
    year_before = cutoff - timedelta(days=365)
    ts_from = int(datetime.combine(year_before, datetime.min.time(), tzinfo=timezone.utc).timestamp())
    ts_to = int(datetime.combine(cutoff, datetime.min.time(), tzinfo=timezone.utc).timestamp())
    failed: list[str] = []
    yearly = await _safe("openalex", openalex.yearly_counts(http, phrase), {}, failed)
    nih_recent = await _safe("nih", grants.nih_yearly(http, phrase, [c - 3, c - 2, c - 1]), {}, failed)
    nih_prior = await _safe("nih", grants.nih_yearly(http, phrase, [c - 6, c - 5, c - 4]), {}, failed)
    _, hn = await _safe("hackernews", hackernews.search(http, phrase, ts_from, 10, until_ts=ts_to), ([], None), failed)
    gh = await _safe("github", github.count_created(http, phrase, year_before.isoformat(), cutoff.isoformat()), None, failed)
    wiki = await _safe("wikipedia", wikipedia.lookup(http, phrase, as_of=cutoff), {}, failed)
    nr, npr = sum(nih_recent.values()), sum(nih_prior.values())
    feats = {
        **series_features(yearly, c),
        "log_nih_recent3": math.log1p(nr), "nih_growth": math.log1p(nr) - math.log1p(npr),
        **yc_features(companies, phrase, c),
        "log_gh_repos_12m": math.log1p(gh or 0), "log_hn_12m": math.log1p(hn or 0), "wiki_exists": 1.0 if wiki.get("exists") else 0.0,
    }
    return feats, sorted(set(failed))


C_MAIN = 0.3  # выбрано заранее, до просмотра результатов; другие варианты публикуются рядом (variants_tried)
VARIANTS = {
    "13 признаков, C=0.3 (основная)": (TM_FEATURES, 0.3),
    "13 признаков, C=0.05": (TM_FEATURES, 0.05),
    "13 признаков, C=1": (TM_FEATURES, 1.0),
    "только динамика публикаций (4)": (["growth2", "accel", "recent_share3", "age_years"], 0.3),
    "динамика + GitHub, HN, гранты (7)": (["growth2", "accel", "recent_share3", "age_years", "log_gh_repos_12m", "log_hn_12m", "log_nih_recent3"], 0.3),
}


def _fit(X: np.ndarray, y: np.ndarray, C: float = C_MAIN):
    sc = StandardScaler().fit(X)
    clf = LogisticRegression(C=C, max_iter=2000, class_weight="balanced").fit(sc.transform(X), y)
    return sc, clf


def variants_tried(rows: list[dict]) -> dict[str, float]:
    """Все опробованные варианты модели — без выбора лучшего задним числом."""
    y = np.array([r["label"] for r in rows])
    return {name: round(float(roc_auc_score(y, out_of_time(rows, feats, C))), 3) for name, (feats, C) in VARIANTS.items()}


def out_of_time(rows: list[dict], feats: list[str], C: float = C_MAIN) -> np.ndarray:
    """Предсказание для каждой темы моделью, которая не видела ни одной темы того же года среза."""
    X = np.array([[r["features"][f] for f in feats] for r in rows])
    y = np.array([r["label"] for r in rows])
    cut = np.array([r["cutoff"] for r in rows])
    p = np.zeros(len(rows))
    for c in sorted(set(cut)):
        tr, te = cut != c, cut == c
        if len(set(y[tr])) < 2:
            p[te] = 0.5
            continue
        sc, clf = _fit(X[tr], y[tr], C)
        p[te] = clf.predict_proba(sc.transform(X[te]))[:, 1]
    return p


def _auc_ci(y: np.ndarray, s: np.ndarray, n_boot: int = 1000, seed: int = 0) -> dict:
    rng = np.random.default_rng(seed)
    auc = float(roc_auc_score(y, s))
    boots = []
    for _ in range(n_boot):
        i = rng.integers(0, len(y), len(y))
        if len(set(y[i])) == 2:
            boots.append(roc_auc_score(y[i], s[i]))
    lo, hi = np.percentile(boots, [2.5, 97.5])
    return {"roc_auc": round(auc, 3), "ci95": [round(float(lo), 3), round(float(hi), 3)]}


def _precision_at_k(y: np.ndarray, s: np.ndarray) -> float:
    k = max(1, int(y.sum()))
    return round(float(y[np.argsort(-s)[:k]].mean()), 3)


def evaluate(rows: list[dict]) -> dict:
    y = np.array([r["label"] for r in rows])
    cut = np.array([r["cutoff"] for r in rows])
    scorers = {
        "model_out_of_time": out_of_time(rows, TM_FEATURES),
        "model_out_of_time_without_yc": out_of_time(rows, NO_YC),
        "baseline_growth": np.array([r["features"]["growth2"] for r in rows]),
        "baseline_more_works": np.array([r["features"]["log_works_total"] for r in rows]),
        "baseline_more_grants": np.array([r["features"]["log_nih_recent3"] for r in rows]),
    }
    out = {"n": len(rows), "n_trend": int(y.sum()), "cutoffs": {str(c): int((cut == c).sum()) for c in sorted(set(cut))}}
    for name, s in scorers.items():
        out[name] = {**_auc_ci(y, s), "precision_at_k": _precision_at_k(y, s),
                     "by_cutoff": {str(c): round(float(roc_auc_score(y[cut == c], s[cut == c])), 3)
                                   for c in sorted(set(cut)) if len(set(y[cut == c])) == 2}}
    for r, p in zip(rows, scorers["model_out_of_time"], strict=True):
        r["p_out_of_time"] = round(float(p), 3)
    return out


async def collect(limit: int | None = None) -> list[dict]:
    http = HttpClient(patient=True)
    companies = await yc.load(http)
    rows = []
    for i, (phrase, c, label, note) in enumerate(CASES[:limit] if limit else CASES, 1):
        feats, failed = await as_of(http, phrase, c, companies)
        rows.append({"phrase": phrase, "cutoff": c, "label": label, "note": note, "features": {k: round(v, 4) for k, v in feats.items()},
                     "failed_sources": failed})
        log.info("%3d/%d %-40s %d label=%d growth=%.2f nih=%.1f yc=%.1f failed=%s", i, len(CASES), phrase, c, label,
                 feats["growth2"], feats["log_nih_recent3"], feats["log_yc_total"], failed)
    await http.close()
    return rows


def _previous() -> dict | None:
    """Результат прежней проверки (один срез 2021, модель на данных 2026 года) — для сравнения."""
    p = get_settings().model_dir / "backtest.json"
    if not p.exists():
        return None
    m = (json.loads(p.read_text(encoding="utf-8")).get("metrics") or {})
    return {"n": m.get("n"), "model_roc_auc": (m.get("model") or {}).get("roc_auc"), "growth_roc_auc": (m.get("baseline_growth") or {}).get("roc_auc")}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--reuse", action="store_true", help="пересчитать метрики по сохранённым признакам, без сети")
    args = ap.parse_args()
    s = get_settings()
    path = s.model_dir / "timemachine.json"
    rows = json.loads(path.read_text(encoding="utf-8"))["results"] if args.reuse and path.exists() else asyncio.run(collect(args.limit))
    # Без рядов OpenAlex признаки публикаций нулевые — такие темы в метрики не входят.
    complete = [r for r in rows if "openalex" not in r["failed_sources"]]
    if len({r["label"] for r in complete}) < 2 or len({r["cutoff"] for r in complete}) < 2:
        print(f"Собрано {len(complete)} тем, но для проверки нужны оба исхода и хотя бы два года среза.")
        return
    metrics = evaluate(complete)
    X = np.array([[r["features"][f] for f in TM_FEATURES] for r in complete])
    sc, clf = _fit(X, np.array([r["label"] for r in complete]))
    coefs = sorted(({"feature": f, "label": FEATURE_RU[f], "weight": round(float(w), 3)} for f, w in zip(TM_FEATURES, clf.coef_[0], strict=True)),
                   key=lambda x: -abs(x["weight"]))
    report = {"method": __doc__.split("Запуск:")[0].strip(), "metrics": metrics, "weights_all_data": coefs,
              "variants_tried": variants_tried(complete),
              "previous_single_cutoff": _previous(),
              "incomplete": len(rows) - len(complete), "results": sorted(rows, key=lambda r: (r["cutoff"], -r.get("p_out_of_time", 0)))}
    path.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in metrics.items()}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
