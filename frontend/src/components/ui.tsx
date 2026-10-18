import { Passport, Predictor, prob, Radar, Robustness, RussiaWindow, YearPoint } from "../api";

export function RadarBadge({ r }: { r?: Radar | null }) {
  if (!r) return null;
  const cls = r.ring === "Пилотировать" ? "high" : r.ring === "Изучать" ? "med" : "neutral";
  return <span className={`badge ${cls}`} title={`Направление банка: ${r.area}; горизонт: ${r.horizon}`}>{r.ring} · {r.area}</span>;
}

const LINK_RU: Record<string, [string, string]> = {
  ok: ["ссылка проверена", "high"],
  restricted: ["сайт ограничивает автопроверку", "neutral"],
  dead: ["ссылка не открывается", "low"],
};

export function LinkBadge({ status }: { status?: string | null }) {
  if (!status || !LINK_RU[status]) return null;
  const [label, cls] = LINK_RU[status];
  return <span className={`badge ${cls}`}>{label}</span>;
}

export function DynamicsBars({ points }: { points?: YearPoint[] | null }) {
  if (!points || !points.length) return <p className="muted small">Ряд публикаций недоступен (источник не ответил).</p>;
  const max = Math.max(1, ...points.map((p) => p.works));
  return (
    <div className="dyn" role="img" aria-label="Научные работы по годам">
      {points.map((p) => (
        <div className="dyn-col" key={p.year} title={`${p.year}: ${p.works} работ${p.partial ? " (год не завершён)" : ""}`}>
          <div className="dyn-val">{p.works}</div>
          <div className={`dyn-bar ${p.partial ? "partial" : ""}`} style={{ height: `${Math.max(2, (p.works / max) * 100)}%` }} />
          <div className="dyn-year">{p.year}{p.partial ? "*" : ""}</div>
        </div>
      ))}
    </div>
  );
}

export function ScoreBadge({ p }: { p: number | null }) {
  if (p == null) return <span className="badge neutral">—</span>;
  const cls = p >= 0.75 ? "high" : p >= 0.5 ? "med" : "low";
  const label = p >= 0.75 ? "Высокая" : p >= 0.5 ? "Средняя" : "Низкая";
  return <span className={`badge ${cls}`} title="Вероятность слабого сигнала по классификатору">{label} ({prob(p)})</span>;
}

export function PassportBadge({ p }: { p?: Passport | null }) {
  if (!p) return null;
  const cls = p.level === "A" ? "high" : p.level === "B" ? "med" : "low";
  return (
    <span className={`badge ${cls}`} title={`${p.label}. Decision-модель подтвердила ${p.confirmed} из ${p.checked} документов, ${p.domains} разных источника; событие: ${p.event}`}>
      Доказательства {p.level}: {p.confirmed}/{p.checked} · {p.domains} ист.
    </span>
  );
}

export function RobustnessBadge({ r }: { r?: Robustness | null }) {
  if (!r) return null;
  const cls = r.level === "strong" ? "high" : r.level === "stable" ? "med" : "low";
  return <span className={`badge ${cls}`} title={r.text}>Запас прочности: {r.label}</span>;
}

export function WindowBadge({ w }: { w?: RussiaWindow | null }) {
  if (!w) return null;
  const cls = w.status === "open" ? "accent" : w.status === "closing" ? "med" : "neutral";
  return <span className={`badge ${cls}`} title={w.text}>Россия: {w.label}</span>;
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
