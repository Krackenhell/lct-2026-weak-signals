import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, Run, Showcase } from "../api";

const EXAMPLES = [
  "микрофлюидные технологии",
  "технологии многослойного графена",
  "газлифт в газоконденсатных скважинах",
  "перспективные решения в финтехе",
  "кибербезопасность ИИ",
  "робототехника",
  "энергетика и накопители",
];

const STATUS_RU: Record<string, string> = { queued: "в очереди", running: "выполняется", done: "готово", failed: "ошибка", rejected: "отклонён" };

export default function Home() {
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [watch, setWatch] = useState(false);
  const [err, setErr] = useState("");
  const [runs, setRuns] = useState<Run[]>([]);
  const [ready, setReady] = useState<Showcase[]>([]);
  const nav = useNavigate();

  useEffect(() => {
    api.runs().then(setRuns).catch(() => {});
    api.showcase().then(setReady).catch(() => {});
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
      <section className="panel hero">
        <h1>Поиск зарождающихся технологий</h1>
        <p className="muted">
          Введите направление — широкое («финтех») или узкое («микрофлюидные чипы»). Система найдёт до 15 технологий, которые только
          начинают расти, и для каждой покажет основания оценки и проверяемые источники.
        </p>
        <form
          className="searchbox"
          onSubmit={(e) => {
            e.preventDefault();
            start(q);
          }}
        >
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Например: технологии многослойного графена" autoFocus />
          <button disabled={busy || q.trim().length < 2}>{busy ? "Запуск…" : "Найти сигналы"}</button>
        </form>
        <div className="chips">
          {EXAMPLES.map((ex) => (
            <button key={ex} className="chip" type="button" onClick={() => setQ(ex)}>
              {ex}
            </button>
          ))}
        </div>
        <details className="small muted" style={{ marginTop: 10 }}>
          <summary>Дополнительно</summary>
          <label style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 8 }}>
            <input type="checkbox" checked={watch} onChange={(e) => setWatch(e.target.checked)} />
            Режим мониторинга: добавить к поиску известные сигналы из базы отслеживания (по умолчанию — поиск только в открытых источниках)
          </label>
        </details>
        {err && <div className="error" style={{ marginTop: 12 }}>{err}</div>}
      </section>

      {ready.length > 0 && (
        <>
          <h2>Готовые результаты</h2>
          <p className="muted small">
            Посчитаны заранее по типовым темам и открываются сразу; дата расчёта указана. Новые темы и кнопка «Пересчитать» запускают анализ с нуля.
          </p>
          <div className="showcase">
            {ready.map((r) => (
              <Link key={r.run_id} to={`/runs/${r.run_id}`} className="panel showcase-card">
                <b>{r.query}</b>
                <div className="small muted">
                  {r.date ? `расчёт ${new Date(r.date).toLocaleDateString("ru-RU")}` : ""} · сигналов: {r.signals}
                </div>
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
                  <td>{STATUS_RU[r.status] ?? r.status}{r.status === "running" ? ` · ${r.progress}%` : ""}</td>
                  <td>{(r.stats?.signals as number) ?? "—"}</td>
                  <td className="muted small">{r.created_at ? new Date(r.created_at).toLocaleString("ru-RU") : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
