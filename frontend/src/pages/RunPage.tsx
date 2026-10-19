import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, CandidateBrief, Changes, EXPORT_FORMATS, exportUrl, fmtScore, ModelCall, rankScore, RunFull, SCORE_HINT } from "../api";
import { ChecksBadge, ScoreBadge } from "../components/ui";

const TOP_K = 15;

type Tab = "signals" | "watch" | "excluded" | "log";

export default function RunPage() {
  const { id } = useParams();
  const [run, setRun] = useState<RunFull | null>(null);
  const [tab, setTab] = useState<Tab>("signals");
  const [log, setLog] = useState<ModelCall[] | null>(null);
  const [err, setErr] = useState("");
  const [rerun, setRerun] = useState(false);
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
  const changes = s.changes as Changes | undefined;
  const seconds = run.finished_at && run.created_at ? Math.round((Date.parse(run.finished_at) - Date.parse(run.created_at)) / 1000) : null;
  const emerging = run.plan?.emerging ?? [];
  const confident = s.confident_signals as number | undefined;
  // Добор до 15 строк — только в интерфейсе и только из «Наблюдать»: статус, экспорт и статистика не меняются.
  const topUp = run.signals.length > 0 ? watch.slice(0, Math.max(0, TOP_K - run.signals.length)) : [];

  async function recompute() {
    setRerun(true);
    try {
      const r = await api.search(run!.query, !!run!.options?.use_watchlist, true);
      nav(`/runs/${r.id}`);
    } catch (e) {
      setErr(String(e));
    } finally {
      setRerun(false);
    }
  }

  return (
    <>
      <p className="muted small"><Link to="/">← Новый запрос</Link></p>
      <h1>«{run.query}»</h1>
      <div className="meta-row small muted">
        {run.status === "done" && run.created_at && (
          <span>
            Результат от {new Date(run.created_at).toLocaleString("ru-RU")}
            {run.options?.precompute ? " · рассчитано заранее" : ""}
            {seconds != null ? ` · обработка ${Math.floor(seconds / 60)} мин ${seconds % 60} с` : ""}
          </span>
        )}
        {run.providers?.llm && <span>· {modelsLine(run.providers)}</span>}
        {run.status === "done" && (
          <button className="chip" type="button" disabled={rerun} onClick={recompute} title="Повторный запрос темы в течение 4 суток открывает готовый результат; эта кнопка считает заново">
            {rerun ? "Запуск…" : "Пересчитать"}
          </button>
        )}
      </div>

      {run.status === "rejected" && (
        <div className="panel" style={{ marginTop: 16, borderLeft: "4px solid var(--bad)" }}>
          <h3 style={{ marginTop: 0 }}>Запрос не похож на технологическое направление</h3>
          <p>{run.error}</p>
          <p className="muted small">Примеры запросов: «микрофлюидные технологии», «технологии многослойного графена», «edge AI», «газлифт в скважинах».</p>
          <Link to="/">Задать другой запрос →</Link>
        </div>
      )}

      {active && (
        <div className="panel" style={{ marginTop: 16 }}>
          <b>{run.stage || "Ожидание"}</b>
          <div className="progress"><div style={{ width: `${run.progress}%` }} /></div>
          <span className="muted small">
            {run.status === "queued" && run.queue
              ? `В очереди: перед вами ${run.queue.ahead} ${run.queue.ahead === 1 ? "запрос" : "запроса"}, ожидание около ${Math.max(1, Math.round(run.queue.eta_seconds / 60))} мин`
              : `${run.progress}% · новый анализ занимает 2–4 минуты`}
            {" · страница обновляется сама"}
          </span>
        </div>
      )}
      {run.status === "failed" && <div className="error" style={{ marginTop: 16 }}>Ошибка обработки: {run.error}</div>}
      {run.status === "done" && run.error && <div className="error" style={{ marginTop: 16 }}>{run.error}</div>}
      {run.status === "done" && s.budget && (
        <div className="error" style={{ marginTop: 16 }}>
          Проверено {(s.budget as { checked: number; total: number }).checked} из {(s.budget as { checked: number; total: number }).total} кандидатов —
          сработал лимит времени обработки; непроверенные кандидаты в выдачу не попали.
        </div>
      )}
      {run.status === "done" && s.degraded && (
        <div className="error" style={{ marginTop: 16 }}>
          Статистика публикаций OpenAlex была недоступна для части кандидатов: признаки публикаций заменены средними, и эти числа в карточках
          не показываются. Выдачу стоит пересчитать позже.
        </div>
      )}

      {run.status === "done" && (
        <div className="kpis">
          <div className="kpi"><div className="label">Слабых сигналов</div><div className="value accent">{run.signals.length}</div></div>
          <div className="kpi" title="Показатель ТЗ. Оценка классификатора — сходство с эталонными слабыми сигналами, а не вероятность успеха технологии.">
            <div className="label">Оценка классификатора ≥ 0,75</div>
            <div className="value">{confident != null ? `${confident} из ${run.signals.length}` : "—"}</div>
          </div>
          <div className="kpi"><div className="label">Кандидатов проверено</div><div className="value">{(s.candidates as number) ?? "—"}</div></div>
          <div className="kpi"><div className="label">Документов обработано</div><div className="value">{(s.sources_processed as number)?.toLocaleString("ru-RU") ?? "—"}</div></div>
        </div>
      )}

      {run.status === "done" && changes && (
        <div className="panel small">
          С прошлого анализа <Link to={`/runs/${changes.prev_run_id}`}>от {changes.prev_date ? new Date(changes.prev_date).toLocaleDateString("ru-RU") : `#${changes.prev_run_id}`}</Link>:
          сохранилось {changes.kept}, новых {changes.new.length}, выпало {changes.dropped.length}.
          {changes.new.length > 0 && <span> Новые: {changes.new.join(", ")}.</span>}
        </div>
      )}

      {run.status === "done" && (
        <>
          <div className="tabs">
            <button className={`tab ${tab === "signals" ? "active" : ""}`} onClick={() => setTab("signals")}>Слабые сигналы ({run.signals.length})</button>
            <button className={`tab ${tab === "watch" ? "active" : ""}`} onClick={() => setTab("watch")}>Наблюдать ({watch.length})</button>
            <button className={`tab ${tab === "excluded" ? "active" : ""}`} onClick={() => setTab("excluded")}>Не вошли в топ ({run.excluded.length})</button>
            <button className={`tab ${tab === "log" ? "active" : ""}`} onClick={() => setTab("log")}>Журнал моделей</button>
          </div>
          {tab === "signals" && run.signals.length === 0 && watch.length > 0 && (
            <>
              <p className="small">
                Подтверждённых сигналов нет: по этой теме пока мало независимых источников (нужно не меньше трёх подтверждённых документов).
                Ниже — ранние кандидаты, которые модель оценивает как перспективные; их стоит перепроверить позже.
              </p>
              <SignalList items={watch} />
            </>
          )}
          {tab === "signals" && (run.signals.length > 0 || watch.length === 0) && <SignalList items={run.signals} />}
          {tab === "signals" && topUp.length > 0 && (
            <>
              <p className="muted small divider">Ниже планки — под наблюдением: модель подтвердила меньше трёх документов, в топ не входят.</p>
              <SignalList items={topUp} dim />
            </>
          )}
          {tab === "watch" && (
            <>
              <p className="muted small">
                Модель оценивает их высоко, но подтверждённых документов пока меньше трёх. Без доказательств оценка не принимается — кандидаты
                остаются под наблюдением.
              </p>
              <SignalList items={watch} />
            </>
          )}
          {tab === "excluded" && <ExcludedTable items={run.excluded} />}
          {tab === "log" && <LogTable items={log} />}

          <div className="meta-row small" style={{ marginTop: 16 }}>
            <span className="muted">Скачать отчёт:</span>
            {EXPORT_FORMATS.map(([f, label]) => (
              <a key={f} className="chip" href={exportUrl(run.id, f)} download>{label}</a>
            ))}
          </div>

          {run.plan?.subqueries && (
            <details className="panel small" style={{ marginTop: 12 }}>
              <summary><b>Как искали</b> <span className="muted">— поисковые фразы и растущие поднаправления</span></summary>
              {emerging.length > 0 && (
                <>
                  <p style={{ marginBottom: 4 }}>
                    Растущие поднаправления по научной литературе (OpenAlex, тема «{run.plan.core_term}»: доля ключевого слова в работах
                    за последние 2 года против 2 лет до этого):
                  </p>
                  <div className="chips">
                    {emerging.map((e) => (
                      <span key={e.keyword} className="chip static" title={`работ: ${e.recent} против ${e.prior}; тема — ${Math.round(e.specificity * 100)}% работ этого ключевого слова`}>
                        {e.keyword} · {e.recent} работ
                      </span>
                    ))}
                  </div>
                </>
              )}
              {run.plan.scope_en && <p style={{ marginBottom: 4 }}>Как система поняла запрос: {run.plan.scope_en}.</p>}
              {run.plan.route && (
                <p style={{ marginBottom: 4 }}>
                  Маршрут источников: {run.plan.route.text}.{run.plan.broad === false ? " Узкий запрос: подтемы словаря направлений не подмешивались." : ""}
                </p>
              )}
              <p style={{ marginBottom: 4 }}>
                Поисковые фразы ({run.plan.generated_by === "lexicon" ? "словарь направлений" : `план: ${run.plan.generated_by}`}{run.plan.plan_cached ? ", план сохранён с прошлого расчёта темы" : ""}):
              </p>
              <div className="chips">
                {run.plan.subqueries.map((q) => <span key={q} className="chip static">{q}</span>)}
                {(run.plan.ru_terms ?? []).map((q) => <span key={q} className="chip static">{q}</span>)}
              </div>
            </details>
          )}
        </>
      )}
    </>
  );
}

