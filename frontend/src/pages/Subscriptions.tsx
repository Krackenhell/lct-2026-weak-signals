import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, Subscription } from "../api";

export default function Subscriptions() {
  const [subs, setSubs] = useState<Subscription[] | null>(null);
  const [err, setErr] = useState("");

  const load = () => api.subscriptions().then(setSubs).catch((e) => setErr(String(e)));
  useEffect(() => { load(); }, []);

  async function off(id: number) {
    try {
      await api.unsubscribe(id);
      load();
    } catch (e) {
      setErr(String(e));
    }
  }

  return (
    <>
      <h1>Подписки на темы</h1>
      <p className="muted small">
        Тема пересчитывается по расписанию. После каждого расчёта видно, что изменилось: новые сигналы, выпавшие и усилившиеся.
        Усилившиеся — это сигналы, у которых появился патент, раунд, пилот, контракт или закупка либо выросли подтверждения.
        Подписаться можно на странице результата.
      </p>
      {err && <div className="error">{err}</div>}
      {subs && subs.length === 0 && <p className="muted">Подписок пока нет.</p>}
      {subs?.map((s) => (
        <div className="panel" key={s.id}>
          <div className="meta-row">
            <b>{s.query}</b>
            <span className="muted small">раз в {s.every_days} дн. · следующий расчёт {s.next_at ? new Date(s.next_at).toLocaleDateString("ru-RU") : "—"}</span>
            {s.last_run_id && <Link className="small" to={`/runs/${s.last_run_id}`}>последний результат →</Link>}
            <button className="chip" type="button" onClick={() => off(s.id)}>Отписаться</button>
          </div>
          {s.events.length === 0 ? (
            <p className="muted small">Изменений пока нет: первый расчёт по подписке ещё не выполнен.</p>
          ) : (
            <ul className="small">
              {s.events.map((e) => (
                <li key={e.id}>
                  <span className="muted">{new Date(e.created_at).toLocaleDateString("ru-RU")}:</span> {e.summary}{" "}
                  <Link to={`/runs/${e.run_id}`}>открыть</Link>
                </li>
              ))}
            </ul>
          )}
        </div>
      ))}
    </>
  );
}
