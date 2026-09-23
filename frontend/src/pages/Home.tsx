import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, Run } from "../api";

const EXAMPLES = [
  "перспективные решения в финтехе",
  "слабые сигналы в кибербезопасности ИИ",
  "инфраструктура для ИИ",
  "робототехника",
  "edge AI",
  "индустриальный ИИ",
  "энергетика и накопители",
];

const STATUS_RU: Record<string, string> = { queued: "в очереди", running: "выполняется", done: "готово", failed: "ошибка" };

export default function Home() {
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [runs, setRuns] = useState<Run[]>([]);
  const nav = useNavigate();

  useEffect(() => {
    api.runs().then(setRuns).catch(() => {});
  }, []);

  async function start(query: string) {
    if (query.trim().length < 2) return;
    setBusy(true);
    setErr("");
    try {
      const run = await api.search(query.trim());
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
          Введите технологическое направление в свободной форме. Система соберёт свежие научные публикации, препринты,
          новости и сигналы разработчиков, выделит конкретные технологии, отделит зрелые решения, стандарты и хайп и
          сформирует топ-15 слабых сигналов с проверяемыми источниками.
        </p>
        <form
          className="searchbox"
          onSubmit={(e) => {
            e.preventDefault();
            start(q);
          }}
        >
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Например: перспективные решения в финтехе" autoFocus />
          <button disabled={busy || q.trim().length < 2}>{busy ? "Запуск…" : "Найти сигналы"}</button>
        </form>
        <div className="chips">
          {EXAMPLES.map((ex) => (
            <button key={ex} className="chip" type="button" onClick={() => setQ(ex)}>
              {ex}
            </button>
          ))}
        </div>
        {err && <div className="error" style={{ marginTop: 12 }}>{err}</div>}
      </section>

      <h2>Последние запросы</h2>
      {runs.length === 0 ? (
        <p className="muted">Запросов пока нет.</p>
      ) : (
        <div className="tablewrap">
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>Запрос</th>
                <th>Статус</th>
                <th>Сигналов</th>
                <th>Источников</th>
                <th>Дата</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.id}>
                  <td>{r.id}</td>
                  <td><Link to={`/runs/${r.id}`}>{r.query}</Link></td>
                  <td>{STATUS_RU[r.status] ?? r.status}{r.status === "running" ? ` · ${r.progress}%` : ""}</td>
                  <td>{(r.stats?.signals as number) ?? "—"}</td>
                  <td>{(r.stats?.sources_processed as number) ?? "—"}</td>
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
