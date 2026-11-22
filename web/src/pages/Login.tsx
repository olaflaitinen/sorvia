import { useState, type FormEvent } from "react";
import { Navigate } from "react-router-dom";
import { ApiError } from "../api";
import { useAuth } from "../auth";
import { Alert, Button, Logo, Mark, Slogan } from "../components/ui";

const DEMO = [
  { username: "admin", label: "Administrator", note: "bütün filiallar, indeks məsləhətçisi" },
  { username: "menecer", label: "Menecer", note: "bütün filiallar, statistika" },
  { username: "aysel.bak01", label: "Əczaçı, BAK01", note: "yalnız Nizami filialı" },
  { username: "tural.gnc01", label: "Əczaçı, GNC01", note: "yalnız Gəncə Mərkəz" },
];

export function Login() {
  const { user, login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (user) return <Navigate to="/" replace />;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(username, password);
    } catch (err) {
      setError(err instanceof ApiError && err.status === 401 ? "İstifadəçi adı və ya parol yanlışdır." : (err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login" data-theme-scope>
      <section className="login-hero" data-theme="dark">
        <div className="login-hero-inner">
          <Mark />
          <Slogan />
          <p className="login-lead">
            Verilənlər bazasına Azərbaycan dilində sual verin. Sorvia sualı SQL-ə çevirir, onu üç təhlükəsizlik qatından
            keçirir və cavabı cədvəl və qrafik şəklində qaytarır.
          </p>
          <ul className="login-points">
            <li>Model yalnız oxuya bilər; yazma əmrləri bazanın özü tərəfindən bloklanır.</li>
            <li>Hər istifadəçi yalnız öz filialının məlumatını görür (Row-Level Security).</li>
            <li>Baza iş yükünə baxıb özü indeks tövsiyə edir.</li>
          </ul>
        </div>
      </section>
      <section className="login-form-wrap">
        <form className="login-form" onSubmit={submit}>
          <Logo size={30} />
          <h1>Daxil olun</h1>
          {error && <Alert kind="error">{error}</Alert>}
          <label>
            İstifadəçi adı
            <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" required minLength={3} />
          </label>
          <label>
            Parol
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required minLength={8} />
          </label>
          <Button type="submit" disabled={busy}>
            {busy ? "Yoxlanılır..." : "Daxil ol"}
          </Button>
          <div className="demo">
            <div className="demo-title">Demo hesablar</div>
            {DEMO.map((d) => (
              <button type="button" key={d.username} className="demo-item" onClick={() => setUsername(d.username)}>
                <span>
                  <b>{d.username}</b> <span className="muted">{d.label}</span>
                </span>
                <span className="muted small">{d.note}</span>
              </button>
            ))}
            <p className="muted small">Demo parolu layihə müəllifindən alın.</p>
          </div>
        </form>
      </section>
    </div>
  );
}
