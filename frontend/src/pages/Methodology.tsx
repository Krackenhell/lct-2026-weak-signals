import { useEffect, useState } from "react";
import { api, Forecasts, prob } from "../api";

const METRIC_RU: Record<string, string> = { precision: "Precision", recall: "Recall", f1: "F1", accuracy: "Accuracy", roc_auc: "ROC-AUC", brier: "Brier (↓)" };
const ABL_RU: Record<string, string> = { numeric_only: "Только наблюдаемые показатели", decision_model_only: "Только ответы модели Jev", all: "Все признаки" };

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
    ["model_out_of_time_without_yc", "Та же модель без данных Y Combinator"],
    ["baseline_growth", "Правило «быстрее рост — перспективнее»"],
    ["baseline_more_grants", "Правило «больше грантов NIH — перспективнее»"],
    ["baseline_more_works", "Правило «больше публикаций — перспективнее»"],
  ];
  const cutoffs = Object.keys(m.cutoffs);
  return (
    <>
      <h2>«Машина времени»: {m.n} тем, срезы {cutoffs.join(", ")}</h2>
      <p className="muted small">
        Признаки каждой темы посчитаны строго на 1 января года среза: публикации OpenAlex, гранты NIH, стартапы Y Combinator из наборов до среза,
        GitHub, Hacker News, Википедия. Модель учится на темах одних лет среза и предсказывает темы года, которого не видела.
        Стали массовыми к 2026 году: {m.n_trend} из {m.n}. Разметка экспертная, открыта ниже.
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
                <td>{r.phrase}</td><td>{r.cutoff}</td><td>{prob(r.p_out_of_time)}</td>
                <td>{r.label ? <span className="badge high">стало массовым</span> : <span className="badge neutral">осталось нишевым</span>}</td>
                <td className="muted">{r.note}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </>
  );
}

function ForecastsBlock({ blind }: { blind: any }) {
  const [f, setF] = useState<Forecasts | null>(null);
  useEffect(() => { api.forecasts().then(setF).catch(() => {}); }, []);
  return (
    <>
      <h2>Прогнозы с проверкой</h2>
      <div className="panel small">
        <p>
          <b>Прогноз с проверкой.</b> По каждому сигналу прогноз фиксируется на дату расчёта, а через полгода система сама проверяет,
          сбылся ли он. Критерий записан заранее: {f?.criteria ?? "—"}
        </p>
        {f && (
          <p>
            Зафиксировано прогнозов: <b>{f.total}</b>; ждут срока: {f.pending}
            {f.next_check ? ` (первая проверка — ${new Date(f.next_check).toLocaleDateString("ru-RU")})` : ""}; проверено: {f.checked}
            {f.confirmed_share != null ? `, сбылось ${Math.round(f.confirmed_share * 100)}%` : ""}.
          </p>
        )}
        {blind?.by_variant && <p>
          <b>Слепой замер.</b> Карточки топ-15 нашей системы и ответа «только языковая модель» по темам из отраслей, которых нет в примерах, перемешаны.
          Оценки модели и происхождение скрыты. Люди размечают по рубрике: релевантность, технология, ранняя стадия, русское название.
          «Полезная карточка» — по теме, конкретная технология и не зрелая.
        </p>}
        {blind?.by_variant && (
          <table>
            <thead><tr><th>Вариант</th><th>Карточек</th><th>Полезных</th><th>Доля полезных</th><th>Полезных в топ-15 на тему</th></tr></thead>
            <tbody>
              {Object.entries(blind.by_variant).map(([k, v]: [string, any]) => (
                <tr key={k}><td>{k}</td><td>{v.cards}</td><td>{v.useful}</td><td>{v.useful_share != null ? `${Math.round(v.useful_share * 100)}%` : "—"}</td><td>{v["U@15"] ?? "—"}</td></tr>
              ))}
            </tbody>
          </table>
        )}
        {blind?.kappa_useful != null && <p className="muted">Согласие двух разметчиков (каппа Коэна): {blind.kappa_useful} на {blind.kappa_n} карточках.</p>}
      </div>
    </>
  );
}

