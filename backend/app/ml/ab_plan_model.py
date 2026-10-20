"""A/B модели плана поиска (П7, docs/research): GigaChat-2 против GigaChat-2-Max на одних и тех же запросах.

Объективные метрики без судьи-LLM (оценку «хорошая подтема» вслепую делают люди по выгрузке):
- валидный план (JSON с подзапросами) и задержка;
- «выдуманные» подзапросы: точная фраза находит меньше 5 работ в OpenAlex с 2023 года;
- подзапросы по теме: содержат якорь запроса (регулярка зафиксирована заранее).
Правило выбора (из протокола): Max для плана, если в среднем даёт +1 хороший подзапрос из 6, на 30 % меньше выдуманных,
p95 задержки ≤ 20 с и без таймаутов; иначе план остаётся на основной модели.

Запуск: python -m app.ml.ab_plan_model   Результат: data/model/ab_plan_model.json
"""
import asyncio
import json
import re
import time
from datetime import date
from pathlib import Path

from app.collectors import openalex
from app.collectors.http import HttpClient, SourceError
from app.config import get_settings
from app.llm import tasks
from app.llm.providers import ModelView, get_llm

QUERIES = {
    "технология многослойного графена": r"graphen",
    "микрофлюидные чипы": r"microflu|lab.on.a.chip|organ.on|droplet",
    "перовскитные солнечные элементы": r"perovskit",
    "твердотельные аккумуляторы": r"solid.state|electrolyte|batter",
    "спайковые нейронные сети": r"spik|neuromorph",
    "гомоморфное шифрование": r"homomorph|encrypt|fhe",
    "газлифт в газоконденсатных скважинах": r"gas.lift|well|condensate",
    "перспективные решения в финтехе": r"fintech|payment|bank|financ|token|stablecoin|credit|kyc|aml",
}
MODELS = ["GigaChat-2", "GigaChat-2-Max"]


async def invented(http: HttpClient, phrase: str, cache: dict) -> bool | None:
    if phrase in cache:
        return cache[phrase]
    try:
        n = await openalex.count(http, f"{openalex._phrase_filter(phrase)},publication_year:2023-{date.today().year}")
        cache[phrase] = n < 5
    except SourceError:
        cache[phrase] = None
    return cache[phrase]


async def main_async() -> None:
    base = get_llm()
    http = HttpClient()
    cache: dict = {}
    rows = []
    try:
        for q, anchor in QUERIES.items():
            for m in MODELS:
                llm = base if m == base.model else ModelView(base, m)
                t = time.perf_counter()
                plan, res = await tasks.plan_query(llm, q)
                sec = round(time.perf_counter() - t, 1)
                llm_subs = [s for s in plan["subqueries"] if s] if plan.get("generated_by", "").startswith("gigachat") else []
                # Оцениваем подтемы самой модели (до словаря): у широкого запроса — первые 6, у узкого — все, кроме названия предмета.
                own = llm_subs[:6] if plan.get("broad") else [s for s in llm_subs if s not in plan.get("query_en", [])][:6]
                inv = [await invented(http, s, cache) for s in own]
                rows.append({
                    "query": q, "model": m, "seconds": sec, "ok": bool(res and res.ok and own), "error": (res.error if res else "") or "",
                    "subqueries": own, "query_en": plan.get("query_en"), "topic_en": plan.get("topic_en"),
                    "on_topic": sum(1 for s in own if re.search(anchor, s, re.I)), "invented": sum(1 for x in inv if x), "checked": sum(1 for x in inv if x is not None),
                })
                print(json.dumps({k: rows[-1][k] for k in ("query", "model", "seconds", "ok", "on_topic", "invented", "checked")}, ensure_ascii=False), flush=True)
    finally:
        await http.close()
    summary = {}
    for m in MODELS:
        r = [x for x in rows if x["model"] == m]
        secs = sorted(x["seconds"] for x in r)
        summary[m] = {
            "valid_plans": sum(x["ok"] for x in r), "n": len(r),
            "on_topic_per_plan": round(sum(x["on_topic"] for x in r) / len(r), 2),
            "good_per_plan": round(sum(x["on_topic"] - x["invented"] for x in r) / len(r), 2),
            "invented_share": round(sum(x["invented"] for x in r) / max(sum(x["checked"] for x in r), 1), 3),
            "p95_seconds": secs[min(len(secs) - 1, int(0.95 * len(secs)))],
            "median_seconds": secs[len(secs) // 2],
        }
    a, b = summary[MODELS[0]], summary[MODELS[1]]
    choose_max = (b["good_per_plan"] - a["good_per_plan"] >= 1 and b["invented_share"] <= 0.7 * a["invented_share"]
                  and b["p95_seconds"] <= 20 and b["valid_plans"] == b["n"])
    out = {"date": date.today().isoformat(), "summary": summary, "decision": "GigaChat-2-Max для плана" if choose_max else "план остаётся на GigaChat-2",
           "rule": "Max, если +1 хороший подзапрос из 6, выдуманных на 30 % меньше, p95 ≤ 20 с, без сбоев", "rows": rows}
    path = Path(get_settings().model_dir) / "ab_plan_model.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"summary": summary, "decision": out["decision"]}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    asyncio.run(main_async())
