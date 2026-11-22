import { useEffect, useState } from "react";
import { api, type QueryLogItem, type QueryStatus } from "../api";
import { useAuth } from "../auth";
import { STATUS_LABEL, formatDate, reasonText } from "../labels";
import { Alert, Card, Empty, PageHeader, SqlBlock, Spinner, StatusBadge, Tabs } from "../components/ui";

type Filter = "all" | QueryStatus;

export function History() {
  const { user } = useAuth();
  const [filter, setFilter] = useState<Filter>("all");
  const [items, setItems] = useState<QueryLogItem[] | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setItems(null);
    api
      .queries(filter === "all" ? undefined : filter, 150)
      .then(setItems)
      .catch((e) => setError((e as Error).message));
  }, [filter]);

  return (
    <div className="page">
      <PageHeader
        title="Tarixçə"
        subtitle={user?.role === "pharmacist" ? "Verdiyiniz bütün suallar və nəticələri." : "Bütün istifadəçilərin sualları. Hər sorğu audit üçün saxlanılır."}
      />
      <Tabs<Filter>
        value={filter}
        onChange={setFilter}
        items={[{ id: "all", label: "Hamısı" }, ...(["ok", "blocked", "error", "timeout"] as QueryStatus[]).map((s) => ({ id: s, label: STATUS_LABEL[s] }))]}
      />
      {error && <Alert kind="error">{error}</Alert>}
      {!items && !error && <Spinner />}
      {items && items.length === 0 && <Empty>Hələ sual verilməyib.</Empty>}
      {items && items.length > 0 && (
        <Card>
          <ul className="log">
            {items.map((q) => (
              <li key={q.query_id} className="log-item">
                <button className="log-row" onClick={() => setOpen(open === q.query_id ? null : q.query_id)} aria-expanded={open === q.query_id}>
                  <StatusBadge status={q.status} />
                  <span className="log-q">{q.question}</span>
                  <span className="muted small mono">{q.row_count ?? ""}{q.row_count !== null ? " sətir · " : ""}{q.total_ms ?? 0} ms</span>
                  <span className="muted small">{formatDate(q.created_at)}</span>
                </button>
                {open === q.query_id && (
                  <div className="log-detail">
                    {q.block_reason && <Alert kind="warning">{reasonText(q.block_reason)}</Alert>}
                    {q.error_message && <Alert kind="error">{q.error_message}</Alert>}
                    {q.executed_sql ? <SqlBlock sql={q.executed_sql} /> : <p className="muted small">Bu sorğu icra olunmayıb.</p>}
                    <p className="muted small">
                      Strategiya: {q.strategy}
                      {q.repair_attempts ? `, ${q.repair_attempts} avtomatik düzəliş` : ""}, istifadəçi #{q.user_id}
                    </p>
                  </div>
                )}
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}
