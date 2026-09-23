"""Оркестратор открытого запроса: план → корпус → кандидаты → доказательства → скоринг → исключения → досье.

Прогресс и все промежуточные результаты пишутся в БД, поэтому интерфейс показывает
ход обработки в реальном времени, а журнал вызовов моделей доступен для проверки.
"""
import asyncio
import logging
import traceback
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from app.collectors.base import RawDoc
from app.collectors.http import HttpClient
from app.config import get_settings
from app.db import SessionLocal
from app.decision import get_decision_model
from app.llm.providers import get_llm
from app.llm.tasks import plan_query, summarize_sources, write_dossier
from app.ml.model import SignalModel
from app.models import Candidate, Document, ModelCall, Run
from app.pipeline import discovery, evidence as evidence_mod
from app.pipeline.decide import decide, template_dossier
from app.pipeline.features import answer_features, numeric_features
from app.pipeline.questions import EVIDENCE_MATCH, QUESTIONS, build_state, relevance_question
from app.pipeline.trust import classify

log = logging.getLogger(__name__)


class RunContext:
    def __init__(self, run_id: int):
        self.run_id = run_id
        self.session: Session = SessionLocal()
        self.run: Run = self.session.get(Run, run_id)

    def stage(self, text: str, progress: int) -> None:
        self.run.stage = text
        self.run.progress = progress
        self.session.commit()

    def log_call(self, provider: str, model: str, purpose: str, subject: str, request: dict, response: dict, latency_ms: int, ok: bool = True) -> None:
        self.session.add(
            ModelCall(run_id=self.run_id, provider=provider, model=model, purpose=purpose, subject=subject[:300], request=request, response=response, latency_ms=latency_ms, ok=ok)
        )


def _doc_row(run_id: int, d: RawDoc) -> Document:
    stype, trust, reason = classify(d)
    return Document(
        run_id=run_id, url=d.url[:1000], title=d.title[:2000], snippet=d.snippet, published=d.published, source_name=d.source_name[:200],
        source_type=stype, language=d.language or "en", trust_level=trust, trust_reason=reason, collector=d.collector,
    )


