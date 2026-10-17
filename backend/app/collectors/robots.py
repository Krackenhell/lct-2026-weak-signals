"""Проверка robots.txt перед обращением к сайтам изданий.

Научные API (arXiv, OpenAlex, Crossref) — это программные интерфейсы для таких запросов, а у новостных сайтов
правила задаёт robots.txt. Перед чтением ленты издания проверяем, разрешён ли адрес нашему агенту: например,
Finextra закрывает /rss/, TechCrunch — свой поиск (/?s=), Google News — RSS-поиск. Такие адреса не запрашиваем.

Стандартный urllib.robotparser не понимает шаблоны «*» и «$», поэтому правила разбираются здесь
(RFC 9309: побеждает самое длинное совпавшее правило, при равной длине — Allow).
"""
import re
from urllib.parse import urlparse

from app.collectors.http import USER_AGENT, HttpClient, NotFound, SourceError

AGENT = USER_AGENT.split("/")[0].lower()

Rules = list[tuple[bool, str]]  # (разрешено, шаблон пути)
_RULES: dict[str, Rules] = {}


def parse(text: str, agent: str = AGENT) -> Rules:
    """Правила для нашего агента: его собственная группа, а если её нет — группа «*»."""
    groups: list[tuple[list[str], Rules]] = []
    agents: list[str] = []
    rules: Rules = []
    after_agent = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, value = (p.strip() for p in line.split(":", 1))
        key = key.lower()
        if key == "user-agent":
            if not after_agent and (agents or rules):
                groups.append((agents, rules))
                agents, rules = [], []
            agents.append(value.lower())
            after_agent = True
            continue
        after_agent = False
        if key in ("allow", "disallow") and value:  # пустой Disallow — «разрешено всё»
            rules.append((key == "allow", value))
    groups.append((agents, rules))
    own = [r for a, rs in groups for r in rs if any(x != "*" and agent.startswith(x) for x in a)]
    if any(any(x != "*" and agent.startswith(x) for x in a) for a, _ in groups):
        return own
    return [r for a, rs in groups if "*" in a for r in rs]


def _match(pattern: str, path: str) -> bool:
    anchored = pattern.endswith("$")
    body = re.escape(pattern.rstrip("$")).replace(r"\*", ".*")
    return re.match(body + ("$" if anchored else ""), path) is not None


def is_allowed(rules: Rules, url: str) -> bool:
    u = urlparse(url)
    path = (u.path or "/") + (f"?{u.query}" if u.query else "")
    best: tuple[int, bool] | None = None
    for allow, pattern in rules:
        if _match(pattern, path):
            cand = (len(pattern), allow)
            if best is None or cand > best:  # длиннее — сильнее; при равной длине True > False, т.е. Allow
                best = cand
    return True if best is None else best[1]


async def allowed(http: HttpClient, url: str) -> bool:
    """Можно ли запрашивать адрес. Нет robots.txt (404) — можно; robots.txt недоступен — не рискуем."""
    host = urlparse(url).netloc
    if host not in _RULES:
        try:
            text = await http.get(f"https://{host}/robots.txt", as_json=False)
        except NotFound:
            text = ""
        except SourceError:
            return False  # не кэшируем: при следующем запуске проверим снова
        _RULES[host] = parse(text)
    return is_allowed(_RULES[host], url)
