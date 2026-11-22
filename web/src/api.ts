// Thin typed client for the Sorvia HTTP API (same origin; Vite proxies in development).

export type Role = "admin" | "manager" | "pharmacist";
export type QueryStatus = "ok" | "blocked" | "error" | "timeout";

export interface User {
  user_id: number;
  username: string;
  display_name: string;
  role: Role;
  branch_id: number | null;
}

export interface TokenResponse {
  access_token: string;
  expires_in: number;
  user: User;
}

export type Cell = string | number | boolean | null;

export interface AskResponse {
  query_id: number | null;
  status: QueryStatus;
  question: string;
  sql: string | null;
  columns: string[];
  rows: Cell[][];
  row_count: number;
  truncated: boolean;
  reason_code: string | null;
  message: string | null;
  relations: string[];
  strategy: string;
  repair_attempts: number;
  timings_ms: { llm: number; db: number; total: number };
}

export interface QueryLogItem {
  query_id: number;
  user_id: number;
  question: string;
  executed_sql: string | null;
  status: QueryStatus;
  block_reason: string | null;
  error_message: string | null;
  strategy: string;
  repair_attempts: number;
  row_count: number | null;
  total_ms: number | null;
  created_at: string;
}

export interface TableResponse {
  columns: string[];
  rows: Cell[][];
  row_count: number;
  truncated: boolean;
}

export interface SchemaObject {
  qualified: string;
  kind: string;
  ddl_summary: string;
}

export interface Recommendation {
  recommendation_id: number;
  table_name: string;
  columns: string[];
  index_ddl: string;
  workload_size: number;
  cost_before: number;
  cost_after: number;
  improvement_pct: number;
  status: "proposed" | "applied" | "rejected";
  created_at: string;
}

export interface Stats {
  days: number;
  by_status: { status: QueryStatus; n: number; avg_ms: number | null; p95_ms: number | null }[];
  blocked_reasons: { block_reason: string | null; n: number }[];
  feedback: { rated: number; accuracy: number | null };
}

export interface Meta {
  version: string;
  llm_provider: string;
  llm_model: string | null;
  strategy: string;
  max_rows: number;
  demo_password: string | null;
}

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) {
    super(message);
  }
}

const TOKEN_KEY = "sorvia.token";

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null): void {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable: token lives only in memory for this tab */
  }
}

let onUnauthorized: (() => void) | null = null;
export function setUnauthorizedHandler(fn: () => void): void {
  onUnauthorized = fn;
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  let res: Response;
  try {
    res = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  } catch {
    throw new ApiError(0, "network", "Serverə qoşulmaq mümkün olmadı. İnternet bağlantısını yoxlayın.");
  }
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    if (res.status === 401 && path !== "/v1/auth/token") onUnauthorized?.();
    const detail = Array.isArray(data?.detail) ? "Daxil edilən məlumat düzgün deyil." : undefined;
    throw new ApiError(res.status, data?.code ?? "error", data?.message ?? detail ?? `Xəta (${res.status})`);
  }
  return data as T;
}

export const api = {
  login: (username: string, password: string) =>
    request<TokenResponse>("POST", "/v1/auth/token", { username, password }),
  me: () => request<User>("GET", "/v1/me"),
  meta: () => request<Meta>("GET", "/v1/meta"),
  ask: (question: string, strategy?: string) => request<AskResponse>("POST", "/v1/ask", { question, strategy }),
  suggestions: () => request<string[]>("GET", "/v1/suggestions"),
  allSuggestions: () => request<{ question: string; difficulty: string }[]>("GET", "/v1/suggestions/all"),
  queries: (status?: string, limit = 100) =>
    request<QueryLogItem[]>("GET", `/v1/queries?limit=${limit}${status ? `&status=${status}` : ""}`),
  feedback: (id: number, is_correct: boolean, comment?: string) =>
    request<void>("POST", `/v1/queries/${id}/feedback`, { is_correct, comment }),
  schema: () => request<SchemaObject[]>("GET", "/v1/schema"),
  lowStock: () => request<TableResponse>("GET", "/v1/stock/low"),
  expiring: () => request<TableResponse>("GET", "/v1/stock/expiring"),
  trace: (batchId: number, at?: string) =>
    request<TableResponse>("GET", `/v1/batches/${batchId}/trace${at ? `?at=${encodeURIComponent(at)}` : ""}`),
  createSale: (payload: {
    employee_id: number;
    items: { drug_id: number; quantity: number }[];
    customer_id?: number;
    prescription_id?: number;
    branch_id?: number;
  }) => request<Record<string, unknown>>("POST", "/v1/sales", payload),
  stats: (days = 30) => request<Stats>("GET", `/v1/stats?days=${days}`),
  recommendations: () => request<Recommendation[]>("GET", "/v1/advisor/recommendations"),
  runAdvisor: () => request<Recommendation[]>("POST", "/v1/advisor/run"),
  applyRecommendation: (id: number) => request<{ ddl: string }>("POST", `/v1/advisor/recommendations/${id}/apply`),
  rejectRecommendation: (id: number) => request<void>("POST", `/v1/advisor/recommendations/${id}/reject`),
  refreshAnalytics: () => request<{ facts: number }>("POST", "/v1/analytics/refresh"),
};
