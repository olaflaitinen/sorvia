import type { QueryStatus, Role } from "./api";

export const STATUS_LABEL: Record<QueryStatus, string> = {
  ok: "Uğurlu",
  blocked: "Bloklandı",
  error: "Xəta",
  timeout: "Vaxt bitdi",
};

export const ROLE_LABEL: Record<Role, string> = {
  admin: "Administrator",
  manager: "Menecer",
  pharmacist: "Əczaçı",
};

// Why a question was stopped, in plain Azerbaijani. Keys are API reason codes.
export const REASON_LABEL: Record<string, string> = {
  cannot_answer: "Bu sual sxemdəki məlumatlarla cavablandırıla bilmir və ya məlumatı dəyişməyi tələb edir.",
  not_a_query: "Yalnız oxuma sorğularına icazə verilir; məlumatı dəyişən əmrlər bloklanır.",
  multiple_statements: "Bir sorğuda yalnız bir SQL ifadəsi ola bilər.",
  forbidden_construct: "Sorğuda icazə verilməyən konstruksiya var (məsələn, SELECT INTO və ya FOR UPDATE).",
  function_not_allowed: "Sorğu icazə verilməyən funksiyanı çağırır.",
  system_object: "Sistem kataloqlarına giriş qadağandır.",
  schema_not_allowed: "Bu sxemə giriş qadağandır.",
  unknown_relation: "Sorğu mövcud olmayan və ya icazəsiz cədvələ müraciət edir.",
  cross_database: "Başqa verilənlər bazasına müraciət qadağandır.",
  too_complex: "Sorğu çox mürəkkəbdir. Sualı sadələşdirin.",
  too_long: "Sorğu çox uzundur.",
  invalid_limit: "LIMIT dəyəri düzgün deyil.",
  parse_error: "Yaradılan SQL təhlil oluna bilmədi.",
  empty: "Model SQL qaytarmadı.",
  cost_limit: "Sorğu çox böyük həcmdə məlumat oxuyardı. Dövrü, filialı və ya nəticə sayını daraldın.",
  timeout: "Sorğu vaxt limitini keçdi.",
  insufficient_privilege: "Bu məlumatı görmək üçün icazəniz yoxdur.",
  llm_unavailable: "Dil modeli hazırda əlçatan deyil.",
};

export function reasonText(code: string | null | undefined, fallback?: string | null): string {
  if (!code) return fallback ?? "";
  return REASON_LABEL[code] ?? fallback ?? code;
}

export function formatCell(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "number") {
    return Number.isInteger(value)
      ? value.toLocaleString("az-AZ")
      : value.toLocaleString("az-AZ", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  if (typeof value === "boolean") return value ? "bəli" : "xeyr";
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}T/.test(value)) {
    const d = new Date(value);
    if (!Number.isNaN(d.getTime())) return d.toLocaleString("az-AZ", { dateStyle: "short", timeStyle: "short" });
  }
  return String(value);
}

export function formatDate(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString("az-AZ", { dateStyle: "medium", timeStyle: "short" });
}
