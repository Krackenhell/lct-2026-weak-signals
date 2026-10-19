import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, CandidateFull, CLASSIFIER_HINT, Feedback, fmtScore, pct, prob, SCORE_HINT, VERDICTS } from "../api";
import { ContributionBars, DynamicsBars, LinkBadge, PassportBadge, RobustnessBadge, TrustBadge, WindowBadge } from "../components/ui";

// Порядок разделов справки: сначала что это и почему сигнал, затем пример, польза, применение и риски.
const SECTIONS: [string, string][] = [
  ["description", "Что это"],
  ["why_weak_signal", "Почему это слабый сигнал"],
  ["case_example", "Кейс-пример"],
  ["advantage", "Потенциальное преимущество"],
  ["application", "Где применяется"],
  ["bank_application", "Возможное применение"], // поле прогонов до 19.10
  ["risks", "Риски и неопределённость"],
];

const LANG_RU: Record<string, string> = { en: "английский", ru: "русский", zh: "китайский", de: "немецкий", fr: "французский", ja: "японский" };
const SOURCES_SHOWN = 6;

export default function Insight() {
  const { id } = useParams();
  const [c, setC] = useState<CandidateFull | null>(null);
  const [err, setErr] = useState("");
  const [fb, setFb] = useState<Feedback>(null);
  const [fbErr, setFbErr] = useState("");
  const [allSources, setAllSources] = useState(false);

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
  const answers = Object.entries(c.answers || {}).filter(([k, a]) => a.value != null && !k.startsWith("doc_") && !k.startsWith("claim_"));
  const p = c.passport;
  const v = d.verification;
  const sections = SECTIONS.filter(([k]) => d[k] && !(k === "bank_application" && d.application));
  const sources = allSources ? c.sources : c.sources.slice(0, SOURCES_SHOWN);
  const miss = new Set(c.missing ?? []);
  const NA = (src: string) => <span className="muted">нет данных ({src} недоступен)</span>;
  const level = c.probability == null ? "" : c.probability >= 0.75 ? " · высокая" : c.probability >= 0.5 ? " · средняя" : " · низкая";

  return (
    <article className="report">
      <p className="muted small"><Link to={`/runs/${c.run_id}`}>← К результатам «{c.query}»</Link></p>

      <div className="panel">
        <div className="muted small">
          {c.status === "signal" ? `Слабый сигнал № ${c.rank}` : c.status === "watch" ? "Наблюдать: подтверждений пока мало" : "Не вошёл в топ"}
        </div>
        <h1>{c.name_ru || c.name}</h1>
        {c.name_ru && c.name_ru !== c.name && <div className="muted">{c.name}</div>}
        {c.name_check && <div className="muted small">Русское название не показано: {c.name_check}.</div>}
        {c.in_training && (
          <p className="small"><span className="badge neutral">пример из обучающей выборки</span> Оценка классификатора не является независимой проверкой: модель училась на этом примере.</p>
        )}

        <div className="facts">
          <div className="fact" title={CLASSIFIER_HINT}><div className="label">Оценка классификатора</div><div className="value">{prob(c.probability)}{level}</div></div>
          <div className="fact" title="Счёт выполненных проверок, а не вероятность">
            <div className="label">Проверки доказательств</div>
            <div className="value">{c.checks ? `${c.checks.passed} из ${c.checks.total}` : "—"}{p ? ` · уровень ${p.level}` : ""}</div>
          </div>
          <div className="fact"><div className="label">Стадия</div><div className="value">{c.stage ? `${c.stage.label}, УГТ ${c.stage.trl}` : "—"}</div></div>
          <div className="fact">
            <div className="label">Публикации</div>
            <div className="value">
              {miss.has("openalex") ? "нет данных (OpenAlex недоступен)" : ""}
              {c.first_year ? `с ${c.first_year} г.` : ""}
              {c.growth_x && c.growth_x >= 1.2 ? ` · рост ×${c.growth_x.toLocaleString("ru-RU")} за 2 года` : c.works_2y ? ` · ${c.works_2y} работ за 2 года` : ""}
              {!c.first_year && !c.works_2y && !miss.has("openalex") ? "—" : ""}
            </div>
          </div>
        </div>

        {c.why_early && <p className="small" style={{ marginTop: 10 }}><b>Почему рано.</b> {c.why_early}</p>}
        {c.topic_rel && c.topic_rel.faster >= 1.2 && (
          <p className="small"><b>Относительно темы:</b> растёт в {c.topic_rel.faster.toLocaleString("ru-RU")} раза быстрее темы запроса
            ({Math.round(c.topic_rel.share * 1000) / 10}% её работ).</p>
        )}
        {c.impulse && (
          <p className="small" title="Рост публикаций за 2 года, приглушённый возрастом темы. Проверен на машине времени; на место в выдаче не влияет.">
            <b>Импульс роста:</b> {c.impulse.label}{c.impulse.level ? ` (работ за 4 года: ${c.impulse.works_4y})` : ""}.
          </p>
        )}

        {c.status !== "signal" && c.exclusion_reason && (
          <div className="error" style={{ marginTop: 12 }}><b>{c.exclusion_label}.</b> {c.exclusion_reason}</div>
        )}

        {sections.map(([k, title]) => (
          <div className="section" key={k}>
            <h3>{title}</h3>
            <p>{d[k]}</p>
          </div>
        ))}
        {generated && (
          <p className="small muted" style={{ marginTop: 12 }}>
            Справку написал {String(d.generated_by).split(":").pop()} только по найденным источникам (ссылки [n] — номера источников ниже).
            {v?.by ? ` Каждое фактическое утверждение проверила модель ${v.by.split(":")[0] === "jev" ? "Jev" : v.by}: подтверждено ${v.supported} из ${v.checked}.` : v?.note ? ` ${v.note}` : ""}
          </p>
        )}
        {v && v.removed.length > 0 && (
          <details className="small">
            <summary>Удалено при проверке ({v.removed.length})</summary>
            <ul>{v.removed.map((r, i) => <li key={i}><span className="muted">{r.why}:</span> {r.text}</li>)}</ul>
          </details>
        )}
      </div>

      {c.market?.ladder && (
        <>
          <h2>Путь от науки до рынка</h2>
          <div className="panel">
            <div className="ladder">
              {c.market.ladder.steps.map((s) => (
                <div key={s.key} className={`step ${s.n ? "on" : ""}`} title={s.example ? `${s.example}${s.first_date ? ` (${s.first_date})` : ""}` : "не найдено"}>
                  <div className="step-label">{s.label}</div>
                  <div className="step-val">{s.n ? (s.first_date ? `с ${s.first_date.slice(0, 4)}` : `${s.n}`) : "—"}</div>
                </div>
              ))}
            </div>
            <p className="small">{c.market.ladder.text ?? "Подтверждённых ступеней пока нет."}</p>
            <p className="muted small">
              Каждая ступень заполняется документом, который модель Jev подтвердила как описывающий именно эту технологию: из научных баз,
              грантов, каталога стартапов и открытого веб-поиска (патенты, пилоты, контракты, раунды, российские госзакупки).
            </p>
          </div>
        </>
      )}

      {(c.market?.against?.length || c.players) && (
        <div className="grid2" style={{ marginTop: 8 }}>
          <div className="panel">
            <h3 style={{ marginTop: 0 }}>Доводы «против»</h3>
            {c.market?.against?.length ? (
              <ul className="small">
                {c.market.against.map((a, i) => (
                  <li key={i}><span className="badge low">{a.why}</span> <a href={a.url} target="_blank" rel="noreferrer">{a.title}</a>
                    <span className="muted"> · {a.source}{a.date ? `, ${a.date}` : ""}</span></li>
                ))}
              </ul>
            ) : (
              <p className="small muted">Сообщений о провале, отказе или массовом внедрении не найдено{c.market?.web_checked ? "" : " (веб-поиск для этой карточки не выполнялся)"}.</p>
            )}
            <p className="small muted">Признаки модели «против» — красные полосы в разделе «Почему такая оценка».</p>
          </div>
          {c.players && (
            <div className="panel">
              <h3 style={{ marginTop: 0 }}>Кто работает (2 года)</h3>
              {c.players.institutions.length > 0 && <p className="small">{c.players.institutions.map((x) => `${x.name} (${x.works})`).join(" · ")}</p>}
              <p className="small"><b>Россия:</b> {c.players.russia.length ? c.players.russia.map((x) => `${x.name} (${x.works})`).join(" · ") : "работ российских организаций не найдено"}</p>
              {c.players.companies.length > 0 && (
                <p className="small"><b>Компании:</b> {c.players.companies.map((x) => `${x.name} (${x.kind})`).join(" · ")}</p>
              )}
              <p className="muted small">Число в скобках — научные работы с этим термином (OpenAlex).</p>
            </div>
          )}
        </div>
      )}

      <h2>Почему такая оценка</h2>
      <div className="panel">
        <div className="gauge">
          <div className="num">{prob(c.probability)}</div>
          <div className="small">
            Оценка классификатора: насколько кандидат похож на слабые сигналы из эталона организатора (не вероятность того, что технология
            станет трендом). Зелёные полосы — признаки «за», красные — «против».
            {c.score && c.score.probability != null && (
              <span title={SCORE_HINT}> Балл места: min({prob(c.score.probability)}; 95%) × (0,6 + 0,4 × релевантность {c.score.relevance.toFixed(2).replace(".", ",")}) = <b>{fmtScore(c.score.final)}</b>.</span>
            )}
          </div>
        </div>
        {c.score && c.score.outside_training.length > 0 && (
          <p className="small"><span className="badge med">оценка приблизительная</span> Значения признаков вне диапазона обучающей выборки:
            {" "}{c.score.outside_training.join(", ")}. Ориентируйтесь прежде всего на доказательства.</p>
        )}
        <ContributionBars items={c.contributions || []} intercept={c.score?.intercept} p={c.probability} />
        <details className="small" style={{ marginTop: 10 }}>
          <summary>Как считается оценка</summary>
          <p>
            Модель Jev отвечает на вопросы о найденных текстах не «да / нет», а вероятностью ответа «да» от 0 до 1 (новизна, ранняя стадия,
            массовость, рынок с лидерами и др.). 9 ответов вместе с 9 наблюдаемыми показателями (рост публикаций, возраст темы, Википедия,
            доля науки) — 18 признаков собственной логистической регрессии с весами, обученными на размеченных примерах. Вклад признака = вес ×
            отклонение от среднего; точка отсчёта плюс все вклады дают итог, из которого получается оценка. Оценка откалибрована на примерах,
            которых модель не видела; выше 95% не показывается, потому что живой поиск сложнее обучающей выборки.
          </p>
        </details>
      </div>

      <h2>Динамика публикаций</h2>
      <div className="panel">
        <DynamicsBars points={c.dynamics} />
        <p className="muted small">Научные работы с точной фразой в названии или аннотации (OpenAlex); * — текущий год, данные неполные.</p>
      </div>

      <h2>Источники ({c.sources.length})</h2>
      <div className="panel">
        {sources.map((s, i) => (
          <div className="source" key={s.id}>
            <div className="title">[{i + 1}] <a href={s.url} target="_blank" rel="noreferrer">{s.title}</a></div>
            <div className="meta-row small">
              <span className="badge neutral">{s.source_type_ru}</span>
              <TrustBadge level={s.trust_level} label={s.trust_level_ru} />
              <LinkBadge status={s.link_status} />
              <span className="muted">{s.source_name} · {s.published || "дата не указана"} · {LANG_RU[s.language] ?? s.language}</span>
            </div>
            {s.summary_ru && <div className="summary">{s.summary_ru}</div>}
          </div>
        ))}
        {c.sources.length > SOURCES_SHOWN && (
          <button type="button" className="chip" onClick={() => setAllSources(!allSources)}>
            {allSources ? "Свернуть" : `Показать все (${c.sources.length})`}
          </button>
        )}
      </div>

      {p && (
        <details className="fold">
          <summary>Паспорт доказательств — подробно</summary>
          <div className="panel">
            <div className="meta-row"><PassportBadge p={p} /><span className="small">{p.label}</span></div>
            <table style={{ marginTop: 10 }}>
              <tbody>
                <tr><td className="small">Документов проверено моделью Jev</td><td className="small"><b>{p.checked}</b></td></tr>
                <tr><td className="small">Подтверждают, что речь именно об этой технологии</td><td className="small"><b>{p.confirmed}</b></td></tr>
                <tr><td className="small">Независимых источников</td><td className="small"><b>{p.domains}</b>{p.domain_list.length > 0 && <span className="muted"> — {p.domain_list.join(", ")}</span>}</td></tr>
                <tr><td className="small">Из них научных работ и препринтов</td><td className="small"><b>{p.science}</b></td></tr>
                <tr><td className="small">Самое значимое событие</td><td className="small"><b>{p.event}</b></td></tr>
                {(p.funding_news || p.grants) ? (
                  <tr><td className="small">Финансирование направления</td><td className="small">раунды и сделки: <b>{p.funding_news ?? 0}</b>; гранты NIH / NSF / UKRI: <b>{p.grants ?? 0}</b></td></tr>
                ) : null}
                {c.startups_by_year && Object.keys(c.startups_by_year).length > 0 && (
                  <tr><td className="small">Стартапы Y Combinator по году набора</td><td className="small">{Object.entries(c.startups_by_year).slice(-5).map(([y, n]) => `${y} — ${n}`).join("; ")}</td></tr>
                )}
                {c.geography && (
                  <tr><td className="small">Где ведутся работы (2 года)</td><td className="small">
                    {c.geography.top.map((t) => `${t.name} ${Math.round(t.share * 100)}%`).join(", ")}
                  </td></tr>
                )}
                {p.links && (
                  <tr><td className="small">Ссылки проверены при анализе</td><td className="small">открываются: <b>{p.links.ok}</b>; сайт ограничивает проверку: {p.links.restricted}; не открываются (исключены): {p.links.dead}</td></tr>
                )}
              </tbody>
            </table>
            <p className="muted small">
              A — не меньше 5 подтверждённых документов из 3+ источников и научная работа или пилот; B — не меньше 3 из 2+ источников;
              C — меньше: кандидат остаётся под наблюдением.
            </p>
          </div>
        </details>
      )}

      {(c.robustness || c.window) && (
        <details className="fold">
          <summary>Устойчивость вывода и активность в России</summary>
          <div className="panel">
            {c.robustness && (
              <p className="small"><RobustnessBadge r={c.robustness} /> {c.robustness.text}</p>
            )}
            {c.window && (
              <p className="small">
                <WindowBadge w={c.window} /> {c.window.text} Мир: научные работы за 2 года — {c.window.world ?? "нет данных"};
                Россия: упоминания в русскоязычных источниках — {c.window.ru ?? "нет данных"}
                {c.window.terms && c.window.terms.length > 0 ? ` (искали: ${c.window.terms.join(", ")})` : ""}.
              </p>
            )}
          </div>
        </details>
      )}

      <details className="fold">
        <summary>Ответы Jev (вероятность ответа «да», {answers.length} вопросов) и наблюдаемые показатели</summary>
        <div className="panel grid2">
          <table>
            <tbody>
              {answers.map(([k, a]) => (
                <tr key={k}><td className="small">{a.label}</td><td className="small"><b>{prob(a.value)}</b></td></tr>
              ))}
            </tbody>
          </table>
          <table>
            <tbody>
              <tr><td className="small">Научных работ (OpenAlex)</td><td className="small">{miss.has("openalex") ? NA("OpenAlex") : <b>{Math.round(Math.expm1(c.features.log_total_works ?? 0))}</b>}</td></tr>
              <tr><td className="small">Доля работ за 3 года</td><td className="small">{miss.has("openalex") ? NA("OpenAlex") : <b>{pct(c.features.recent_share)}</b>}</td></tr>
              <tr><td className="small">Рост публикаций (лог-отношение)</td><td className="small">{miss.has("openalex") ? NA("OpenAlex") : <b>{(c.features.growth ?? 0).toFixed(2)}</b>}</td></tr>
              <tr><td className="small">Возраст темы, лет</td><td className="small">{miss.has("openalex") ? NA("OpenAlex") : <b>{Math.round(c.features.age_years ?? 0)}</b>}</td></tr>
              <tr><td className="small">Статья в Википедии</td><td className="small">{miss.has("wikipedia") ? NA("Википедия") : <b>{c.features.wiki_exists ? "есть" : "нет"}</b>}</td></tr>
              <tr><td className="small">Новых репозиториев GitHub за 12 мес</td><td className="small">{miss.has("github") ? <span className="muted">не собирался (не входит в модель)</span> : <b>{Math.round(Math.expm1(c.features.log_gh_repos_12m ?? 0))}</b>}</td></tr>
              <tr><td className="small">Обсуждений в инженерном сообществе за 12 мес</td><td className="small"><b>{Math.round(Math.expm1(c.features.log_hn_12m ?? 0))}</b></td></tr>
            </tbody>
          </table>
        </div>
      </details>

      <div className="panel feedback small" style={{ marginTop: 16 }}>
        <span className="muted">Оценка аналитика:</span>
        {VERDICTS.map(([vv, label]) => (
          <button key={vv} type="button" className={`chip ${fb?.verdict === vv ? "active" : ""}`} onClick={() => judge(vv)} aria-pressed={fb?.verdict === vv}>
            {label}
          </button>
        ))}
        {fb && <span className="muted">сохранено — учитывается при дообучении модели</span>}
        {fbErr && <span className="error">{fbErr}</span>}
      </div>
    </article>
  );
}
