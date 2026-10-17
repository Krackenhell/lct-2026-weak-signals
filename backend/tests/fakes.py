"""Записанные образцы ответов открытых источников и поддельная сеть для тестов без интернета.

Форматы повторяют реальные ответы API (Atom arXiv, JSON OpenAlex/GDELT/HN/GitHub/Википедии, RSS Хабра)
в сокращённом виде — ровно те поля, которые читают сборщики.
"""
import json
import re
import tempfile
import zlib
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from app.collectors.http import HttpClient


def arxiv_feed(entries: list[dict]) -> str:
    items = "".join(
        f"""<entry><id>http://arxiv.org/abs/{e['id']}</id><published>{e.get('date', '2026-09-01')}T10:00:00Z</published>
<title>{e['title']}</title><summary>{e.get('summary', '')}</summary>
<author><name>A. Researcher</name></author><author><name>B. Engineer</name></author></entry>"""
        for e in entries
    )
    return f'<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom"><title>arXiv</title>{items}</feed>'


def openalex_works(works: list[dict]) -> dict:
    def inv(text: str) -> dict:
        out: dict[str, list[int]] = {}
        for i, w in enumerate(text.split()):
            out.setdefault(w, []).append(i)
        return out

    return {
        "results": [
            {
                "id": f"https://openalex.org/W{i}", "doi": w.get("doi"), "title": w["title"], "publication_date": w.get("date", "2026-05-01"),
                "abstract_inverted_index": inv(w.get("abstract", "")), "type": w.get("type", "article"), "language": "en",
                "primary_location": {"source": {"display_name": w.get("journal", "Journal of Tests")}, "landing_page_url": w.get("url")},
            }
            for i, w in enumerate(works)
        ]
    }


def habr_rss(items: list[dict]) -> str:
    body = "".join(
        f"<item><title>{i['title']}</title><link>{i['link']}?utm_source=habr</link><description>{i.get('desc', '')}</description>"
        f"<pubDate>Mon, 01 Sep 2026 10:00:00 GMT</pubDate></item>"
        for i in items
    )
    return f'<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>Хабр</title>{body}</channel></rss>'


FEED_HOSTS = {"techcrunch.com", "www.theblock.co", "www.prnewswire.com", "vc.ru", "www.cnews.ru", "www.finextra.com"}
# Как у настоящих изданий: Finextra закрывает /rss/, TechCrunch — поиск.
ROBOTS = {"www.finextra.com": "User-agent: *\nCrawl-delay: 60\nDisallow: /rss/\n", "techcrunch.com": "User-agent: *\nDisallow: /?s=\nDisallow: /wp-json/\n"}


def _phrase(q: str) -> str:
    """Поисковая фраза из параметра запроса источника (all:"x y", "x y", title_and_abstract.search:"x")."""
    q = unquote(q or "")
    m = re.search(r'"([^"]+)"', q)
    if m:
        return m.group(1)
    return re.sub(r"^\w+(\.\w+)?:", "", q).split(",")[0].split(" sourcelang")[0].strip()


# Технологии, которые «встречаются» в разведочном корпусе. По умолчанию у каждой своя судьба:
# зрелая (много работ и популярная Википедия), без находок, с нерелевантными документами, нормальные ранние.
TERMS = ["Neuromorphic event cameras", "Analog compute arrays", "Federated analytics", "Spiking photonic processors", "Chiplet interconnect fabrics"]
MATURE = {"federated analytics"}
EMPTY = {"spiking photonic processors"}
VAGUE = {"analog compute arrays"}


def _crc(*parts) -> int:
    return zlib.crc32("|".join(map(str, parts)).encode())


