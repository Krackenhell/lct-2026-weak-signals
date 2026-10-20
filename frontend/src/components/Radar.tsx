import { lazy, Suspense, useState } from "react";
import type { LiveDocument, LiveFeed, RunFull } from "../api";
import type { SceneKind } from "./RadarScene";

const Scene = lazy(() => import("./RadarScene"));
export function Sculpture({ kind }: { kind: SceneKind }) {
  return <div className="sculpture"><Suspense fallback={<div className="scene-placeholder" />}><Scene kind={kind} /></Suspense></div>;
}

export function HeroRadar() {
  return <div className="hero-radar">
    <div className="radar-coordinate coordinate-top">ОТ ИДЕИ — К ОТКРЫТИЮ</div>
    <Suspense fallback={<div className="scene-placeholder" />}><Scene decorative /></Suspense>
    <div className="glass-note note-science"><span className="note-icon">↗</span><div><small>НАУКА</small><strong>Начало большого тренда</strong></div></div>
    <div className="glass-note note-source"><i className="coral-dot" /><div><small>ДОКАЗАТЕЛЬСТВА</small><strong>У каждой находки — источник</strong></div></div>
    <div className="radar-coordinate coordinate-bottom"><span className="tiny-cross">+</span> СЛАБЫЙ СИГНАЛ. СИЛЬНАЯ ИДЕЯ.</div>
  </div>;
}

// Та же раскладка, что в RadarScene.pointPosition (золотой угол), но в процентах плоского диска: точка стоит на месте
// с первого кадра и без WebGL; 3D-сцена затем уточняет координаты с учётом наклона.
function flatPosition(id: number) {
  const angle = id * 2.399963;
  const radius = (.62 + ((id * 37) % 100) / 100 * 1.23) / 2.14 * 34;
  return { left: `${50 + Math.cos(angle) * radius}%`, top: `${44 + Math.sin(angle) * radius * .55}%` };
}

export function safeSourceUrl(url: string) {
  try { const u = new URL(url); return ["https:", "http:"].includes(u.protocol) ? u.href : undefined; }
  catch { return undefined; }
}
const TYPE: Record<string,string> = { science:"Публикация",preprint:"Препринт",news:"Новость",patent:"Патент",repository:"Репозиторий",community:"Сообщество",grant:"Грант" };

export function SearchRadar({ run, connectionIssue }: { run: RunFull; connectionIssue?: string }) {
  const feed = run.stats.live as LiveFeed | undefined;
  const docs = feed?.documents ?? [];
  const [selectedId, select] = useState<number | null>(null);
  const [paused, setPaused] = useState(false);
  const selected = docs.find(d=>d.id===selectedId) ?? docs.at(-1);
  const running = run.status === "running";
  const latest = docs.slice(-12);
  const points = selected && !latest.some(d=>d.id===selected.id) ? [...latest.slice(-11), selected] : latest;
  const progress = Math.max(0,Math.min(100,run.progress || 0));
  const sourceLabel = (d: LiveDocument) => TYPE[d.source_type] ?? "Материал";
  return <section className="search-observatory" aria-label="Поиск источников в реальном времени">
    <div className="observatory-visual">
      <div className="observatory-top"><span className={`live-label ${connectionIssue ? "reconnecting" : ""}`}><i />{connectionIssue ? "Восстанавливаем связь" : run.status==="queued" ? "В очереди" : "Сканируем источники"}</span>
        <button className="motion-toggle" onClick={()=>setPaused(!paused)} aria-pressed={paused} aria-label={paused ? "Включить анимацию радара" : "Приостановить анимацию радара"}>{paused ? "▷" : "Ⅱ"}</button></div>
      <div className={`live-radar-model ${paused ? "motion-paused" : ""}`}>
        <Suspense fallback={<div className="scene-placeholder" />}><Scene active={running} paused={paused} pointIds={points.map(d=>d.id)} /></Suspense>
        {points.map(d=><button key={d.id} data-radar-point={d.id} style={flatPosition(d.id)} className={`radar-point ${selected?.id===d.id ? "selected" : ""}`} onClick={()=>select(d.id)} aria-label={`${d.source_name}: ${d.title}`} title={d.title}><span /><span className="point-label">{d.source_name}</span></button>)}
      </div>
      {selected ? <a className="radar-selected" href={safeSourceUrl(selected.url)} target="_blank" rel="noopener noreferrer">
        <span className="eyebrow"><i className="coral-dot" />{sourceLabel(selected)} · {selected.source_name}</span>
        <strong>{selected.title}</strong><span className="selected-arrow">↗</span>
      </a> : <div className="radar-waiting">{run.status==="queued" ? "Поиск начнётся, когда освободится очередь" : "Настраиваем радар на ваше направление"}<span>Здесь появятся первые найденные материалы</span></div>}
      <div className="scan-counts"><span><b>{feed?.total ?? 0}</b> материалов найдено</span><span><b>{feed?.source_count ?? 0}</b> уникальных источников</span></div>
    </div>
    <div className="observatory-feed">
      <div className="feed-heading"><div><span className="eyebrow">ПОИСК В ПРЯМОМ ЭФИРЕ</span><h2>Находки на радаре</h2></div><span className="feed-count">{feed?.total ?? 0}</span></div>
      <div className="scan-stage"><div><span>{run.stage || "Готовим поиск"}</span><b>{progress}%</b></div>
        <div className="progress" role="progressbar" aria-valuenow={progress} aria-valuemin={0} aria-valuemax={100} aria-label="Прогресс анализа"><div style={{width:`${progress}%`}} /></div>
      </div>
      <p className="sr-only" role="status">{connectionIssue || `Найдено ${feed?.total ?? 0} материалов. ${run.stage}`}</p>
      <div className="live-feed-list">
        {[...docs].reverse().map(d=><article key={d.id} className={`feed-item ${selected?.id===d.id ? "selected" : ""}`}>
          <button className="feed-dot" aria-label={`Показать на радаре: ${d.title}`} onClick={()=>select(d.id)}>↗</button>
          <div><div className="feed-item-meta"><span>{d.source_name}</span><span>{sourceLabel(d)}</span></div>
            <a href={safeSourceUrl(d.url)} target="_blank" rel="noopener noreferrer">{d.title}</a>
            {d.published && <time dateTime={d.published}>{d.published}</time>}
          </div>
        </article>)}
        {!docs.length && <div className="feed-empty"><div className="empty-orbit"><span /></div><strong>Любое открытие начинается с поиска</strong><p>Собираем публикации и другие материалы.<br />Первые ответы появятся здесь автоматически.</p></div>}
      </div>
      <div className="feed-footnote"><span className="coral-dot" />Это найденные материалы. Проверка и отбор сигналов — следующий этап.{docs.length===60 && " Показаны последние 60."}</div>
    </div>
  </section>;
}
