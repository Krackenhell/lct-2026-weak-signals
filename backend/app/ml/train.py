"""Этап 1 ТЗ: обучение и оценка модели на датасете.

Положительные примеры — 100 слабых сигналов организатора. Отрицательные — наш набор
зрелых технологий, стандартов, хайпа и слишком общих областей (data/seed/negatives.json).
Для каждого примера собираются доказательства из открытых источников тем же кодом,
что и при живом поиске, затем считаются признаки и обучается логистическая регрессия.

Запуск:
    python -m app.ml.train                 # собрать признаки (с кэшем) и обучить
    python -m app.ml.train --refit         # только переобучить по сохранённым признакам
    python -m app.ml.train --reask         # заново опросить decision-модель по сохранённым доказательствам
"""
import argparse
import asyncio
import json
import logging
import math
from datetime import date
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, f1_score, precision_score, recall_score, roc_auc_score
from sklearn.model_selection import StratifiedKFold
from sklearn.preprocessing import StandardScaler

from app.collectors.http import HttpClient
from app.config import get_settings
from app.decision import get_decision_model
from app.ml.model import SignalModel
from app.pipeline import evidence as evidence_mod
from app.pipeline.features import ANSWERS, CORE_COLLECTORS, FEATURES, NUMERIC, answer_features, numeric_features
from app.pipeline.questions import EVENT, QUESTIONS, build_state

log = logging.getLogger("train")
# Дата отсечения для обучения фиксирована, чтобы признаки были воспроизводимы.
TRAIN_DATE = date(2026, 9, 23)
# Минимум найденных документов, чтобы пример участвовал в обучении и оценке (как турникет в живом поиске).
MIN_DOCS = 3
# Источники, из которых считаются числовые признаки: без них пример неполный и в обучение не идёт.
CORE_SOURCES = {"arxiv", "openalex"}
# Перенос на область с меньшим числом сигналов в проверке не публикуется числом: оценка по 2–4 примерам ничего не значит.
MIN_LODO_POS = 5
EVIDENCE_RULE = "OpenAlex находит хотя бы одну работу по термину"
# Признаки, которые не входят в классификатор (П9, ворота app/ml/gates_h4.py пройдены 19.10.2026):
# - GitHub и Hacker News: вне IT почти у всех ноль, и ноль давал +1,9 логита — «нет GitHub = сигнал» для графена и химии;
#   репозитории и обсуждения остаются документами-доказательствами;
# - independent, early_stage, benefit: вес получался против смысла вопроса (противоречие знаков), а ответы Jev на живом
#   поиске сдвинуты относительно обучения (independent — на 2,8 sd).
# Списки FEATURES и ANSWERS не меняются: признаки по-прежнему считаются и видны в карточке.
MODEL_EXCLUDE = ("log_gh_repos_12m", "log_hn_12m", "independent", "early_stage", "benefit")
Z_CLIP = 3.0  # отсечка отклонения при оценке — та же, что при предсказании (model._z)


def has_evidence(r: dict) -> bool:
    """Пример участвует в обучении, если по термину есть научная история (OpenAlex нашёл работы).

    Подобрано на данных 17.10.2026: так в обучении нет «пустых» примеров ни в одном классе
    (иначе модель учит правило «ничего не нашли — значит сигнал»), а сигналов остаётся больше всего."""
    return (r.get("numeric") or {}).get("log_total_works", 0) > 0


def load_examples() -> list[dict]:
    s = get_settings()
    seed = Path(s.seed_dir)
    pos = json.loads((seed / "weak_signals_2026.json").read_text(encoding="utf-8"))
    terms = json.loads((seed / "positive_terms.json").read_text(encoding="utf-8"))
    neg = json.loads((seed / "negatives.json").read_text(encoding="utf-8"))["items"]
    rows = []
    for p in pos:
        t = terms[str(p["id"])]
        rows.append({"key": f"pos-{p['id']}", "label": 1, "name": p["name"], "domain": p["domain"], "code": "signal", "phrase": t[0], "alt_terms": t[1:]})
    for i, n in enumerate(neg):
        rows.append({"key": f"neg-{i}", "label": 0, "name": n["name_ru"], "domain": n["domain"], "code": n["code"], "phrase": n["terms"][0], "alt_terms": n["terms"][1:]})
    return rows


