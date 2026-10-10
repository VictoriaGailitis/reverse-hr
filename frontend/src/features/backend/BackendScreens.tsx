import { useEffect, useRef } from "react";
import { Link, useNavigate } from "react-router-dom";
import type { Screen } from "../../design/types";
import { useBackend } from "../../state/BackendContext";
import { initializeSession, login } from "../../auth/session";
import { Button } from "../../components/Button";
import { ProfilePage } from "./ProfilePage";
import { PrivacyPage } from "./PrivacyPage";
import { PortalPage } from "./PortalPage";
import { AdminPage, ReviewPage } from "./AdminPage";
import { AtsPage } from "./AtsPage";
import { CompanyTasksPage } from "./CompanyTasksPage";
import { VacanciesPage } from "./VacanciesPage";
import { AchievementsPage } from "./AchievementsPage";
import { AssessmentPage } from "./AssessmentPage";
import { HiringPage } from "./HiringPage";
import { MessagesPage } from "./MessagesPage";
import { InvitationsPage } from "./InvitationsPage";
import { OrganizationPage } from "./OrganizationPage";

export function AuthCallback() {
  const { session } = useBackend();
  const navigate = useNavigate();
  const redirected = useRef(false);
  useEffect(() => {
    if (session.status !== "authenticated" || redirected.current) return;
    redirected.current = true;
    let destination = "/candidate/profile";
    try {
      const saved = sessionStorage.getItem("fsp:return-to");
      sessionStorage.removeItem("fsp:return-to");
      if (
        saved?.startsWith("/") &&
        !saved.startsWith("//") &&
        !saved.includes("\\") &&
        !saved.startsWith("/auth/")
      )
        destination = saved;
    } catch {
      /* Use the default route. */
    }
    navigate(destination, { replace: true });
  }, [session.status, navigate]);
  return (
    <main className="not-found">
      <h1>Вход в платформу</h1>
      <AuthGate />
    </main>
  );
}

function AuthGate({ registration = false }: { registration?: boolean }) {
  const { session } = useBackend();
  return (
    <section className="api-card">
      <p role={session.status === "error" ? "alert" : "status"}>
        {session.status === "loading"
          ? "Подключаем сервер входа…"
          : session.status === "authenticated"
            ? "Вход выполнен"
            : session.status === "expired"
              ? "Сессия истекла. Войдите снова, чтобы продолжить."
              : (session.error ??
                "Для работы с данными сервера нужен вход через Keycloak.")}
      </p>
      {session.status !== "authenticated" && (
        <Button
          disabled={session.status === "loading"}
          onClick={() =>
            void (session.status === "error"
              ? initializeSession()
              : login(registration))
          }
        >
          {session.status === "error"
            ? "Повторить подключение"
            : registration
              ? "Зарегистрироваться через Keycloak"
              : "Войти через Keycloak"}
        </Button>
      )}
    </section>
  );
}

export function BackendScreens({ screen }: { screen: Screen }) {
  const { session, setMode } = useBackend();
  const entered = useRef(false);
  if (session.status === "authenticated") entered.current = true;
  if (screen.key === "login")
    return (
      <div className="screen-form">
        <h1>Начните с профиля</h1>
        <p>Аккаунт создаётся на сервере входа.</p>
        <AuthGate registration />
        {session.status === "authenticated" && (
          <Link className="button button-primary" to="/candidate/profile">
            Открыть профиль
          </Link>
        )}
      </div>
    );
  if (!entered.current)
    return (
      <div className="screen-form">
        <h1>{screen.name.replace(/^\d+ · /, "")}</h1>
        <AuthGate />
      </div>
    );
  let content;
  if (
    screen.key === "start" ||
    screen.key === "dashboard" ||
    screen.key === "mobile-dashboard"
  )
    content = <PortalPage overview={screen.key !== "start"} />;
  else if (screen.key === "candidate") content = <HiringPage mode="search" />;
  else if (screen.key === "profile") content = <ProfilePage />;
  else if (screen.key === "achievements") content = <AchievementsPage />;
  else if (screen.key === "privacy") content = <PrivacyPage />;
  else if (
    [
      "invitations",
      "disclose",
      "disclosure-pending",
      "mobile-invite",
      "mobile-disclose",
    ].includes(screen.key)
  )
    content = <InvitationsPage />;
  else if (
    screen.key === "need" ||
    screen.key === "search" ||
    screen.key === "offer"
  )
    content = <HiringPage mode={screen.key} />;
  else if (
    [
      "assessment",
      "equipment",
      "equipment-ready",
      "editor",
      "code-queued",
      "video",
      "video-recording",
      "video-preview",
      "board",
      "processing",
      "result",
    ].includes(screen.key)
  )
    content = <AssessmentPage />;
  else if (screen.key === "admin") content = <AdminPage />;
  else if (screen.key === "review") content = <ReviewPage />;
  else if (screen.key === "ats") content = <AtsPage />;
  else if (screen.key === "constructor") content = <CompanyTasksPage />;
  else if (screen.key === "vacancies") content = <VacanciesPage />;
  else if (screen.key === "messages") content = <MessagesPage />;
  else if (screen.key === "organization") content = <OrganizationPage />;
  else
    content = (
      <div className="screen-form">
        <h1>{screen.name.replace(/^\d+ · /, "")}</h1>
        <section className="api-card">
          <h2>Подключение сервисов</h2>
          <p>
            В первом этапе подключены базовые сервисы; теперь доступны найм,
            оценка, резюме, достижения, вакансии, задания и проверка. Этот
            служебный экран остаётся демонстрацией состояний.
          </p>
          <div className="api-actions">
            <Link className="button button-primary" to="/candidate/profile">
              Профиль
            </Link>
            <Link className="button button-secondary" to="/candidate/privacy">
              Приватность
            </Link>
            <Link className="button button-secondary" to="/employer">
              Организации
            </Link>
          </div>
          <Button variant="secondary" onClick={() => setMode("demo")}>
            Открыть деморежим
          </Button>
        </section>
      </div>
    );
  return (
    <>
      {session.status !== "authenticated" && <AuthGate />}
      {content}
    </>
  );
}
