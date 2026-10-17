// Тесты интерфейса: форматирование вероятностей, бейджи проверяемости, токен доступа, ссылки экспорта.
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EXPORT_FORMATS, exportUrl, headers, pct, prob, readToken, saveToken, VERDICTS } from "./api";
import { PassportBadge, RobustnessBadge, ScoreBadge, WindowBadge } from "./components/ui";

describe("вероятность без ложной точности", () => {
  it("никогда не показывает 100% и 0%", () => {
    for (const p of [0.95, 0.996, 0.99999, 1]) expect(prob(p)).toBe("> 95%");
    for (const p of [0, 0.001, 0.05]) expect(prob(p)).toBe("< 5%");
    expect(prob(0.8)).toBe("80%");
    expect(prob(null)).toBe("—");
  });

  it("обычные доли (доля работ за 3 года) показываются как есть", () => {
    expect(pct(1)).toBe("100%");
    expect(pct(undefined)).toBe("—");
  });

  it("бейдж вероятности: уровень и подпись", () => {
    expect(renderToStaticMarkup(<ScoreBadge p={0.999} />)).toContain("Высокая (&gt; 95%)");
    expect(renderToStaticMarkup(<ScoreBadge p={0.6} />)).toContain("Средняя (60%)");
    expect(renderToStaticMarkup(<ScoreBadge p={0.2} />)).toContain("badge low");
    expect(renderToStaticMarkup(<ScoreBadge p={null} />)).toContain("—");
  });
});

describe("бейджи проверяемости", () => {
  const pp = { level: "B" as const, label: "Достаточно", checked: 6, confirmed: 4, domains: 3, domain_list: [], science: 2, event_level: 4, event: "пилот / испытания", hard_event: true };

  it("паспорт доказательств", () => {
    const html = renderToStaticMarkup(<PassportBadge p={pp} />);
    expect(html).toContain("Доказательства B: 4/6 · 3 ист.");
    expect(html).toContain("badge med");
    expect(renderToStaticMarkup(<PassportBadge p={{ ...pp, level: "C" }} />)).toContain("badge low");
    expect(renderToStaticMarkup(<PassportBadge p={null} />)).toBe("");
  });

  it("запас прочности и окно для России", () => {
    expect(renderToStaticMarkup(<RobustnessBadge r={{ level: "fragile", label: "хрупкий", text: "t", p_without: 0.3 }} />)).toContain("Запас прочности: хрупкий");
    expect(renderToStaticMarkup(<WindowBadge w={{ status: "open", label: "Окно открыто", text: "t", world: 30, ru: 0 }} />)).toContain("Россия: Окно открыто");
    expect(renderToStaticMarkup(<WindowBadge w={null} />)).toBe("");
  });
});

describe("доступ и экспорт", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("без localStorage (приватный режим) токен пустой и не ломает запросы", () => {
    expect(readToken()).toBe("");
    expect(headers()).toEqual({ "Content-Type": "application/json" });
  });

  it("токен уходит в заголовке X-API-Token", () => {
    const store: Record<string, string> = {};
    vi.stubGlobal("localStorage", { getItem: (k: string) => store[k] ?? null, setItem: (k: string, v: string) => (store[k] = v) });
    saveToken("s3cret");
    expect(headers()["X-API-Token"]).toBe("s3cret");
  });

  it("ссылки экспорта и варианты оценки аналитика совпадают с API", () => {
    expect(exportUrl(7, "xlsx")).toBe("/api/runs/7/export?format=xlsx");
    expect(EXPORT_FORMATS.map(([f]) => f)).toEqual(["xlsx", "csv", "md", "json"]);
    expect(VERDICTS.map(([v]) => v)).toEqual(["signal", "mature", "noise", "not_tech"]);
  });
});
