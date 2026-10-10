import { Link } from "react-router-dom";
import { useBackend } from "../../state/BackendContext";
import { Notifications } from "./MessagesPage";
export function PortalPage({ overview = false }: { overview?: boolean }) {
  const { session } = useBackend();
  const candidate = session.roles?.includes("candidate");
  const employer = session.roles?.includes("employer");
  const reviewer = session.roles?.some((r) =>
    [
      "assessment_reviewer",
      "company_moderator",
      "content_admin",
      "privacy_officer",
    ].includes(r),
  );
  return (
    <div className="screen-form">
      <h1>{overview ? "Ваш кабинет" : "Платформа обратного найма"}</h1>
      <p>Выберите доступный раздел.</p>
      {candidate && (
        <section className="api-card">
          <h2>Кандидат</h2>
          <div className="api-actions">
            {[
              ["/candidate/profile", "Профиль и резюме"],
              ["/candidate/assessment", "Оценить навыки"],
              ["/candidate/assessment?tab=company", "Задания компаний"],
              ["/candidate/achievements", "Достижения"],
              ["/candidate/invitations", "Приглашения"],
              ["/vacancies", "Вакансии и отклики"],
              ["/messages", "Переписка"],
              ["/candidate/privacy", "Приватность"],
            ].map(([url, name]) => (
              <Link className="button button-secondary" key={url} to={url}>
                {name}
              </Link>
            ))}
          </div>
        </section>
      )}
      {employer && (
        <section className="api-card">
          <h2>Работодатель</h2>
          <div className="api-actions">
            {[
              ["/employer", "Компания и сотрудники"],
              ["/employer/need", "Потребности"],
              ["/employer/search", "Подбор кандидатов"],
              ["/employer/invitation/new", "Приглашения"],
              ["/vacancies?role=employer", "Вакансии компании"],
              ["/employer/tasks", "Задания"],
              ["/employer/integrations/ats", "Демо-ATS"],
            ].map(([url, name]) => (
              <Link className="button button-secondary" key={url} to={url}>
                {name}
              </Link>
            ))}
          </div>
        </section>
      )}
      {reviewer && (
        <Link className="button button-primary" to="/admin">
          Кабинет проверяющего
        </Link>
      )}
      {!candidate && !employer && !reviewer && (
        <p>Пользователь вошёл, но рабочие роли ещё не назначены.</p>
      )}
      {overview && <Notifications employer={!candidate && !!employer} />}
    </div>
  );
}