async def collect(rows: list[dict], concurrency: int = 3) -> tuple[list[dict], dict]:
    """Собирает доказательства и числовые признаки для каждого примера.

    Терпеливый режим: если основной источник признаков (arXiv, OpenAlex) не ответил, пример собирается заново
    через паузу; если и после повторов данных нет — пример помечается неполным и в обучение не идёт.
    """
    http = HttpClient(patient=True)
    sem = asyncio.Semaphore(concurrency)
    evidence_store: dict = {}
    done = 0

    async def gather_example(r):
        ev = await evidence_mod.gather(http, r["phrase"], TRAIN_DATE, with_news=False, with_repos=False)
        # Как при живом поиске (runner.assess): мало документов — пробуем запасной термин.
        for alt in r.get("alt_terms", [])[:1]:
            if len(ev.docs) >= 5:
                break
            alt_ev = await evidence_mod.gather(http, alt, TRAIN_DATE, with_news=False, with_repos=False)
            if len(alt_ev.docs) > len(ev.docs) and not set(alt_ev.failed) & CORE_SOURCES:
                ev = alt_ev
        return ev

    async def one(r):
        nonlocal done
        async with sem:
            ev = await gather_example(r)
            for attempt in range(3):
                if not set(ev.failed) & CORE_SOURCES:
                    break
                await asyncio.sleep(30 * (attempt + 1))
                ev = await gather_example(r)
        r["phrase_used"] = ev.phrase
        r["numeric"] = numeric_features(ev)
        r["failed_sources"] = sorted(set(ev.failed))
        r["incomplete"] = sorted(set(ev.failed) & CORE_SOURCES)
        # Порог «есть доказательства» считается по тем же источникам, что и признаки (arXiv, Hacker News).
        # Crossref ищет нестрого и находит «документы» почти по любой фразе — по нему порог терял смысл.
        r["n_docs_all"] = len(ev.docs)
        r["n_docs"] = sum(1 for d in ev.docs if d.collector in CORE_COLLECTORS)
        evidence_store[r["key"]] = evidence_mod.evidence_items(ev)
        done += 1
        if done % 10 == 0:
            log.info("collected %d/%d", done, len(rows))

    await asyncio.gather(*(one(r) for r in rows))
    log.info("http stats: %s", http.stats)
    await http.close()
    return rows, evidence_store


async def ask_all(rows: list[dict], evidence_store: dict, provider: str | None = None) -> str:
    model = get_decision_model(provider)
    sem = asyncio.Semaphore(8)

    questions = {**QUESTIONS, "event": EVENT}

    async def one(r):
        state = build_state(r["phrase"], "", evidence_store.get(r["key"], []))
        async with sem:
            res = await model.ask(state, questions)
        r["answers"] = answer_features(res.answers)
        r["decision_ok"] = res.ok

    await asyncio.gather(*(one(r) for r in rows))
    return f"{model.provider}:{model.model}"


def feedback_rows(provider: str) -> tuple[list[dict], dict]:
    """Оценки аналитиков как дополнительные размеченные примеры (human-in-the-loop).

    Берём только оценки по кандидатам, признаки которых дала та же decision-модель, что и обучающая выборка
    (иначе распределения признаков разойдутся), и только с доказательствами (≥ MIN_DOCS документов).
    """
    from app.db import SessionLocal
    from app.models import Feedback

    with SessionLocal() as s:
        fbs = s.query(Feedback).order_by(Feedback.id).all()
    latest = {f.candidate_id: f for f in fbs}  # если аналитик передумал — берём последнее решение
    rows, skipped = [], {"other_provider": 0, "no_evidence": 0}
    for f in latest.values():
        if f.provider.split(":")[0] != provider.split(":")[0]:
            skipped["other_provider"] += 1
            continue
        if f.n_docs < MIN_DOCS:
            skipped["no_evidence"] += 1
            continue
        feats = f.features or {}
        rows.append({
            "key": f"fb-{f.id}", "label": int(f.verdict == "signal"), "name": f.name, "domain": "Оценки аналитиков", "code": f"feedback:{f.verdict}",
            "numeric": {k: feats.get(k, 0.0) for k in NUMERIC}, "answers": {k: feats[k] for k in ANSWERS if k in feats}, "n_docs": f.n_docs,
        })
    return rows, {"used": len(rows), **skipped}


