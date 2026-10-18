export type Predictor = { feature: string; label: string; value: number; contribution: number };

export type Passport = {
  level: "A" | "B" | "C";
  label: string;
  checked: number;
  confirmed: number;
  domains: number;
  domain_list: string[];
  science: number;
  event_level: number;
  event: string;
  hard_event: boolean;
  links?: { ok: number; restricted: number; dead: number };
  funding_news?: number;
  grants?: number;
};

export type Geography = { top: { country: string; name: string; share: number }[]; china: number; usa: number; russia: number; leader: string };

export type Radar = { area: string; ring: "Пилотировать" | "Изучать" | "Наблюдать"; horizon: string; by: string };
export type YearPoint = { year: number; works: number; partial: boolean };

export type Robustness = { level: "strong" | "stable" | "fragile"; label: string; text: string; p_without: number; feature_label?: string };

export type RussiaWindow = { status: "open" | "closing" | "closed" | "thin" | "unknown"; label: string; text: string; world: number; ru: number | null; failed?: string[] };

export type Verification = { by: string | null; checked: number; supported: number; removed: { field: string; text: string; why: string }[]; note?: string };

export type CandidateBrief = {
  id: number;
  run_id: number;
  name: string;
  name_ru: string | null;
  origin: "discovered" | "watchlist";
  status: "signal" | "excluded" | "candidate" | "watch";
  passport?: Passport | null;
  robustness?: Robustness | null;
  window?: RussiaWindow | null;
  radar?: Radar | null;
  dynamics?: YearPoint[] | null;
  geography?: Geography | null;
  score?: { probability: number | null; relevance: number; final: number | null; outside_training: string[] } | null;
  startups_by_year?: Record<string, number> | null;
  missing?: string[];
  rank: number | null;
  probability: number | null;
  relevance: number | null;
  exclusion_code: string | null;
  exclusion_label: string | null;
  exclusion_reason: string | null;
  key_predictors: Predictor[];
  n_sources: number;
};

export type Source = {
  id: number;
  title: string;
  url: string;
  published: string | null;
  source_name: string;
  source_type: string;
  source_type_ru: string;
  language: string;
  trust_level: "high" | "medium" | "low";
  trust_level_ru: string;
  trust_reason: string;
  summary_ru: string | null;
  summary_generated: boolean;
  snippet: string;
  link_status?: "ok" | "dead" | "restricted" | null;
};

export const RINGS = ["Пилотировать", "Изучать", "Наблюдать"] as const;

/** Сетка радара банка: направление → кольцо → технологии. Направления — в порядке числа технологий. */
export function radarGrid(items: CandidateBrief[]): [string, Record<string, CandidateBrief[]>][] {
  const grid: Record<string, Record<string, CandidateBrief[]>> = {};
  for (const c of items) {
    if (!c.radar) continue;
    grid[c.radar.area] ??= { Пилотировать: [], Изучать: [], Наблюдать: [] };
    grid[c.radar.area][c.radar.ring].push(c);
  }
  const total = (r: Record<string, CandidateBrief[]>) => RINGS.reduce((n, k) => n + r[k].length, 0);
  return Object.entries(grid).sort((a, b) => total(b[1]) - total(a[1]) || a[0].localeCompare(b[0]));
}

export type Answer = { type: string; value?: number; label: string; level?: number };

export type CandidateFull = CandidateBrief & {
  query: string;
  features: Record<string, number>;
  contributions: Predictor[];
  methods: string[];
  answers: Record<string, Answer>;
  dossier: Record<string, string> & { verification?: Verification };
  sources: Source[];
  feedback?: Feedback;
};

export type Changes = { prev_run_id: number; prev_date: string | null; new: string[]; dropped: string[]; kept: number } | null;

export type Run = {
  id: number;
  query: string;
  status: "queued" | "running" | "done" | "failed" | "rejected";
  stage: string;
  progress: number;
  error: string | null;
  plan: { topic_en?: string; subqueries?: string[]; ru_terms?: string[]; generated_by?: string };
  stats: Record<string, number | object>;
  providers: Record<string, string>;
  options?: { use_watchlist?: boolean };
  created_at: string | null;
  finished_at: string | null;
};

