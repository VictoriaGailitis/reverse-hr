import { useEffect, useState, type ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import { navigation, routeFor } from "../design/catalog";
import type { Screen } from "../design/types";
import { Badge } from "./Badge";
import { useDemo } from "../state/DemoContext";
import { useBackend } from "../state/BackendContext";
import { ConnectionPanel } from "../features/backend/ConnectionPanel";

export function AppShell({
  screen,
  children,
}: {
  screen: Screen;
  children: ReactNode;
}) {
  const location = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);
  const { notice, toast } = useDemo();
  const { mode, session } = useBackend();
  useEffect(() => {
    setMenuOpen(false);
    window.scrollTo(0, 0);
  }, [location.key]);
  const roles = session.roles ?? [];
  const activeRole =
    mode === "api"
      ? (new URLSearchParams(location.search).has("organization") ||
          new URLSearchParams(location.search).get("role") === "employer") &&
        roles.includes("employer")
        ? "employer"
        : roles.includes(screen.role) ||
            (screen.role === "admin" &&
              roles.some((r) =>
                [
                  "assessment_reviewer",
                  "company_moderator",
                  "content_admin",
                  "privacy_officer",
                ].includes(r),
              ))
          ? screen.role
          : roles.includes("candidate")
            ? "candidate"
            : roles.includes("employer")
              ? "employer"
              : "admin"
      : screen.role;
  const adminNavigation: [string, string][] = [
    ["Кабинет проверяющего", "/admin"],
    ...(roles.includes("assessment_reviewer")
      ? [["Оценки и апелляции", "/admin?tab=reviews"] as [string, string]]
      : []),
    ...(roles.includes("company_moderator")
      ? ([
          ["Вакансии", "/admin?tab=vacancies"],
          ["Жалобы", "/admin?tab=complaints"],
        ] as [string, string][])
      : []),
    ...(roles.includes("content_admin")
      ? [["Задания компаний", "/admin?tab=content"] as [string, string]]
      : []),
    ...(roles.includes("privacy_officer")
      ? [["Обращения о данных", "/admin?tab=rights"] as [string, string]]
      : []),
  ];
  const roleName =
    activeRole === "candidate"
      ? "Кандидат"
      : activeRole === "employer"
        ? "Работодатель"
        : "Администратор";
  return (
    <div className={`app-shell ${screen.mobile ? "mobile-artboard" : ""}`}>
      <a
        className="skip-link"
        href="#main-content"
        onClick={(event) => {
          event.preventDefault();
          document.getElementById("main-content")?.focus();
        }}
      >
        К содержимому
      </a>
      {!screen.mobile && (
        <>
          <button
            className="mobile-menu"
            aria-label="Открыть меню"
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen((value) => !value)}
          >
            ☰
          </button>
          {menuOpen && (
            <button
              className="menu-backdrop"
              aria-label="Закрыть меню"
              onClick={() => setMenuOpen(false)}
            />
          )}
          <aside className={`sidebar ${menuOpen ? "is-open" : ""}`}>
            <Link className="brand" to="/" aria-label="ФСП — главная">
              <img
                src="/brand/fsp-logo.svg"
                width="156"
                height="52.5"
                alt="ФСП"
              />
              <strong>
                ОБРАТНЫЙ
                <br />
                НАЙМ
              </strong>
              <span>{roleName}</span>
            </Link>
            <nav className="sidebar-nav" aria-label={`Навигация: ${roleName}`}>
              {(mode === "api" && activeRole === "admin"
                ? adminNavigation
                : navigation[activeRole]
              ).map(([label, key]) => (
                <Link
                  key={key}
                  className={`nav-item ${screen.key === key ? "active" : ""}`}
                  aria-current={screen.key === key ? "page" : undefined}
                  to={
                    mode === "api" && activeRole === "admin"
                      ? key
                      : mode === "api" &&
                          activeRole === "employer" &&
                          key === "vacancies"
                        ? "/vacancies?role=employer"
                        : routeFor(key)
                  }
                >
                  {mode === "api" ? label.replace(/ · \d+$/, "") : label}
                </Link>
              ))}
            </nav>
            <div className="sidebar-promo">
              <strong>
                Ваши навыки.
                <br />
                Ваши возможности.
              </strong>
              <span>Практика вместо эссе</span>
            </div>
            <Link className="button button-secondary role-switch" to="/">
              Сменить роль
            </Link>
          </aside>
        </>
      )}
      <div className="main-column">
        <header className="topbar">
          <span className="topbar-caption">
            {screen.mobile
              ? "ФСП / ОБРАТНЫЙ НАЙМ"
              : "ФСП / Платформа обратного найма"}
          </span>
          <Badge label={mode === "api" ? "API" : "ДЕМО"} />
          {!screen.mobile && (
            <strong className="topbar-user">
              {mode === "api"
                ? session.name || "Вход не выполнен"
                : screen.role === "candidate"
                  ? "Кандидат №1042"
                  : screen.role === "employer"
                    ? "Команда «Спектр»"
                    : "Проверяющий"}
            </strong>
          )}
          <ConnectionPanel />
        </header>
        <main
          id="main-content"
          className={`main-content ${mode === "api" ? "api-content" : ""}`}
          tabIndex={-1}
          key={screen.key}
        >
          {children}
        </main>
      </div>
      {notice && (
        <div className="toast" role="status">
          <span>{notice}</span>
          <button aria-label="Закрыть уведомление" onClick={() => toast("")}>
            ×
          </button>
        </div>
      )}
    </div>
  );
}
