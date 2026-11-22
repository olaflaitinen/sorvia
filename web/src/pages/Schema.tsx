import { useEffect, useMemo, useState } from "react";
import { api, type SchemaObject } from "../api";
import { Alert, Card, PageHeader, Spinner } from "../components/ui";

export function Schema() {
  const [items, setItems] = useState<SchemaObject[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");

  useEffect(() => {
    api.schema().then(setItems).catch((e) => setError((e as Error).message));
  }, []);

  const filtered = useMemo(() => {
    const term = q.trim().toLocaleLowerCase("az");
    if (!items || !term) return items;
    return items.filter((i) => i.ddl_summary.toLocaleLowerCase("az").includes(term));
  }, [items, q]);

  return (
    <div className="page">
      <PageHeader
        title="Məlumat xəritəsi"
        subtitle="Sorvia-nın sualları anlamaq üçün istifadə etdiyi semantik qat: hər cədvəlin Azərbaycan dilində təsviri, sütunları və əlaqələri."
      />
      <input className="search" placeholder="Axtar: satış, resept, filial..." value={q} onChange={(e) => setQ(e.target.value)} aria-label="Axtar" />
      {error && <Alert kind="error">{error}</Alert>}
      {!items && !error && <Spinner />}
      <div className="schema-grid">
        {filtered?.map((o) => {
          const [head, ...cols] = o.ddl_summary.split("\n");
          const comment = head.split("  -- ")[1];
          return (
            <Card key={o.qualified} title={<span className="mono">{o.qualified}</span>} actions={<span className="tag">{o.kind === "view" ? "view" : "cədvəl"}</span>}>
              {comment && <p className="muted small">{comment}</p>}
              <ul className="cols">
                {cols.map((c, i) => {
                  const [def, note] = c.trim().split(" -- ");
                  return (
                    <li key={i}>
                      <span className="mono">{def}</span>
                      {note && <span className="muted small"> {note}</span>}
                    </li>
                  );
                })}
              </ul>
            </Card>
          );
        })}
      </div>
    </div>
  );
}
