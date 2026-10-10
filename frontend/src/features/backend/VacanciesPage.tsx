import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import type { components as H } from "../../api/generated/hiring";
import { useBackend } from "../../state/BackendContext";
import { Button } from "../../components/Button";
import { useResource } from "./Resource";
import {
  CommandStatus,
  Field,
  LoadState,
  OrganizationScope,
  useCommand,
} from "./ApiUI";
type Vacancy = H["schemas"]["VacancyView"];
type Application = H["schemas"]["ApplicationView"];
const labels: Record<string, string> = {
  draft: "Черновик",
  submitted: "На рассмотрении",
  approved: "Одобрено",
  rejected: "Отклонено",
  published: "Опубликовано",
  archived: "В архиве",
  reviewing: "Рассматривается",
  invited: "Приглашение отправлено",
  interview: "Собеседование",
  offer: "Предложение",
  hired: "Принят на работу",
  withdrawn: "Отозвано",
};
export function VacanciesPage() {
  const { session } = useBackend();
  const [params, setParams] = useSearchParams();
  const employer = params.get("role") === "employer";
  return (
    <div className="screen-form">
      <h1>Вакансии и отклики</h1>
      <div className="api-actions">
        <Button variant="secondary" onClick={() => setParams({})}>
          Для кандидата
        </Button>
        {session.roles?.includes("employer") && (
          <Button
            variant="secondary"
            onClick={() => setParams({ role: "employer" })}
          >
            Управление вакансиями компании
          </Button>
        )}
      </div>
      {employer ? (
        <OrganizationScope>
          {(org) => <Vacancies organization={org.organization_id} />}
        </OrganizationScope>
      ) : (
        <Vacancies />
      )}
    </div>
  );
}
function Vacancies({ organization }: { organization?: string }) {
  const [after, setAfter] = useState("");
  const [filter, setFilter] = useState("");
  const [query, setQuery] = useState("");
  return (
    <>
      <form
        className="api-form"
        onSubmit={(e) => {
          e.preventDefault();
          setQuery(filter);
          setAfter("");
        }}
      >
        <Field label="Фильтр специализации">
          <input value={filter} onChange={(e) => setFilter(e.target.value)} />
        </Field>
        <Button type="submit">Найти вакансии</Button>
      </form>
      {organization && <VacancyForm organization={organization} />}
      <VacancyList
        key={`${after}:${query}`}
        organization={organization}
        after={after}
        query={query}
        next={setAfter}
      />
      <Applications organization={organization} />
    </>
  );
}
function VacancyList({
  organization,
  after,
  query,
  next,
}: {
  organization?: string;
  after: string;
  query: string;
  next: (v: string) => void;
}) {
  const { api } = useBackend();
  const params = new URLSearchParams();
  if (organization) params.set("organization_id", organization);
  if (after) params.set("after", after);
  if (query) params.set("specialization", query);
  const resource = useResource((signal) =>
    api.request<Vacancy[]>("hiring", `/v1/vacancies?${params}`, { signal }),
  );
  return (
    <>
      <LoadState resource={resource} />
      {resource.status === "ready" && !resource.data?.length && (
        <p>Подходящих вакансий на этой странице нет.</p>
      )}
      {resource.data?.map((item) => (
        <VacancyCard
          key={`${item.vacancy_id}:${item.version}`}
          item={item}
          employer={!!organization}
          reload={resource.reload}
        />
      ))}
      <div className="api-actions">
        <Button variant="secondary" onClick={resource.reload}>
          Обновить вакансии
        </Button>
        {after && (
          <Button variant="secondary" onClick={() => next("")}>
            В начало списка
          </Button>
        )}
        {!!resource.data?.length && (
          <Button
            variant="secondary"
            onClick={() => next(resource.data!.at(-1)!.vacancy_id)}
          >
            Следующие вакансии
          </Button>
        )}
      </div>
    </>
  );
}
function VacancyCard({
  item,
  employer,
  reload,
}: {
  item: Vacancy;
  employer: boolean;
  reload: () => void;
}) {
  const { api } = useBackend();
  const command = useCommand();
  const [apply, setApply] = useState(false);
  const [edit, setEdit] = useState(false);
  const [archive, setArchive] = useState(false);
  const act = (action: string) =>
    command.run(async () => {
      await api.request(
        "hiring",
        `/v1/vacancies/${item.vacancy_id}/${action}`,
        {
          method: "POST",
          version: item.version,
          intent: `vacancy:${item.vacancy_id}:${action}`,
        },
      );
      reload();
    });
  return (
    <article className="api-card">
      <h2>{item.title}</h2>
      <p>{labels[item.status]}</p>
      <p className="invitation-description">{item.description}</p>
      <p>
        {item.salary.minimum.toLocaleString("ru-RU")}–
        {item.salary.maximum.toLocaleString("ru-RU")} ₽ / месяц ·{" "}
        {item.salary.tax_basis === "gross" ? "до вычета налогов" : "на руки"}
      </p>
      <p>
        {item.requirements.specialization} · {item.requirements.confirmed_grade}
      </p>
      <p>
        Навыки: {item.requirements.required_skills?.join(", ") || "не указаны"}
      </p>
      <p>Контакт работодателя: {item.employer_contact}</p>
      {employer ? (
        <>
          <div className="api-actions">
            {["draft", "rejected"].includes(item.status) && (
              <>
                <Button variant="secondary" onClick={() => setEdit((v) => !v)}>
                  Редактировать вакансию
                </Button>
                <Button
                  disabled={command.disabled}
                  onClick={() => void act("submit")}
                >
                  На модерацию
                </Button>
              </>
            )}
            {item.status === "approved" && (
              <Button
                disabled={command.disabled}
                onClick={() => void act("publish")}
              >
                Опубликовать вакансию
              </Button>
            )}
          </div>
          {item.status !== "archived" && (
            <>
              <label className="consent">
                <input
                  type="checkbox"
                  checked={archive}
                  onChange={(e) => setArchive(e.target.checked)}
                />
                <span>Подтверждаю архивирование вакансии</span>
              </label>
              <Button
                variant="secondary"
                disabled={command.disabled || !archive}
                onClick={() => void act("archive")}
              >
                Архивировать вакансию
              </Button>
            </>
          )}
          {edit && (
            <VacancyForm
              organization={item.organization_id}
              initial={item}
              saved={reload}
            />
          )}
        </>
      ) : (
        item.status === "published" && (
          <>
            <Button onClick={() => setApply((v) => !v)}>
              Просмотреть условия отклика
            </Button>
            {apply && <Apply vacancy={item} />}
          </>
        )
      )}
      <CommandStatus command={command} refresh={reload} />
    </article>
  );
}
function VacancyForm({
  organization,
  initial,
  saved,
}: {
  organization: string;
  initial?: Vacancy;
  saved?: () => void;
}) {
  const { api } = useBackend();
  const command = useCommand();
  const [title, setTitle] = useState(initial?.title ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [contact, setContact] = useState(initial?.employer_contact ?? "");
  const [minimum, setMinimum] = useState(String(initial?.salary.minimum ?? ""));
  const [maximum, setMaximum] = useState(String(initial?.salary.maximum ?? ""));
  const [tax, setTax] = useState(initial?.salary.tax_basis ?? "gross");
  const [specialization, setSpecialization] = useState(
    initial?.requirements.specialization ?? "",
  );
  const [grade, setGrade] = useState(
    initial?.requirements.confirmed_grade ?? "junior",
  );
  const [skills, setSkills] = useState(
    initial?.requirements.required_skills?.join(", ") ?? "",
  );
  const [done, setDone] = useState(false);
  return (
    <form
      className="api-card api-form"
      onSubmit={(e) => {
        e.preventDefault();
        void command.run(async () => {
          await api.request(
            "hiring",
            `/v1/vacancies${initial ? `/${initial.vacancy_id}` : ""}`,
            {
              method: initial ? "PUT" : "POST",
              body: {
                organization_id: organization,
                title: title.trim(),
                description: description.trim(),
                employer_contact: contact.trim(),
                salary: {
                  minimum: Number(minimum),
                  maximum: Number(maximum),
                  tax_basis: tax,
                  currency: "RUB",
                  period: "month",
                },
                requirements: {
                  organization_id: organization,
                  specialization,
                  confirmed_grade: grade,
                  required_skills: skills
                    .split(",")
                    .map((x) => x.trim())
                    .filter(Boolean),
                },
                conditions: initial?.conditions ?? null,
              },
              version: initial?.version,
              intent: `save-vacancy:${initial?.vacancy_id ?? organization}`,
            },
          );
          setDone(true);
          saved?.();
        }, "Вакансия сохранена. Обновите список для дальнейших действий.");
      }}
    >
      <h2>{initial ? "Изменить вакансию" : "Создать вакансию"}</h2>
      {[
        ["Название вакансии", title, setTitle, 200],
        ["Описание вакансии", description, setDescription, 5000],
        ["Контакт для вакансии", contact, setContact, 300],
        ["Специализация вакансии", specialization, setSpecialization, 100],
      ].map(([label, value, setter, max]) => (
        <Field key={String(label)} label={String(label)}>
          <input
            required
            maxLength={Number(max)}
            value={String(value)}
            onChange={(e) => (setter as (v: string) => void)(e.target.value)}
          />
        </Field>
      ))}
      <Field label="Грейд вакансии">
        <select
          value={grade}
          onChange={(e) => setGrade(e.target.value as typeof grade)}
        >
          {["junior", "middle", "senior", "lead"].map((x) => (
            <option key={x}>{x}</option>
          ))}
        </select>
      </Field>
      <Field label="Навыки вакансии через запятую">
        <input value={skills} onChange={(e) => setSkills(e.target.value)} />
      </Field>
      <Field label="Зарплата вакансии от">
        <input
          required
          type="number"
          min="1"
          value={minimum}
          onChange={(e) => setMinimum(e.target.value)}
        />
      </Field>
      <Field label="Зарплата вакансии до">
        <input
          required
          type="number"
          min={minimum || "1"}
          value={maximum}
          onChange={(e) => setMaximum(e.target.value)}
        />
      </Field>
      <Field label="Налоги в вакансии">
        <select
          value={tax}
          onChange={(e) => setTax(e.target.value as typeof tax)}
        >
          <option value="gross">До вычета налогов</option>
          <option value="net">На руки</option>
        </select>
      </Field>
      <Button
        type="submit"
        disabled={
          command.disabled ||
          done ||
          !title.trim() ||
          !description.trim() ||
          Number(maximum) < Number(minimum)
        }
      >
        Сохранить вакансию
      </Button>
      <CommandStatus command={command} refresh={saved} />
    </form>
  );
}
function Apply({ vacancy }: { vacancy: Vacancy }) {
  const { api } = useBackend();
  const command = useCommand();
  const [checked, setChecked] = useState(false);
  const [done, setDone] = useState(false);
  const resource = useResource((signal) =>
    api.request<H["schemas"]["ApplicationPreview"]>(
      "hiring",
      `/v1/vacancies/${vacancy.vacancy_id}/application-preview`,
      { signal },
    ),
  );
  return (
    <section className="api-card">
      <LoadState resource={resource} />
      {resource.data && (
        <>
          <p>
            Передаваемые поля:{" "}
            {resource.data.shared_fields
              .map(
                (x) =>
                  ({
                    candidate_id: "идентификатор",
                    display_name: "имя",
                    specialization: "специализация",
                    confirmed_grade: "подтверждённый грейд",
                    declared_skills: "заявленные навыки",
                    qualification: "подтверждения квалификации",
                  })[x] ?? x,
              )
              .join(", ")}
          </p>
          <p>Контакты при отклике не раскрываются.</p>
          <label className="consent">
            <input
              type="checkbox"
              checked={checked}
              onChange={(e) => setChecked(e.target.checked)}
            />
            <span>Подтверждаю отклик и передачу перечисленных данных</span>
          </label>
          <Button
            disabled={command.disabled || !checked || done}
            onClick={() =>
              void command.run(async () => {
                await api.request(
                  "hiring",
                  `/v1/vacancies/${vacancy.vacancy_id}/applications`,
                  {
                    method: "POST",
                    body: { vacancy_version: resource.data!.vacancy.version },
                    intent: `apply:${vacancy.vacancy_id}`,
                  },
                );
                setDone(true);
              }, "Отклик отправлен.")
            }
          >
            Отправить отклик
          </Button>
        </>
      )}
      <CommandStatus command={command} refresh={resource.reload} />
    </section>
  );
}
function Applications({ organization }: { organization?: string }) {
  const [after, setAfter] = useState("");
  return (
    <ApplicationList
      key={after}
      organization={organization}
      after={after}
      next={setAfter}
    />
  );
}
function ApplicationList({
  organization,
  after,
  next,
}: {
  organization?: string;
  after: string;
  next: (v: string) => void;
}) {
  const { api } = useBackend();
  const p = new URLSearchParams();
  if (organization) p.set("organization_id", organization);
  if (after) p.set("after", after);
  const resource = useResource((signal) =>
    api.request<Application[]>("hiring", `/v1/applications?${p}`, { signal }),
  );
  return (
    <section className="screen-form">
      <h2>{organization ? "Отклики кандидатов" : "Мои отклики"}</h2>
      <LoadState resource={resource} />
      {resource.status === "ready" && !resource.data?.length && (
        <p>На этой странице откликов нет.</p>
      )}
      {resource.data?.map((item) => (
        <ApplicationCard
          key={`${item.application_id}:${item.version}`}
          item={item}
          employer={!!organization}
          reload={resource.reload}
        />
      ))}
      <Button variant="secondary" onClick={resource.reload}>
        Обновить отклики
      </Button>
      {!!resource.data?.length && (
        <Button
          variant="secondary"
          onClick={() => next(resource.data!.at(-1)!.application_id)}
        >
          Следующие отклики
        </Button>
      )}
      {after && (
        <Button variant="secondary" onClick={() => next("")}>
          В начало откликов
        </Button>
      )}
    </section>
  );
}
function ApplicationCard({
  item,
  employer,
  reload,
}: {
  item: Application;
  employer: boolean;
  reload: () => void;
}) {
  const { api } = useBackend();
  const command = useCommand();
  const [status, setStatus] = useState("reviewing");
  const [withdraw, setWithdraw] = useState(false);
  const act = (action: string, body?: unknown) =>
    command.run(async () => {
      await api.request(
        "hiring",
        `/v1/applications/${item.application_id}/${action}`,
        {
          method: "POST",
          body,
          version: item.version,
          intent: `application:${item.application_id}:${action}`,
        },
      );
      reload();
    });
  return (
    <article className="api-card">
      <h3>{item.vacancy_snapshot.title}</h3>
      <p>{labels[item.status]}</p>
      {employer ? (
        <>
          <p>Кандидат {item.candidate_id}</p>
          <Field label="Новый статус отклика">
            <select value={status} onChange={(e) => setStatus(e.target.value)}>
              {["reviewing", "interview", "offer", "hired", "rejected"].map(
                (x) => (
                  <option key={x} value={x}>
                    {labels[x]}
                  </option>
                ),
              )}
            </select>
          </Field>
          <Button
            disabled={command.disabled}
            onClick={() => void act("status", { status })}
          >
            Изменить статус
          </Button>
          {!item.invitation_id && (
            <Button
              disabled={command.disabled}
              onClick={() => void act("invite", {})}
            >
              Пригласить по условиям вакансии
            </Button>
          )}
        </>
      ) : (
        item.status !== "withdrawn" && (
          <>
            <label className="consent">
              <input
                type="checkbox"
                checked={withdraw}
                onChange={(e) => setWithdraw(e.target.checked)}
              />
              <span>Подтверждаю отзыв отклика</span>
            </label>
            <Button
              variant="secondary"
              disabled={command.disabled || !withdraw}
              onClick={() => void act("withdraw")}
            >
              Отозвать отклик
            </Button>
          </>
        )
      )}
      {item.invitation_id && (
        <Link
          to={
            employer
              ? "/employer/invitation/new"
              : `/candidate/invitations?invitation=${item.invitation_id}`
          }
        >
          Открыть приглашение
        </Link>
      )}
      <CommandStatus command={command} refresh={reload} />
    </article>
  );
}
