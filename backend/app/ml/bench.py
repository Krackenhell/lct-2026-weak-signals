"""Набор для оценки (раздел 7 исследования): снимки этапов прогона и повтор решения по снимку.

Снимок (SNAPSHOT_DIR задан) — план, корпус и все оценённые кандидаты одного прогона в gz-JSON. По снимку `redecide`
прогоняет продовый decide() с другой моделью или параметрами без сети и без вызовов моделей: изменения «ниже по конвейеру»
(разнообразие, фильтры, классификатор) сравниваются на одних и тех же входах, повтор детерминирован, стоимость 0 ₽.

Запуск:
    python -m app.ml.bench redecide data/bench/snapshots/run-61.json.gz [--model data/model/signal_model_prev.json]
    python -m app.ml.bench queries          # списки DEV / HOLD-OUT / контролей (data/bench/queries.json)
"""
import argparse
import gzip
import json
from pathlib import Path
from types import SimpleNamespace

from app.collectors.base import RawDoc
from app.config import get_settings
from app.ml.model import SignalModel
from app.pipeline.decide import decide


def save_snapshot(path: Path, run_id: int, query: str, plan: dict, corpus: list, assessed: list[dict], decide_kwargs: dict) -> Path:
    """Сохраняет всё, что нужно decide(), — без ключей и без текстов ответов LLM."""
    def doc(d) -> dict:
        return {"url": d.url, "title": d.title, "source_name": d.source_name, "source_type": d.source_type, "collector": d.collector,
                "published": d.published, "language": d.language}

    data = {
        "run_id": run_id, "query": query, "plan": {k: v for k, v in plan.items() if k != "emerging"} | {"emerging": plan.get("emerging", [])},
        "corpus": [doc(d) for d in corpus],
        "assessed": [{"c": {k: v for k, v in a["c"].items() if k in ("name_en", "name_ru", "methods", "doc_idx", "watch_id")},
                      "features": a["features"], "prob": a["prob"], "passport": a["passport"], "missing": a.get("missing", []),
                      "answers": a["res"].answers, "ok": a["res"].ok, "provider": getattr(a["res"], "provider", ""),
                      "docs": [doc(d) for d in a["ev"].docs], "topic_rel": a.get("topic_rel")} for a in assessed],
        "decide_kwargs": {k: (sorted(v) if isinstance(v, (set, frozenset)) else v) for k, v in decide_kwargs.items()},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return path


def load_assessed(snap: dict, model: SignalModel | None) -> list[dict]:
    out = []
    for a in snap["assessed"]:
        docs = [RawDoc(url=d["url"], title=d["title"], source_name=d["source_name"], source_type=d["source_type"], collector=d["collector"],
                       published=d.get("published"), language=d.get("language") or "en") for d in a["docs"]]
        prob = model.predict(a["features"]) if model else a["prob"]
        out.append({"c": a["c"], "features": a["features"], "prob": prob, "passport": a["passport"], "missing": a["missing"],
                    "res": SimpleNamespace(answers=a["answers"], ok=a["ok"], provider=a["provider"]),
                    "ev": SimpleNamespace(docs=docs, failed=[]), "topic_rel": a.get("topic_rel")})
    return out


def redecide(path: Path, model_path: Path | None = None) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        snap = json.load(f)
    model = SignalModel.load(model_path) if model_path else SignalModel.load()
    kw = dict(snap["decide_kwargs"])
    kw["anchors"] = frozenset(kw.get("anchors", []))
    assessed = load_assessed(snap, model)
    res = decide(assessed, model, get_settings().top_k, **kw)
    return [{"name": a["c"]["name_en"], "status": d["status"], "rank": d.get("rank"), "code": d.get("code"),
             "p": round(a["prob"], 3) if a["prob"] is not None else None} for a, d in zip(assessed, res, strict=True)]


# Списки из раздела 7A исследования. HOLD-OUT не смотрим до финального замера и не используем в примерах, глоссарии и тестах.
QUERIES = {
    "dev": ["технологии многослойного графена", "микрофлюидные чипы", "органы на чипе", "твердотельные аккумуляторы",
            "перовскитные солнечные элементы", "персонализированные противоопухолевые вакцины",
            "медицинские микророботы и адресная доставка лекарств", "долговременное хранение энергии", "агентная коммерция",
            "безопасность ИИ-агентов и протокола MCP", "оптические межсоединения для ИИ-кластеров", "multilayer graphene", "LNP доставка мРНК"],
    "holdout": ["жидкостная биопсия", "аддитивное производство титановых сплавов", "цифровые двойники месторождений", "биоразлагаемая упаковка",
                "вертикальные фермы", "сверхпроводящие кабели", "твердооксидные электролизёры", "SiC силовая электроника", "уничтожение PFAS",
                "прецизионная ферментация и альтернативные белки"],
    "regression": ["перспективные решения в финтехе", "слабые сигналы в кибербезопасности ИИ", "робототехника",
                   "edge AI и вычисления на устройствах", "инфраструктура для ИИ", "индустриальный ИИ"],
    "controls": {"reject": ["Привет", "почему мирэа лучший вуз"], "broad": ["искусственный интеллект"], "maturity": ["постквантовая криптография"]},
    "silver": {
        "технологии многослойного графена": ["rhombohedral multilayer graphene", "ABC multilayer graphene", "twisted multilayer graphene",
                                             "epitaxial SiC graphene", "graphene BEOL interconnects", "flash graphene", "laser-induced graphene"],
        "микрофлюидные чипы": ["organ-on-chip", "digital microfluidics", "EWOD", "droplet single-cell", "acoustofluidics",
                               "sweat-sensing wearables", "microfluidic LNP formulation", "3D-printed microfluidics"],
    },
    "mature_controls": {"технологии многослойного графена": ["graphene oxide", "CVD graphene"],
                        "микрофлюидные чипы": ["PCR", "ELISA", "PDMS soft lithography"]},
}


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("redecide")
    r.add_argument("snapshot")
    r.add_argument("--model", default="")
    sub.add_parser("queries")
    args = ap.parse_args()
    if args.cmd == "queries":
        p = Path(get_settings().model_dir).parent / "bench" / "queries.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(QUERIES, ensure_ascii=False, indent=1), encoding="utf-8")
        print(p)
        return
    for row in redecide(Path(args.snapshot), Path(args.model) if args.model else None):
        print(json.dumps(row, ensure_ascii=False))


if __name__ == "__main__":
    main()
