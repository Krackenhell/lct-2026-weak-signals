"""Оркестратор открытого запроса: план → корпус → кандидаты → доказательства → скоринг → исключения → досье.

Прогресс и все промежуточные результаты пишутся в БД, поэтому интерфейс показывает
ход обработки в реальном времени, а журнал вызовов моделей доступен для проверки.
"""
import asyncio
import logging
import re
import time
import traceback
import weakref
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from app.collectors.base import RawDoc
from app.collectors.http import HttpClient
from app.config import get_settings
from app.db import SessionLocal
from app.decision import get_decision_model
from app.decision.heuristic import HeuristicDecision
from app.llm.providers import for_task, get_llm
from app.collectors import cyberleninka, gdelt, habr, news_search, openalex
from app.llm.tasks import check_query, plan_query, summarize_sources, write_dossier
from app.llm.terms import check_name_ru
from app.ml.model import SignalModel
from app.models import Candidate, Document, ModelCall, Run
from app.pipeline import cost as cost_mod
from app.pipeline import discovery, evidence as evidence_mod
from app.pipeline import links as links_mod
from app.pipeline import passport as pp_mod
from app.pipeline import routing, subtopics
from app.pipeline.decide import decide, query_anchors, template_dossier, wiki_fact
from app.pipeline.features import answer_features, numeric_features
from app.pipeline.questions import (
    EVENT, EVIDENCE_MATCH, IS_TECHNOLOGY, PRODUCT_NAME, QUESTIONS, build_state, claim_questions, count_items,
    doc_questions, query_relevance_question, relevance_question,
)
from app.pipeline.trust import classify

log = logging.getLogger(__name__)

# Версия конвейера: увеличивается вручную при любом изменении, влияющем на выдачу. Готовые результаты другой версии
# повторно не отдаются (см. api/routes.reuse_blockers) — эксперт не увидит выдачу старого кода.
PIPELINE_VERSION = "2026-10-19.2"


