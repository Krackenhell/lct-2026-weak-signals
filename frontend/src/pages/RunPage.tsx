import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, CandidateBrief, ModelCall, pct, RunFull } from "../api";
import { OriginBadge, ScoreBadge } from "../components/ui";

type Tab = "signals" | "excluded" | "log";

export default function RunPage() {
  const { id } = useParams();
  const [run, setRun] = useState<RunFull | null>(null);
  const [tab, setTab] = useState<Tab>("signals");
  const [log, setLog] = useState<ModelCall[] | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    let timer: number | undefined;
    const load = async () => {
      try {
        const r = await api.run(id!);
        setRun(r);
        if (r.status === "queued" || r.status === "running") timer = window.setTimeout(load, 2000);
      } catch (e) {
        setErr(String(e));
      }
    };
    load();
    return () => window.clearTimeout(timer);
  }, [id]);

  useEffect(() => {
    if (tab === "log" && id) api.log(id).then(setLog).catch(() => {});
  }, [tab, id, run?.status]);

  if (err) return <div className="error">{err}</div>;
  if (!run) return <p className="muted">Загрузка…</p>;

  const s = run.stats || {};
  const active = run.status === "queued" || run.status === "running";
  const confident = run.signals.filter((c) => (c.probability ?? 0) >= 0.75).length;

  return (
    <>
      <p className="muted small"><Link to="/">← К поиску</Link></p>
      <h1>«{run.query}»</h1>
      <div className="meta-row small muted">
        {run.providers?.decision_model && <span>Decision-модель: <b>{run.providers.decision_model}</b></span>}
        {run.providers?.llm && <span>· LLM: <b>{run.providers.llm}</b></span>}
        {run.providers?.classifier && <span>· Классификатор: <b>{run.providers.classifier}</b></span>}
        <span>· База отслеживания: <b>{run.options?.use_watchlist === false ? "выключена" : "включена"}</b></span>
      </div>

      {active && (
        <div className="panel" style={{ marginTop: 16 }}>
          <b>{run.stage || "Ожидание"}</b>
          <div className="progress"><div style={{ width: `${run.progress}%` }} /></div>
          <span className="muted small">{run.progress}% · обработка обычно занимает 5–15 минут</span>
        </div>
      )}
      {run.status === "failed" && <div className="error" style={{ marginTop: 16 }}>Ошибка обработки: {run.error}</div>}

      <div className="kpis">
        <div className="kpi"><div className="label">Обработано источников</div><div className="value">{(s.sources_processed as number)?.toLocaleString("ru-RU") ?? "…"}</div></div>
        <div className="kpi">
          <div className="label">Кандидатов проверено</div>
          <div className="value warn">
            {s.candidates != null ? <a href="#excluded" onClick={() => setTab("excluded")}>{s.candidates as number}</a> : "…"}
          </div>
        </div>
        <div className="kpi"><div className="label">Слабых сигналов в топе</div><div className="value accent">{run.status === "done" ? run.signals.length : "…"}</div></div>
        <div className="kpi"><div className="label">Уверенность модели &gt; 75%</div><div className="value good">{run.status === "done" ? confident : "…"}</div></div>
      </div>

      {run.plan?.subqueries && (
        <div className="panel small">
          <b>План поиска</b> <span className="muted">({run.plan.generated_by === "lexicon" ? "словарь направлений" : `сгенерирован ${run.plan.generated_by}`})</span>
          <div className="chips">
            {run.plan.subqueries.map((q) => <span key={q} className="chip static">{q}</span>)}
            {(run.plan.ru_terms ?? []).map((q) => <span key={q} className="chip static">{q}</span>)}
          </div>
        </div>
      )}

      {run.status === "done" && (
        <>
          <div className="tabs" id="excluded">
            <button className={`tab ${tab === "signals" ? "active" : ""}`} onClick={() => setTab("signals")}>Топ слабых сигналов ({run.signals.length})</button>
            <button className={`tab ${tab === "excluded" ? "active" : ""}`} onClick={() => setTab("excluded")}>Исключённые кандидаты ({run.excluded.length})</button>
            <button className={`tab ${tab === "log" ? "active" : ""}`} onClick={() => setTab("log")}>Журнал моделей</button>
          </div>
          {tab === "signals" && <SignalsTable items={run.signals} />}
          {tab === "excluded" && <ExcludedTable items={run.excluded} />}
          {tab === "log" && <LogTable items={log} />}
        </>
      )}
    </>
  );
}

