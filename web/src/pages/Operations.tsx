import { useEffect, useState, type FormEvent } from "react";
import { api, type TableResponse } from "../api";
import { useAuth } from "../auth";
import { formatCell } from "../labels";
import { Alert, Button, Card, DataTable, PageHeader, Spinner, Tabs } from "../components/ui";

type View = "low" | "expiring" | "trace" | "sale";

function useTable(loader: () => Promise<TableResponse>, deps: unknown[]) {
  const [data, setData] = useState<TableResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setData(null);
    loader().then(setData).catch((e) => setError((e as Error).message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return { data, error };
}

function Low() {
  const { data, error } = useTable(api.lowStock, []);
  if (error) return <Alert kind="error">{error}</Alert>;
  if (!data) return <Spinner />;
  return <DataTable columns={["Filial", "Dərman", "Qalıq", "Minimum"]} rows={data.rows} />;
}

function Expiring() {
  const { data, error } = useTable(api.expiring, []);
  if (error) return <Alert kind="error">{error}</Alert>;
  if (!data) return <Spinner />;
  return <DataTable columns={["Filial", "Dərman", "Lot", "Son tarix", "Qalan gün", "Miqdar"]} rows={data.rows} />;
}

function Trace() {
  const [batch, setBatch] = useState("1");
  const [at, setAt] = useState("");
  const [data, setData] = useState<TableResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      setData(await api.trace(Number(batch), at ? new Date(at).toISOString() : undefined));
    } catch (err) {
      setError((err as Error).message);
    }
  }
  return (
    <>
      <p className="muted">
        Hər qalıq dəyişikliyi dəyişməz jurnala yazılır. Bu sayədə istənilən partiyanın istənilən anda harada və nə qədər olduğunu
        bilmək olur (temporal izlənmə).
      </p>
      <form className="inline-form" onSubmit={submit}>
        <label>
          Partiya nömrəsi
          <input type="number" min={1} value={batch} onChange={(e) => setBatch(e.target.value)} required />
        </label>
        <label>
          An (boş: indi)
          <input type="datetime-local" value={at} onChange={(e) => setAt(e.target.value)} />
        </label>
        <Button type="submit">Göstər</Button>
      </form>
      {error && <Alert kind="error">{error}</Alert>}
      {data && (data.rows.length ? <DataTable columns={["Filial №", "Filial", "Miqdar"]} rows={data.rows} /> : <Alert>Bu anda partiya heç bir filialda (sizin görə bildiyiniz) yoxdur.</Alert>)}
    </>
  );
}

function Sale() {
  const { user } = useAuth();
  const [employee, setEmployee] = useState("");
  const [branch, setBranch] = useState("");
  const [customer, setCustomer] = useState("");
  const [prescription, setPrescription] = useState("");
  const [items, setItems] = useState([{ drug_id: "", quantity: "1" }]);
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const r = await api.createSale({
        employee_id: Number(employee),
        items: items.filter((i) => i.drug_id).map((i) => ({ drug_id: Number(i.drug_id), quantity: Number(i.quantity) })),
        ...(customer ? { customer_id: Number(customer) } : {}),
        ...(prescription ? { prescription_id: Number(prescription) } : {}),
        ...(user?.branch_id ? {} : { branch_id: Number(branch) }),
      });
      setResult(r);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <p className="muted">
        Satış bütövlükdə bazanın prosedurunda (pharma.register_sale) icra olunur: partiyalar FEFO qaydası ilə seçilir, vaxtı keçmiş
        dərman və reseptsiz reseptli dərman satıla bilməz, qalıq mənfiyə düşə bilməz.
      </p>
      <form className="sale-form" onSubmit={submit}>
        <div className="form-grid">
          {!user?.branch_id && (
            <label>
              Filial №
              <input type="number" min={1} value={branch} onChange={(e) => setBranch(e.target.value)} required />
            </label>
          )}
          <label>
            İşçi №
            <input type="number" min={1} value={employee} onChange={(e) => setEmployee(e.target.value)} required />
          </label>
          <label>
            Müştəri № (istəyə görə)
            <input type="number" min={1} value={customer} onChange={(e) => setCustomer(e.target.value)} />
          </label>
          <label>
            Resept № (istəyə görə)
            <input type="number" min={1} value={prescription} onChange={(e) => setPrescription(e.target.value)} />
          </label>
        </div>
        <div className="items">
          {items.map((it, i) => (
            <div className="item-row" key={i}>
              <label>
                Dərman №
                <input type="number" min={1} value={it.drug_id} onChange={(e) => setItems(items.map((x, j) => (j === i ? { ...x, drug_id: e.target.value } : x)))} required={i === 0} />
              </label>
              <label>
                Miqdar
                <input type="number" min={1} max={1000} value={it.quantity} onChange={(e) => setItems(items.map((x, j) => (j === i ? { ...x, quantity: e.target.value } : x)))} />
              </label>
              {items.length > 1 && (
                <Button type="button" variant="ghost" onClick={() => setItems(items.filter((_, j) => j !== i))}>
                  Sil
                </Button>
              )}
            </div>
          ))}
          <Button type="button" variant="secondary" onClick={() => setItems([...items, { drug_id: "", quantity: "1" }])}>
            Sətir əlavə et
          </Button>
        </div>
        <Button type="submit" disabled={busy}>{busy ? "Qeydə alınır..." : "Satışı qeydə al"}</Button>
      </form>
      {error && <Alert kind="error">{error}</Alert>}
      {result && (
        <Alert kind="success">
          Satış #{String(result.sale_id)} qeydə alındı. Məbləğ: {formatCell(result.gross_amount as number)} AZN, endirim:{" "}
          {formatCell(result.discount_amount as number)} AZN, ödənilən: <b>{formatCell(result.net_amount as number)} AZN</b>.
        </Alert>
      )}
    </>
  );
}

export function Operations() {
  const [view, setView] = useState<View>("low");
  return (
    <div className="page">
      <PageHeader title="Əməliyyatlar" subtitle="Anbar, son istifadə tarixləri, partiya izlənməsi və satış. Hər şey sizin filial icazənizlə göstərilir." />
      <Tabs<View>
        value={view}
        onChange={setView}
        items={[
          { id: "low", label: "Az qalan dərmanlar" },
          { id: "expiring", label: "Vaxtı bitən partiyalar" },
          { id: "trace", label: "Partiya izlənməsi" },
          { id: "sale", label: "Yeni satış" },
        ]}
      />
      <Card>
        {view === "low" && <Low />}
        {view === "expiring" && <Expiring />}
        {view === "trace" && <Trace />}
        {view === "sale" && <Sale />}
      </Card>
    </div>
  );
}