function Hypotheses({ info }: { info: any }) {
  const g = info?.gates_h4, e = info?.emergence, ab = info?.ab_plan_model, lb = info?.llm_baseline, np = info?.ab_narrow_plan;
  if (!g && !e && !ab && !lb) return null;
  const main = e?.variants?.["все индикаторы без отбора (заранее заданный вариант)"];
  return (
    <>
      <h2>Проверка гипотез</h2>
      <p className="muted small">Правила принятия каждого решения записаны до прогона; неудачи публикуются наравне с успехами.</p>
      <div className="tablewrap">
        <table>
          <thead><tr><th>Гипотеза</th><th>Результат</th><th>Решение</th></tr></thead>
          <tbody>
            {g && (
              <tr><td>Классификатор без GitHub, HN и признаков с перевёрнутым знаком</td>
                <td>F1 {g.base.f1_repeated} → {g.candidate.f1_repeated}; AUC {g.base.auc} → {g.candidate.auc}; противоречий знаков {g.base.sign_contradictions.length} → {g.candidate.sign_contradictions.length};
                  чувствительность к шуму ответов {g.base.noise_dlogit} → {g.candidate.noise_dlogit}</td>
                <td>{g.passed ? "все критерии выполнены — внедрено" : "критерии не выполнены — не внедрено"}</td></tr>
            )}
            {main && (
              <tr><td>Импульс роста на ретроспективной проверке ({e.n} тем)</td>
                <td>AUC «вне времени» {e.base_auc} → {main.auc} (Δ {main.delta > 0 ? "+" : ""}{main.delta}, 95% ДИ {main.ci95.join("…")}); на малых темах {e.small_topics?.base_auc} → {e.small_topics?.young_growth_auc}</td>
                <td>{e.success ? "подтверждено — показатель «Импульс роста» в карточке" : "отрицательный результат"}</td></tr>
            )}
            {np && (
              <tr><td>План узких запросов без общего словаря областей</td>
                <td>{np.runs.map((r: any) => `${r.query}: ${Math.round(r.old.share * 100)}% → ${Math.round(r.new.share * 100)}%`).join("; ")} документов корпуса по теме</td>
                <td>внедрено</td></tr>
            )}
            {lb && (
              <tr><td>Только языковая модель против нашей системы</td>
                <td>{lb.pairs.map((p: any) => `${p.query}: ${p.llm_only.signals} против ${p.pipeline?.signals ?? "—"} сигналов`).join("; ")}; названий от языковой модели, не прошедших наши проверки, — {Math.round(lb.total.llm_only_excluded_share * 100)}%</td>
                <td>вопрос к языковой модели не заменяет поиск по источникам</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}

export default function Methodology() {  const [info, setInfo] = useState<any>(null);
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
          <b>GigaChat-2</b> (Сбер) работает с текстом: разбирает запрос, извлекает названия технологий, пишет справку.
          <b>Jev</b> (System One) отвечает на вопросы о документах числом от 0 до 1.
          <b> Решение «сигнал / не сигнал» принимает собственная логистическая регрессия.</b>
        </p>
        <div className="tablewrap">
          <table>
            <thead><tr><th>#</th><th>Этап</th><th>Кто выполняет</th><th>Что получается</th></tr></thead>
            <tbody>
              <tr><td>1</td><td>Проверка запроса</td><td>GigaChat, при недоступности — правила</td><td>запросы не по теме отклоняются с причиной</td></tr>
              <tr><td>2</td><td>Расширение запроса</td><td>GigaChat; наше правило «широкий / узкий запрос»</td><td>поисковые фразы и подтемы; для широких тем — проверенный словарь областей</td></tr>
              <tr><td>2б</td><td>Растущие поднаправления</td><td>наш код по OpenAlex</td><td>ключевые слова, доля которых в работах по теме выросла за 2 года, с проверкой специфичности</td></tr>
              <tr><td>3</td><td>Сбор корпуса</td><td>наш код: 30 источников с соблюдением правил сайтов</td><td>400–700 документов: наука, препринты, СМИ, гранты, стартапы; для наук о жизни, материалов и энергетики — ещё Europe PMC</td></tr>
              <tr><td>4</td><td>Кандидаты</td><td>GigaChat (названия по тексту) + статистическое извлечение терминов</td><td>~150 названий технологий со ссылками на документы; синонимы объединены</td></tr>
              <tr><td>5</td><td>Доказательства по кандидату</td><td>наш код: 15+ источников</td><td>ряд публикаций по годам, свежие работы, раунды, гранты, стартапы, патенты, география</td></tr>
              <tr><td>6</td><td>Вопросы о текстах</td><td>Jev</td><td>ответы о новизне, зрелости, массовости и рынке; проверка каждого документа</td></tr>
              <tr><td>7</td><td>Решение и ранжирование</td><td>наша логистическая регрессия + фильтры</td><td>оценка классификатора, вклад каждого признака, балл места, причина каждого исключения</td></tr>
              <tr><td>8</td><td>Паспорт доказательств</td><td>Jev + наши правила</td><td>A/B/C: меньше 3 подтверждённых документов — «Наблюдать»</td></tr>
              <tr><td>9</td><td>Справка</td><td>GigaChat пишет, Jev проверяет каждое утверждение</td><td>неподтверждённые утверждения удаляются</td></tr>
              <tr><td>10</td><td>Проверка ссылок, запас прочности, окно для России</td><td>наш код</td><td>неработающие ссылки убраны; устойчивость вывода; активность в мире и в России</td></tr>
            </tbody>
          </table>
        </div>
        <h3>Как строится рейтинг</h3>
        <p className="small">
          На карточке два разных числа. <b>Оценка классификатора</b> — насколько кандидат похож на слабые сигналы из эталона организатора;
          это не вероятность того, что технология станет трендом. Её считает наша регрессия по 18 признакам: 9 ответов Jev (вероятность ответа
          «да» на вопросы о новизне, зрелости, рынке и др.) и 9 наблюдаемых показателей (рост публикаций, возраст темы, Википедия, доля науки).
          Оценка откалибрована на примерах, которых модель не видела; выше 95% не показываем. <b>Проверки доказательств: k из 5</b> — счёт
          выполненных проверок (не меньше 5 подтверждённых документов, 3 независимых источника, научная работа, подтверждённое событие (пилот, раунд, патент), рабочие ссылки),
          а не вероятность.
        </p>
        <p className="small">
          <b>Балл места</b> = <code>min(оценка; 0,95) × (0,6 + 0,4 × релевантность)</code>, при равенстве — по оценке. Релевантность — меньшая
          из двух оценок Jev: к теме и к исходной формулировке. Оценки выше 0,95 не различаются, поэтому наверху порядок
          решает релевантность. Кандидаты «Наблюдать» ниже порога и в топ не входят.
        </p>
        <h3>Два режима: готовые ответы и живой поиск</h3>
        <p className="small">
          Темы-примеры с главной страницы (узкие запросы из разных отраслей и два широких направления) рассчитаны заранее и открываются
          за секунду; на странице результата видна дата расчёта и кнопка «Пересчитать». Повторно отдаётся только полный результат той же версии
          системы и моделей. Любой другой запрос считается с нуля за 4–6 минут.
        </p>
        <h3>Модель по задачам</h3>
        <div className="tablewrap">
          <table>
            <thead><tr><th>Задача</th><th>Модель</th><th>Почему</th></tr></thead>
            <tbody>
              <tr><td>Проверка запроса, план поиска</td><td>GigaChat-2</td><td>от плана зависит весь корпус; модель выбрана по результатам сравнения</td></tr>
              <tr><td>Названия технологий, справка, резюме источников</td><td>GigaChat-2</td><td>десятки вызовов: важна скорость; названия проверяются по глоссарию</td></tr>
              <tr><td>Ответы о документах, релевантность, проверка утверждений справки</td><td>Jev</td><td>классификатор обучен на ответах Jev; для признаков модель не меняется</td></tr>
              <tr><td>Решение «сигнал / не сигнал»</td><td>наша логистическая регрессия</td><td>прозрачный вклад каждого признака</td></tr>
            </tbody>
          </table>
        </div>
        <details className="small">
          <summary>Собственные технические решения команды (не обращение к готовой модели)</summary>
          <ul>
            <li>Сборщики 30 источников с общим клиентом: ограничение частоты запросов, защита от сбоев, соблюдение правил сайтов.</li>
            <li>Отбор новостей по основам слов (EN/RU) и парам иероглифов (ZH); распознавание раундов, запусков и грантов на трёх языках.</li>
            <li>Статистическое извлечение терминов, объединение синонимов, квоты источников при чтении корпуса моделью.</li>
            <li>Признаки по временным рядам публикаций, грантов и стартапов; собственный классификатор с объяснением вклада каждого признака.</li>
            <li>Паспорт доказательств, запас прочности (точный пересчёт линейной модели), окно для России, живая проверка ссылок.</li>
            <li>Глоссарий и проверка русских названий; доверие к источнику по типу и домену издания.</li>
            <li>Машина времени: 118 тем, 5 дат среза, проверка «вне времени».</li>
          </ul>
        </details>
      </div>

      <h2>Качество на датасете (этап 1)</h2>
      {!m ? (
        <p className="muted">Модель ещё не обучена.</p>
      ) : (
        <>
          <p className="muted small">
            Положительные примеры: {m.n_pos} слабых сигналов организатора. Отрицательные: {m.n_neg} — зрелые технологии, стандарты,
            темы с завышенными ожиданиями и общие области (наш набор). Оценка — 5-кратная стратифицированная кросс-валидация, порог 0.5.
          </p>
          {m.dropped_no_evidence && (
            <div className="panel small">
              <b>Отбор примеров.</b> В обучение и проверку входят только примеры с научной историей ({m.evidence_rule ?? `не меньше ${m.min_docs} документов`}):
              {" "}{m.n} из {m.reference_all_rows?.n}; без неё остались {m.dropped_no_evidence?.pos} сигналов и {m.dropped_no_evidence?.neg} отрицательных.
              Иначе модель училась бы правилу «ничего не нашли — значит сигнал».
              <div style={{ marginTop: 8 }}>
                F1 = <b>{m.cv5.f1}</b>, 95% интервал <b>{m.cv5_ci95?.f1?.join(" – ")}</b>; precision {m.cv5_ci95?.precision?.join(" – ")}; recall {m.cv5_ci95?.recall?.join(" – ")}.
                Повтор 5×{m.cv5_repeated?.repeats}: F1 {m.cv5_repeated?.f1_mean} ± {m.cv5_repeated?.f1_std}.
              </div>
              {m.cv5_grouped && (
                <div style={{ marginTop: 6 }}>
                  Проверка на синонимы: близкие формулировки одной технологии ({m.cv5_grouped.rows_in_shared_groups} примеров в общих группах)
                  всегда в одном блоке проверки — F1 <b>{m.cv5_grouped.grouped_cv5.f1}</b> против {m.cv5_grouped.plain_cv5.f1}, ROC-AUC {m.cv5_grouped.grouped_cv5.roc_auc} против {m.cv5_grouped.plain_cv5.roc_auc}.
                  Качество не падает — модель не «узнаёт» синонимы из обучения.
                </div>
              )}
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
                Каждый пример оценён моделью, которая его не видела (5-кратная кросс-валидация). Подобранная температура калибровки T = {m.calibration.temperature}
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
              <h3>Ограничения</h3>
              <div className="panel">
                <ul className="small">{m.limitations.filter((l: string) => !l.includes("ничего не нашли")).map((l: string, i: number) => <li key={i}>{l}</li>)}</ul>
              </div>
            </>
          )}
        </>
      )}

      {info?.decision_comparison && (
        <>
          <h3>Вклад модели Jev (одни и те же доказательства)</h3>
          
          <div className="tablewrap">
            <table>
              <thead><tr><th>Модель ответов</th><th>F1 (все признаки)</th><th>Precision</th><th>ROC-AUC</th><th>F1 (только ответы модели)</th></tr></thead>
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
          <p className="muted small">«Только обнаружение» — поиск без базы известных сигналов, только по открытым источникам.</p>
          <div className="tablewrap">
            <table>
              <thead><tr><th>Запрос</th><th>Режим</th><th>Время</th><th>Сигналов</th><th>Доказательства A / B</th><th>Наблюдать</th><th>Новых кандидатов</th></tr></thead>
              <tbody>
                {info.live_eval.runs.filter((r: any) => r.status !== "rejected").map((r: any, i: number) => (
                  <tr key={i}>
                    <td><a href={`/runs/${r.run_id}`}>{r.query}</a></td>
                    <td className="small">{r.mode}</td>
                    <td className="small">{r.seconds ? `${Math.round(r.seconds / 60)} мин` : "—"}</td>
                    <td>{r.n_signals}</td>
                    <td>{r.passport ? `${r.passport.A ?? 0} / ${r.passport.B ?? 0}` : "—"}</td>
                    <td>{r.watch ?? "—"}</td>
                    <td>{r.new_candidates_in_top}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {info?.timemachine && <TimeMachine t={info.timemachine} />}
      <Hypotheses info={info} />
      <ForecastsBlock blind={info?.blind_eval} />

      {fb && fb.total > 0 && (
        <>
          <h2>Оценки аналитиков</h2>
          <div className="panel small">
            Всего оценок: <b>{fb.total}</b> — {Object.entries(fb.by_verdict).map(([k, v]) => `${fb.labels[k]}: ${v}`).join(", ")}.
            {fb.agreement != null && <> Согласие аналитиков с системой: <b>{Math.round(fb.agreement * 100)}%</b>.</>}
            <div className="muted" style={{ marginTop: 6 }}>Оценки используются при дообучении модели.</div>
          </div>
        </>
      )}

      {info?.weights?.length > 0 && (
        <>
          <h2>Веса признаков (интерпретация модели)</h2>
          <div className="panel">
            <p className="muted small">Положительный вес — признак повышает вероятность слабого сигнала; отрицательный — указывает на зрелость или недостаток подтверждений.</p>
            <table>
              <tbody>
                {info.weights.map((w: any) => (
                  <tr key={w.feature}>
                    <td className="small">{String(w.label).replace("(decision-модель)", "(Jev)").replace("Самое твёрдое событие", "Подтверждённое событие")}</td>
                    <td className="small" style={{ color: w.weight >= 0 ? "var(--good)" : "var(--bad)", fontWeight: 700 }}>{w.weight > 0 ? "+" : ""}{w.weight}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

    </div>
  );
}
