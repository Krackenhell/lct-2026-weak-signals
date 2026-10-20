import { useEffect, useRef, useState, type MouseEvent, type PointerEvent } from "react";
import { Link } from "react-router-dom";

type Source = { name: string; kind: string; url: string; serif?: boolean; dot?: boolean };

// Источники корпуса (backend/app/collectors, проверка — scripts.check_sources). Ссылки ведут на сами сервисы.
const SOURCES: Source[] = [
  { name: "arXiv", kind: "препринты", url: "https://arxiv.org", dot: true },
  { name: "OpenAlex", kind: "научные статьи", url: "https://openalex.org" },
  { name: "Crossref", kind: "DOI и метаданные", url: "https://www.crossref.org", serif: true },
  { name: "GitHub", kind: "открытый код", url: "https://github.com" },
  { name: "Хабр", kind: "инженерное сообщество", url: "https://habr.com", serif: true },
  { name: "Semantic Scholar", kind: "цитирования", url: "https://www.semanticscholar.org" },
  { name: "Europe PMC", kind: "науки о жизни", url: "https://europepmc.org" },
  { name: "PubMed", kind: "медицина", url: "https://pubmed.ncbi.nlm.nih.gov" },
  { name: "bioRxiv", kind: "препринты биологии", url: "https://www.biorxiv.org" },
  { name: "КиберЛенинка", kind: "российская наука", url: "https://cyberleninka.ru", serif: true },
  { name: "NASA ADS", kind: "физика и астрономия", url: "https://ui.adsabs.harvard.edu" },
  { name: "Lens.org", kind: "патенты мира", url: "https://www.lens.org" },
  { name: "EPO", kind: "европейские патенты", url: "https://www.epo.org" },
  { name: "Роспатент", kind: "российские патенты", url: "https://searchplatform.rospatent.gov.ru", serif: true },
  { name: "ClinicalTrials", kind: "клинические испытания", url: "https://clinicaltrials.gov" },
  { name: "SEC EDGAR", kind: "отчётность компаний", url: "https://www.sec.gov/edgar/search/" },
  { name: "ЕИС", kind: "госзакупки", url: "https://zakupki.gov.ru" },
  { name: "GDELT", kind: "мировые СМИ", url: "https://www.gdeltproject.org" },
  { name: "Hacker News", kind: "технологическое сообщество", url: "https://news.ycombinator.com" },
  { name: "Stack Exchange", kind: "вопросы разработчиков", url: "https://stackexchange.com" },
  { name: "Википедия", kind: "зрелость темы", url: "https://ru.wikipedia.org", serif: true },
  { name: "Brave Search", kind: "веб-поиск", url: "https://search.brave.com" },
];

export function SourceRibbon() {
  const track = useRef<HTMLDivElement>(null);
  const drag = useRef({ active: false, moved: false, x: 0, left: 0 });
  const [edges, setEdges] = useState({ start: true, end: false });
  const [dragging, setDragging] = useState(false);

  const updateEdges = () => {
    const el = track.current;
    if (!el) return;
    setEdges({ start: el.scrollLeft <= 4, end: el.scrollLeft + el.clientWidth >= el.scrollWidth - 4 });
  };

  useEffect(() => {
    updateEdges();
    window.addEventListener("resize", updateEdges);
    return () => window.removeEventListener("resize", updateEdges);
  }, []);

  const page = (dir: 1 | -1) => {
    const el = track.current;
    if (el) el.scrollBy({ left: dir * el.clientWidth * 0.8, behavior: "smooth" });
  };

  // Мышью ленту можно тянуть; тач и тачпад листают её штатной прокруткой.
  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    if (e.pointerType !== "mouse" || e.button !== 0 || !track.current) return;
    drag.current = { active: true, moved: false, x: e.clientX, left: track.current.scrollLeft };
  };
  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    if (!d.active || !track.current) return;
    const dx = e.clientX - d.x;
    if (!d.moved && Math.abs(dx) < 6) return;
    if (!d.moved) { d.moved = true; setDragging(true); }
    track.current.scrollLeft = d.left - dx;
  };
  const endDrag = () => {
    drag.current.active = false;
    setDragging(false);
  };
  // После перетаскивания отпускание кнопки над карточкой не должно открывать ссылку.
  const onClickCapture = (e: MouseEvent<HTMLDivElement>) => {
    if (drag.current.moved) { e.preventDefault(); e.stopPropagation(); drag.current.moved = false; }
  };

  const trackClass = ["source-track", edges.start && "at-start", edges.end && "at-end", dragging && "dragging"].filter(Boolean).join(" ");

  return (
    <div className="source-ribbon">
      <span className="source-label">СВЯЗЫВАЕМ ЗНАНИЯ{" "}<br />ИЗ ОТКРЫТЫХ ИСТОЧНИКОВ</span>
      <button type="button" className="source-nav" onClick={() => page(-1)} disabled={edges.start} aria-label="Предыдущие источники">‹</button>
      <div
        ref={track}
        className={trackClass}
        onScroll={updateEdges}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerLeave={endDrag}
        onClickCapture={onClickCapture}
        role="list"
        aria-label="Источники данных"
      >
        {SOURCES.map((s) => (
          <a key={s.name} role="listitem" className={s.serif ? "source-chip serif" : "source-chip"} href={s.url} target="_blank" rel="noreferrer noopener" draggable={false} title={`${s.name} — ${s.kind}`}>
            <b>{s.name}{s.dot && <span className="coral-text">.</span>}</b>
            <small>{s.kind} <span aria-hidden="true">↗</span></small>
          </a>
        ))}
      </div>
      <button type="button" className="source-nav" onClick={() => page(1)} disabled={edges.end} aria-label="Следующие источники">›</button>
      <Link className="source-more" to="/methodology">как используем →</Link>
    </div>
  );
}
