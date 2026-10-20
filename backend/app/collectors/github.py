"""GitHub: активность разработчиков (новые репозитории) как ранний инженерный сигнал."""
from app.collectors.base import RawDoc, clean
from app.collectors.http import HttpClient
from app.config import get_settings

API = "https://api.github.com/search/repositories"


def _headers() -> dict:
    s = get_settings()
    h = {"Accept": "application/vnd.github+json"}
    if s.github_token:
        h["Authorization"] = f"Bearer {s.github_token}"
    return h


def _q(query: str) -> str:
    query = query.replace('"', "").strip()
    return f'"{query}"' if " " in query else query


async def count_created(http: HttpClient, query: str, date_from: str, date_to: str) -> int:
    data = await http.get(API, params={"q": f"{_q(query)} created:{date_from}..{date_to}", "per_page": 1}, headers=_headers())
    return int(data.get("total_count", 0))


async def created_with_top(http: HttpClient, query: str, date_from: str, date_to: str, n: int = 3) -> tuple[int, list[RawDoc]]:
    """Один запрос вместо двух: число репозиториев, созданных за период (признак модели — тот же, что у count_created),
    и самые заметные из них. GitHub разрешает с токеном 30 поисковых запросов в минуту — это узкое место скорости."""
    data = await http.get(API, params={"q": f"{_q(query)} created:{date_from}..{date_to}", "sort": "stars", "per_page": n}, headers=_headers())
    return int(data.get("total_count", 0)), _docs(data)


async def top_repos(http: HttpClient, query: str, n: int = 5) -> list[RawDoc]:
    data = await http.get(API, params={"q": _q(query), "sort": "stars", "per_page": n}, headers=_headers())
    return _docs(data)


def _docs(data: dict) -> list[RawDoc]:
    docs = []
    for r in data.get("items", []):
        docs.append(
            RawDoc(
                url=r.get("html_url", ""),
                title=r.get("full_name", ""),
                snippet=clean(r.get("description"), 400),
                published=(r.get("created_at") or "")[:10] or None,
                source_name="GitHub",
                source_type="repository",
                language="en",
                collector="github",
                extra={"stars": r.get("stargazers_count", 0)},
            )
        )
    return docs
