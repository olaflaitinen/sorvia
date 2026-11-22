import { NavLink, Outlet } from "react-router-dom";
import { useAuth, useTheme } from "../auth";
import { ROLE_LABEL } from "../labels";
import { Logo } from "./ui";

const NAV = [
  { to: "/", label: "Sual ver", end: true, roles: null },
  { to: "/history", label: "Tarixçə", end: false, roles: null },
  { to: "/operations", label: "Əməliyyatlar", end: false, roles: null },
  { to: "/schema", label: "Məlumat xəritəsi", end: false, roles: null },
  { to: "/admin", label: "İdarəetmə", end: false, roles: ["admin", "manager"] },
] as const;

export function Layout() {
  const { user, logout } = useAuth();
  const [theme, toggleTheme] = useTheme();
  if (!user) return null;
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="sidebar-logo">
          <Logo size={26} />
        </div>
        <nav aria-label="Əsas menyu">
          {NAV.filter((n) => !n.roles || (n.roles as readonly string[]).includes(user.role)).map((n) => (
            <NavLink key={n.to} to={n.to} end={n.end} className={({ isActive }) => (isActive ? "nav-item active" : "nav-item")}>
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot">
          <div className="user-box">
            <div className="user-name">{user.display_name}</div>
            <div className="user-role">
              {ROLE_LABEL[user.role]}
              {user.branch_id ? ` · filial ${user.branch_id}` : " · bütün filiallar"}
            </div>
          </div>
          <div className="sidebar-actions">
            <button className="btn btn-ghost" onClick={toggleTheme} aria-label="Rejimi dəyiş">
              {theme === "dark" ? "Açıq rejim" : "Tünd rejim"}
            </button>
            <button className="btn btn-ghost" onClick={logout}>
              Çıxış
            </button>
          </div>
        </div>
      </aside>
      <main className="main">
        <Outlet />
      </main>
    </div>
  );
}