def _matrix(rows, feats):
    # Нет ответа на вопрос (например, «event» до переопроса) — нейтральные 0.5; такие признаки отбрасывает _usable.
    X = np.array([[{**r["numeric"], **r["answers"]}.get(f, 0.5) for f in feats] for r in rows], dtype=float)
    y = np.array([r["label"] for r in rows])
    return X, y


def _usable(rows, feats) -> list[str]:
    """Признаки, которые реально различаются у примеров: постоянный столбец не несёт информации."""
    X, _ = _matrix(rows, feats)
    return [f for f, col in zip(feats, X.T, strict=False) if np.std(col) > 1e-9]


def _fit(X, y, C=0.5):
    sc = StandardScaler().fit(X)
    clf = LogisticRegression(C=C, max_iter=2000, class_weight="balanced").fit(sc.transform(X), y)
    return sc, clf


def _oof(X, y, groups=None, C=0.5, seed=42):
    """Out-of-fold вероятности с той же отсечкой ±3σ, что и в проде: оценка не расходится с живым поиском."""
    oof = np.zeros(len(y))
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=seed)
    for tr, te in skf.split(X, y):
        sc, clf = _fit(X[tr], y[tr], C)
        z = np.clip(sc.transform(X[te]), -Z_CLIP, Z_CLIP)
        oof[te] = _sigmoid(z @ clf.coef_[0] + clf.intercept_[0])
    return oof


def _oof_logit(X, y, C=0.5, seed=42):
    """Логиты кросс-валидации: каждый пример оценён моделью, которая его не видела."""
    out = np.zeros(len(y))
    for tr, te in StratifiedKFold(n_splits=5, shuffle=True, random_state=seed).split(X, y):
        sc, clf = _fit(X[tr], y[tr], C)
        out[te] = clf.decision_function(sc.transform(X[te]))
    return out


def _sigmoid(z):
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))


def _ece(y, p, bins: int = 10) -> float:
    """Ожидаемая ошибка калибровки: насколько «80%» на деле расходится с долей сигналов среди таких кандидатов."""
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges) - 1, 0, bins - 1)
    return float(sum(abs(p[idx == b].mean() - y[idx == b].mean()) * (idx == b).mean() for b in range(bins) if (idx == b).any()))


def fit_temperature(logits, y) -> float:
    """Температура T ≥ 1, минимизирующая логарифмическую потерю на out-of-fold логитах (поиск по сетке)."""
    best_t, best = 1.0, float("inf")
    for t in np.arange(1.0, 15.01, 0.05):
        p = np.clip(_sigmoid(logits / t), 1e-6, 1 - 1e-6)
        loss = float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
        if loss < best - 1e-9:
            best_t, best = float(t), loss
    return round(best_t, 2)


def calibration_report(logits, y, t: float) -> dict:
    before, after = _sigmoid(logits), _sigmoid(logits / t)
    bins = []
    for lo, hi in ((0, 0.25), (0.25, 0.5), (0.5, 0.75), (0.75, 0.9), (0.9, 1.01)):
        m = (after >= lo) & (after < hi)
        if m.any():
            bins.append({"range": f"{int(lo * 100)}–{min(int(hi * 100), 100)}%", "n": int(m.sum()), "mean_p": round(float(after[m].mean()), 3),
                         "share_signals": round(float(y[m].mean()), 3)})
    return {"temperature": t, "ece_before": round(_ece(y, before), 3), "ece_after": round(_ece(y, after), 3),
            "max_p_before": round(float(before.max()), 4), "max_p_after": round(float(after.max()), 4),
            "brier_before": round(float(brier_score_loss(y, before)), 3), "brier_after": round(float(brier_score_loss(y, after)), 3),
            "bins": bins}


