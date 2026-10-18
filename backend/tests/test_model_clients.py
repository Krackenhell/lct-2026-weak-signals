"""Клиенты моделей на записанных форматах API: Jev/Kev (System One), GigaChat, YandexGPT, OpenAI-совместимый.

Проверяем протокол (что отправляем, как разбираем ответ), повторы при перегрузке и честный отказ —
без ключей и без сети."""
import asyncio
import json

import httpx
import pytest

from app.config import get_settings
from app.decision import get_decision_model
from app.decision.base import normalize_answer
from app.decision.heuristic import HeuristicDecision
from app.decision.systemone import SystemOneClient
from app.llm import providers
from app.llm.providers import GigaChat, NoLLM, OpenAICompatible, YandexGPT, get_llm


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    async def _s(_):
        return None

    monkeypatch.setattr(asyncio, "sleep", _s)


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------- System One (Jev / Kev)

def _jev(handler, **kw) -> SystemOneClient:
    c = SystemOneClient("jev", "https://api.typesafe.test/", "jev-latest", api_key="secret", **kw)
    c._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), headers=c._client.headers)
    return c


def test_systemone_request_and_answers():
    seen = {}

    def handler(r):
        seen["url"], seen["auth"], seen["body"] = str(r.url), r.headers["authorization"], json.loads(r.content)
        return httpx.Response(200, json={"model": "jev-1.13.0", "usage": {"input_tokens": 120}, "answers": {
            "novelty": {"type": "noul", "noul": 0.83},
            "maturity": {"type": "score", "score": 2, "probabilities": {"0": 0.1, "1": 0.2, "2": 0.4, "3": 0.2, "4": 0.05, "5": 0.05}, "confidence": 0.4},
        }})

    res = run(_jev(handler).ask("SUBJECT: x\nEVIDENCE:\n[1] t", {"novelty": {"type": "noul", "instructions": "?"}}))
    assert seen["url"] == "https://api.typesafe.test/v1/systemone" and seen["auth"] == "Bearer secret"
    assert seen["body"]["model"] == "jev-latest" and "novelty" in seen["body"]["questions"]
    assert res.ok and res.model == "jev-1.13.0" and res.usage == {"input_tokens": 120}
    assert res.answers["novelty"] == {"type": "noul", "value": 0.83}
    assert res.answers["maturity"]["value"] == pytest.approx(2 / 5) and res.answers["maturity"]["level"] == 2.0


def test_systemone_retries_on_overload_then_succeeds():
    calls = []

    def handler(r):
        calls.append(1)
        return httpx.Response(429) if len(calls) < 3 else httpx.Response(200, json={"answers": {"hype": {"type": "noul", "noul": 0.1}}})

    res = run(_jev(handler).ask("s", {}))
    assert res.ok and len(calls) == 3 and res.answers["hype"]["value"] == 0.1


def test_systemone_gives_up_honestly():
    res = run(_jev(lambda r: httpx.Response(503)).ask("s", {}))
    assert not res.ok and res.answers == {} and "503" in res.error


def test_systemone_timeout_has_readable_error():
    def handler(r):
        raise httpx.ReadTimeout("", request=r)

    res = run(_jev(handler).ask("s", {}))
    assert not res.ok and res.error.startswith("ReadTimeout")


@pytest.mark.parametrize("raw, expected", [
    ({"type": "noul", "noul": 0.25}, {"type": "noul", "value": 0.25}),
    ({"type": "noul"}, {"type": "noul", "value": 0.5}),
    ({"type": "weird"}, {"type": "weird", "value": 0.5}),
    ({}, {"type": "unknown", "value": 0.5}),
])
def test_normalize_answer(raw, expected):
    assert normalize_answer(raw) == expected


def test_normalize_choice():
    a = normalize_answer({"type": "choice", "choice": "pilot", "confidence": 0.7, "probabilities": {"pilot": 0.7}})
    assert a == {"type": "choice", "choice": "pilot", "confidence": 0.7, "probabilities": {"pilot": 0.7}}


def test_decision_routing(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "typesafe_api_key", "")
    assert isinstance(get_decision_model("jev"), HeuristicDecision)  # нет ключа — офлайн-правила, это видно в журнале
    monkeypatch.setattr(s, "typesafe_api_key", "k")
    m = get_decision_model("jev")
    assert isinstance(m, SystemOneClient) and m.provider == "jev" and m.model == s.jev_model
    kev = get_decision_model("kev")
    assert kev.provider == "kev" and kev._url.endswith("/v1/systemone")
    assert isinstance(get_decision_model("heuristic"), HeuristicDecision)