function modelsLine(p: Record<string, string>) {
  const llm = (p.llm || "").split(":").pop();
  const dm = (p.decision_model || "").split(":")[0];
  const llmName = p.llm?.startsWith("gigachat") ? `GigaChat (${llm})` : llm;
  const dmName = dm === "jev" ? "Jev" : dm === "heuristic" ? "правила (Jev недоступна)" : dm;
  return `тексты: ${llmName} · проверка: ${dmName} · решение: собственная модель`;
}

function facts(c: CandidateBrief) {
  const parts: string[] = [];
  if (c.stage) parts.push(`${c.stage.label} (УГТ ${c.stage.trl})`);
  if (c.first_year) parts.push(`в литературе с ${c.first_year} г.`);
  if (c.growth_x && c.growth_x >= 1.2) parts.push(`работ за 2 года больше в ${c.growth_x.toLocaleString("ru-RU")} раза`);
  else if (c.works_2y) parts.push(`${c.works_2y} работ за 2 года`);
  return parts.join(" · ");
}

function SignalList({ items, dim = false }: { items: CandidateBrief[]; dim?: boolean }) {
  if (!items.length) return <p className="muted">Список пуст. Причины по каждому кандидату — во вкладке «Не вошли в топ».</p>;
  return (
    <div className={`signal-list${dim ? " dim" : ""}`}>
      {items.map((c) => (
        <Link key={c.id} to={`/insight/${c.id}`} className="panel signal-card">
          <div className="signal-rank">{c.rank ?? "·"}</div>
          <div className="signal-body">
            <div className="signal-title">
              <b>{c.name_ru || c.name}</b>
              {c.name_ru && c.name_ru !== c.name && <span className="en"> {c.name}</span>}
            </div>
            {c.summary && <div className="small">{c.summary}</div>}
            <div className="muted small">
              {facts(c)}
              {c.missing?.includes("openalex") && <span className="badge med" style={{ marginLeft: 6 }}>публикации не проверены</span>}
              {c.in_training && <span className="badge neutral" style={{ marginLeft: 6 }} title="Совпадает с примером обучающей выборки: высокая оценка ожидаема и не является независимой проверкой">пример из обучения</span>}
            </div>
          </div>
          <div className="signal-badges">
            {c.status === "signal" && <span className="badge neutral" title={SCORE_HINT}>балл {fmtScore(c.score?.final ?? rankScore(c.probability, c.relevance))}</span>}
            <ScoreBadge p={c.probability} />
            <ChecksBadge c={c.checks} />
          </div>
        </Link>
      ))}
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
      <p className="muted small">Каждый проверенный кандидат с причиной, по которой он не вошёл в топ.</p>
      <div className="chips" style={{ marginBottom: 12 }}>
        {Object.entries(groups).map(([k, v]) => <span key={k} className="chip static">{k}: {v}</span>)}
      </div>
      <div className="tablewrap">
        <table>
          <thead><tr><th>Кандидат</th><th>Причина</th><th>Оценка модели</th></tr></thead>
          <tbody>
            {items.map((c) => (
              <tr key={c.id}>
                <td><Link to={`/insight/${c.id}`}><b>{c.name_ru || c.name}</b></Link>{c.name_ru && c.name_ru !== c.name && <div className="en">{c.name}</div>}</td>
                <td><span className="badge low">{c.exclusion_label}</span><div className="small" style={{ marginTop: 6 }}>{c.exclusion_reason}</div></td>
                <td><ScoreBadge p={c.probability} /></td>
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
