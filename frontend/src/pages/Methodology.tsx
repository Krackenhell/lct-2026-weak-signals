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

export default function Methodology() {
  const [info, setInfo] = useState<any>(null);
  useEffect(() => {
    api.model().then(setInfo).catch(() => {});
  }, []);
  const m = info?.metrics;

  return (
    <div className="report">
      <h1>Методология и качество модели</h1>

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>Как система понимает, что это слабый сигнал</h3>
        <ol>
          <li><b>Поиск.</b> Запрос расширяется до 10–12 подтем; по ним собираются свежие препринты (arXiv), научные работы (OpenAlex), мировые и российские новости (GDELT).</li>
          <li><b>Кандидаты.</b> Из документов извлекаются названия конкретных технологий (LLM по тексту документов и статистический майнинг терминов), дубли и синонимы склеиваются.</li>
          <li><b>Доказательства.</b> По каждому кандидату отдельно собираются: годовая динамика публикаций, свежие препринты, новые репозитории GitHub, обсуждения инженеров, наличие и популярность статьи в Википедии, новости.</li>
          <li><b>Признаки.</b> Decision-модель (Jev / Kev) отвечает на 10 атомарных вопросов по тексту доказательств: конкретная ли это технология, есть ли массовое внедрение, рынок с лидерами, стандарт, ранняя стадия, независимые участники, маркетинговый шум, новизна, преимущество, уровень зрелости.</li>
          <li><b>Классификатор.</b> Собственная логистическая регрессия на 21 признаке, обученная на датасете организатора и нашей выборке отрицательных примеров, выдаёт вероятность слабого сигнала и вклад каждого признака.</li>
          <li><b>Фильтры исключения.</b> Явные правила отсекают нерелевантное, общие области, стандарты, зрелые технологии, хайп и кандидатов без независимых подтверждений. Каждое исключение сопровождается причиной.</li>
          <li><b>Досье.</b> LLM из разрешённого списка пишет русскую справку только по найденным документам со ссылками; иностранные источники получают русское резюме с пометкой о генерации.</li>
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
          <div className="tablewrap">
            <table>
              <thead><tr><th>Область</th>{Object.values(METRIC_RU).map((v) => <th key={v}>{v}</th>)}</tr></thead>
              <tbody>
                {Object.entries(m.leave_one_domain_out || {}).map(([k, v]: [string, any]) => (
                  <tr key={k}><td>{k}</td><MetricsRow m={v} /></tr>
                ))}
              </tbody>
            </table>
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
