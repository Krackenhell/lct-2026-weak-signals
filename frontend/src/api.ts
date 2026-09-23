export type Predictor = { feature: string; label: string; value: number; contribution: number };

export type CandidateBrief = {
  id: number;
  run_id: number;
  name: string;
  name_ru: string | null;
  origin: "discovered" | "watchlist";
  status: "signal" | "excluded" | "candidate";
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
};

export type Answer = { type: string; value?: number; label: string; level?: number };

export type CandidateFull = CandidateBrief & {
  query: string;
  features: Record<string, number>;
  contributions: Predictor[];
  methods: string[];
  answers: Record<string, Answer>;
  dossier: Record<string, string>;
  sources: Source[];
};

export type Run = {
  id: number;
  query: string;
  status: "queued" | "running" | "done" | "failed";
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

export type RunFull = Run & { signals: CandidateBrief[]; excluded: CandidateBrief[] };

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

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...init });
  if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`);
  return r.json();
}

export const api = {
  search: (query: string, use_watchlist: boolean) =>
    req<Run>("/api/search", { method: "POST", body: JSON.stringify({ query, use_watchlist }) }),
  runs: () => req<Run[]>("/api/runs"),
  run: (id: number | string) => req<RunFull>(`/api/runs/${id}`),
  log: (id: number | string) => req<ModelCall[]>(`/api/runs/${id}/log`),
  candidate: (id: number | string) => req<CandidateFull>(`/api/candidates/${id}`),
  model: () => req<any>("/api/model"),
};

export const pct = (v: number | null | undefined) => (v == null ? "—" : `${Math.round(v * 100)}%`);
