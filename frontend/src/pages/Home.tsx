import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, Run, Showcase } from "../api";

// Запасной список, если API недоступен. Основной — GET /api/examples: те же темы рассчитываются заранее (app/examples.py),
// поэтому клик по примеру открывает готовый ответ.
const FALLBACK_EXAMPLES = [
  "технология многослойного графена",
  "микрофлюидные чипы",
  "твердотельные аккумуляторы",
  "газлифт в газоконденсатных скважинах",
  "перспективные решения в финтехе",
];

const STATUS_RU: Record<string, string> = { queued: "в очереди", running: "выполняется", done: "готово", failed: "ошибка", rejected: "отклонён" };

// Экран радара: кольца — зрелость (центр — массовые технологии, край — ранние), отметки — найденные кандидаты.
function RadarScreen() {
  const blips: [number, number, boolean][] = [
    [292, 118, true], [118, 96, false], [86, 254, true], [262, 300, false], [318, 214, false], [170, 330, false], [226, 64, false],
  ];
  return (
    <svg className="radar" viewBox="0 0 400 400" role="img" aria-label="Радар: отметки — найденные ранние технологии">
      <defs>
        <linearGradient id="sweepGrad" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stopColor="currentColor" stopOpacity="0" />
          <stop offset="1" stopColor="currentColor" stopOpacity=".16" />
        </linearGradient>
      </defs>
      <circle className="ring outer" cx="200" cy="200" r="190" />
      <circle className="ring" cx="200" cy="200" r="140" />
      <circle className="ring" cx="200" cy="200" r="90" />
      <circle className="ring" cx="200" cy="200" r="40" />
      <line className="axis" x1="10" y1="200" x2="390" y2="200" />
      <line className="axis" x1="200" y1="10" x2="200" y2="390" />
      <g className="sweep">
        <path className="sweep-fill" d="M200 200 L200 10 A190 190 0 0 1 364.5 105 Z" />
        <line x1="200" y1="200" x2="364.5" y2="105" stroke="currentColor" strokeWidth="1.5" />
      </g>
      {blips.map(([x, y, hot], i) =>
        hot ? (
          <g key={i}>
            <circle className="blip-ring" cx={x} cy={y} r="7" style={{ animationDelay: `${i * 0.7}s` }} />
            <circle className="blip" cx={x} cy={y} r="5" />
          </g>
        ) : (
          <circle key={i} className="blip-dim" cx={x} cy={y} r="3" />
        )
      )}
      <text x="206" y="196">МАССОВЫЕ</text>
      <text x="206" y="106">РАСТУЩИЕ</text>
      <text x="206" y="56">РАННИЕ</text>
    </svg>
  );
}

export default function Home() {
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [watch, setWatch] = useState(false);
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
      const run = await api.search(query.trim(), watch);
      nav(`/runs/${run.id}`);
    } catch (e) {
      setErr(String(e));
      setBusy(false);
    }
  }

  return (
    <>
      <section className="hero">
        <div>
          <div className="eyebrow"><span className="dot">●</span> Поиск зарождающихся технологий в открытых источниках</div>
          <h1>Заметить технологию <em>до того,</em> как она станет трендом</h1>
          <p className="lead">
            Введите направление — широкое («финтех») или узкое («микрофлюидные чипы»). Радар соберёт научные работы, патенты, гранты,
            стартапы и новости, отберёт до 15 технологий, которые только начинают расти, и для каждой покажет доказательства и путь
            от науки до рынка.
          </p>
          <form
            className="searchbox"
            onSubmit={(e) => {
              e.preventDefault();
              start(q);
            }}
          >
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Например: технологии многослойного графена" aria-label="Технологическое направление" autoFocus />
            <button disabled={busy || q.trim().length < 2}>{busy ? "Запуск…" : "Найти сигналы →"}</button>
          </form>
          <div className="eyebrow examples-label">Примеры запросов</div>
          <div className="chips">
            {examples.map((ex) => (
              <button key={ex} className="chip" type="button" onClick={() => setQ(ex)}>
                {ex}
              </button>
            ))}
          </div>
          <details className="small muted" style={{ marginTop: 14 }}>
            <summary>Дополнительно</summary>
            <label style={{ display: "flex", gap: 8, alignItems: "flex-start", marginTop: 8 }}>
              <input type="checkbox" checked={watch} onChange={(e) => setWatch(e.target.checked)} style={{ marginTop: 4 }} />
              Перепроверить известные сигналы из обучающей выборки (режим мониторинга). Их оценка не независимая: модель училась на этих
              примерах. По умолчанию — поиск только в открытых источниках.
            </label>
          </details>
          {err && <div className="error" style={{ marginTop: 12 }}>{err}</div>}
        </div>
        <RadarScreen />
      </section>

      {ready.length > 0 && (
        <>
          <h2>Готовые результаты</h2>
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

      <h2>Последние запросы</h2>
      {runs.length === 0 ? (
        <p className="muted">Запросов пока нет.</p>
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