# ---------------------------------------------------------------- GigaChat

def _giga(handler) -> GigaChat:
    g = GigaChat()
    g._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return g


def test_gigachat_oauth_then_completion_and_token_reuse(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "gigachat_auth_key", "base64key")
    monkeypatch.setattr(s, "gigachat_model", "GigaChat-2-Max")
    log = []

    def handler(r):
        if "oauth" in str(r.url):
            log.append(("oauth", r.headers["authorization"], r.content.decode()))
            return httpx.Response(200, json={"access_token": "tok", "expires_at": 4102444800000})
        body = json.loads(r.content)
        log.append(("chat", r.headers["authorization"], body["model"], body["messages"][0]["role"]))
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"is_tech": true}'}}]})

    g = _giga(handler)
    r1 = run(g.complete("sys", "user"))
    r2 = run(g.complete("sys", "user2"))
    assert r1.ok and r1.text == '{"is_tech": true}' and r1.provider == "gigachat" and r1.model == "GigaChat-2-Max"
    assert r2.ok
    assert [e[0] for e in log] == ["oauth", "chat", "chat"]  # токен получен один раз и переиспользуется
    assert log[0][1] == "Basic base64key" and "scope=GIGACHAT_API_PERS" in log[0][2]
    assert log[1][1] == "Bearer tok" and log[1][2] == "GigaChat-2-Max" and log[1][3] == "system"


def test_gigachat_rate_limit_is_retried(monkeypatch):
    monkeypatch.setattr(get_settings(), "gigachat_auth_key", "k")
    n = {"chat": 0}

    def handler(r):
        if "oauth" in str(r.url):
            return httpx.Response(200, json={"access_token": "t", "expires_at": 4102444800000})
        n["chat"] += 1
        return httpx.Response(429) if n["chat"] == 1 else httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    assert run(_giga(handler).complete("s", "u")).text == "ok" and n["chat"] == 2


def test_gigachat_failure_is_reported_not_raised(monkeypatch):
    monkeypatch.setattr(get_settings(), "gigachat_auth_key", "k")
    res = run(_giga(lambda r: httpx.Response(401)).complete("s", "u"))
    assert not res.ok and res.text == "" and "401" in res.error


# ---------------------------------------------------------------- YandexGPT, OpenAI-совместимый, маршрутизация

def test_yandexgpt_protocol(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "yandex_api_key", "ya")
    monkeypatch.setattr(s, "yandex_folder_id", "b1g")
    seen = {}

    def handler(r):
        seen["auth"], seen["body"] = r.headers["authorization"], json.loads(r.content)
        return httpx.Response(200, json={"result": {"alternatives": [{"message": {"text": "привет"}}]}})

    y = YandexGPT()
    y._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), headers=y._client.headers)
    assert run(y.complete("s", "u", temperature=0.1, max_tokens=50)).text == "привет"
    assert seen["auth"] == "Api-Key ya" and seen["body"]["modelUri"] == f"gpt://b1g/{s.yandex_model}"
    assert seen["body"]["completionOptions"] == {"temperature": 0.1, "maxTokens": "50"}


def test_openai_compatible_protocol(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "openai_api_key", "sk")
    monkeypatch.setattr(s, "openai_base_url", "https://llm.example/v1/")

    def handler(r):
        assert str(r.url) == "https://llm.example/v1/chat/completions"
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    o = OpenAICompatible()
    o._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    assert run(o.complete("s", "u")).text == "ok"


def test_llm_routing(monkeypatch):
    s = get_settings()
    for k in ("gigachat_auth_key", "yandex_api_key", "openai_api_key"):
        monkeypatch.setattr(s, k, "")
    assert isinstance(get_llm("gigachat"), NoLLM)  # без ключа — шаблоны, а не падение
    monkeypatch.setattr(s, "gigachat_auth_key", "k")
    assert isinstance(get_llm("gigachat"), GigaChat)
    monkeypatch.setattr(s, "yandex_api_key", "k")
    assert isinstance(get_llm("yandexgpt"), YandexGPT)
    monkeypatch.setattr(s, "openai_api_key", "k")
    assert isinstance(get_llm("openai"), OpenAICompatible)
    res = run(get_llm("none").complete("s", "u"))
    assert not res.ok and res.provider == "none"


@pytest.mark.parametrize("text, expected", [
    ('{"a": [1, 2]}', {"a": [1, 2]}),
    ('Вот ответ: {"x": 1} — готово', {"x": 1}),
    ("```\n[1]\n```", [1]),
    ('{"a": 1', None),
    ("", None),
])
def test_parse_json_variants(text, expected):
    assert providers.parse_json(text) == expected