def _metrics(y, p, thr=0.5) -> dict:
    pred = (p >= thr).astype(int)
    return {
        "precision": round(float(precision_score(y, pred, zero_division=0)), 3),
        "recall": round(float(recall_score(y, pred, zero_division=0)), 3),
        "f1": round(float(f1_score(y, pred, zero_division=0)), 3),
        "accuracy": round(float((pred == y).mean()), 3),
        "roc_auc": round(float(roc_auc_score(y, p)), 3),
        "brier": round(float(brier_score_loss(y, p)), 3),
    }


def _bootstrap_ci(y, p, n_boot: int = 1000, seed: int = 7) -> dict:
    """95% доверительные интервалы метрик по out-of-fold предсказаниям (бутстрэп по примерам)."""
    rng = np.random.default_rng(seed)
    vals = {"precision": [], "recall": [], "f1": [], "roc_auc": []}
    for _ in range(n_boot):
        idx = rng.integers(0, len(y), len(y))
        if len(set(y[idx])) < 2:
            continue
        m = _metrics(y[idx], p[idx])
        for k in vals:
            vals[k].append(m[k])
    return {k: [round(float(np.percentile(v, 2.5)), 3), round(float(np.percentile(v, 97.5)), 3)] for k, v in vals.items()}


def _repeated(X, y, repeats: int = 10) -> dict:
    """Кросс-валидация 5×10 с разными разбиениями: среднее и разброс, а не одно удачное число."""
    f1s = [_metrics(y, _oof(X, y, seed=s))["f1"] for s in range(repeats)]
    return {"f1_mean": round(float(np.mean(f1s)), 3), "f1_std": round(float(np.std(f1s)), 3), "repeats": repeats}


LIMITATIONS = [
    "Отрицательные примеры собраны командой (включая 26 трудных: малоизвестные зрелые технологии, направления с угасшим интересом, общие "
    "направления); пограничных случаев всё равно мало, поэтому метрики — верхняя оценка.",
    f"В обучение и оценку входят только примеры, у которых есть научная история ({EVIDENCE_RULE}): без неё признаки "
    "не несут информации, и модель училась бы правилу «ничего не нашли — значит сигнал». У части сигналов организатора "
    "такой истории нет — они в обучении не участвуют.",
    f"Перенос на новую область считается на 20–50 примерах; для областей, где в проверке меньше {MIN_LODO_POS} сигналов, число "
    "не публикуется — такая оценка ничего не значит.",
    "В живом поиске кандидат без подтверждённых документов не попадает в топ, а уходит в «Наблюдать».",
    "Признак «самое твёрдое событие» пока не входит в модель: для этого нужен переопрос обучающей выборки decision-моделью (--reask).",
]


def _hard_keys() -> set[str]:
    """Ключи «трудных» отрицательных примеров (малоизвестные зрелые технологии и т. п., поле hard в negatives.json)."""
    try:
        items = json.loads((Path(get_settings().seed_dir) / "negatives.json").read_text(encoding="utf-8"))["items"]
    except (OSError, ValueError, KeyError):
        return set()
    return {f"neg-{i}" for i, n in enumerate(items) if n.get("hard")}


def slices(rows: list[dict], y, oof) -> dict:
    """П16-A: где модель ошибается. Доля ложных сигналов (p ≥ 0,5) по типам отрицательных примеров и по малым темам,
    плюс доля насыщенных оценок. Общий F1 скрывает, что на хайпе и малоизвестных фразах ошибок в разы больше."""
    hard = _hard_keys()
    neg = [i for i, r in enumerate(rows) if r["label"] == 0]
    groups = {
        "Хайп": [i for i in neg if rows[i]["code"] == "hype"],
        "«Трудные» отрицательные": [i for i in neg if rows[i]["key"] in hard],
        "Меньше 300 работ": [i for i in neg if math.expm1((rows[i].get("numeric") or {}).get("log_total_works", 0)) < 300],
        "Зрелые": [i for i in neg if rows[i]["code"] == "mature"],
        "Стандарты и широкие": [i for i in neg if rows[i]["code"] in ("standard", "broad")],
    }
    out = {name: {"n": len(idx), "false_signals": round(float(np.mean([oof[i] >= 0.5 for i in idx])), 3) if idx else None} for name, idx in groups.items()}
    pos = y == 1
    return {"false_signal_share": out, "positives_p_ge_099": round(float((oof[pos] >= 0.99).mean()), 3),
            "all_p_ge_095": round(float((oof >= 0.95).mean()), 3)}


