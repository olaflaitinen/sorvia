import { useEffect, useRef, useState, type FormEvent } from "react";
import { api, ApiError, type AskResponse, type Meta } from "../api";
import { reasonText } from "../labels";
import { Alert, BarChart, Button, Card, DataTable, PageHeader, SqlBlock, Spinner, StatusBadge, Tabs, chartable } from "../components/ui";

type View = "table" | "chart" | "sql";

export function Ask() {
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<AskResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<AskResponse[]>([]);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [view, setView] = useState<View>("table");
  const [rated, setRated] = useState<Record<number, boolean>>({});
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    api.suggestions().then(setSuggestions).catch(() => setSuggestions([]));
    api.meta().then(setMeta).catch(() => setMeta(null));
  }, []);

  async function ask(q: string) {
    const text = q.trim();
    if (text.length < 3 || busy) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api.ask(text);
      setResult(r);
      setView(r.status === "ok" && chartable(r.columns, r.rows) ? "chart" : r.status === "ok" ? "table" : "sql");
      setHistory((h) => [r, ...h].slice(0, 20));
    } catch (err) {
      setError(err instanceof ApiError && err.status === 429 ? "Çox sual verdiniz. Bir dəqiqə gözləyin." : (err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    void ask(question);
  }

  async function rate(ok: boolean) {
    if (!result?.query_id) return;
    try {
      await api.feedback(result.query_id, ok);
      setRated((r) => ({ ...r, [result.query_id!]: ok }));
    } catch (err) {
      setError((err as Error).message);
    }
  }

  const offline = meta?.llm_provider === "static";

  return (
    <div className="page">
      <PageHeader title="Sual ver" subtitle="Aptek şəbəkəsinin məlumat bazasına Azərbaycan və ya ingilis dilində sual verin." />

      {offline && (
        <Alert kind="info">
          Demo rejimi: sistem oflayn işləyir və test dəstindəki 60 suala cavab verir. Aşağıdakı nümunələrdən birini seçin və ya
          onlardan birini yazın. Real dil modeli qoşulduqda istənilən sual işləyir.
        </Alert>
      )}

      <form className="ask-box" onSubmit={submit}>
        <textarea
          ref={inputRef}
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void ask(question);
            }
          }}
          placeholder="Məsələn: Bu il ən az gəlir gətirən filial hansıdır?"
          rows={2}
          maxLength={2000}
          aria-label="Sual"
        />
        <Button type="submit" disabled={busy || question.trim().length < 3}>
          {busy ? "Düşünür..." : "Soruş"}
        </Button>
      </form>

      {suggestions.length > 0 && (
        <div className="chips" aria-label="Nümunə suallar">
          {suggestions.map((s) => (
            <button
              key={s}
              className="chip"
              onClick={() => {
                setQuestion(s);
                void ask(s);
              }}
              disabled={busy}
            >
              {s}
            </button>
          ))}
        </div>
      )}

      {error && <Alert kind="error">{error}</Alert>}
      {busy && <Spinner label="Sual SQL-ə çevrilir və yoxlanılır" />}

      {result && !busy && (
        <Card
          title={
            <span className="result-title">
              <StatusBadge status={result.status} />
              <span>{result.question}</span>
            </span>
          }
          actions={
            result.status === "ok" ? (
              <span className="muted small mono">
                {result.row_count} sətir{result.truncated ? " (kəsilib)" : ""}, {result.timings_ms.total} ms
                {result.repair_attempts ? `, ${result.repair_attempts} düzəliş` : ""}
              </span>
            ) : undefined
          }
        >
          {result.status !== "ok" && (
            <Alert kind={result.status === "blocked" ? "warning" : "error"}>
              {result.status === "blocked" && result.reason_code !== "cannot_answer" && <b>Təhlükəsizlik qatı sorğunu dayandırdı. </b>}
              {reasonText(result.reason_code, result.message)}
              {result.reason_code === "cannot_answer" && result.message && <span className="muted"> ({result.message})</span>}
            </Alert>
          )}
          {(result.status === "ok" || result.sql) && (
            <>
              <Tabs<View>
                value={view}
                onChange={setView}
                items={[
                  ...(result.status === "ok" ? [{ id: "table" as View, label: "Cədvəl" }] : []),
                  ...(result.status === "ok" && chartable(result.columns, result.rows) ? [{ id: "chart" as View, label: "Qrafik" }] : []),
                  ...(result.sql ? [{ id: "sql" as View, label: "SQL" }] : []),
                ]}
              />
              <div className="tab-body">
                {view === "table" && <DataTable columns={result.columns} rows={result.rows} />}
                {view === "chart" && <BarChart columns={result.columns} rows={result.rows} />}
                {view === "sql" && result.sql && (
                  <>
                    <SqlBlock sql={result.sql} />
                    {result.relations.length > 0 && (
                      <p className="muted small">İstifadə olunan cədvəllər: {result.relations.join(", ")}</p>
                    )}
                  </>
                )}
              </div>
            </>
          )}
          {result.query_id && result.status === "ok" && (
            <div className="feedback">
              {result.query_id in rated ? (
                <span className="muted small">Rəyiniz üçün təşəkkürlər.</span>
              ) : (
                <>
                  <span className="muted small">Cavab düzgündürmü?</span>
                  <Button variant="secondary" onClick={() => rate(true)}>Bəli</Button>
                  <Button variant="secondary" onClick={() => rate(false)}>Xeyr</Button>
                </>
              )}
            </div>
          )}
        </Card>
      )}

      {history.length > 1 && (
        <Card title="Bu sessiyada verilən suallar">
          <ul className="session-list">
            {history.slice(1).map((h, i) => (
              <li key={i}>
                <button className="link" onClick={() => { setResult(h); setView(h.status === "ok" ? "table" : "sql"); }}>
                  <StatusBadge status={h.status} /> {h.question}
                </button>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}
