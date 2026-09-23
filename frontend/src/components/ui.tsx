import { Predictor, pct } from "../api";

export function ScoreBadge({ p }: { p: number | null }) {
  if (p == null) return <span className="badge neutral">—</span>;
  const cls = p >= 0.75 ? "high" : p >= 0.5 ? "med" : "low";
  const label = p >= 0.75 ? "Высокая" : p >= 0.5 ? "Средняя" : "Низкая";
  return <span className={`badge ${cls}`}>{label} ({pct(p)})</span>;
}

export function TrustBadge({ level, label }: { level: string; label: string }) {
  const cls = level === "high" ? "high" : level === "medium" ? "med" : "low";
  return <span className={`badge ${cls}`}>Доверие: {label}</span>;
}

export function OriginBadge({ origin }: { origin: string }) {
  return origin === "watchlist" ? (
    <span className="badge neutral" title="Технология из базы отслеживаемых сигналов, перепроверена по живым источникам">из базы отслеживания</span>
  ) : (
    <span className="badge accent" title="Найдена в документах по этому запросу">новый кандидат</span>
  );
}

export function ContributionBars({ items, limit = 12 }: { items: Predictor[]; limit?: number }) {
  const top = items.slice(0, limit);
  const max = Math.max(0.01, ...top.map((i) => Math.abs(i.contribution)));
  return (
    <div className="bars">
      {top.map((i) => {
        const w = (Math.abs(i.contribution) / max) * 50;
        return (
          <div className="bar-row" key={i.feature}>
            <div title={i.feature}>
              {i.label} <span className="muted">= {i.value}</span>
            </div>
            <div className="bar-track">
              <div className="mid" />
              <div className={`bar ${i.contribution >= 0 ? "pos" : "neg"}`} style={{ width: `${w}%` }} />
            </div>
            <div className="bar-val">{i.contribution > 0 ? "+" : ""}{i.contribution.toFixed(2)}</div>
          </div>
        );
      })}
    </div>
  );
}
