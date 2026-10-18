import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, CandidateFull, Feedback, pct, prob, VERDICTS } from "../api";
import { ContributionBars, DynamicsBars, LinkBadge, OriginBadge, PassportBadge, RadarBadge, RobustnessBadge, ScoreBadge, TrustBadge, WindowBadge } from "../components/ui";

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
  const [fb, setFb] = useState<Feedback>(null);
  const [fbErr, setFbErr] = useState("");

  useEffect(() => {
    api.candidate(id!).then((x) => { setC(x); setFb(x.feedback ?? null); }).catch((e) => setErr(String(e)));
  }, [id]);

  async function judge(verdict: string) {
    setFbErr("");
    try {
      const r = await api.feedback(id!, verdict);
      setFb({ verdict: r.verdict as Exclude<Feedback, null>["verdict"], label: r.label, comment: "" });
    } catch (e) {
      setFbErr(String(e));
    }
  }

  if (err) return <div className="error">{err}</div>;
  if (!c) return <p className="muted">Загрузка…</p>;

  const d = c.dossier || {};
  const generated = d.generated_by && d.generated_by !== "template";
  // Ответы по отдельным документам (doc_N) показываются в паспорте доказательств, а не в общей таблице.
  const answers = Object.entries(c.answers || {}).filter(([k, a]) => a.value != null && !k.startsWith("doc_") && !k.startsWith("claim_"));
  const p = c.passport;
  const v = d.verification;

  return (
    <article className="report">
      <p className="muted small"><Link to={`/runs/${c.run_id}`}>← К результатам запроса «{c.query}»</Link></p>
      <div className="panel">
        <div className="muted small">Аналитическая справка · {c.status === "signal" ? `слабый сигнал №${c.rank}` : c.status === "watch" ? "наблюдать: мало доказательств" : "исключённый кандидат"}</div>
        <h1>{c.name_ru || c.name}</h1>
        {c.name_ru && <div className="muted">{c.name}</div>}
        <div className="meta-row">
          <ScoreBadge p={c.probability} />
          <RadarBadge r={c.radar} />
          <PassportBadge p={p} />
          <RobustnessBadge r={c.robustness} />
          <WindowBadge w={c.window} />
          <OriginBadge origin={c.origin} />
          <span className="badge neutral">релевантность {prob(c.relevance)}</span>
          {c.methods?.map((m) => <span key={m} className="badge neutral">{m}</span>)}
        </div>
        {c.status !== "signal" && (
          <div className="error" style={{ marginTop: 12 }}><b>{c.exclusion_label}.</b> {c.exclusion_reason}</div>
        )}
        <div className="feedback small" style={{ marginTop: 12 }}>
          <span className="muted">Ваше решение как аналитика:</span>
          {VERDICTS.map(([v, label]) => (
            <button key={v} type="button" className={`chip ${fb?.verdict === v ? "active" : ""}`} onClick={() => judge(v)} aria-pressed={fb?.verdict === v}>
              {label}
            </button>
          ))}
          {fb && <span className="muted">сохранено: «{fb.label}» — войдёт в дообучение модели</span>}
          {fbErr && <span className="error">{fbErr}</span>}
        </div>
        {generated && <p className="small" style={{ marginTop: 12 }}><span className="gen-mark">сгенерировано {d.generated_by} по найденным источникам</span></p>}
        {generated && v && (
          <p className="small" style={{ marginTop: 4 }}>
            {v.by ? (
              <span className="badge high" title="Каждое фактическое утверждение досье проверено decision-моделью по тем же источникам">
                ✓ Перекрёстная проверка {v.by}: подтверждено {v.supported} из {v.checked} утверждений
              </span>
            ) : (
              <span className="badge neutral">{v.note}</span>
            )}
          </p>
        )}
        {SECTIONS.filter(([k]) => d[k]).map(([k, title]) => (
          <div className="section" key={k}>
            <h3>{title}</h3>
            <p>{d[k]}</p>
          </div>
        ))}
        {v && v.removed.length > 0 && (
          <details className="small" style={{ marginTop: 8 }}>
            <summary>Убрано или помечено при проверке ({v.removed.length})</summary>
            <ul>{v.removed.map((r, i) => <li key={i}><span className="muted">{r.why}:</span> {r.text}</li>)}</ul>
          </details>
        )}
      </div>

      {p && (
        <>
          <h2>Паспорт доказательств</h2>
          <div className="panel">
            <div className="meta-row"><PassportBadge p={p} /><span className="small">{p.label}</span></div>
            <table style={{ marginTop: 10 }}>
              <tbody>
                <tr><td className="small">Документов проверено decision-моделью</td><td className="small"><b>{p.checked}</b></td></tr>
                <tr><td className="small">Подтверждают, что речь именно об этой технологии</td><td className="small"><b>{p.confirmed}</b></td></tr>
                <tr><td className="small">Независимых источников (разные сайты; научные работы — каждая отдельно, но не больше 3)</td><td className="small"><b>{p.domains}</b>{p.domain_list.length > 0 && <span className="muted"> — сайты: {p.domain_list.join(", ")}</span>}</td></tr>
                <tr><td className="small">Из них научных / препринтов</td><td className="small"><b>{p.science}</b></td></tr>
                <tr><td className="small">Самое твёрдое событие</td><td className="small"><b>{p.event}</b>{p.hard_event && <span className="badge high" style={{ marginLeft: 6 }}>твёрдое</span>}</td></tr>
                {(p.funding_news || p.grants) ? (
                  <tr><td className="small">Деньги в направлении (подтверждённые документы)</td><td className="small">раунды и сделки: <b>{p.funding_news ?? 0}</b>; госгранты NIH / NSF / UKRI: <b>{p.grants ?? 0}</b></td></tr>
                ) : null}
                {c.startups_by_year && Object.keys(c.startups_by_year).length > 0 && (
                  <tr><td className="small">Стартапы Y Combinator по году набора</td><td className="small">{Object.entries(c.startups_by_year).slice(-5).map(([y, n]) => `${y} — ${n}`).join("; ")}</td></tr>
                )}
                {c.geography && (
                  <tr><td className="small">Где ведутся работы (2 года, OpenAlex)</td><td className="small">
                    {c.geography.top.map((t) => `${t.name} ${Math.round(t.share * 100)}%`).join(", ")}
                    <span className="muted"> · Китай {Math.round(c.geography.china * 100)}%, Россия {(c.geography.russia * 100).toFixed(1)}%</span>
                  </td></tr>
                )}
                {p.links && (
                  <tr><td className="small">Ссылки проверены вживую</td><td className="small">открываются: <b>{p.links.ok}</b>; сайт ограничивает автопроверку: {p.links.restricted}; не открываются (убраны из подтверждений): {p.links.dead}</td></tr>
                )}
              </tbody>
            </table>
            {c.radar && (
              <p className="small">Радар банка: <b>{c.radar.ring}</b> · направление «{c.radar.area}» · горизонт {c.radar.horizon}.</p>
            )}
            <h3>Научные работы по годам</h3>
            <DynamicsBars points={c.dynamics} />
            <p className="muted small">OpenAlex, точная фраза в названии или аннотации; * — год ещё не завершён.</p>
            <p className="muted small">
              Уровни: A — не меньше 5 подтверждённых документов из 3+ источников и наука или пилот; B — не меньше 3 из 2+ источников;
              C — меньше: кандидат уходит в «Наблюдать». Ссылки из датасета организатора подтверждением не считаются.
            </p>
          </div>
        </>
      )}

      {(c.robustness || c.window) && (
        <div className="grid2" style={{ marginTop: 14 }}>
          {c.robustness && (
            <div className="panel">
              <h3 style={{ marginTop: 0 }}>Запас прочности</h3>
              <RobustnessBadge r={c.robustness} />
              <p className="small">{c.robustness.text}</p>
              <p className="muted small">Модель линейная, поэтому пересчёт точный: из суммы вкладов убирается самый сильный довод «за».</p>
            </div>
          )}
          {c.window && (
            <div className="panel">
              <h3 style={{ marginTop: 0 }}>Окно для России</h3>
              <WindowBadge w={c.window} />
              <p className="small">{c.window.text}</p>
              <p className="muted small">
                Мир: научные работы за 2 года (OpenAlex) — {c.window.world}. Россия: упоминания на Хабре и в русскоязычных СМИ (GDELT) — {c.window.ru ?? "нет данных"}.
                {c.window.failed && c.window.failed.length > 0 && ` Недоступно: ${c.window.failed.join(", ")}.`}
              </p>
            </div>
          )}
        </div>
      )}

      <h2>Почему модель указала такую уверенность</h2>
      <div className="panel">
        <div className="gauge">
          <div className="num">{prob(c.probability)}</div>
          <div className="small">{d.confidence_explanation || "Вероятность отнесения к слабым сигналам по классификатору."}</div>
        </div>
        <p className="small">
          <b>Откуда процент.</b> Jev отвечает не «да / нет», а степенью от 0 до 1 на 12 вопросов о текстах (новизна, ранняя стадия,
          массовость, независимые участники…). Логистическая регрессия складывает эти ответы и 11 наблюдаемых показателей
          (рост публикаций, GitHub, обсуждения) с весами, обученными на 205 размеченных примерах, — получается вероятность.
          На примерах, которых модель не видела, она откалибрована: из кандидатов с оценкой 90–100% сигналами оказались 97%.
          Обучающая выборка проще живого поиска, поэтому выше 95% мы не показываем.
        </p>
        {c.score && (
          <p className="small">
            <b>Место в выдаче.</b> Итоговый балл = вероятность × (0,6 + 0,4 × релевантность запросу) ={" "}
            {c.score.probability != null ? `${prob(c.score.probability)} × (0,6 + 0,4 × ${c.score.relevance.toFixed(2)}) = ${c.score.final?.toFixed(3)}` : "—"}.
            Релевантность — меньшая из двух оценок Jev: к теме и к исходной формулировке запроса.
          </p>
        )}
        {c.score && c.score.outside_training.length > 0 && (
          <p className="small"><span className="badge low">оценка ненадёжна</span> Признаки вне диапазона обучающей выборки: {c.score.outside_training.join(", ")}.
            На таких кандидатах модель не проверялась — опирайтесь на паспорт доказательств.</p>
        )}
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
                <tr key={k}><td className="small">{a.label}</td><td className="small"><b>{prob(a.value)}</b></td></tr>
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
              <LinkBadge status={s.link_status} />
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