function name(c: CandidateBrief) {
  return (
    <>
      <div><b>{c.name_ru || c.name}</b></div>
      {c.name_ru && <div className="en">{c.name}</div>}
    </>
  );
}

function SignalsTable({ items }: { items: CandidateBrief[] }) {
  if (!items.length) return <p className="muted">Сигналы не найдены: все кандидаты отфильтрованы. См. вкладку «Исключённые».</p>;
  return (
    <div className="tablewrap">
      <table>
        <thead>
          <tr><th>#</th><th>Технология / тема</th><th>Скоринг (модель)</th><th>Ключевые предикторы</th><th>Источники</th><th>Статус</th></tr>
        </thead>
        <tbody>
          {items.map((c) => (
            <tr key={c.id}>
              <td>{c.rank}</td>
              <td>{name(c)}<div style={{ marginTop: 4 }}><OriginBadge origin={c.origin} /></div></td>
              <td><ScoreBadge p={c.probability} /><div className="muted small" style={{ marginTop: 4 }}>релевантность {pct(c.relevance)}</div></td>
              <td className="small">{c.key_predictors.map((p) => <div key={p.feature}>+ {p.label} <span className="muted">({p.value})</span></div>)}</td>
              <td>{c.n_sources}</td>
              <td><Link to={`/insight/${c.id}`}>Смотреть инсайт →</Link></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ExcludedTable({ items }: { items: CandidateBrief[] }) {
  const groups = items.reduce<Record<string, number>>((acc, c) => {
    const k = c.exclusion_label || "Прочее";
    acc[k] = (acc[k] || 0) + 1;
    return acc;
  }, {});
  return (
    <>
      <div className="chips" style={{ marginBottom: 12 }}>
        {Object.entries(groups).map(([k, v]) => <span key={k} className="chip static">{k}: {v}</span>)}
      </div>
      <div className="tablewrap">
        <table>
          <thead><tr><th>Кандидат</th><th>Причина исключения</th><th>Вероятность сигнала</th><th></th></tr></thead>
          <tbody>
            {items.map((c) => (
              <tr key={c.id}>
                <td>{name(c)}</td>
                <td><span className="badge low">{c.exclusion_label}</span><div className="small" style={{ marginTop: 6 }}>{c.exclusion_reason}</div></td>
                <td><ScoreBadge p={c.probability} /></td>
                <td><Link to={`/insight/${c.id}`}>Подробнее</Link></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function LogTable({ items }: { items: ModelCall[] | null }) {
  if (!items) return <p className="muted">Загрузка…</p>;
  return (
    <>
      <p className="muted small">Каждое обращение к модели: какая модель, с какой целью и что вернула. Решение о статусе сигнала принимает собственный классификатор по этим ответам.</p>
      <div className="tablewrap">
        <table>
          <thead><tr><th>#</th><th>Модель</th><th>Назначение</th><th>Объект</th><th>Время</th><th>Ответ</th></tr></thead>
          <tbody>
            {items.map((m) => (
              <tr key={m.id}>
                <td>{m.id}</td>
                <td><b>{m.provider}</b><div className="en">{m.model}</div></td>
                <td>{m.purpose}{!m.ok && <span className="badge low" style={{ marginLeft: 6 }}>ошибка</span>}</td>
                <td className="small">{m.subject}</td>
                <td className="small">{m.latency_ms} мс</td>
                <td><details><summary className="small">показать</summary><pre className="code">{JSON.stringify(m.response, null, 1)}</pre></details></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