class FakeWeb:
    """Маршрутизатор поддельной сети: отвечает правдоподобными данными, зависящими от поисковой фразы.

    known_mature — фразы «зрелых» технологий (много работ, популярная Википедия);
    empty — фразы, по которым источники ничего не находят;
    vague — фразы, по которым находятся только нерелевантные документы (decision-модель их не подтвердит);
    down — хосты, которые отвечают 503 (проверка отказоустойчивости).
    """

    def __init__(self, known_mature=MATURE, empty=EMPTY, vague=VAGUE, down=()):
        self.known_mature = {p.lower() for p in known_mature}
        self.empty = {p.lower() for p in empty}
        self.vague = {p.lower() for p in vague}
        self.down = set(down)
        self.calls: list[str] = []
        self.feed_paths: list[str] = []

    def _corpus_title(self, p: str, i: int) -> str:
        """Документ разведочного корпуса (поиск по подтеме): упоминает одну из технологий TERMS."""
        return f"{TERMS[_crc(p, i) % len(TERMS)]} {_crc(p, i) % 1000}"  # число — не токен, n-граммы только внутри названия

    def _is_term(self, p: str) -> bool:
        return any(t.lower() in p.lower() for t in TERMS)

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = urlparse(str(request.url))
        hit = lambda names, p: any(n in p.lower() for n in names)  # noqa: E731
        host, params = url.netloc, {k: v[0] for k, v in parse_qs(url.query).items()}
        self.calls.append(host)
        if host in self.down:
            return httpx.Response(503)
        if host == "export.arxiv.org":
            p = _phrase(params.get("search_query", ""))
            if hit(self.empty, p) or hit(self.vague, p):
                return httpx.Response(200, text=arxiv_feed([]))
            n = min(int(params.get("max_results", 5)), 4)
            if self._is_term(p):  # точный поиск по технологии (сбор доказательств)
                entries = [{"id": f"2609.{_crc(p, i) % 99999:05d}v1", "title": f"{p} prototype with independent labs {i}", "summary": f"We propose a {p} prototype and report a pilot."} for i in range(n)]
            else:  # поиск по подтеме (разведочный корпус)
                entries = [{"id": f"2608.{_crc(p, i) % 99999:05d}v1", "title": self._corpus_title(p, i), "summary": ""} for i in range(n)]
            return httpx.Response(200, text=arxiv_feed(entries))
        if host == "api.openalex.org":
            p = _phrase(params.get("filter", ""))
            if "group_by" in params:
                if hit(self.empty, p):
                    return httpx.Response(200, json={"group_by": []})
                years = {str(y): 900 for y in range(2000, 2027)} if hit(self.known_mature, p) else {"2024": 3, "2025": 12, "2026": 30}
                return httpx.Response(200, json={"group_by": [{"key": k, "count": v} for k, v in years.items()]})
            if hit(self.empty, p):
                return httpx.Response(200, json={"results": []})
            if hit(self.vague, p):
                works = [{"title": f"Weekly technology digest {i}", "abstract": "assorted industry news", "doi": f"https://doi.org/10.2000/{i}"} for i in range(3)]
            elif self._is_term(p):
                works = [{"title": f"{p} evaluated in a field pilot {i}", "abstract": f"{p} prototype evaluated in a pilot", "doi": f"https://doi.org/10.1000/{_crc(p, i) % 9999}",
                          "journal": ["IEEE Access", "Nature Electronics", "ACM Computing"][i % 3]} for i in range(3)]
            else:
                works = [{"title": self._corpus_title(p, 10 + i), "abstract": "", "doi": f"https://doi.org/10.3000/{_crc(p, i) % 9999}"} for i in range(3)]
            return httpx.Response(200, json=openalex_works(works))
        if host == "hn.algolia.com":
            p = _phrase(params.get("query", ""))
            if hit(self.empty, p):
                return httpx.Response(200, json={"hits": [], "nbHits": 0})
            if hit(self.vague, p):
                title = lambda i: f"Weekly tech roundup {i}"  # noqa: E731
            elif self._is_term(p):
                title = lambda i: f"{p} startup raises seed round"  # noqa: E731
            else:
                title = lambda i: self._corpus_title(p, 20 + i)  # noqa: E731
            hits = [{"objectID": str(_crc(p, i)), "title": title(i), "url": f"https://news{i}.example.com/{_crc(p, i)}", "created_at": "2026-08-01T00:00:00Z", "points": 10} for i in range(2)]
            return httpx.Response(200, json={"hits": hits, "nbHits": len(hits)})
        if host == "api.github.com":
            return httpx.Response(200, json={"total_count": 7, "items": [{"html_url": "https://github.com/x/y", "full_name": "x/y", "description": "demo", "created_at": "2026-01-01T00:00:00Z", "stargazers_count": 3}]})
        if host == "en.wikipedia.org":
            p = _phrase(params.get("srsearch", ""))
            if hit(self.known_mature, p):
                return httpx.Response(200, json={"query": {"search": [{"title": p.title()}]}})
            return httpx.Response(200, json={"query": {"search": []}})
        if host == "wikimedia.org":
            return httpx.Response(200, json={"items": [{"views": 60000}, {"views": 40000}]})
        if host == "api.gdeltproject.org":
            p = _phrase(params.get("query", ""))
            lang = "Russian" if "sourcelang:russian" in unquote(params.get("query", "")) else "English"
            if hit(self.empty, p) or lang == "Russian":  # в русскоязычных СМИ темы нет — «окно открыто»
                return httpx.Response(200, json={"articles": []})
            title = "Markets close higher" if hit(self.vague, p) else f"{p} news"
            return httpx.Response(200, json={"articles": [{"url": f"https://media.example.com/{_crc(p)}", "title": title, "seendate": "20260901T000000Z", "domain": "media.example.com", "language": lang}]})
        if host == "habr.com":
            return httpx.Response(200, text=habr_rss([]))
        if host == "api.crossref.org":
            p = _phrase(params.get("query.bibliographic", ""))
            if hit(self.empty, p) or hit(self.vague, p) or not self._is_term(p):
                return httpx.Response(200, json={"message": {"items": []}})
            items = [{"DOI": f"10.5555/{_crc(p, i) % 9999}", "title": [f"{p} in practice {i}"], "published": {"date-parts": [[2025, 6, 1]]},
                      "container-title": ["Applied Systems"], "type": "journal-article", "abstract": f"<jats:p>{p} pilot</jats:p>"} for i in range(2)]
            return httpx.Response(200, json={"message": {"items": items}})
        if url.path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS[host]) if host in ROBOTS else httpx.Response(404)
        if host in FEED_HOSTS:
            self.feed_paths.append(f"{host}{url.path}")
            if host in ("vc.ru", "www.cnews.ru"):  # в русскоязычных СМИ темы нет — «окно открыто»
                return httpx.Response(200, text=habr_rss([]))
            # Ленты не зависят от запроса: в них новости обо всех темах, кроме «пустых».
            live = [t for t in TERMS if t.lower() not in self.empty]
            return httpx.Response(200, text=habr_rss(
                [{"title": f"{t} startup raises $12M Series A", "link": f"https://{host}/2026/09/{_crc(host, t) % 999}/"} for t in live]
                + [{"title": "Quarterly results beat expectations", "link": f"https://{host}/2026/09/earnings/"}]
            ))
        if host == "yc-oss.github.io":
            live = [t for t in TERMS if t.lower() not in self.empty]
            return httpx.Response(200, json=[{"name": f"Startup{i}", "slug": f"s{i}", "one_liner": f"{t} for factories", "long_description": "",
                                              "tags": ["B2B"], "batch": "Summer 2025", "status": "Active", "url": f"https://www.ycombinator.com/companies/s{i}"}
                                             for i, t in enumerate(live)])
        if host == "huggingface.co":
            return httpx.Response(200, json=[])
        if host == "api2.openreview.net":
            return httpx.Response(200, json={"notes": [], "count": 0})
        if host == "api.reporter.nih.gov":
            return httpx.Response(200, json={"meta": {"total": 0}, "results": []})
        if host == "api.nsf.gov":
            return httpx.Response(200, json={"response": {"award": []}})
        if host == "gtr.ukri.org":
            return httpx.Response(200, json={"facetedSearchResultBean": {"results": []}})
        if host == "siliconangle.com":
            return httpx.Response(200, text=habr_rss([]))
        if host == "cyberleninka.ru":
            return httpx.Response(200, json={"found": 0, "articles": []})  # в русскоязычной науке тем нет — «окно открыто»
        if host == "www.ebi.ac.uk":
            return httpx.Response(200, json={"resultList": {"result": []}})
        return httpx.Response(404)

    def client(self, patient: bool = False) -> HttpClient:
        h = HttpClient(patient=patient)
        h._client = httpx.AsyncClient(transport=httpx.MockTransport(self.handler))
        h._interval = {}  # без пауз между запросами: сеть поддельная
        h._cache_dir = Path(tempfile.mkdtemp(prefix="cache-"))  # свой кэш: ответы одного теста не попадают в другой
        return h


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)
