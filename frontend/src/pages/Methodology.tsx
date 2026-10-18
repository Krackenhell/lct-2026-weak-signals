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
        <h3 style={{ marginTop: 0 }}>Этапы обработки и роль каждой модели</h3>
        <p className="small muted">
          Две модели и собственный код. <b>GigaChat-2</b> (Сбер) работает с текстом: понимает запрос, извлекает названия технологий,
          пишет справку. <b>Jev</b> (decision-модель System One) не пишет текст, а отвечает на вопросы о документах степенью от 0 до 1.
          <b>Решение «сигнал / не сигнал» принимает собственная логистическая регрессия</b>, а не языковая модель; всё остальное — наш код.
        </p>
        <div className="tablewrap">
          <table>
            <thead><tr><th>#</th><th>Этап</th><th>Кто выполняет</th><th>Что получается</th></tr></thead>
            <tbody>
              <tr><td>1</td><td>Проверка запроса</td><td>GigaChat (за 30 с), иначе правила</td><td>отказ на «Привет», мусор, бытовые вопросы — с причиной</td></tr>
              <tr><td>2</td><td>Расширение запроса</td><td>GigaChat + словарь областей</td><td>10–12 узких подтем на английском, фразы на русском и китайском</td></tr>
              <tr><td>3</td><td>Сбор корпуса</td><td>наш код: 30 источников, robots.txt, лимиты, кэш</td><td>400–700 документов: наука, препринты, СМИ, гранты, стартапы</td></tr>
              <tr><td>4</td><td>Кандидаты</td><td>GigaChat (названия по тексту) + наш майнинг терминов</td><td>~150 названий технологий со ссылками на документы; синонимы склеены</td></tr>
              <tr><td>5</td><td>Доказательства по кандидату</td><td>наш код: 15+ источников</td><td>ряд публикаций по годам, свежие работы, раунды, гранты, стартапы, патенты, география</td></tr>
              <tr><td>6</td><td>Вопросы о текстах</td><td>Jev</td><td>12 ответов (новизна, ранняя стадия, массовость, рынок с лидерами…) и проверка каждого документа</td></tr>
              <tr><td>7</td><td>Решение и ранжирование</td><td>наша логистическая регрессия + фильтры</td><td>вероятность, вклад каждого признака, причина каждого исключения</td></tr>
              <tr><td>8</td><td>Паспорт доказательств</td><td>Jev + наши правила</td><td>A/B/C: меньше 3 подтверждённых документов — «Наблюдать»</td></tr>
              <tr><td>9</td><td>Справка</td><td>GigaChat пишет, Jev проверяет каждое утверждение</td><td>неподтверждённое удаляется и показывается отдельно; термины — по глоссарию</td></tr>
              <tr><td>10</td><td>Проверка ссылок, запас прочности, окно для России</td><td>наш код</td><td>мёртвые ссылки убраны; устойчивость вывода; активность в мире и в России</td></tr>
            </tbody>
          </table>
        </div>
        <p className="small">
          <b>Как получается процент и место в выдаче.</b> Ответы Jev (степени от 0 до 1) и 11 наблюдаемых показателей (рост публикаций, GitHub,
          обсуждения…) регрессия складывает с весами, обученными на размеченных примерах, — получается вероятность. Она откалибрована на примерах,
          которых модель не видела (см. «Калибровка» ниже); выше 95% не показываем, потому что живой поиск сложнее обучающей выборки.
          Место в выдаче: <code>вероятность × (0,6 + 0,4 × релевантность)</code>, где релевантность — меньшая из двух оценок Jev: к теме и к исходной формулировке.
        </p>
        <details className="small">
          <summary>Собственные технические решения команды (не обращение к готовой модели)</summary>
          <ul>
            <li>Сборщики 30 источников с общим клиентом: ограничение частоты по сайтам, предохранитель, кэш, повторы; разбор robots.txt с шаблонами * и $.</li>
            <li>Отбор новостей по основам слов (EN/RU) и парам иероглифов (ZH); распознавание раундов, запусков и грантов на трёх языках.</li>
            <li>Статистический майнинг терминов, склейка синонимов, квоты источников при чтении корпуса моделью.</li>
            <li>Признаки по временным рядам публикаций, грантов и стартапов; собственный классификатор с объяснением вклада каждого признака.</li>
            <li>Паспорт доказательств, запас прочности (точный пересчёт линейной модели), окно для России, живая проверка ссылок.</li>
            <li>Глоссарий и проверка калек для русских названий; доверие к источнику по типу и домену издания.</li>
            <li>Машина времени 2.0: 118 тем, 5 дат среза, проверка «вне времени».</li>
          </ul>
        </details>
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

          {m.calibration && (
            <>
              <h3>Калибровка: что значит «80%»</h3>
              <p className="small muted">
                Каждый пример оценён моделью, которая его не видела (5-кратная кросс-валидация). Если бы модель была самоуверенной,
                доля сигналов в группе была бы заметно ниже средней оценки. Подобранная температура калибровки T = {m.calibration.temperature}
                {m.calibration.temperature === 1 ? " — поправка не понадобилась" : ""}; ошибка калибровки (ECE) {m.calibration.ece_after}.
              </p>
              <div className="tablewrap">
                <table>
                  <thead><tr><th>Оценка модели</th><th>Примеров</th><th>Средняя оценка</th><th>Доля сигналов на деле</th></tr></thead>
                  <tbody>
                    {m.calibration.bins.map((b: any) => (
                      <tr key={b.range}><td>{b.range}</td><td>{b.n}</td><td>{Math.round(b.mean_p * 100)}%</td><td>{Math.round(b.share_signals * 100)}%</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="small muted">
                Почему в выдаче не бывает «100%»: обучающие примеры разделяются почти идеально, а живой поиск сложнее — там встречаются кандидаты,
                не похожие ни на один обучающий. Поэтому выше 95% не показываем, а если признаки кандидата вне диапазона обучения, карточка
                помечает оценку как ненадёжную.
              </p>
            </>
          )}

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
