import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, CandidateFull, pct } from "../api";
import { ContributionBars, OriginBadge, ScoreBadge, TrustBadge } from "../components/ui";

const SECTIONS: [string, string][] = [
  ["description", "Описание технологии"],
  ["advantage", "Потенциальное преимущество"],
  ["case_example", "Кейс-пример"],
  ["bank_application", "Применение для банка (гипотеза)"],
  ["why_weak_signal", "Почему это слабый сигнал"],
  ["risks", "Риски и неопределённость"],
];

const LANG_RU: Record<string, string> = { en: "английский", ru: "русский", zh: "китайский", de: "немецкий", fr: "французский", ja: "японский" };

export default function Insight() {
  const { id } = useParams();
  const [c, setC] = useState<CandidateFull | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    api.candidate(id!).then(setC).catch((e) => setErr(String(e)));
  }, [id]);

  if (err) return <div className="error">{err}</div>;
  if (!c) return <p className="muted">Загрузка…</p>;

  const d = c.dossier || {};
  const generated = d.generated_by && d.generated_by !== "template";
  const answers = Object.entries(c.answers || {}).filter(([, a]) => a.value != null);

  return (
    <article className="report">
      <p className="muted small"><Link to={`/runs/${c.run_id}`}>← К результатам запроса «{c.query}»</Link></p>
      <div className="panel">
        <div className="muted small">Аналитическая справка · {c.status === "signal" ? `слабый сигнал №${c.rank}` : "исключённый кандидат"}</div>
        <h1>{c.name_ru || c.name}</h1>
        {c.name_ru && <div className="muted">{c.name}</div>}
        <div className="meta-row">
          <ScoreBadge p={c.probability} />
          <OriginBadge origin={c.origin} />
          <span className="badge neutral">релевантность {pct(c.relevance)}</span>
          {c.methods?.map((m) => <span key={m} className="badge neutral">{m}</span>)}
        </div>
        {c.status !== "signal" && (
          <div className="error" style={{ marginTop: 12 }}><b>{c.exclusion_label}.</b> {c.exclusion_reason}</div>
        )}
        {generated && <p className="small" style={{ marginTop: 12 }}><span className="gen-mark">сгенерировано {d.generated_by} по найденным источникам</span></p>}
        {SECTIONS.filter(([k]) => d[k]).map(([k, title]) => (
          <div className="section" key={k}>
            <h3>{title}</h3>
            <p>{d[k]}</p>
          </div>
        ))}
      </div>

      <h2>Почему модель указала такую уверенность</h2>
      <div className="panel">
        <div className="gauge">
          <div className="num">{pct(c.probability)}</div>
          <div className="small">{d.confidence_explanation || "Вероятность отнесения к слабым сигналам по классификатору."}</div>
        </div>
        <p className="muted small">
          Вклад признака = вес логистической регрессии × стандартизованное значение. Зелёные полосы повышают вероятность
          слабого сигнала, красные — понижают.
        </p>
        <ContributionBars items={c.contributions || []} />
      </div>

      <div className="grid2" style={{ marginTop: 14 }}>
        <div className="panel">
          <h3 style={{ marginTop: 0 }}>Ответы decision-модели</h3>
          <table>
            <tbody>
              {answers.map(([k, a]) => (
                <tr key={k}><td className="small">{a.label}</td><td className="small"><b>{pct(a.value)}</b></td></tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="panel">
          <h3 style={{ marginTop: 0 }}>Наблюдаемые показатели</h3>
          <table>
            <tbody>
              <tr><td className="small">Научных работ (OpenAlex)</td><td className="small"><b>{Math.round(Math.expm1(c.features.log_total_works ?? 0))}</b></td></tr>
              <tr><td className="small">Доля работ за 3 года</td><td className="small"><b>{pct(c.features.recent_share)}</b></td></tr>
              <tr><td className="small">Рост публикаций (лог-отношение)</td><td className="small"><b>{(c.features.growth ?? 0).toFixed(2)}</b></td></tr>
              <tr><td className="small">Возраст темы, лет</td><td className="small"><b>{c.features.age_years ?? 0}</b></td></tr>
              <tr><td className="small">Статья в Википедии</td><td className="small"><b>{c.features.wiki_exists ? "есть" : "нет"}</b></td></tr>
              <tr><td className="small">Новых репозиториев GitHub за 12 мес</td><td className="small"><b>{Math.round(Math.expm1(c.features.log_gh_repos_12m ?? 0))}</b></td></tr>
              <tr><td className="small">Обсуждений в сообществе за 12 мес</td><td className="small"><b>{Math.round(Math.expm1(c.features.log_hn_12m ?? 0))}</b></td></tr>
            </tbody>
          </table>
        </div>
      </div>

      <h2>Источники ({c.sources.length})</h2>
      <div className="panel">
        {c.sources.map((s, i) => (
          <div className="source" key={s.id}>
            <div className="title">[{i + 1}] <a href={s.url} target="_blank" rel="noreferrer">{s.title}</a></div>
            <div className="meta-row small">
              <span className="badge neutral">{s.source_type_ru}</span>
              <TrustBadge level={s.trust_level} label={s.trust_level_ru} />
              <span className="muted">{s.source_name}</span>
              <span className="muted">· {s.published || "дата не указана"}</span>
              <span className="muted">· язык: {LANG_RU[s.language] ?? s.language}</span>
            </div>
            <div className="muted small" style={{ marginTop: 4 }}>Критерий доверия: {s.trust_reason}</div>
            {s.summary_ru && (
              <div className="summary">
                {s.summary_ru}
                {s.summary_generated && <span className="gen-mark">автоматическое резюме (LLM)</span>}
              </div>
            )}
          </div>
        ))}
      </div>
    </article>
  );
}
