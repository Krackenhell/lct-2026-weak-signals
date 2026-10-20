import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, Run, Showcase } from "../api";
import { HeroRadar, Sculpture } from "../components/Radar";

// Запасной список, если API недоступен. Основной — GET /api/examples: те же темы рассчитываются заранее (app/examples.py),
// поэтому клик по примеру открывает готовый ответ.
const FALLBACK_EXAMPLES = [
  "технология многослойного графена",
  "микрофлюидные чипы",
  "твердотельные аккумуляторы",
  "газлифт в газоконденсатных скважинах",
  "перспективные решения в финтехе",
];

// Глубина поиска: число проверяемых кандидатов. Время — по замерам: ~2 мин на сбор и ~7 с на кандидата.
const DEFAULT_DEPTH = 35;
const depthMinutes = (n: number) => Math.round(2 + (n * 7) / 60);

const STATUS_RU: Record<string, string> = { queued: "в очереди", running: "выполняется", done: "готово", failed: "ошибка", rejected: "отклонён" };

export default function Home() {
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [watch, setWatch] = useState(false);
  const [depth, setDepth] = useState(DEFAULT_DEPTH);
  const [err, setErr] = useState("");
  const [runs, setRuns] = useState<Run[]>([]);
  const [ready, setReady] = useState<Showcase[]>([]);
  const [examples, setExamples] = useState<string[]>(FALLBACK_EXAMPLES);
  const nav = useNavigate();

  useEffect(() => {
    api.runs().then(setRuns).catch(() => {});
    api.showcase().then(setReady).catch(() => {});
    api.examples().then((x) => x.length && setExamples(x)).catch(() => {});
  }, []);

  async function start(query: string) {
    if (query.trim().length < 2) return;
    setBusy(true);
    setErr("");
    try {
      const run = await api.search(query.trim(), watch, false, depth === DEFAULT_DEPTH ? undefined : depth);
      nav(`/runs/${run.id}`);
    } catch (e) {
      setErr(String(e));
      setBusy(false);
    }
  }

  return (
    <>
      <section className="discovery-hero">
        <div className="hero-copy">
          <div className="hero-kicker"><span className="coral-dot" /> ТЕХНОЛОГИИ ЗАВТРА. СИГНАЛЫ СЕГОДНЯ.</div>
          <h1>Большие перемены<br />начинаются<br />с <em>тихих сигналов.</em></h1>
          <p className="hero-description">Находите технологии до того, как о них заговорят все. От первой научной статьи — до проверенного сигнала для вашего бизнеса.</p>
          <form className="discovery-search" onSubmit={e=>{e.preventDefault(); start(q);}}>
            <label className="search-input-wrap"><span aria-hidden="true">⌕</span><input value={q} onChange={e=>setQ(e.target.value)} placeholder="Какое направление исследуем?" aria-label="Технологическое направление" maxLength={500} required minLength={2} /></label>
            <button disabled={busy || q.trim().length<2}>{busy ? "Запускаем…" : "Найти сигналы"}<span aria-hidden="true">↗</span></button>
          </form>
          <label className="depth-control">
            <span>Глубина поиска</span>
            <input type="range" min={15} max={60} step={5} value={depth} onChange={(e) => setDepth(Number(e.target.value))} aria-label="Глубина поиска" />
            <b>{depth} кандидатов · ~{depthMinutes(depth)} мин</b>
          </label>
          <div className="query-suggestions"><span>Например</span>{examples.slice(0,3).map(ex=><button key={ex} onClick={()=>setQ(ex)}>{ex}<span>↗</span></button>)}</div>
          <details className="search-options"><summary>Настроить поиск</summary><label><input type="checkbox" checked={watch} onChange={e=>setWatch(e.target.checked)} /> Перепроверить известные сигналы из обучающей выборки. Их оценка не независимая: модель училась на этих примерах.</label></details>
          {err && <div className="error" role="alert">{err}</div>}
          <div className="hero-proof"><span className="proof-symbol">✓</span> Открытые источники <i /> Проверяемые доказательства</div>
        </div>
        <HeroRadar />
      </section>
      <div className="source-ribbon"><span>СВЯЗЫВАЕМ ЗНАНИЯ<br />ИЗ ОТКРЫТЫХ ИСТОЧНИКОВ</span><b>arXiv<span className="coral-text">.</span></b><b>OpenAlex</b><b className="source-serif">Crossref</b><b>GitHub</b><b className="source-serif">Хабр</b><span className="source-more">и другие →</span></div>
      <section className="how-section" aria-labelledby="how-title">
        <div className="section-heading"><div><span className="eyebrow">ОТ ШУМА К СМЫСЛУ</span><h2 id="how-title">Будущее оставляет следы.<br />Мы помогаем их увидеть.</h2></div><Link className="text-link" to="/methodology">Как устроен радар <span>↗</span></Link></div>
        <div className="feature-grid">
          <article className="feature-card"><span className="feature-number">01 / ОБНАРУЖИТЬ</span><Sculpture kind="network" /><h3>Соединяем разрозненное</h3><p>Публикации, разработки и новости складываются в общую картину.</p></article>
          <article className="feature-card"><span className="feature-number">02 / ЗАМЕТИТЬ РОСТ</span><Sculpture kind="growth" /><h3>Ловим начало движения</h3><p>Выделяем ранние технологии и отделяем их от зрелых решений и хайпа.</p></article>
          <article className="feature-card"><span className="feature-number">03 / ПРОВЕРИТЬ</span><Sculpture kind="shield" /><h3>Находим опору в фактах</h3><p>У каждого сигнала — объяснение, оценка и ссылки на первоисточники.</p></article>
        </div>
      </section>

      {ready.length > 0 && (
        <>
          <div className="section-heading"><div><span className="eyebrow">УЖЕ В ПОЛЕ ЗРЕНИЯ</span><h2>Исследования, с которых можно начать</h2></div></div>
          <p className="muted small" style={{ marginTop: -4, marginBottom: 14 }}>
            Темы-примеры посчитаны заранее и открываются за секунду, дата расчёта указана. Новая тема считается с нуля за 4–6 минут, предварительные находки видны по ходу;
            кнопка «Пересчитать» на странице результата запускает расчёт заново.
          </p>
          <div className="index-list">
            {ready.map((r, i) => (
              <Link key={r.run_id} to={`/runs/${r.run_id}`} className="index-row">
                <span className="index-n">{String(i + 1).padStart(2, "0")}</span>
                <span className="index-q">{r.query}</span>
                <span className="index-meta">{r.date ? `расчёт ${new Date(r.date).toLocaleDateString("ru-RU")}` : ""}</span>
                <span className="index-count">{r.signals}<small>сигналов</small></span>
              </Link>
            ))}
          </div>
        </>
      )}

      <div className="section-heading history-heading"><div><span className="eyebrow">ВАШИ ИССЛЕДОВАНИЯ</span><h2>История поиска</h2></div></div>
      {runs.length === 0 ? (
        <div className="history-empty"><span>↗</span><div><b>Первое открытие — впереди</b><p>Введите направление выше. Ваши исследования сохранятся здесь.</p></div></div>
      ) : (
        <div className="tablewrap">
          <table>
            <thead>
              <tr><th>Запрос</th><th>Статус</th><th>Сигналов</th><th>Дата</th></tr>
            </thead>
            <tbody>
              {runs.slice(0, 10).map((r) => (
                <tr key={r.id}>
                  <td><Link to={`/runs/${r.id}`}>{r.query}</Link></td>
                  <td className="mono small">{STATUS_RU[r.status] ?? r.status}{r.status === "running" ? ` · ${r.progress}%` : ""}</td>
                  <td className="mono">{(r.stats?.signals as number) ?? "—"}</td>
                  <td className="muted small mono">{r.created_at ? new Date(r.created_at).toLocaleString("ru-RU") : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
