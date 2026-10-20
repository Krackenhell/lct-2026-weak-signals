"""Живая проверка П1 (docs/research): «только корпус» — план старый и новый на ОДНОМ и том же ответе GigaChat.

Старый план: 6 подзапросов LLM + подтемы словаря области (как до доработки; кириллица не отбрасывалась).
Новый план: для узкого запроса — английское название предмета первым, подтемы LLM, без словаря.
Метрика: доля англоязычных документов корпуса, в заголовке или фрагменте которых есть «якорь» темы
(регулярки зафиксированы до прогона). Успех по протоколу: у нового плана ≥ 70 % и на +25 п. п. больше, корпус ≥ 150 документов.

Запуск: python -m app.ml.ab_corpus [--queries "q1;q2"]   Результат: data/model/ab_narrow_plan.json
"""
import argparse
import asyncio
import json
import re
from pathlib import Path

from app.collectors.http import HttpClient
from app.config import get_settings
from app.llm import tasks
from app.llm.providers import get_llm, parse_json
from app.pipeline import discovery

ANCHORS = {
    "микрофлюидные чипы": r"microflu|lab.on.a.chip|organ.on",
    "органы на чипе": r"organ.on|organoid|microflu|lab.on.a.chip|microphysiolog",
    "микрофлюидные устройства": r"microflu|lab.on.a.chip|organ.on",
    "технологии многослойного графена": r"graphen",
    "перовскитные солнечные элементы": r"perovskit",
    "твердотельные аккумуляторы": r"solid.state|solid electrolyte",
}


def old_plan(query: str, data: dict) -> dict:
    """План до доработки: 6 подзапросов LLM как есть + подтемы словаря (DOMAIN_LEXICON по всем совпавшим корням)."""
    subs = [tasks.clean_phrase(s) for s in data.get("subqueries", []) if isinstance(s, str)][:6]
    old_lexicon = {**tasks.DOMAIN_LEXICON}
    # В старом словаре «чип» относился к инфраструктуре ИИ: восстанавливаем это для честного сравнения.
    infra = next(k for k in old_lexicon if "дата-центр" in k)
    old_lexicon[infra.replace("ии-чип|чип\\w* для ии|ai chip", "чип")] = old_lexicon.pop(infra)
    lex = [t for p, ts in old_lexicon.items() if re.search(p, query.lower()) for t in ts]
    return {"topic_en": tasks.clean_phrase(str(data.get("topic_en") or "")) or query,
            "subqueries": subs + [t for t in lex if t not in subs][: max(0, 12 - len(subs))],
            "ru_terms": data.get("ru_terms", []), "query": query}


def share(corpus, anchor: str) -> tuple[int, int]:
    en = [d for d in corpus if (d.language or "en") == "en"]
    hit = sum(1 for d in en if re.search(anchor, f"{d.title} {d.snippet}", re.I))
    return hit, len(en)


async def one(llm, query: str) -> dict:
    res = await llm.complete(tasks.SYSTEM_ANALYST, await _plan_prompt(query), temperature=0.3, max_tokens=700)
    data = parse_json(res.text) if res.ok else None
    if not isinstance(data, dict):
        return {"query": query, "error": "GigaChat не вернул план"}
    new, _ = await tasks.plan_query(_Replay(res), query)
    old = old_plan(query, data)
    out = {"query": query, "anchor": ANCHORS[query], "old_subqueries": old["subqueries"], "new_subqueries": new["subqueries"]}
    for name, plan in (("old", old), ("new", {**new, "query": query})):
        http = HttpClient()
        try:
            corpus = await discovery.build_corpus(http, plan)
        finally:
            await http.close()
        hit, n = share(corpus, ANCHORS[query])
        out[name] = {"docs": len(corpus), "en_docs": n, "on_topic": hit, "share": round(hit / max(n, 1), 3)}
        print(query, name, out[name], flush=True)
    return out


class _Replay:
    """Отдаёт plan_query тот же ответ GigaChat, что получил старый план: сравнение без разброса между вызовами."""

    provider, model = "gigachat", "replay"

    def __init__(self, res):
        self.res = res

    async def complete(self, *a, **k):
        return self.res


async def _plan_prompt(query: str) -> str:
    """Промпт берём из самой plan_query, чтобы проверка не расходилась с продуктом."""
    from app.llm.providers import LLMResult

    captured = {}

    class Cap:
        provider, model = "capture", "capture"

        async def complete(self, system, user, temperature=0.2, max_tokens=1500):
            captured["p"] = user
            return LLMResult("", "capture", "capture", 0, ok=False)

    await tasks.plan_query(Cap(), query)
    return captured["p"]

async def main_async(queries: list[str]) -> None:
    llm = get_llm()
    report = [await one(llm, q) for q in queries]
    path = Path(get_settings().model_dir) / "ab_narrow_plan.json"
    path.write_text(json.dumps({"runs": report}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("Отчёт:", path)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queries", default="")
    args = ap.parse_args()
    qs = [q.strip() for q in args.queries.split(";") if q.strip()] or list(ANCHORS)
    asyncio.run(main_async(qs))


if __name__ == "__main__":
    main()
