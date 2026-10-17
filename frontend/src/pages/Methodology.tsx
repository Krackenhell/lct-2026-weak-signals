import { useEffect, useState } from "react";
import { api } from "../api";

const METRIC_RU: Record<string, string> = { precision: "Precision", recall: "Recall", f1: "F1", accuracy: "Accuracy", roc_auc: "ROC-AUC", brier: "Brier (↓)" };
const ABL_RU: Record<string, string> = { numeric_only: "Только наблюдаемые показатели", decision_model_only: "Только ответы decision-модели", all: "Все признаки" };

function MetricsRow({ m }: { m: Record<string, number> }) {
  return (
    <>
      {Object.keys(METRIC_RU).map((k) => (
        <td key={k}>{m?.[k] != null ? m[k].toFixed(3) : "—"}</td>
      ))}
    </>
  );
}

function TimeMachine({ t }: { t: any }) {
  const m = t.metrics;
  if (!m) return null;
  const rows: [string, string][] = [
    ["model_out_of_time", "Историческая модель (проверка «вне времени»)"],
    ["model_out_of_time_without_yc", "Та же модель без признаков YC"],
    ["baseline_growth", "Правило «быстрее рост — перспективнее»"],
    ["baseline_more_grants", "Правило «больше грантов NIH — перспективнее»"],
    ["baseline_more_works", "Правило «больше публикаций — перспективнее»"],
  ];
  const cutoffs = Object.keys(m.cutoffs);
  const prev = t.previous_single_cutoff;
  return (
    <>
      <h2>«Машина времени 2.0»: {m.n} тем, срезы {cutoffs.join(", ")}</h2>
      <p className="muted small">
        Признаки каждой темы посчитаны строго на 1 января года среза: публикации OpenAlex, гранты NIH, стартапы Y Combinator из наборов до среза,
        GitHub, Hacker News, Википедия. Модель учится на темах одних лет среза и предсказывает темы года, которого не видела.
        Стали трендом к 2026 году: {m.n_trend} из {m.n}. Разметка экспертная, открыта ниже.
        {prev && <> Прежняя проверка (один срез 2021, {prev.n} тем, модель на данных 2026 года): AUC {prev.model_roc_auc}; новая модель на том же срезе — {m.model_out_of_time.by_cutoff["2021"]}.</>}
      </p>
      <div className="tablewrap">
        <table>
          <thead><tr><th>Способ</th><th>ROC-AUC [95% ДИ]</th><th>Точность в топ-{m.n_trend}</th>{cutoffs.map((c) => <th key={c}>{c}</th>)}</tr></thead>
          <tbody>
            {rows.map(([key, label]) => m[key] && (
              <tr key={key}>
                <td>{label}</td><td>{m[key].roc_auc} [{m[key].ci95[0]}–{m[key].ci95[1]}]</td><td>{m[key].precision_at_k}</td>
                {cutoffs.map((c) => <td key={c}>{m[key].by_cutoff?.[c] ?? "—"}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted small">
        Все опробованные варианты модели (без выбора лучшего задним числом): {Object.entries(t.variants_tried || {}).map(([k, v]) => `${k} — ${v}`).join("; ")}.
        Главные признаки: {(t.weights_all_data || []).slice(0, 4).map((w: any) => `${w.label} (${w.weight > 0 ? "+" : ""}${w.weight})`).join(", ")}.
        Ограничение: темы выбраны задним числом (известные успехи и провалы), поэтому реальная задача сложнее.
      </p>
      <details className="small">
        <summary>Все темы, срезы, оценки и разметка</summary>
        <table>
          <thead><tr><th>Тема</th><th>Срез</th><th>Оценка «вне времени»</th><th>Итог к 2026</th><th>Пояснение</th></tr></thead>
          <tbody>
            {t.results.map((r: any) => (
              <tr key={r.phrase}>
                <td>{r.phrase}</td><td>{r.cutoff}</td><td>{r.p_out_of_time != null ? `${Math.round(r.p_out_of_time * 100)}%` : "—"}</td>
                <td>{r.label ? <span className="badge high">стало трендом</span> : <span className="badge neutral">ниша / заглохло</span>}</td>
                <td className="muted">{r.note}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </>
  );
}

function Backtest({ b }: { b: any }) {
  const m = b.metrics;
  if (!m) {
    return (
      <>
        <h2>«Машина времени»: ретроспективная проверка</h2>
        <div className="panel small">
          Проверка на срезе {b.cutoff} не завершена: по {b.incomplete} из {b.results.length} тем недоступны ряды публикаций OpenAlex.
          Без истории публикаций модель видела бы «нет данных» вместо прошлого темы, поэтому метрики не публикуются.
          Запуск с ключом: <code>python -m app.ml.backtest</code>.
        </div>
      </>
    );
  }
  const k = m.n_trend;
  const rows: [string, string][] = [["model", "Наша модель (наблюдаемые показатели)"], ["baseline_more_works", "Правило «больше публикаций — перспективнее»"], ["baseline_growth", "Правило «быстрее рост — перспективнее»"]];
  return (
    <>
      <h2>«Машина времени»: ретроспективная проверка</h2>
      <p className="muted small">
        Система смотрит на {m.n} тем «глазами» {b.cutoff}: данные после этой даты отрезаны. Затем сравниваем с тем, что стало трендом к 2026 году
        ({k} из {m.n}). {b.model}. Разметка «стало трендом» — экспертная, список и критерии открыты ниже.
        {b.incomplete > 0 && <b> Внимание: по {b.incomplete} темам ряды OpenAlex недоступны (нужен ключ) — результат неполный.</b>}
      </p>
      <div className="tablewrap">
        <table>
          <thead><tr><th>Способ</th><th>ROC-AUC</th><th>Точность в топ-{k}</th></tr></thead>
          <tbody>
            {rows.map(([key, label]) => (
              <tr key={key}><td>{label}</td><td>{m[key]?.roc_auc ?? "—"}</td><td>{m[key]?.[`precision_at_${k}`] ?? "—"}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
      <details className="small">
        <summary>Все темы, оценки модели на {b.cutoff} и разметка</summary>
        <table>
          <thead><tr><th>Тема</th><th>Вероятность на срезе</th><th>Работ к срезу</th><th>Итог к 2026</th><th>Пояснение</th></tr></thead>
          <tbody>
            {b.results.map((r: any) => (
              <tr key={r.phrase}>
                <td>{r.phrase}</td><td>{Math.round(r.p * 100)}%</td><td>{r.works_at_cutoff}</td>
                <td>{r.label ? <span className="badge high">стало трендом</span> : <span className="badge neutral">ниша / заглохло</span>}</td>
                <td className="muted">{r.note}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </>
  );
}

export default function Methodology() {
  const [info, setInfo] = useState<any>(null);
  const [fb, setFb] = useState<any>(null);
  useEffect(() => {
    api.model().then(setInfo).catch(() => {});
    api.feedbackStats().then(setFb).catch(() => {});
  }, []);
  const m = info?.metrics;

  return (
    <div className="report">
      <h1>Методология и качество модели</h1>

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>Как система понимает, что это слабый сигнал</h3>
        <ol>
          <li><b>Поиск.</b> Запрос расширяется до 10–12 подтем; по ним собираются свежие препринты (arXiv), научные работы (OpenAlex), мировые и российские новости (GDELT), русскоязычные статьи Хабра.</li>
          <li><b>Кандидаты.</b> Из документов извлекаются названия конкретных технологий (LLM по тексту документов и статистический майнинг терминов), дубли и синонимы склеиваются.</li>
          <li><b>Доказательства.</b> По каждому кандидату отдельно собираются: годовая динамика публикаций, свежие препринты, новые репозитории GitHub, обсуждения инженеров, наличие и популярность статьи в Википедии, новости.</li>
          <li><b>Признаки.</b> Decision-модель (Jev / Kev) отвечает на 10 атомарных вопросов по тексту доказательств: конкретная ли это технология, есть ли массовое внедрение, рынок с лидерами, стандарт, ранняя стадия, независимые участники, маркетинговый шум, новизна, преимущество, уровень зрелости.</li>
          <li><b>Классификатор.</b> Собственная логистическая регрессия на 22 признаках, обученная на датасете организатора и нашей выборке отрицательных примеров, выдаёт вероятность слабого сигнала и вклад каждого признака.</li>
          <li><b>Фильтры исключения.</b> Явные правила отсекают нерелевантное (и к теме, и к исходной формулировке запроса), общие области, стандарты, зрелые технологии, хайп и кандидатов без независимых подтверждений. Каждое исключение сопровождается причиной.</li>
          <li><b>Паспорт доказательств.</b> Decision-модель отдельно проверяет каждый найденный документ: действительно ли он об этой технологии, — и определяет самое твёрдое событие (статья, прототип, грант, пилот, релиз, раунд). Меньше 3 подтверждённых документов из 2+ источников — кандидат уходит в «Наблюдать», какой бы высокой ни была вероятность.</li>
          <li><b>Досье и перекрёстная проверка.</b> GigaChat пишет русскую справку только по найденным документам; каждое фактическое утверждение затем проверяет decision-модель, неподтверждённое удаляется, цитаты сверяются с источником дословно.</li>
          <li><b>Запас прочности и окно для России.</b> Для каждого сигнала — что станет с вероятностью без самого сильного довода «за» (точный пересчёт линейной модели) и есть ли технология в русскоязычных источниках при активности в мире.</li>
          <li><b>Проверка запроса.</b> На запрос, не являющийся технологическим направлением («Привет»), система честно отказывает, а не выдаёт уверенный список.</li>
        </ol>
      </div>

      <h2>Качество на датасете (этап 1)</h2>
      {!m ? (
        <p className="muted">Модель ещё не обучена: запустите <code>python -m app.ml.train</code>.</p>
      ) : (
        <>
          <p className="muted small">
            Положительные примеры: {m.n_pos} слабых сигналов организатора. Отрицательные: {m.n_neg} — зрелые технологии, стандарты,
            хайп и общие области (наш набор). Оценка — 5-кратная стратифицированная кросс-валидация, порог 0.5. Decision-модель при обучении: <b>{m.provider}</b>.
          </p>
          {m.dropped_no_evidence && (
            <div className="panel small">
              <b>Честная оценка.</b> В обучение и проверку входят только примеры с научной историей ({m.evidence_rule ?? `не меньше ${m.min_docs} документов`}):
              {" "}{m.n} из {m.reference_all_rows?.n}; без неё остались {m.dropped_no_evidence?.pos} сигналов и {m.dropped_no_evidence?.neg} отрицательных.
              Иначе модель училась бы правилу «ничего не нашли — значит сигнал».
              <div style={{ marginTop: 8 }}>
                F1 = <b>{m.cv5.f1}</b>, 95% интервал <b>{m.cv5_ci95?.f1?.join(" – ")}</b>; precision {m.cv5_ci95?.precision?.join(" – ")}; recall {m.cv5_ci95?.recall?.join(" – ")}.
                Повтор 5×{m.cv5_repeated?.repeats}: F1 {m.cv5_repeated?.f1_mean} ± {m.cv5_repeated?.f1_std}.
              </div>
              <div className="muted" style={{ marginTop: 6 }}>
                Для сравнения, прежний способ (все {m.reference_all_rows?.n} примеров, включая без доказательств): F1 {m.reference_all_rows?.f1} — завышено.
              </div>
            </div>
          )}
          <div className="tablewrap">
            <table>
              <thead><tr><th>Набор признаков</th>{Object.values(METRIC_RU).map((v) => <th key={v}>{v}</th>)}</tr></thead>
              <tbody>
                {Object.entries(m.ablation || {}).map(([k, v]: [string, any]) => (
                  <tr key={k}><td>{ABL_RU[k] ?? k}</td><MetricsRow m={v} /></tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="small">
            Сигналов с уверенностью ≥ 75%: {Math.round((m.confident_75?.share_of_positives_above_075 ?? 0) * 100)}% от всех положительных,
            точность в этой зоне {Math.round((m.confident_75?.precision_above_075 ?? 0) * 100)}%.
          </p>

          <h3>Перенос на новую область (обучение без области → проверка на ней)</h3>
          <p className="muted small">На область приходится 20–30 примеров, поэтому разброс большой — смотрите интервал F1.</p>
          <div className="tablewrap">
            <table>
              <thead><tr><th>Область</th><th>Примеров (сигналов)</th><th>Результат</th><th>F1</th><th>ROC-AUC</th></tr></thead>
              <tbody>
                {Object.entries(m.leave_one_domain_out || {}).map(([k, v]: [string, any]) => (
                  <tr key={k}>
                    <td>{k}</td>
                    <td>{v.n ?? "—"} ({v.n_pos ?? "—"})</td>
                    <td className="small">
                      {v.too_few
                        ? "мало сигналов в проверке — число не публикуется"
                        : v.errors === 0
                          ? `без ошибок на ${v.n} примерах; с 95% уверенностью доля ошибок не выше ${Math.round(v.error_rate_upper95 * 100)}%`
                          : `ошибок: ${v.errors} из ${v.n}; F1, 95% интервал: ${v.f1_ci95?.join(" – ")}`}
                    </td>
                    <td>{v.too_few || v.errors === 0 ? "—" : v.f1}</td>
                    <td>{v.too_few || v.errors === 0 ? "—" : v.roc_auc}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {m.limitations?.length > 0 && (
            <>
              <h3>Ограничения, о которых честно</h3>
              <div className="panel">
                <ul className="small">{m.limitations.map((l: string, i: number) => <li key={i}>{l}</li>)}</ul>
              </div>
            </>
          )}
        </>
      )}

      {info?.decision_comparison && (
        <>
          <h3>Вклад decision-модели Jev (те же доказательства, 5-кратная кросс-валидация)</h3>
          <p className="muted small">Сравнение посчитано на всех 240 примерах (до исключения примеров без доказательств) — абсолютные значения завышены, важна разница между строками.</p>
          <div className="tablewrap">
            <table>
              <thead><tr><th>Decision-модель</th><th>F1 (все признаки)</th><th>Precision</th><th>ROC-AUC</th><th>F1 (только ответы модели)</th></tr></thead>
              <tbody>
                {[["Словарные правила", info.decision_comparison.heuristic_rules], ["Jev (TypeSafe)", info.decision_comparison.jev]].map(([n, v]: any) => (
                  <tr key={n}><td>{n}</td><td>{v.cv5.f1}</td><td>{v.cv5.precision}</td><td>{v.cv5.roc_auc}</td><td>{v.decision_model_only.f1}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {info?.live_eval?.runs?.length > 0 && (
        <>
          <h2>Живые запросы (этап 2)</h2>
          <p className="muted small">
            Для областей датасета — сколько сигналов организатора оказалось в топ-15. «Только обнаружение» — без базы отслеживания:
            система находит их сама в открытых источниках.
          </p>
          <div className="tablewrap">
            <table>
              <thead><tr><th>Запрос</th><th>Режим</th><th>Время</th><th>Сигналов</th><th>Доказательства A / B</th><th>Наблюдать</th><th>Из датасета в топ-15</th><th>Новых кандидатов</th></tr></thead>
              <tbody>
                {info.live_eval.runs.map((r: any, i: number) => (
                  <tr key={i}>
                    <td><a href={`/runs/${r.run_id}`}>{r.query}</a></td>
                    <td className="small">{r.status === "rejected" ? "запрос отклонён" : r.mode}</td>
                    <td className="small">{r.seconds ? `${Math.round(r.seconds / 60)} мин` : "—"}</td>
                    <td>{r.n_signals}</td>
                    <td>{r.passport ? `${r.passport.A ?? 0} / ${r.passport.B ?? 0}` : "—"}</td>
                    <td>{r.watch ?? "—"}</td>
                    <td>{r.dataset_hits_in_top15 != null ? `${r.dataset_hits_in_top15} из ${r.dataset_signals_in_domain}` : "—"}</td>
                    <td>{r.new_candidates_in_top}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {info?.timemachine && <TimeMachine t={info.timemachine} />}
      {info?.backtest && <Backtest b={info.backtest} />}

      {info?.sources_check && (
        <>
          <h2>Проверка источников</h2>
          <p className="muted small">
            Живой опрос всех источников {info.sources_check.date} по запросам «{info.sources_check.query_en}» и «{info.sources_check.query_ru}»
            (<code>python -m scripts.check_sources</code>). Недоступный источник не ломает запрос — он попадает в замечание.
          </p>
          <div className="tablewrap">
            <table>
              <thead><tr><th>Источник</th><th>Статус</th><th>Записей</th><th>Время, с</th></tr></thead>
              <tbody>
                {info.sources_check.sources.map((s: any) => (
                  <tr key={s.source}>
                    <td>{s.source}</td>
                    <td>{s.ok ? <span className="badge high">отвечает</span> : <span className="badge low" title={s.error}>{s.error}</span>}</td>
                    <td>{s.records ?? "—"}</td>
                    <td>{s.seconds}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {fb && fb.total > 0 && (
        <>
          <h2>Оценки аналитиков</h2>
          <div className="panel small">
            Всего оценок: <b>{fb.total}</b> — {Object.entries(fb.by_verdict).map(([k, v]) => `${fb.labels[k]}: ${v}`).join(", ")}.
            {fb.agreement != null && <> Согласие аналитиков с системой: <b>{Math.round(fb.agreement * 100)}%</b>.</>}
            <div className="muted" style={{ marginTop: 6 }}>
              Оценки сохраняются со снимком признаков и используются при дообучении: <code>python -m app.ml.train --refit --with-feedback</code>.
            </div>
          </div>
        </>
      )}

      {info?.weights?.length > 0 && (
        <>
          <h2>Веса признаков (интерпретация модели)</h2>
          <div className="panel">
            <p className="muted small">Положительный вес — признак повышает вероятность слабого сигнала; отрицательный — указывает на зрелость или шум.</p>
            <table>
              <tbody>
                {info.weights.map((w: any) => (
                  <tr key={w.feature}>
                    <td className="small">{w.label}</td>
                    <td className="small" style={{ color: w.weight >= 0 ? "var(--good)" : "var(--bad)", fontWeight: 700 }}>{w.weight > 0 ? "+" : ""}{w.weight}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {m?.errors?.length > 0 && (
        <>
          <h2>Ошибки модели на кросс-валидации</h2>
          <p className="muted small">Показываем честно, где модель ошибается — это ориентир для доработки.</p>
          <div className="tablewrap">
            <table>
              <thead><tr><th>Пример</th><th>Истинный класс</th><th>Вероятность</th></tr></thead>
              <tbody>
                {m.errors.slice(0, 15).map((e: any, i: number) => (
                  <tr key={i}><td className="small">{e.name}</td><td className="small">{e.label ? "слабый сигнал" : `не сигнал (${e.code})`}</td><td className="small">{e.p}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