def evaluate_and_fit(rows: list[dict], provider: str) -> dict:
    incomplete = [r for r in rows if r.get("incomplete")]
    all_rows = [r for r in rows if not r.get("incomplete")]  # источники признаков не ответили — пример не используем вовсе
    rows = [r for r in all_rows if has_evidence(r)]
    feats_all = [f for f in _usable(rows, FEATURES) if f not in MODEL_EXCLUDE]
    X, y = _matrix(rows, feats_all)
    oof = _oof(X, y)
    report = {"provider": provider, "n": int(len(y)), "n_pos": int(y.sum()), "n_neg": int((1 - y).sum()), "train_date": TRAIN_DATE.isoformat()}
    report["min_docs"] = MIN_DOCS
    report["evidence_rule"] = EVIDENCE_RULE
    report["incomplete_sources"] = {"rows": len(incomplete), "names": [r["name"] for r in incomplete][:20]}
    dropped = [r for r in all_rows if r.get("n_docs", 0) < MIN_DOCS]
    report["dropped_no_evidence"] = {"pos": sum(r["label"] for r in dropped), "neg": sum(1 - r["label"] for r in dropped)}
    report["cv5"] = _metrics(y, oof)
    report["cv5_ci95"] = _bootstrap_ci(y, oof)
    report["cv5_repeated"] = _repeated(X, y)
    report["slices"] = slices(rows, y, oof)
    # Для сравнения — прежний способ: все 240 примеров, включая примеры без доказательств.
    Xa, ya = _matrix(all_rows, [f for f in _usable(all_rows, FEATURES) if f not in MODEL_EXCLUDE])
    report["reference_all_rows"] = {"n": int(len(ya)), **_metrics(ya, _oof(Xa, ya))}
    report["features_used"] = feats_all
    report["features_dropped"] = [f for f in FEATURES if f not in feats_all]
    report["model_exclude"] = {"features": list(MODEL_EXCLUDE), "why": "ворота П9 (app/ml/gates_h4.py, data/model/gates_h4.json)"}
    report["limitations"] = LIMITATIONS if "event" not in feats_all else [s for s in LIMITATIONS if "событие" not in s]
    report["confident_75"] = {
        "share_of_positives_above_075": round(float((oof[y == 1] >= 0.75).mean()), 3),
        "precision_above_075": round(float(y[oof >= 0.75].mean()) if (oof >= 0.75).any() else 0.0, 3),
    }

    # Ablation: какой вклад дают группы признаков.
    report["ablation"] = {}
    for name, feats in {"numeric_only": [f for f in NUMERIC if f in feats_all], "decision_model_only": [f for f in ANSWERS if f in feats_all], "all": feats_all}.items():
        Xa, _ = _matrix(rows, feats)
        report["ablation"][name] = _metrics(y, _oof(Xa, y))

    # Перенос на новую область: обучаемся без одной области, проверяем на ней.
    domains = sorted({r["domain"] for r in rows if r["label"] == 1})
    lodo = {}
    for d in domains:
        tr = np.array([r["domain"] != d for r in rows])
        te = ~tr
        sc, clf = _fit(X[tr], y[tr])
        p = clf.predict_proba(sc.transform(X[te]))[:, 1]
        n_pos = int(y[te].sum())
        if n_pos >= MIN_LODO_POS and len(set(y[te])) > 1:
            lodo[d] = _metrics(y[te], p)
            lodo[d]["f1_ci95"] = _bootstrap_ci(y[te], p, n_boot=500)["f1"]
            errors = int(((p >= 0.5) != y[te]).sum())
            lodo[d]["errors"] = errors
            if errors == 0:
                # Ни одной ошибки: бутстрэп вырождается в «1,00–1,00». Честнее верхняя граница доли ошибок
                # (точная, по Клопперу — Пирсону): с 95% уверенностью ошибок не больше этой доли.
                lodo[d]["error_rate_upper95"] = round(1 - 0.05 ** (1 / int(te.sum())), 3)
        else:
            lodo[d] = {"too_few": True}  # мало сигналов для оценки — число не публикуем
        lodo[d].update(n=int(te.sum()), n_pos=n_pos)
    report["leave_one_domain_out"] = lodo

    # Полнота по областям датасета организатора (out-of-fold).
    report["recall_by_domain"] = {
        d: round(float(np.mean([oof[i] >= 0.5 for i, r in enumerate(rows) if r["label"] == 1 and r["domain"] == d])), 3) for d in domains
    }
    report["errors"] = sorted(
        [{"name": r["name"], "label": r["label"], "code": r["code"], "p": round(float(oof[i]), 3)} for i, r in enumerate(rows) if (oof[i] >= 0.5) != bool(r["label"])],
        key=lambda e: -abs(e["p"] - 0.5),
    )[:40]

    # Калибровка: почему не бывает «100%». Температура подбирается по прогнозам на невиденных примерах.
    logits = _oof_logit(X, y)
    temperature = fit_temperature(logits, y)
    report["calibration"] = calibration_report(logits, y, temperature)

    sc, clf = _fit(X, y)
    model = SignalModel(
        temperature=temperature,
        features=list(feats_all),
        mean=[float(v) for v in sc.mean_],
        scale=[float(v) for v in sc.scale_],
        coef=[float(v) for v in clf.coef_[0]],
        intercept=float(clf.intercept_[0]),
        meta={"provider": provider, "trained_on": report["n"], "min_docs": MIN_DOCS, "train_date": TRAIN_DATE.isoformat(), "cv5": report["cv5"]},
    )
    model.save()
    report["weights"] = sorted(
        [{"feature": f, "weight": round(c, 3)} for f, c in zip(feats_all, model.coef, strict=False)], key=lambda r: -abs(r["weight"])
    )
    return report


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # URL запросов содержат api_key источников
    ap = argparse.ArgumentParser()
    ap.add_argument("--refit", action="store_true")
    ap.add_argument("--reask", action="store_true")
    ap.add_argument("--provider", default=None)
    ap.add_argument("--with-feedback", action="store_true", help="добавить оценки аналитиков из БД как размеченные примеры")
    args = ap.parse_args()

    s = get_settings()
    out = Path(s.model_dir)
    out.mkdir(parents=True, exist_ok=True)
    rows_path, ev_path = out / "training_rows.json", out / "training_evidence.json"

    if args.refit or args.reask:
        rows = json.loads(rows_path.read_text(encoding="utf-8"))
        evidence_store = json.loads(ev_path.read_text(encoding="utf-8"))
        provider = rows[0].get("provider", "unknown") if rows else "unknown"
    else:
        rows, evidence_store = asyncio.run(collect(load_examples()))
        ev_path.write_text(json.dumps(evidence_store, ensure_ascii=False), encoding="utf-8")
        args.reask = True

    if args.reask:
        provider = asyncio.run(ask_all(rows, evidence_store, args.provider))
        for r in rows:
            r["provider"] = provider
        rows_path.write_text(json.dumps(rows, ensure_ascii=False, indent=0), encoding="utf-8")

    before = out / "metrics_before.json"
    if (out / "metrics.json").exists() and not before.exists():
        before.write_text((out / "metrics.json").read_text(encoding="utf-8"), encoding="utf-8")  # исходные цифры — для сравнения
    fb_info = None
    if args.with_feedback:
        extra, fb_info = feedback_rows(provider)
        rows = rows + extra
        log.info("feedback: %s", fb_info)
    report = evaluate_and_fit(rows, provider)
    if fb_info is not None:
        report["feedback"] = fb_info
    (out / "metrics.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    log.info("CV5: %s", report["cv5"])
    log.info("ablation: %s", report["ablation"])
    log.info("LODO: %s", report["leave_one_domain_out"])


if __name__ == "__main__":
    main()
