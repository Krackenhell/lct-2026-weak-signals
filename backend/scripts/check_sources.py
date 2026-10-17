"""Живая проверка открытых источников: кто отвечает, сколько записей, за сколько секунд.

Запуск из папки backend:  python -m scripts.check_sources "federated learning" "федеративное обучение"
Результат печатается и пишется в data/model/sources_check.json (видно на вкладке «Методология»).
"""
import asyncio
import json
import sys
import time
from datetime import date, datetime, timedelta, timezone

from app.collectors import arxiv, crossref, cyberleninka, europepmc, gdelt, github, habr, hackernews, openalex, semanticscholar, wikipedia
from app.collectors.http import HttpClient
from app.config import get_settings


async def main(en: str, ru: str) -> list[dict]:
    http = HttpClient()
    since = (date.today() - timedelta(days=730)).isoformat()
    ts = int((datetime.now(timezone.utc) - timedelta(days=365)).timestamp())
    checks = {
        "arXiv": arxiv.search(http, en, 5),
        "OpenAlex": openalex.search(http, en, since, 5),
        "Crossref": crossref.search(http, en, since, 5),
        "Semantic Scholar (ключ)": semanticscholar.search(http, en, date.today().year - 2, 5),
        "Europe PMC": europepmc.search(http, en, since, 5),
        "КиберЛенинка (RU)": cyberleninka.search(http, ru, 5),
        "Хабр (RU)": habr.search(http, ru, 5),
        "GDELT (EN)": gdelt.search(http, en, "12m", 5),
        "GDELT (RU)": gdelt.search(http, ru, "12m", 5, lang="russian"),
        "GDELT (ZH)": gdelt.search(http, en, "12m", 5, lang="chinese"),
        "Hacker News": hackernews.search(http, en, ts, 5),
        "GitHub": github.top_repos(http, en, 3),
        "Википедия": wikipedia.lookup(http, en),
    }
    out = []
    for name, coro in checks.items():
        t = time.perf_counter()
        try:
            res = await coro
            n = len(res[0]) if isinstance(res, tuple) else (1 if isinstance(res, dict) and res.get("exists") else len(res) if isinstance(res, list) else 0)
            row = {"source": name, "ok": True, "records": n}
        except Exception as exc:  # отчёт должен показать сбой, а не упасть
            row = {"source": name, "ok": False, "error": str(exc)[:160]}
        row["seconds"] = round(time.perf_counter() - t, 1)
        out.append(row)
        print(f"{'OK ' if row['ok'] else 'ERR'} {name:26} {row.get('records', '-'):>3} записей  {row['seconds']:>5} с  {row.get('error', '')}", flush=True)
    await http.close()
    path = get_settings().model_dir / "sources_check.json"
    path.write_text(json.dumps({"date": date.today().isoformat(), "query_en": en, "query_ru": ru, "sources": out}, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "federated learning", sys.argv[2] if len(sys.argv) > 2 else "федеративное обучение"))
