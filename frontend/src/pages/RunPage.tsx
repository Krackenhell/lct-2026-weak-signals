import { useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, CandidateBrief, Changes, EXPORT_FORMATS, exportUrl, ModelCall, prob, radarGrid, RINGS, RunFull } from "../api";
import { OriginBadge, PassportBadge, RadarBadge, RobustnessBadge, ScoreBadge, WindowBadge } from "../components/ui";

type Tab = "signals" | "radar" | "watch" | "excluded" | "log";

export default function RunPage() {
  const { id } = useParams();
  const [run, setRun] = useState<RunFull | null>(null);
  const [tab, setTab] = useState<Tab>("signals");
  const [log, setLog] = useState<ModelCall[] | null>(null);
  const [err, setErr] = useState("");
  const [fresh, setFresh] = useState(false);
  const [params] = useSearchParams();
  const reused = params.get("reused") === "1";
  const nav = useNavigate();

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
  const watch = run.watch ?? [];
  const solid = run.signals.filter((c) => c.passport?.level === "A" || c.passport?.level === "B").length;
  const changes = s.changes as Changes | undefined;

  return (
    <>
      <p className="muted small"><Link to="/">← К поиску</Link></p>
      <h1>«{run.query}»</h1>
      <div className="meta-row small muted">
        {run.providers?.decision_model && <span>Decision-модель: <b>{run.providers.decision_model}</b></span>}
        {run.providers?.llm && <span>· LLM: <b>{run.providers.llm}</b></span>}
        {run.providers?.classifier && <span>· Классификатор: <b>{run.providers.classifier}</b></span>}
        <span>· Режим: <b>{run.options?.use_watchlist ? "мониторинг (с базой отслеживания)" : "чистое обнаружение"}</b></span>
      </div>

      {reused && (
        <div className="panel" style={{ marginTop: 16, borderLeft: "4px solid var(--accent)" }}>
          <b>Заранее посчитанная выдача</b> — эта тема уже обрабатывалась вживую{" "}
          {run.finished_at ? new Date(run.finished_at).toLocaleString("ru-RU") : ""}, поэтому результат открыт сразу.
          Новые темы всегда считаются с нуля.{" "}
          <button className="chip" type="button" disabled={fresh} onClick={async () => {
            setFresh(true);
            const r = await api.search(run.query, !!run.options?.use_watchlist, false);
            nav(`/runs/${r.id}`);
          }}>{fresh ? "Запуск…" : "Посчитать заново"}</button>
        </div>
      )}

      {run.status === "rejected" && (
        <div className="panel" style={{ marginTop: 16, borderLeft: "4px solid var(--bad)" }}>
          <h3 style={{ marginTop: 0 }}>Запрос не похож на технологическое направление</h3>
          <p>{run.error}</p>
          <p className="muted small">
            Система ищет ранние технологии по направлениям вроде «финтех», «кибербезопасность ИИ», «edge AI», «микрофлюидика».
            Проверку выполнил: {(s.query_check as { by?: string })?.by ?? "—"}. Сигналы не формируются — чтобы не выдавать уверенный ответ на бессмысленный вопрос.
          </p>
          <Link to="/">Задать другой запрос →</Link>
        </div>
      )}

      {active && (
        <div className="panel" style={{ marginTop: 16 }}>
          <b>{run.stage || "Ожидание"}</b>
          <div className="progress"><div style={{ width: `${run.progress}%` }} /></div>
          <span className="muted small">{run.progress}% · обработка обычно занимает 5–15 минут</span>
        </div>
      )}
      {run.status === "failed" && <div className="error" style={{ marginTop: 16 }}>Ошибка обработки: {run.error}</div>}

      {run.status !== "rejected" && <div className="kpis">
        <div className="kpi"><div className="label">Обработано источников</div><div className="value">{(s.sources_processed as number)?.toLocaleString("ru-RU") ?? "…"}</div></div>
        <div className="kpi">
          <div className="label">Кандидатов проверено</div>
          <div className="value warn">
            {s.candidates != null ? <a href="#excluded" onClick={() => setTab("excluded")}>{s.candidates as number}</a> : "…"}
          </div>
        </div>
        <div className="kpi"><div className="label">Слабых сигналов в топе</div><div className="value accent">{run.status === "done" ? run.signals.length : "…"}</div></div>
        <div className="kpi"><div className="label">Доказательства A/B (подтверждено ≥ 3 док.)</div><div className="value good">{run.status === "done" ? solid : "…"}</div></div>
        <div className="kpi"><div className="label">Наблюдать: мало данных</div><div className="value">{run.status === "done" ? watch.length : "…"}</div></div>
      </div>}

      {run.status === "done" && (
        <div className="meta-row small" style={{ marginBottom: 12 }}>
          <span className="muted">Скачать отчёт:</span>
          {EXPORT_FORMATS.map(([f, label]) => (
            <a key={f} className="chip" href={exportUrl(run.id, f)} download>{label}</a>
          ))}
          <span className="muted">Excel — в колонках датасета организатора, с листами «Наблюдать», «Исключённые», «Источники».</span>
        </div>
      )}

      {run.status === "done" && changes && (
        <div className="panel small">
          <b>Мониторинг темы:</b> по сравнению с прогоном <Link to={`/runs/${changes.prev_run_id}`}>#{changes.prev_run_id}</Link>
          {changes.prev_date ? ` от ${new Date(changes.prev_date).toLocaleDateString("ru-RU")}` : ""} — сохранилось {changes.kept},
          новых {changes.new.length}, выпало {changes.dropped.length}.
          {changes.new.length > 0 && <div style={{ marginTop: 6 }}>Новые: {changes.new.join(", ")}</div>}
          {changes.dropped.length > 0 && <div className="muted" style={{ marginTop: 4 }}>Выпали: {changes.dropped.join(", ")}</div>}
        </div>
      )}

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
            <button className={`tab ${tab === "radar" ? "active" : ""}`} onClick={() => setTab("radar")}>Радар банка</button>
            <button className={`tab ${tab === "watch" ? "active" : ""}`} onClick={() => setTab("watch")}>Наблюдать ({watch.length})</button>
            <button className={`tab ${tab === "excluded" ? "active" : ""}`} onClick={() => setTab("excluded")}>Исключённые кандидаты ({run.excluded.length})</button>
            <button className={`tab ${tab === "log" ? "active" : ""}`} onClick={() => setTab("log")}>Журнал моделей</button>
          </div>
          {tab === "signals" && <SignalsTable items={run.signals} />}
          {tab === "radar" && <RadarTable items={[...run.signals, ...watch]} />}
          {tab === "watch" && (
            <>
              <p className="muted small">
                Кандидаты с высокой вероятностью по модели, но без достаточных доказательств: decision-модель подтвердила меньше 3 документов
                из разных источников. Без доказательств вероятность ничего не значит, поэтому в топ они не попадают — их стоит перепроверить позже.
              </p>
              <ExcludedTable items={watch} />
            </>
          )}
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
          <tr><th>#</th><th>Технология / тема</th><th>Скоринг (модель)</th><th>Проверяемость</th><th>Ключевые предикторы</th><th>Источники</th><th>Статус</th></tr>
        </thead>
        <tbody>
          {items.map((c) => (
            <tr key={c.id}>
              <td>{c.rank}</td>
              <td>{name(c)}<div style={{ marginTop: 4 }}><OriginBadge origin={c.origin} /></div></td>
              <td><ScoreBadge p={c.probability} /><div className="muted small" style={{ marginTop: 4 }}>релевантность {prob(c.relevance)}</div></td>
              <td className="small">
                <div className="badges-col"><RadarBadge r={c.radar} /><PassportBadge p={c.passport} /><RobustnessBadge r={c.robustness} /><WindowBadge w={c.window} /></div>
                {c.passport && <div className="muted" style={{ marginTop: 4 }}>событие: {c.passport.event}</div>}
              </td>
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

function RadarTable({ items }: { items: CandidateBrief[] }) {
  const grid = radarGrid(items);
  if (!grid.length) return <p className="muted">Радар строится по сигналам и кандидатам «Наблюдать».</p>;
  return (
    <>
      <p className="muted small">
        Что делать банку с каждой технологией. <b>Пилотировать</b> — надёжные доказательства (паспорт A) и уже есть пилот, релиз или инвестиции;
        <b> Изучать</b> — сигнал с достаточными доказательствами; <b>Наблюдать</b> — мало подтверждений, перепроверить позже. В скобках — горизонт.
      </p>
      <div className="tablewrap">
        <table>
          <thead><tr><th>Направление банка</th>{RINGS.map((r) => <th key={r}>{r}</th>)}</tr></thead>
          <tbody>
            {grid.map(([area, rings]) => (
              <tr key={area}>
                <td><b>{area}</b></td>
                {RINGS.map((r) => (
                  <td key={r} className="small">
                    {rings[r].map((c) => (
                      <div key={c.id}><Link to={`/insight/${c.id}`}>{c.name_ru || c.name}</Link> <span className="muted">({c.radar?.horizon})</span></div>
                    ))}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
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
                <td><ScoreBadge p={c.probability} />{c.passport && <div style={{ marginTop: 4 }}><PassportBadge p={c.passport} /></div>}</td>
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