export type RunFull = Run & { signals: CandidateBrief[]; watch?: CandidateBrief[]; excluded: CandidateBrief[] };

export type ModelCall = {
  id: number;
  provider: string;
  model: string;
  purpose: string;
  subject: string;
  latency_ms: number;
  ok: boolean;
  request: Record<string, unknown>;
  response: Record<string, unknown>;
  created_at: string | null;
};

const TOKEN_KEY = "weak-signals-api-token";

export function readToken(): string {
  try {
    return localStorage.getItem(TOKEN_KEY) || "";
  } catch {
    return "";
  }
}

export function saveToken(t: string) {
  try {
    localStorage.setItem(TOKEN_KEY, t);
  } catch {
    /* приватный режим браузера — токен просто не запомнится */
  }
}

export function headers(): Record<string, string> {
  const h: Record<string, string> = { "Content-Type": "application/json" };
  const t = readToken();
  if (t) h["X-API-Token"] = t;
  return h;
}

async function req<T>(path: string, init?: RequestInit, retried = false): Promise<T> {
  const r = await fetch(path, { ...init, headers: headers() });
  if (r.status === 401 && !retried && typeof window !== "undefined") {
    // Сервер защищён токеном (API_TOKEN): спрашиваем один раз и запоминаем.
    const t = window.prompt("Для запуска поиска нужен токен доступа:");
    if (t) {
      saveToken(t.trim());
      return req<T>(path, init, true);
    }
  }
  if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`);
  return r.json();
}

export type Feedback = { verdict: "signal" | "mature" | "noise" | "not_tech"; label: string; comment: string } | null;

export const VERDICTS: [Exclude<Feedback, null>["verdict"], string][] = [
  ["signal", "Слабый сигнал"],
  ["mature", "Зрелая технология"],
  ["noise", "Хайп / шум"],
  ["not_tech", "Не технология"],
];

export const EXPORT_FORMATS: [string, string][] = [
  ["xlsx", "Excel"],
  ["csv", "CSV"],
  ["md", "Markdown"],
  ["json", "JSON"],
];

export const exportUrl = (runId: number | string, format: string) => `/api/runs/${runId}/export?format=${format}`;

export const api = {
  search: (query: string, use_watchlist: boolean) =>
    req<Run>("/api/search", { method: "POST", body: JSON.stringify({ query, use_watchlist }) }),
  runs: () => req<Run[]>("/api/runs"),
  run: (id: number | string) => req<RunFull>(`/api/runs/${id}`),
  log: (id: number | string) => req<ModelCall[]>(`/api/runs/${id}/log`),
  candidate: (id: number | string) => req<CandidateFull>(`/api/candidates/${id}`),
  model: () => req<any>("/api/model"),
  showcase: () => req<Showcase[]>("/api/showcase"),
  feedback: (candId: number | string, verdict: string, comment = "") =>
    req<{ id: number; verdict: string; label: string }>(`/api/candidates/${candId}/feedback`, { method: "POST", body: JSON.stringify({ verdict, comment }) }),
  feedbackStats: () => req<{ total: number; by_verdict: Record<string, number>; labels: Record<string, string>; agreement: number | null }>("/api/feedback/stats"),
};

export type Showcase = { run_id: number; query: string; date: string | null; signals: number; passport?: { A?: number; B?: number }; providers: Record<string, string>; mode: string };

export const pct = (v: number | null | undefined) => (v == null ? "—" : `${Math.round(v * 100)}%`);

// Вероятность модели без ложной точности: логистическая регрессия не бывает уверена «на 100%».
export const prob = (v: number | null | undefined) => (v == null ? "—" : v >= 0.95 ? "> 95%" : v <= 0.05 ? "< 5%" : `${Math.round(v * 100)}%`);
