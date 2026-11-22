import { useMemo, useState, type ReactNode } from "react";
import markSvg from "../assets/brand/mark.svg?raw";
import wordSvg from "../assets/brand/wordmark.svg?raw";
import sloganSvg from "../assets/brand/slogan.svg?raw";
import type { Cell, QueryStatus } from "../api";
import { STATUS_LABEL, formatCell } from "../labels";

function Svg({ svg, className, label }: { svg: string; className?: string; label?: string }) {
  return <span className={className} role="img" aria-label={label} dangerouslySetInnerHTML={{ __html: svg }} />;
}

export function Logo({ size = 28 }: { size?: number }) {
  return (
    <span className="logo" style={{ height: size }} aria-label="Sorvia">
      <Svg svg={markSvg} className="logo-mark" />
      <Svg svg={wordSvg} className="logo-word" />
    </span>
  );
}

export function Mark() {
  return <Svg svg={markSvg} className="mark" label="Sorvia" />;
}

export function Slogan() {
  return <Svg svg={sloganSvg} className="slogan" label="Soruş, aşkara çıxsın." />;
}

export function StatusBadge({ status }: { status: QueryStatus }) {
  return (
    <span className={`badge badge-${status}`}>
      <span className="badge-dot" />
      {STATUS_LABEL[status]}
    </span>
  );
}

export function Button({
  children,
  variant = "primary",
  ...rest
}: { children: ReactNode; variant?: "primary" | "secondary" | "ghost" | "danger" } & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button className={`btn btn-${variant}`} {...rest}>
      {children}
    </button>
  );
}

