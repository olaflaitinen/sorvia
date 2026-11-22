import { useCallback, useEffect, useState } from "react";
import { api, type Recommendation, type Stats } from "../api";
import { useAuth } from "../auth";
import { STATUS_LABEL, formatDate, reasonText } from "../labels";
import { Alert, Button, Card, Empty, PageHeader, SqlBlock, Spinner, StatusBadge } from "../components/ui";

export function Admin() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [stats, setStats] = useState<Stats | null>(null);
  const [recs, setRecs] = useState<Recommendation[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<{ kind: "success" | "error" | "info"; text: string } | null>(null);

  const load = useCallback(() => {
    api.stats(30).then(setStats).catch((e) => setMessage({ kind: "error", text: (e as Error).message }));
    api.recommendations().then(setRecs).catch(() => setRecs([]));
  }, []);
  useEffect(load, [load]);

  async function run(label: string, fn: () => Promise<unknown>, ok: string) {
    setBusy(label);
    setMessage(null);
    try {
      await fn();
      setMessage({ kind: "success", text: ok });
      load();
    } catch (e) {
      setMessage({ kind: "error", text: (e as Error).message });
    } finally {
      setBusy(null);
    }
  }

  const total = stats?.by_status.reduce((a, s) => a + s.n, 0) ?? 0;

  return (
    <div className="page">
      <PageHeader title="İdarəetmə" subtitle="Son 30 gündə sistemin necə işlədiyi və bazanın özünü optimallaşdırması." />
      {message && <Alert kind={message.kind}>{message.text}</Alert>}

      <div className="stat-grid">
        <div className="stat">
          <div className="stat-label">Ümumi sual</div>
          <div className="stat-value">{stats ? total : "..."}</div>
        </div>
        {stats?.by_status.map((s) => (
          <div className="stat" key={s.status}>
            <div className="stat-label"><StatusBadge status={s.status} /></div>
            <div className="stat-value">{s.n}</div>
            <div className="muted small mono">orta {Math.round(s.avg_ms ?? 0)} ms, p95 {s.p95_ms ?? 0} ms</div>
          </div>
        ))}
        <div className="stat">
          <div className="stat-label">İstifadəçi rəyi</div>
          <div className="stat-value">{stats?.feedback.accuracy != null ? `${Math.round(stats.feedback.accuracy * 100)}%` : "-"}</div>
          <div className="muted small">{stats?.feedback.rated ?? 0} qiymətləndirmə</div>
        </div>
      </div>

      <Card title="Bloklanma səbəbləri">
        {!stats && <Spinner />}
        {stats && stats.blocked_reasons.length === 0 && <Empty>Bloklanmış sual yoxdur.</Empty>}
        <ul className="reasons">
          {stats?.blocked_reasons.map((r) => (
            <li key={r.block_reason ?? "none"}>
              <span className="mono">{r.block_reason}</span> <b>{r.n}</b>
              <div className="muted small">{reasonText(r.block_reason)}</div>
            </li>
          ))}
        </ul>
      </Card>

      <Card
        title="İndeks məsləhətçisi"
        actions={
          isAdmin && (
            <Button onClick={() => run("advisor", api.runAdvisor, "Məsləhətçi iş yükünü təhlil etdi.")} disabled={busy !== null}>
              {busy === "advisor" ? "Təhlil olunur..." : "İş yükünü təhlil et"}
            </Button>
          )
        }
      >
        <p className="muted">
          Məsləhətçi uğurlu sorğuların planlarını öyrənir, HypoPG ilə hipotetik indeksləri yoxlayır və ən çox qazanc verənləri
          tövsiyə edir. İndeks real yaradılmadan əvvəl onun təsiri ölçülür.
        </p>
        {!recs && <Spinner />}
        {recs && recs.length === 0 && <Empty>Hələ tövsiyə yoxdur. Bir neçə sual verin və təhlili işə salın.</Empty>}
        {recs?.map((r) => (
          <div className="rec" key={r.recommendation_id}>
            <div className="rec-head">
              <b className="mono">{r.table_name} ({r.columns.join(", ")})</b>
              <span className={`tag tag-${r.status}`}>{r.status === "proposed" ? "təklif" : r.status === "applied" ? "tətbiq olunub" : "rədd edilib"}</span>
              <span className="muted small">
                təxmini qazanc <b>{r.improvement_pct.toFixed(1)}%</b>, iş yükü {r.workload_size} sorğu, {formatDate(r.created_at)}
              </span>
            </div>
            <SqlBlock sql={r.index_ddl} />
            {isAdmin && r.status === "proposed" && (
              <div className="rec-actions">
                <Button onClick={() => run(`apply${r.recommendation_id}`, () => api.applyRecommendation(r.recommendation_id), "İndeks yaradıldı.")} disabled={busy !== null}>
                  Tətbiq et
                </Button>
                <Button variant="secondary" onClick={() => run(`reject${r.recommendation_id}`, () => api.rejectRecommendation(r.recommendation_id), "Tövsiyə rədd edildi.")} disabled={busy !== null}>
                  Rədd et
                </Button>
              </div>
            )}
          </div>
        ))}
      </Card>

      <Card
        title="Analitik sxem"
        actions={
          <Button variant="secondary" onClick={() => run("etl", api.refreshAnalytics, "Ulduz sxemi yeniləndi.")} disabled={busy !== null}>
            {busy === "etl" ? "Yenilənir..." : "Yenilə"}
          </Button>
        }
      >
        <p className="muted">
          Yeni satışları analitik ulduz sxeminə (analytics.fact_sales) köçürür. Analitik suallar oradan daha sürətli cavablanır.
        </p>
      </Card>

      <p className="muted small">Statuslar: {Object.values(STATUS_LABEL).join(", ")}.</p>
    </div>
  );
}