async def execute(run_id: int) -> None:
    ctx = RunContext(run_id)
    s = get_settings()
    http = HttpClient()
    llm = get_llm()
    dm = get_decision_model()
    model = SignalModel.load()
    query = ctx.run.query
    ctx.run.status = "running"
    ctx.run.providers = {
        "decision_model": f"{dm.provider}:{dm.model}",
        "llm": f"{llm.provider}:{llm.model}",
        "classifier": "logistic-regression" + (f" (обучена на {model.meta.get('trained_on')} примерах)" if model else " (не обучена)"),
    }
    ctx.session.commit()
    try:
        # 1. План поиска
        ctx.stage("Расширение запроса: подтемы и поисковые фразы", 3)
        plan, res = await plan_query(llm, query)
        if res:
            ctx.log_call(res.provider, res.model, "расширение запроса", query, {"query": query}, {"text": res.text[:3000]}, res.latency_ms, res.ok)
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
            ctx.log_call(r.provider, r.model, "извлечение технологий из документов", query, {"docs": "пачка документов корпуса"}, {"text": r.text[:3000]}, r.latency_ms, r.ok)
        watch = discovery.watchlist(query, plan, (ctx.run.options or {}).get("use_watchlist"))
        pool = discovery.merge(extracted + mined + watch)
        # Предварительный отбор: сначала подтверждённые несколькими документами/методами.
        # Сигналы из базы отслеживания получают зарезервированные места (до 20), остальное — новые кандидаты.
        watched = [c for c in pool if "watchlist" in c["methods"]][:20]
        # Кандидаты, извлечённые LLM из текстов, приоритетнее статистических фраз.
        fresh = sorted(
            (c for c in pool if "watchlist" not in c["methods"]),
            key=lambda c: (-("llm-extraction" in c["methods"]), -(len(c["doc_idx"]) + 2 * c["support"])),
        )
        pool = watched + fresh[: max(s.max_candidates - len(watched), 0)]
        ctx.run.stats = {**ctx.run.stats, "corpus_docs": len(corpus), "raw_candidates": len(extracted) + len(mined) + len(watch)}
        ctx.stage(f"Проверка {len(pool)} кандидатов по открытым источникам", 32)

        # 4. Доказательства, decision-модель, скоринг
        questions = {**QUESTIONS, "relevance": relevance_question(plan.get("topic_en") or query), "evidence_match": EVIDENCE_MATCH}
        done = 0
        topic = plan.get("topic_en") or query

        async def assess(c: dict) -> dict:
            nonlocal done
            with_repos = bool(s.github_token)  # без токена лимит GitHub слишком мал для топ-репозиториев
            ev = await evidence_mod.gather(http, c["name_en"], date.today(), with_news=True, with_repos=with_repos)
            for alt in c.get("alt_terms", []):
                if len(ev.docs) >= 5:
                    break
                alt_ev = await evidence_mod.gather(http, alt, date.today(), with_news=True, with_repos=with_repos)
                if len(alt_ev.docs) > len(ev.docs):
                    ev = alt_ev
            numeric = numeric_features(ev)  # до добавления документов корпуса — как при обучении
            corpus_docs = [corpus[i] for i in c["doc_idx"][:6]]
            dataset_docs = [
                RawDoc(url=w["url"], title=w["title"], source_name="Датасет организатора: ссылка на первоисточник", source_type="dataset", collector="dataset")
                for w in c.get("watch_sources", [])
            ]
            ev.docs = evidence_mod._dedupe(corpus_docs + ev.docs + dataset_docs)
            items = evidence_mod.evidence_items(ev)
            state = build_state(c["name_en"], topic, items)
            res = await dm.ask(state, questions)
            feats = {**numeric, **answer_features(res.answers)}
            prob = model.predict(feats) if model else None
            done += 1
            ctx.stage(f"Проверка кандидатов: {done}/{len(pool)} — «{c['name_en']}»", 32 + int(48 * done / len(pool)))
            return {"c": c, "ev": ev, "items": items, "state": state, "res": res, "features": feats, "prob": prob}

        sem = asyncio.Semaphore(6)

        async def guarded(c):
            async with sem:
                return await assess(c)

        assessed = await asyncio.gather(*(guarded(c) for c in pool))

        for a in assessed:
            r = a["res"]
            ctx.log_call(r.provider, r.model, "ответы на вопросы-признаки", a["c"]["name_en"], {"state": a["state"][:4000], "questions": list(questions)}, {"answers": r.answers, "error": r.error}, r.latency_ms, r.ok)
        ctx.session.commit()

        # 5. Решение: сигнал / исключение
        ctx.stage("Ранжирование и фильтрация зрелых технологий, стандартов и хайпа", 82)
        decisions = decide(assessed, model, s.top_k)

        # 6. Сохранение документов и кандидатов
        doc_ids_by_url: dict[str, int] = {}
        total_docs = 0
        for a, dcs in zip(assessed, decisions):
            ids = []
            for d in a["ev"].docs[:20]:
                if d.url not in doc_ids_by_url:
                    row = _doc_row(run_id, d)
                    ctx.session.add(row)
                    ctx.session.flush()
                    doc_ids_by_url[d.url] = row.id
                    total_docs += 1
                ids.append(doc_ids_by_url[d.url])
            cand = Candidate(
                run_id=run_id, name=a["c"]["name_en"], name_ru=a["c"].get("name_ru") or None,
                origin="watchlist" if "watchlist" in a["c"]["methods"] and not (set(a["c"]["methods"]) - {"watchlist"}) else "discovered",
                status=dcs["status"], rank=dcs.get("rank"), probability=a["prob"], relevance=dcs["relevance"],
                exclusion_code=dcs.get("code"), exclusion_reason=dcs.get("reason"), features=a["features"],
                contributions={"items": dcs["contributions"], "methods": a["c"]["methods"]}, answers=a["res"].answers,
                dossier=template_dossier(a, dcs), document_ids=ids,
            )
            ctx.session.add(cand)
        ctx.session.commit()

        # 7. Досье и русские резюме источников для топ-15
        signals = ctx.session.query(Candidate).filter_by(run_id=run_id, status="signal").order_by(Candidate.rank).all()
        ctx.stage(f"Подготовка аналитических досье по {len(signals)} сигналам", 88)
        by_name = {a["c"]["name_en"]: a for a in assessed}

        async def dossier(cand: Candidate):
            a = by_name[cand.name]
            facts = {
                "публикаций_всего": round(2.718 ** cand.features.get("log_total_works", 0) - 1),
                "доля_публикаций_за_3_года": round(cand.features.get("recent_share", 0), 2),
                "статья_в_википедии": bool(cand.features.get("wiki_exists")),
                "вероятность_слабого_сигнала": round(cand.probability or 0, 2),
            }
            data, res = await write_dossier(llm, query, cand.name, a["items"][:10], facts)
            return cand, data, res

        if llm.provider != "none":
            for cand, data, res in await asyncio.gather(*(dossier(c) for c in signals)):
                ctx.log_call(res.provider, res.model, "аналитическое досье", cand.name, {"evidence": len(by_name[cand.name]["items"])}, {"text": res.text[:4000]}, res.latency_ms, res.ok)
                if data:
                    cand.dossier = {**cand.dossier, **{k: v for k, v in data.items() if v}, "generated_by": f"{res.provider}:{res.model}"}
                    cand.name_ru = data.get("name_ru") or cand.name_ru
            ctx.session.commit()

            ctx.stage("Русские резюме иностранных источников", 94)
            sig_doc_ids = sorted({i for c in signals for i in c.document_ids[:10]})
            docs = [ctx.session.get(Document, i) for i in sig_doc_ids]
            docs = [d for d in docs if d and d.language != "ru"]
            chunks = [docs[k : k + 15] for k in range(0, len(docs), 15)]

            async def summ(chunk):
                return chunk, *(await summarize_sources(llm, [{"title": d.title, "snippet": d.snippet} for d in chunk]))

            for chunk, sums, res in await asyncio.gather(*(summ(ch) for ch in chunks)):
                ctx.log_call(res.provider, res.model, "резюме источников на русском", f"{len(chunk)} источников", {}, {"text": res.text[:3000]}, res.latency_ms, res.ok)
                for i, d in enumerate(chunk):
                    if i in sums:
                        d.summary_ru = sums[i]
                        d.summary_generated = True
            ctx.session.commit()

        n_signals = len(signals)
        ctx.run.stats = {
            **ctx.run.stats,
            "sources_processed": len(corpus) + sum(len(a["ev"].docs) for a in assessed),
            "documents_saved": total_docs,
            "candidates": len(assessed),
            "signals": n_signals,
            "confident_signals": sum(1 for c in signals if (c.probability or 0) >= s.confident_threshold),
            "excluded": len(assessed) - n_signals,
            "http": http.stats,
        }
        ctx.run.status = "done"
        ctx.stage("Готово", 100)
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
        await http.close()