export function Card({ title, actions, children }: { title?: ReactNode; actions?: ReactNode; children: ReactNode }) {
  return (
    <section className="card">
      {(title || actions) && (
        <header className="card-head">
          {title && <h3>{title}</h3>}
          {actions && <div className="card-actions">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <header className="page-head">
      <div>
        <h1>{title}</h1>
        {subtitle && <p className="muted">{subtitle}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </header>
  );
}

export function Alert({ kind = "info", children }: { kind?: "info" | "error" | "warning" | "success"; children: ReactNode }) {
  return <div className={`alert alert-${kind}`} role={kind === "error" ? "alert" : "status"}>{children}</div>;
}

export function Spinner({ label = "Yüklənir" }: { label?: string }) {
  return (
    <span className="spinner" role="status">
      <span className="spinner-ring" />
      {label}
    </span>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

function isNumeric(values: Cell[]): boolean {
  const present = values.filter((v) => v !== null && v !== "");
  return present.length > 0 && present.every((v) => typeof v === "number");
}

export function DataTable({ columns, rows, maxHeight = 520 }: { columns: string[]; rows: Cell[][]; maxHeight?: number }) {
  const [sort, setSort] = useState<{ col: number; dir: 1 | -1 } | null>(null);
  const numeric = useMemo(() => columns.map((_, i) => isNumeric(rows.map((r) => r[i]))), [columns, rows]);
  const sorted = useMemo(() => {
    if (!sort) return rows;
    const copy = [...rows];
    copy.sort((a, b) => {
      const x = a[sort.col];
      const y = b[sort.col];
      if (x === y) return 0;
      if (x === null) return 1;
      if (y === null) return -1;
      return (x > y ? 1 : -1) * sort.dir;
    });
    return copy;
  }, [rows, sort]);
  if (!columns.length) return <Empty>Nəticə yoxdur.</Empty>;
  return (
    <div className="table-wrap" style={{ maxHeight }}>
      <table className="table">
        <thead>
          <tr>
            {columns.map((c, i) => (
              <th
                key={c + i}
                className={numeric[i] ? "num" : undefined}
                onClick={() => setSort((s) => ({ col: i, dir: s?.col === i && s.dir === 1 ? -1 : 1 }))}
                aria-sort={sort?.col === i ? (sort.dir === 1 ? "ascending" : "descending") : "none"}
              >
                {c}
                {sort?.col === i ? (sort.dir === 1 ? " ▲" : " ▼") : ""}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((r, ri) => (
            <tr key={ri}>
              {r.map((v, ci) => (
                <td key={ci} className={numeric[ci] ? "num" : undefined}>
                  {formatCell(v)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {!rows.length && <Empty>Sorğu boş nəticə qaytardı.</Empty>}
    </div>
  );
}

/** Horizontal bar chart for a label column plus one numeric column. */
export function chartable(columns: string[], rows: Cell[][]): { label: number; value: number } | null {
  if (rows.length < 2 || rows.length > 40 || columns.length < 2) return null;
  const value = columns.findIndex((_, i) => isNumeric(rows.map((r) => r[i])));
  if (value < 0) return null;
  const label = columns.findIndex((_, i) => i !== value);
  return { label, value };
}

export function BarChart({ columns, rows }: { columns: string[]; rows: Cell[][] }) {
  const spec = chartable(columns, rows);
  if (!spec) return <Empty>Bu nəticə üçün qrafik uyğun deyil.</Empty>;
  const data = rows.map((r) => ({ label: formatCell(r[spec.label]), value: Number(r[spec.value] ?? 0) }));
  const max = Math.max(...data.map((d) => Math.abs(d.value)), 1);
  return (
    <div className="bars" role="img" aria-label={`${columns[spec.value]} qrafiki`}>
      <div className="bars-title">{columns[spec.value]}</div>
      {data.map((d, i) => (
        <div className="bar-row" key={i}>
          <span className="bar-label" title={d.label}>{d.label}</span>
          <span className="bar-track">
            <span className="bar-fill" style={{ width: `${(Math.abs(d.value) / max) * 100}%` }} />
          </span>
          <span className="bar-value">{formatCell(d.value)}</span>
        </div>
      ))}
    </div>
  );
}

const SQL_KEYWORDS =
  /\b(SELECT|FROM|WHERE|JOIN|LEFT|RIGHT|INNER|OUTER|ON|GROUP BY|ORDER BY|HAVING|LIMIT|AS|AND|OR|NOT|IN|IS|NULL|WITH|UNION|ALL|DISTINCT|CASE|WHEN|THEN|ELSE|END|OVER|PARTITION BY|DESC|ASC|FILTER|CAST|INTERVAL|EXISTS|BETWEEN|LIKE|ILIKE)\b/g;

export function SqlBlock({ sql }: { sql: string }) {
  const [copied, setCopied] = useState(false);
  const pretty = sql.replace(/\s+(FROM|WHERE|GROUP BY|ORDER BY|HAVING|LIMIT|LEFT JOIN|JOIN|UNION ALL|UNION)\b/g, "\n$1");
  const parts = pretty.split(SQL_KEYWORDS);
  const isKeyword = (p: string) => new RegExp(`^${SQL_KEYWORDS.source}$`).test(p);
  return (
    <div className="sql">
      <button
        className="btn btn-ghost sql-copy"
        onClick={() => {
          navigator.clipboard?.writeText(sql).then(() => {
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          });
        }}
      >
        {copied ? "Kopyalandı" : "Kopyala"}
      </button>
      <pre>
        <code>
          {parts.map((p, i) => (isKeyword(p) ? <b key={i}>{p}</b> : <span key={i}>{p}</span>))}
        </code>
      </pre>
    </div>
  );
}

export function Tabs<T extends string>({ value, onChange, items }: { value: T; onChange: (v: T) => void; items: { id: T; label: string }[] }) {
  return (
    <div className="tabs" role="tablist">
      {items.map((it) => (
        <button key={it.id} role="tab" aria-selected={value === it.id} className={value === it.id ? "tab active" : "tab"} onClick={() => onChange(it.id)}>
          {it.label}
        </button>
      ))}
    </div>
  );
}