def training_phrases() -> set[str]:
    """Фразы обучающей выборки классификатора (сигналы организатора): оценка таких кандидатов не независима."""
    import json
    from pathlib import Path

    try:
        terms = json.loads((Path(get_settings().seed_dir) / "positive_terms.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    return {re.sub(r"\s+", " ", p.lower()).strip() for k, v in terms.items() if not k.startswith("_") and isinstance(v, list) for p in v}


# Клиенты моделей и ограничитель параллельных запусков — общие на процесс (точнее, на цикл событий).
# Раньше каждый запуск создавал свои HTTP-клиенты GigaChat и Jev и не закрывал их, а лимит «1 поток GigaChat»
# действовал внутри запуска: три одновременных запроса жюри давали три потока и ошибки 429 на бесплатном тарифе.
_SHARED: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict]" = weakref.WeakKeyDictionary()


def _shared(key, factory):
    per_loop = _SHARED.setdefault(asyncio.get_running_loop(), {})
    if key not in per_loop:
        per_loop[key] = factory()
    return per_loop[key]


class RunContext:
    def __init__(self, run_id: int):
        self.run_id = run_id
        self.session: Session = SessionLocal()
        self.run: Run = self.session.get(Run, run_id)
        self.timing: dict[str, float] = {}
        self._t = time.perf_counter()
        self._phase = "старт"
        self.usage: dict[str, dict] = {}  # провайдер модели -> вызовы и токены (для стоимости запроса)

    def stage(self, text: str, progress: int) -> None:
        self.run.stage = text
        self.run.progress = progress
        # Время по этапам: что именно занимает минуты запроса (видно в статистике прогона).
        phase = re.sub(r"[:—(].*$|\d+/\d+.*$", "", text).strip() or text
        if phase != self._phase:
            now = time.perf_counter()
            self.timing[self._phase] = round(self.timing.get(self._phase, 0) + now - self._t, 1)
            self._t, self._phase = now, phase
        self.session.commit()

    def finish_timing(self) -> dict:
        self.timing[self._phase] = round(self.timing.get(self._phase, 0) + time.perf_counter() - self._t, 1)
        return self.timing

    def log_call(self, provider: str, model: str, purpose: str, subject: str, request: dict, response: dict, latency_ms: int, ok: bool = True,
                 usage: dict | None = None) -> None:
        if usage:
            response = {**response, "usage": usage}
        if provider not in ("none", "heuristic"):  # шаблоны и офлайн-правила бесплатны и в расчёт стоимости не входят
            # Ключ — провайдер и модель: план на GigaChat-2-Max и остальное на GigaChat-2 считаются по своим тарифам.
            key = provider if provider in ("jev", "kev") else f"{provider}:{model}"
            u = self.usage.setdefault(key, {"provider": provider, "model": model, "calls": 0, "tokens": 0})
            u["calls"] += 1
            u["tokens"] += int((usage or {}).get("total") or (usage or {}).get("total_tokens") or 0)
        self.session.add(
            ModelCall(run_id=self.run_id, provider=provider, model=model, purpose=purpose, subject=subject[:300], request=request, response=response, latency_ms=latency_ms, ok=ok)
        )


def _doc_row(run_id: int, d: RawDoc) -> Document:
    stype, trust, reason = classify(d)
    return Document(
        run_id=run_id, url=d.url[:1000], title=d.title[:2000], snippet=d.snippet, published=d.published, source_name=d.source_name[:200],
        source_type=stype, language=d.language or "en", trust_level=trust, trust_reason=reason, collector=d.collector,
    )


def _changes(session: Session, run: Run, names: list[str]) -> dict | None:
    """Мониторинг темы: что появилось и что выпало по сравнению с прошлым прогоном того же запроса."""
    prev = (
        session.query(Run)
        .filter(Run.id < run.id, Run.status == "done")
        .order_by(Run.id.desc())
        .all()
    )
    prev = next((r for r in prev if r.query.strip().lower() == run.query.strip().lower()), None)
    if not prev:
        return None
    old = {c.name for c in session.query(Candidate).filter_by(run_id=prev.id, status="signal")}
    new = set(names)
    return {
        "prev_run_id": prev.id,
        "prev_date": prev.created_at.isoformat() if prev.created_at else None,
        "new": sorted(new - old),
        "dropped": sorted(old - new),
        "kept": len(new & old),
    }


async def execute(run_id: int) -> None:
    ctx = RunContext(run_id)
    s = get_settings()
    try:
        # Подключения к источникам и моделям — внутри обработки ошибок: сбой здесь не должен оставлять запуск
        # «в очереди» навсегда (найдено стресс-тестом).
        # Очередь: одновременно обрабатываются не больше MAX_PARALLEL_RUNS запросов, остальные ждут
        # со статусом «в очереди» — лимиты источников и моделей общие, а сервер не должен падать от наплыва.
        ctx.stage("В очереди: ждёт завершения других запросов", 0)
        gate = _shared(("runs", s.max_parallel_runs), lambda: asyncio.Semaphore(max(1, s.max_parallel_runs)))
        async with gate:
            await _execute(ctx, s)
    except Exception as exc:  # запуск не должен «зависнуть»: фиксируем ошибку в БД
        log.exception("run %s failed", run_id)
        ctx.session.rollback()
        ctx.run.status = "failed"
        ctx.run.error = f"{exc}\n{traceback.format_exc()[-2000:]}"
        ctx.session.commit()
    finally:
        ctx.run.finished_at = datetime.now(timezone.utc)
        ctx.session.commit()
        ctx.session.close()


async def _execute(ctx: RunContext, s) -> None:
    run_id = ctx.run_id
    http = None
    try:
        http = HttpClient()
        llm = _shared(("llm", get_llm), get_llm)
        dm = _shared(("dm", get_decision_model), get_decision_model)
        model = SignalModel.load()
        # Режим без Jev (офлайн-правила вместо ответов decision-модели): прежняя модель с признаками GitHub и HN.
        # Основная модель (П9, без GitHub и признаков с перевёрнутым знаком) обучена на ответах Jev; на правилах она
        # отсекала почти всё (прогоны 17.10 на правилах: 12 → 1 кандидат выше 0,5).
        rules_model = SignalModel.load(s.model_dir / "signal_model_rules.json") or model
        if dm.provider == "heuristic":
            model = rules_model
        query = ctx.run.query
        ctx.run.status = "running"
        ctx.run.providers = {
            "decision_model": f"{dm.provider}:{dm.model}",
            # Та же подпись, что у llm_label() (по ней проверяется повторное использование результата).
            "llm": f"{llm.provider}:{llm.model}" + (f" (план поиска: {pm.model})" if (pm := for_task(llm, "plan")) is not llm else ""),
            "pipeline": PIPELINE_VERSION,
            "classifier": "logistic-regression" + (f" (обучена на {model.meta.get('trained_on')} примерах)" if model else " (не обучена)"),
        }
        ctx.session.commit()
        # 0. Это вообще технологическое направление? На «Привет» честно отказываем, а не выдаём 15 «сигналов».
        ctx.stage("Проверка запроса", 1)
        verdict, res = await check_query(llm, query)
        if res:
            ctx.log_call(res.provider, res.model, "проверка запроса", query, {"query": query}, {"text": res.text[:1000], "verdict": verdict}, res.latency_ms, res.ok, usage=res.usage)
        ctx.run.stats = {**(ctx.run.stats or {}), "query_check": verdict}
        if not verdict["ok"]:
            ctx.run.status = "rejected"
            ctx.run.error = verdict["reason"]
            ctx.stage("Запрос отклонён: не технологическое направление", 100)
            return

        # 1. План поиска
        ctx.stage("Расширение запроса: подтемы и поисковые фразы", 3)
        # П12: план той же темы берётся из кэша (14 дней) — повторные прогоны сравнимы; опция replan строит план заново.
        plan, res = await plan_query(for_task(llm, "plan"), query, cache_dir=s.cache_dir.parent / "plan_cache",
                                     refresh=bool((ctx.run.options or {}).get("replan")))
        if res:
            ctx.log_call(res.provider, res.model, "расширение запроса", query, {"query": query}, {"text": res.text[:3000]}, res.latency_ms, res.ok, usage=res.usage)
        plan = {**plan, "query": query}  # исходная формулировка нужна сбору корпуса (выбор тематических баз)

        # 1б. Растущие поднаправления по литературе (собственное решение, без LLM): ключевой термин темы и ключевые
        # слова OpenAlex, доля которых в работах по теме быстро растёт. На узких запросах («многослойный графен»,
        # «газлифт») именно они — ранние сигналы, а подтемы LLM бывают общими или испорченными.
        ctx.stage("Поиск растущих поднаправлений в научной литературе", 4)
        try:
            core = await asyncio.wait_for(subtopics.resolve_core(http, plan.get("topic_en", ""), query), 45)
            found = await asyncio.wait_for(subtopics.emerging(http, core), 60) if core else []
        except Exception as exc:  # без этого шага запрос всё равно выполняется по плану LLM
            log.info("run %s: emerging subtopics failed: %s", run_id, exc)
            core, found = "", []
        if core and re.search(r"[a-z]", core, re.I):
            kws = [e["keyword"] for e in found]
            # Запасные подтемы словаря (узкий запрос без перевода) больше не нужны: термин найден в литературе.
            subs0 = [] if plan.get("backup") else plan.get("subqueries", [])
            # Подтемы, которые после снятия общих слов совпадают с самим термином («novel multilayer graphene applications»,
            # «multilayer graphene technology»), ничего не добавляют к корпусу — их место отдаём другим.
            llm_subs = [x for x in subtopics.drop_buzz(subs0, query)
                        if x.lower() not in kws and subtopics.core_term(x).lower() != core.lower()]
            plan["subqueries"] = (kws + [core] + llm_subs)[:12]
            if not re.search(r"[a-z]", plan.get("topic_en", ""), re.I):
                plan["topic_en"] = core  # без LLM русская фраза не находит ничего в англоязычных базах
        plan = {**plan, "core_term": core, "emerging": found}
        # Маршрут источников по профилю запроса (науки о жизни, материалы, энергетика, ИТ) — виден в «Как искали».
        route = routing.route(query, plan)
        plan["route"] = route
        # П11: как система поняла запрос (без LLM): тема и первые подтемы — видно в «Как искали» и уточняет вопрос о релевантности.
        plan["scope_en"] = f"{plan.get('topic_en') or query}: " + "; ".join((plan.get("subqueries") or [])[:5])
        ctx.run.plan = plan
        ctx.session.commit()

        # 2. Разведочный корпус
        async def corpus_progress(done, total):
            ctx.stage(f"Сбор документов по подтемам: {done}/{total} запросов", 5 + int(20 * done / max(total, 1)))

        corpus = await discovery.build_corpus(http, plan, corpus_progress)
        ctx.stage(f"Извлечение технологий из {len(corpus)} документов", 27)

        # 3. Кандидаты
        mined = discovery.mine_phrases(corpus)
        extracted, llm_res = await discovery.llm_candidates(llm, plan.get("topic_en", query), corpus)
        for r in llm_res:
            ctx.log_call(r.provider, r.model, "извлечение технологий из документов", query, {"docs": "пачка документов корпуса"}, {"text": r.text[:3000]}, r.latency_ms, r.ok, usage=r.usage)
        watch = discovery.watchlist(query, plan, (ctx.run.options or {}).get("use_watchlist"))
        lit = subtopics.literature_candidates(plan.get("emerging", []), corpus)
        pool = discovery.merge(extracted + lit + mined + watch)
        # Предварительный отбор: сначала подтверждённые несколькими документами/методами.
        # Сигналы из базы отслеживания получают зарезервированные места (до 20), остальное — новые кандидаты.
        watched = [c for c in pool if "watchlist" in c["methods"]][:20]
        # Кандидаты, извлечённые LLM из текстов, приоритетнее статистических фраз.
        fresh = sorted(
            (c for c in pool if "watchlist" not in c["methods"]),
            key=lambda c: (-("llm-extraction" in c["methods"]), -(len(c["doc_idx"]) + 2 * c["support"])),
        )
        # Отраслевым событиям (раунд, запуск) — до 8 мест: у них мало документов, и по числу ссылок
        # они проигрывают научным темам, хотя именно такие события лежат в основе большинства сигналов датасета.
        slots = max(s.max_candidates - len(watched), 0)
        # Растущим поднаправлениям из литературы — до 6 мест: их рост уже измерен, а документов в корпусе может быть мало.
        growing = [c for c in fresh if "literature-growth" in c["methods"]][: min(6, slots)]
        taken = {id(c) for c in growing}
        # П11: места под события — только новостям о раундах и запусках (ленты изданий, HN); записи каталога YC и гранты
        # места не занимают (раньше они вытесняли кандидатов, подтверждённых наукой). Мест 5 вместо 8.
        def news_event(i: int) -> bool:
            d = corpus[i]
            return d.extra.get("event") in ("funding", "launch") and d.collector not in ("yc", "nih", "nsf", "ukri")

        events = [c for c in fresh if id(c) not in taken and any(news_event(i) for i in c["doc_idx"] if i < len(corpus))]
        events = events[: min(5, slots - len(growing))]
        taken |= {id(c) for c in events}
        pool = watched + growing + events + [c for c in fresh if id(c) not in taken][: slots - len(growing) - len(events)]
        ctx.run.stats = {**ctx.run.stats, "corpus_docs": len(corpus), "raw_candidates": len(extracted) + len(mined) + len(watch),
                         # П11, T0: пул целиком — для воронки (где теряются эталонные технологии: в поиске или при отборе).
                         "pool": [{"name": c["name_en"], "methods": c["methods"], "docs": len(c["doc_idx"])} for c in pool],
                         "pool_raw": len(discovery.merge(extracted + lit + mined + watch))}
        ctx.stage(f"Проверка {len(pool)} кандидатов по открытым источникам", 32)

        # 4. Доказательства, decision-модель, скоринг
        topic = plan.get("topic_en") or query
        questions = {
            **QUESTIONS,
            "relevance": relevance_question(topic, plan.get("scope_en", "")),
            "relevance_query": query_relevance_question(query, topic),
            "evidence_match": EVIDENCE_MATCH, "product_name": PRODUCT_NAME, "is_technology": IS_TECHNOLOGY,
            "event": EVENT,
        }
        done = 0

        # Скорость. Источники требуют пауз между запросами (GitHub без токена — 6,5 с, GDELT — 5,5 с, arXiv — 3,1 с),
        # поэтому по 40 кандидатам эти пары источников занимали минуты. Без токена GitHub счётчик репозиториев
        # заменяется нейтральным значением (как при сбое источника); новости GDELT берутся в корпусе и для окна
        # для России, а не по каждому кандидату.
        with_gh = bool(s.github_token)
        # Счётчик новых репозиториев нужен, только если он есть в признаках модели (после П9 — нет): минус вызов GitHub на кандидата.
        gh_count = with_gh and bool(model) and "log_gh_repos_12m" in model.features

        async def assess(c: dict) -> dict:
            nonlocal done
            # География — после решения и только для сигналов (экономия 20–30 запросов OpenAlex); Europe PMC и ML-источники — по маршруту.
            opts = {"with_news": s.news_per_candidate, "with_repos": with_gh, "with_gh_count": gh_count, "with_countries": False,
                    "with_europepmc": route["europepmc_evidence"], "with_ml": route["ml_evidence"]}
            ev = await evidence_mod.gather(http, c["name_en"], date.today(), **opts)
            for alt in c.get("alt_terms", [])[:1]:
                if len(ev.docs) >= 5:
                    break
                alt_ev = await evidence_mod.gather(http, alt, date.today(), **opts)
                if len(alt_ev.docs) > len(ev.docs):
                    ev = alt_ev
            numeric = numeric_features(ev)  # до добавления документов корпуса — как при обучении
            missing = []
            # Счётчик репозиториев не собирался (нет токена или он не нужен основной модели): для модели, где он есть
            # (режим без Jev), — нейтральное среднее, а не ноль, который давал бы бонус «нет GitHub = сигнал».
            gm = next((m for m in (model, rules_model) if m and "log_gh_repos_12m" in m.features), None)
            if not gh_count and gm:
                numeric["log_gh_repos_12m"] = gm.mean[gm.features.index("log_gh_repos_12m")]
                missing.append("github")
            if "openalex" in ev.failed and model:
                # Нет данных о публикациях: нейтральные значения (средние обучающей выборки) вместо нулей,
                # иначе зрелая технология выглядела бы «молодой».
                for k in ("log_total_works", "recent_share", "growth", "age_years"):
                    numeric[k] = model.mean[model.features.index(k)]
                missing.append("openalex")
            if "wikipedia" in ev.failed and model:
                # То же для Википедии: ноль означал бы «статьи нет» и сдвигал бы кандидата к сигналу.
                for k in ("wiki_exists", "log_wiki_views"):
                    numeric[k] = model.mean[model.features.index(k)]
                missing.append("wikipedia")
            corpus_docs = [corpus[i] for i in c["doc_idx"][:6]]
            dataset_docs = [
                RawDoc(url=w["url"], title=w["title"], source_name="Датасет организатора: ссылка на первоисточник", source_type="dataset", collector="dataset")
                for w in c.get("watch_sources", [])
            ]
            ev.docs = evidence_mod._dedupe(corpus_docs + ev.docs + dataset_docs)
            items = evidence_mod.evidence_items(ev)
            state = build_state(c["name_en"], topic, items)
            # Паспорт доказательств: в том же вызове decision-модель проверяет каждый документ отдельно.
            n_asked = count_items(state)
            q_c = {**questions, **doc_questions(n_asked)}
            res = await dm.ask(state, q_c)
            feats = {**numeric, **answer_features(res.answers)}
            prob = model.predict(feats) if model else None
            done += 1
            ctx.stage(f"Проверка кандидатов: {done}/{len(pool)} — «{c['name_en']}»", 32 + int(48 * done / len(pool)))
            return {
                "c": c, "ev": ev, "items": items, "state": state, "questions": q_c, "n_asked": n_asked, "res": res, "features": feats,
                "prob": prob, "missing": missing, "passport": pp_mod.passport(items, res.answers, n_asked, s.min_confirmed_docs),
            }

        # Скорость: время этапа — это очереди к источникам с обязательными паузами (arXiv 3 с, GitHub 2 с), а не модели
        # (Jev отвечает за 0,5 с). 12 кандидатов одновременно держат все очереди занятыми параллельно, а не по очереди.
        sem = asyncio.Semaphore(12)

        async def guarded(c):
            async with sem:
                try:
                    return await assess(c)
                except Exception:  # сбой на одном кандидате (неожиданный ответ источника) не роняет весь запрос
                    log.exception("run %s: candidate %r failed", run_id, c.get("name_en"))
                    return None

        # П15: бюджет времени на проверку кандидатов. Зависшие источники не держат запрос дольше RUN_BUDGET_SECONDS:
        # непроверенные кандидаты отбрасываются, а на странице прогона видно «проверено N из M — лимит времени».
        tasks_c = [asyncio.ensure_future(guarded(c)) for c in pool]
        budget = s.run_budget_seconds or None
        done_set, pending = await asyncio.wait(tasks_c, timeout=budget) if tasks_c else (set(), set())
        for t_ in pending:
            t_.cancel()
        if pending:
            ctx.run.stats = {**ctx.run.stats, "budget": {"checked": len(done_set), "total": len(pool), "seconds": budget}}
        assessed = [a for a in (t_.result() for t_ in tasks_c if t_ in done_set) if a is not None]
        if len(assessed) < len(done_set):
            ctx.run.stats = {**ctx.run.stats, "candidate_errors": len(done_set) - len(assessed)}

        # Повторный опрос тех, по кому decision-модель не ответила (обычно таймаут под нагрузкой).
        async def reask(a: dict) -> None:
            a["res"] = await dm.ask(a["state"], a["questions"])
            a["features"] = {**a["features"], **answer_features(a["res"].answers)}
            a["prob"] = model.predict(a["features"]) if model else None
            a["passport"] = pp_mod.passport(a["items"], a["res"].answers, a["n_asked"], s.min_confirmed_docs)

        await asyncio.gather(*(reask(a) for a in assessed if not a["res"].ok))

        # Если decision-модель так и не ответила (сеть, лимит), признаки по этим кандидатам считают офлайн-правила:
        # выдача не должна стать пустой из-за сбоя одного сервиса. Это видно в журнале и в паспорте кандидата.
        failed_dm = [a for a in assessed if not a["res"].ok]
        if failed_dm and dm.provider != "heuristic":
            rules = HeuristicDecision()
            for a in failed_dm:
                err = a["res"].error
                a["res"] = await rules.ask(a["state"], a["questions"])
                a["res"].provider, a["res"].error = "heuristic", f"запасной режим: {dm.provider} не ответила ({err})"
                a["features"] = {**a["features"], **answer_features(a["res"].answers)}
                a["prob"] = rules_model.predict(a["features"]) if rules_model else None  # ответы правил — модель режима без Jev
                a["passport"] = {**pp_mod.passport(a["items"], a["res"].answers, a["n_asked"], s.min_confirmed_docs), "fallback": True}
            ctx.run.stats = {**ctx.run.stats, "decision_fallback": len(failed_dm)}

        for a in assessed:
            r = a["res"]
            ctx.log_call(r.provider, r.model, "ответы на вопросы-признаки и проверка документов", a["c"]["name_en"], {"state": a["state"][:4000], "questions": list(a["questions"])}, {"answers": r.answers, "error": r.error, "passport": a["passport"]}, r.latency_ms, r.ok, usage=r.usage)
        ctx.session.commit()

        # 5. Решение: сигнал / исключение
        ctx.stage("Ранжирование: исключение зрелых технологий, стандартов и тем без технического подтверждения", 82)
        # Слова самого запроса не считаются «темой» в правиле разнообразия; без надёжных слов запроса (словарный план без
        # термина из литературы) правило «не больше 3 на тему» отключается — лучше не резать, чем резать по случайным словам.
        anchors = query_anchors(plan, query)
        crowding = not (plan.get("generated_by") == "lexicon" and not plan.get("core_term"))
        decisions = decide(assessed, model, s.top_k, topic_terms=[t for t in (plan.get("core_term"), plan.get("topic_en"), *plan.get("query_en", [])) if t],
                           anchors=anchors, crowding=crowding)

        # Честный режим при сбое OpenAlex: доля кандидатов, у которых статистика публикаций заменена средними. Такой прогон
        # помечается (баннер в интерфейсе) и не отдаётся повторно; подставленные значения не показываются как факты.
        n_imputed = sum(1 for a in assessed if "openalex" in a.get("missing", []))
        imputed_share = round(n_imputed / max(len(assessed), 1), 3)
        oa = (http.stats or {}).get("api.openalex.org", {})
        ctx.run.stats = {**ctx.run.stats, "openalex": {**oa, "imputed": n_imputed, "imputed_share": imputed_share},
                         "degraded": imputed_share > 0.2}

        # География работ — только для сигналов, после решения (раньше — для каждого из 30 кандидатов).
        async def countries(a):
            if "openalex" in a["ev"].failed or not s.extra_sources:
                return
            a["ev"].countries = await evidence_mod._safe("openalex_countries", openalex.country_counts(http, a["ev"].phrase, date.today().year - 2), {}, a["ev"].failed)

        await asyncio.gather(*(countries(a) for a, d in zip(assessed, decisions, strict=False) if d["status"] == "signal"))

        # 6. Сохранение документов и кандидатов
        doc_ids_by_url: dict[str, int] = {}
        total_docs = 0
        trained = training_phrases()
        for a, dcs in zip(assessed, decisions, strict=False):
            # Русское название: названия организатора (база отслеживания) не трогаем; остальные — через валидатор
            # (глоссарий, кальки, утечка запроса, длина). Не прошло — показывается английский термин, причина пишется в карточку.
            name_check = None
            if "watchlist" not in a["c"]["methods"]:
                ru, name_check = check_name_ru(a["c"]["name_en"], a["c"].get("name_ru"), query)
                a["c"]["name_ru"] = ru if ru and ru != a["c"]["name_en"] else ""
            ids = []
            for d in a["ev"].docs[:20]:
                if d.url not in doc_ids_by_url:
                    row = _doc_row(run_id, d)
                    ctx.session.add(row)
                    ctx.session.flush()
                    doc_ids_by_url[d.url] = row.id
                    total_docs += 1
                ids.append(doc_ids_by_url[d.url])
            extra = {"passport": a["passport"], "dynamics": pp_mod.dynamics(a["ev"].yearly, date.today().year) if "openalex" not in a["ev"].failed else None,
                     "missing": a.get("missing", []), "startups_by_year": a["ev"].yc_yearly or None,
                     "geography": pp_mod.geography(a["ev"].countries), "patents": a["ev"].patents, "score": dcs.get("score"),
                     "name_check": name_check,
                     # Совпадает с примером обучающей выборки: высокая оценка ожидаема и не является независимой проверкой.
                     "in_training": re.sub(r"\s+", " ", a["c"]["name_en"].lower()).strip() in trained or bool(a["c"].get("watch_id"))}
            if dcs["status"] == "signal":
                # Вклады уже поделены на температуру калибровки — свободный член делим так же.
                extra["robustness"] = pp_mod.robustness(a["prob"], dcs["contributions"], model.intercept / model.temperature if model else None)
            cand = Candidate(
                run_id=run_id, name=a["c"]["name_en"], name_ru=a["c"].get("name_ru") or None,
                origin="watchlist" if "watchlist" in a["c"]["methods"] and not (set(a["c"]["methods"]) - {"watchlist"}) else "discovered",
                status=dcs["status"], rank=dcs.get("rank"), probability=a["prob"], relevance=dcs["relevance"],
                exclusion_code=dcs.get("code"), exclusion_reason=dcs.get("reason"), features=a["features"],
                contributions={"items": dcs["contributions"], "methods": a["c"]["methods"], **extra}, answers=a["res"].answers,
                dossier=template_dossier(a, dcs), document_ids=ids,
            )
            ctx.session.add(cand)
        ctx.session.commit()

        signals = ctx.session.query(Candidate).filter_by(run_id=run_id, status="signal").order_by(Candidate.rank).all()
        by_name = {a["c"]["name_en"]: a for a in assessed}

        # 6–7. Для топа одновременно: окно для России, живая проверка ссылок, досье с перекрёстной проверкой.
        # Раньше эти шаги шли по очереди; это разные источники и модели, ждать друг друга им незачем.
        ctx.stage(f"Окно для России, проверка ссылок и досье по {len(signals)} сигналам", 85)
        year = date.today().year

        async def window(cand: Candidate):
            a = by_name[cand.name]
            # Русское название передаём в поиск, только если оно прошло проверку (кальку искать бессмысленно).
            name_ru = cand.name_ru if cand.name_ru and not (cand.contributions or {}).get("name_check") else ""
            terms = [evidence_mod.search_phrase(cand.name), name_ru]
            failed: list[str] = []
            ru_query = name_ru or evidence_mod.search_phrase(cand.name)
            hb = await evidence_mod._safe("habr", habr.search(http, ru_query, 15), [], failed)
            gd = await evidence_mod._safe("gdelt", gdelt.search(http, evidence_mod.search_phrase(cand.name), "24m", 20, lang="russian"), [], failed)
            sources = 2
            cl, gn = [], []
            if s.extra_sources:  # русскоязычная наука: упоминания в статьях КиберЛенинки за 3 года
                sources += 1
                cl = await evidence_mod._safe("cyberleninka", cyberleninka.search(http, ru_query, 15, min_year=year - 3), [], failed)
            if s.news_sources:  # русскоязычные СМИ: ленты vc.ru и CNews (GDELT часто ограничивает запросы)
                sources += 1
                gn = await evidence_mod._safe("rss", news_search.matching(http, [t for t in terms if t], "ru", 20), [], failed)
            ru = None if len(failed) == sources else sum(pp_mod.mentions(x, terms) for x in (hb, gd, cl, gn))
            world = None if "openalex" in a["ev"].failed else pp_mod.world_recent_works(a["ev"].yearly, year)
            w = pp_mod.russia_window(world, ru)
            w["failed"] = failed
            w["terms"] = [t for t in terms if t]  # по каким словам искали — видно в карточке
            return cand, w

        sem_w = asyncio.Semaphore(4)

        async def guarded_window(cand):
            async with sem_w:
                try:
                    return await window(cand)
                except Exception:
                    log.exception("run %s: russia window for %r failed", run_id, cand.name)
                    return cand, {"status": "unknown", "label": "Нет данных", "text": "Не удалось проверить русскоязычные источники.", "world": None, "ru": None, "failed": ["error"]}

        async def windows_phase():
            if not (s.russia_window and signals):
                return []
            return await asyncio.gather(*(guarded_window(c) for c in signals))

        async def links_phase() -> dict[str, str]:
            if not (s.check_links and signals):
                return {}
            ids = sorted({i for c in signals for i in (c.document_ids or [])[:12]})
            urls = [d.url for d in (ctx.session.get(Document, i) for i in ids) if d]
            return await links_mod.check_all(urls)

        async def dossier(cand: Candidate):
            a = by_name[cand.name]
            f = cand.features
            total = round(2.718281828 ** f.get("log_total_works", 0) - 1)
            # При сбое OpenAlex признаки публикаций — средние обучающей выборки: в досье их как факты не передаём.
            pubs = ["Статистика публикаций недоступна (OpenAlex не ответил) — признаки заменены средними, чисел о публикациях не приводи."] \
                if "openalex" in a.get("missing", []) else [
                f"Научных работ с этим термином за всё время: {total}; из них за последние 3 года: {f.get('recent_share', 0):.0%}.",
                f"Тема заметна в литературе около {f.get('age_years', 0):.0f} лет." if f.get("age_years") else "Устойчивой истории публикаций нет — тема новая.",
            ]
            facts = [
                *pubs,
                wiki_fact(f, a.get("missing", [])) + ".",
                f"Оценка классификатора {pp_mod.prob_text(cand.probability)} ({'высокая' if (cand.probability or 0) >= 0.75 else 'средняя'}): "
                "это сходство с размеченными слабыми сигналами, а не вероятность того, что технология станет трендом.",
                f"Паспорт доказательств: decision-модель подтвердила {a['passport']['confirmed']} документов из {a['passport']['domains']} разных источников; самое твёрдое событие — {a['passport']['event']}.",
                *([f"Новостей о раундах или сделках среди подтверждений: {a['passport']['funding_news']}."] if a["passport"].get("funding_news") else []),
                *([f"Госгрантов среди подтверждений: {a['passport']['grants']}."] if a["passport"].get("grants") else []),
                *([f"География работ за 2 года (OpenAlex): лидер — {g['leader']}; доля Китая {g['china']:.0%}, США {g['usa']:.0%}, России {g['russia']:.1%}."]
                  if (g := pp_mod.geography(a["ev"].countries)) else []),
                *([f"Патентных публикаций с {pt['since']} года (EPO OPS): {pt['total']}, из них китайских — {pt['china']}."]
                  if (pt := a["ev"].patents) and pt.get("total") else []),
                *([f"Стартапов Y Combinator по годам набора: {', '.join(f'{y} — {n}' for y, n in list(a['ev'].yc_yearly.items())[-4:])}."]
                  if a["ev"].yc_yearly else []),
            ]
            data, res = await write_dossier(llm, query, cand.name, a["items"][:10], facts)
            check = None
            if data:
                data = await verify(cand, a, data)
                check = data.pop("_check", None)
            return cand, data, res, check

        async def verify(cand: Candidate, a: dict, data: dict) -> dict:
            """Перекрёстная проверка: досье пишет LLM, каждое фактическое утверждение проверяет decision-модель."""
            evidence_text = " ".join(f"{e.get('title', '')}. {e.get('snippet', '')}" for e in a["items"][:10])
            claims = pp_mod.split_claims(data)
            if dm.provider == "heuristic" or not claims:
                # Словарные правила не сравнивают русский текст с английскими источниками — честно не проверяем.
                data["verification"] = {"by": None, "checked": 0, "supported": 0, "removed": [], "note": "Проверка утверждений выполняется decision-моделью Jev/Kev; сейчас она недоступна."}
                return data
            state = build_state(cand.name, topic, a["items"][:10])
            r = await dm.ask(state, claim_questions([c for _, c in claims]))
            data = pp_mod.apply_verification(data, claims, r.answers, evidence_text, f"{r.provider}:{r.model}") if r.ok else {**data, "verification": {"by": None, "checked": 0, "supported": 0, "removed": [], "note": "Decision-модель не ответила — утверждения не проверены."}}
            data["_check"] = (r, claims)
            return data

        async def dossiers_phase():
            if llm.provider == "none":
                return []
            async def safe_dossier(cand):
                try:
                    return await dossier(cand)
                except Exception:  # досье — не критичный шаг: остаётся шаблонное
                    log.exception("run %s: dossier for %r failed", run_id, cand.name)
                    return None

            return [r for r in await asyncio.gather(*(safe_dossier(c) for c in signals)) if r is not None]

        win_res, link_res, dos_res = await asyncio.gather(windows_phase(), links_phase(), dossiers_phase())
        for cand, w in win_res:
            cand.contributions = {**(cand.contributions or {}), "window": w}
        if link_res:
            for i in sorted({i for c in signals for i in (c.document_ids or [])}):
                d = ctx.session.get(Document, i)
                if d and d.url in link_res:
                    d.link_status = link_res[d.url]
            dead = {u for u, st in link_res.items() if st == "dead"}
            for cand in signals:
                # Битые ссылки не показываются как подтверждение; число проверенных ссылок — в паспорте.
                docs = [ctx.session.get(Document, i) for i in cand.document_ids or []]
                cand.document_ids = [d.id for d in docs if d and d.url not in dead]
                pp = dict((cand.contributions or {}).get("passport") or {})
                pp["links"] = {st: sum(1 for d in docs if d and link_res.get(d.url) == st) for st in ("ok", "restricted", "dead")}
                cand.contributions = {**cand.contributions, "passport": pp}
        ctx.session.commit()

        if dos_res:
            for cand, data, res, check in dos_res:
                ctx.log_call(res.provider, res.model, "аналитическое досье", cand.name, {"evidence": len(by_name[cand.name]["items"])}, {"text": res.text[:4000]}, res.latency_ms, res.ok, usage=res.usage)
                if check:
                    r, claims = check
                    ctx.log_call(r.provider, r.model, "проверка утверждений досье", cand.name, {"claims": [c for _, c in claims]}, {"answers": r.answers, "error": r.error}, r.latency_ms, r.ok, usage=r.usage)
                if data:
                    cand.dossier = {**cand.dossier, **{k: v for k, v in data.items() if v}, "generated_by": f"{res.provider}:{res.model}"}
                    # Досье больше не затирает название: названия организатора и уже проверенные переводы остаются;
                    # название из досье берётся, только если своего нет и оно прошло тот же валидатор.
                    methods = (cand.contributions or {}).get("methods", [])
                    if not cand.name_ru and "watchlist" not in methods and data.get("name_ru"):
                        ru, why = check_name_ru(cand.name, data["name_ru"], query)
                        if ru and ru != cand.name and not why:
                            cand.name_ru = ru
                            cand.contributions = {**cand.contributions, "name_check": None}
            ctx.session.commit()

            ctx.stage("Русские резюме иностранных источников", 94)
            sig_doc_ids = sorted({i for c in signals for i in c.document_ids[:10]})
            docs = [ctx.session.get(Document, i) for i in sig_doc_ids]
            docs = [d for d in docs if d and d.language != "ru"]
            chunks = [docs[k : k + 15] for k in range(0, len(docs), 15)]

            async def summ(chunk):
                return chunk, *(await summarize_sources(llm, [{"title": d.title, "snippet": d.snippet} for d in chunk]))

            for chunk, sums, res in await asyncio.gather(*(summ(ch) for ch in chunks)):
                ctx.log_call(res.provider, res.model, "резюме источников на русском", f"{len(chunk)} источников", {}, {"text": res.text[:3000]}, res.latency_ms, res.ok, usage=res.usage)
                for i, d in enumerate(chunk):
                    if i in sums:
                        d.summary_ru = sums[i]
                        d.summary_generated = True
            ctx.session.commit()

        # Радар банка: направление, кольцо («пилотировать / изучать / наблюдать») и горизонт для топа и «Наблюдать».
        for cand in ctx.session.query(Candidate).filter(Candidate.run_id == run_id, Candidate.status.in_(["signal", "watch"])):
            a = by_name.get(cand.name)
            radar = pp_mod.bank_radar(cand.name_ru or cand.name, a["items"] if a else [], cand.dossier or {}, (cand.contributions or {}).get("passport"), cand.status)
            cand.contributions = {**(cand.contributions or {}), "radar": radar}
        ctx.session.commit()

        n_signals = len(signals)
        n_watch = sum(1 for d in decisions if d["status"] == "watch")
        ctx.run.stats = {
            **ctx.run.stats,
            "sources_processed": len(corpus) + sum(len(a["ev"].docs) for a in assessed),
            "documents_saved": total_docs,
            "candidates": len(assessed),
            "signals": n_signals,
            "confident_signals": sum(1 for c in signals if (c.probability or 0) >= s.confident_threshold),
            "passport": {lv: sum(1 for c in signals if (c.contributions or {}).get("passport", {}).get("level") == lv) for lv in ("A", "B")},
            "watch": n_watch,
            "excluded": len(assessed) - n_signals - n_watch,
            "changes": _changes(ctx.session, ctx.run, [c.name for c in signals]),
            "http": http.stats,
        }
        if not corpus and not any(st.get("ok") or st.get("cached") for st in http.stats.values()):
            # Пустая выдача без объяснения выглядела бы как «технологий нет»; на деле сервер не достучался до источников.
            ctx.run.stats = {**ctx.run.stats, "sources_down": True}
            ctx.run.error = ("Ни один открытый источник не ответил, поэтому сигналов нет. Проверьте доступ сервера в интернет "
                             "(прокси, файрвол) и повторите запрос кнопкой «Пересчитать заново».")
        ctx.run.status = "done"
        ctx.stage("Готово", 100)
        ctx.run.stats = {**ctx.run.stats, "timing": ctx.finish_timing()}
        ctx.stage("Готово", 100)
    finally:
        # Стоимость считается и для отклонённых запросов: проверка запроса — тоже вызов модели.
        ctx.run.stats = {**(ctx.run.stats or {}), "cost": cost_mod.estimate(ctx.usage)}
        if http is not None:
            await http.close()
