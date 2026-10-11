import { SpecializationInput } from "../../components/SpecializationInput";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import type { components as Hiring } from "../../api/generated/hiring";
import type { components as Matching } from "../../api/generated/matching";
import type { Invitation } from "../../api/types";
import { useBackend } from "../../state/BackendContext";
import { Button } from "../../components/Button";
import { useResource } from "./Resource";
import {
  CommandStatus,
  Field,
  LoadState,
  OrganizationScope,
  useCommand,
  uuidPattern,
} from "./ApiUI";
import { InvitationSummary } from "./InvitationsPage";
type Need = Hiring["schemas"]["NeedView"];
type NeedCommand = Hiring["schemas"]["NeedCommand"];
type Match = Matching["schemas"]["MatchResult"];

export function HiringPage({ mode }: { mode: "need" | "search" | "offer" }) {
  return (
    <div className="screen-form">
      <h1>
        {mode === "need"
          ? "Потребности в найме"
          : mode === "search"
            ? "Подбор кандидатов"
            : "Приглашения компании"}
      </h1>
      <OrganizationScope>
        {(org) =>
          mode === "offer" ? (
            <EmployerInvitations organization={org.organization_id} />
          ) : (
            <Needs
              organization={org.organization_id}
              search={mode === "search"}
            />
          )
        }
      </OrganizationScope>
    </div>
  );
}
function Needs({
  organization,
  search,
}: {
  organization: string;
  search: boolean;
}) {
  const { api } = useBackend();
  const [params, setParams] = useSearchParams();
  const [after, setAfter] = useState("");
  return (
    <NeedsPage
      key={after}
      organization={organization}
      search={search}
      after={after}
      next={setAfter}
      snapshot={params.get("snapshot")}
      setSnapshot={(value, need) =>
        setParams({ snapshot: value, need, organization })
      }
      api={api}
    />
  );
}
function NeedsPage({
  organization,
  search,
  after,
  next,
  snapshot,
  setSnapshot,
  api,
}: {
  organization: string;
  search: boolean;
  after: string;
  next: (v: string) => void;
  snapshot: string | null;
  setSnapshot: (v: string, need: string) => void;
  api: ReturnType<typeof useBackend>["api"];
}) {
  const resource = useResource((signal) =>
    api.request<Need[]>(
      "hiring",
      `/v1/hiring-needs?organization_id=${organization}${after ? `&after=${after}` : ""}`,
      { signal },
    ),
  );
  const [editing, setEditing] = useState<Need>();
  return (
    <>
      <LoadState resource={resource} />
      {resource.status === "ready" && (
        <>
          {!search && (
            <NeedForm
              key={editing?.need_id ?? "new"}
              organization={organization}
              initial={editing}
              saved={() => {
                setEditing(undefined);
                resource.reload();
              }}
            />
          )}
          {!resource.data?.length && <p>На этой странице потребностей нет.</p>}
          {resource.data?.map((need) => (
            <section className="api-card" key={need.need_id}>
              <h2>
                {need.specialization} · {need.confirmed_grade}
              </h2>
              <p>
                {need.required_skills?.join(", ") ||
                  "Обязательные навыки не указаны"}
              </p>
              <p>
                {need.status === "published"
                  ? "Опубликована"
                  : need.status === "closed"
                    ? "Закрыта"
                    : "Черновик"}
              </p>
              {search ? (
                <MatchSearch need={need} saved={setSnapshot} />
              ) : (
                <Button variant="secondary" onClick={() => setEditing(need)}>
                  Редактировать потребность
                </Button>
              )}
            </section>
          ))}
          <div className="api-actions">
            <Button variant="secondary" onClick={resource.reload}>
              Обновить потребности
            </Button>
            {after && (
              <Button variant="secondary" onClick={() => next("")}>
                К началу списка
              </Button>
            )}
            {!!resource.data?.length && (
              <Button
                variant="secondary"
                onClick={() => next(resource.data!.at(-1)!.need_id)}
              >
                Следующая страница потребностей
              </Button>
            )}
            <Link to={search ? "/employer/need" : "/employer/search"}>
              {search ? "Создать потребность" : "Перейти к подбору"}
            </Link>
          </div>
        </>
      )}
      {snapshot && (
        <MatchResults
          key={`${organization}:${snapshot}`}
          id={snapshot}
          organization={organization}
        />
      )}
    </>
  );
}
function NeedForm({
  organization,
  initial,
  saved,
}: {
  organization: string;
  initial?: Need;
  saved: () => void;
}) {
  const { api } = useBackend();
  const command = useCommand();
  const [specialization, setSpecialization] = useState(
    initial?.specialization ?? "",
  );
  const [grade, setGrade] = useState<NeedCommand["confirmed_grade"]>(
    initial?.confirmed_grade ?? "junior",
  );
  const [skills, setSkills] = useState(
    initial?.required_skills?.join(", ") ?? "",
  );
  const [status, setStatus] = useState<NeedCommand["status"]>(
    initial?.status ?? "draft",
  );
  return (
    <form
      className="api-card api-form"
      onSubmit={(event) => {
        event.preventDefault();
        void command.run(async () => {
          await api.request<Need>(
            "hiring",
            `/v1/hiring-needs${initial ? `/${initial.need_id}` : ""}`,
            {
              method: initial ? "PUT" : "POST",
              body: {
                organization_id: organization,
                specialization: specialization.trim(),
                confirmed_grade: grade,
                required_skills: skills
                  .split(",")
                  .map((x) => x.trim())
                  .filter(Boolean),
                status,
                conditions: initial?.conditions ?? null,
              },
              version: initial?.version,
              intent: `need:${organization}:${initial?.need_id ?? "new"}`,
            },
          );
          saved();
        });
      }}
    >
      <h2>{initial ? "Изменить потребность" : "Новая потребность"}</h2>
      <Field label="Специализация">
        <SpecializationInput
          required
          maxLength={100}
          value={specialization}
          onChange={(e) => setSpecialization(e.target.value)}
        />
      </Field>
      <Field label="Минимальный подтверждённый грейд">
        <select
          value={grade}
          onChange={(e) => setGrade(e.target.value as typeof grade)}
        >
          {["junior", "middle", "senior", "lead"].map((x) => (
            <option key={x}>{x}</option>
          ))}
        </select>
      </Field>
      <Field label="Обязательные навыки через запятую">
        <input value={skills} onChange={(e) => setSkills(e.target.value)} />
      </Field>
      <Field label="Статус потребности">
        <select
          value={status}
          onChange={(e) => setStatus(e.target.value as typeof status)}
        >
          <option value="draft">Черновик</option>
          <option value="published">Опубликована</option>
          <option value="closed">Закрыта</option>
        </select>
      </Field>
      <Button
        type="submit"
        disabled={command.disabled || !specialization.trim()}
      >
        Сохранить потребность
      </Button>
      <CommandStatus command={command} refresh={saved} />
    </form>
  );
}
function MatchSearch({
  need,
  saved,
}: {
  need: Need;
  saved: (id: string, need: string) => void;
}) {
  const { api } = useBackend();
  const command = useCommand();
  const [mode, setMode] = useState<"production" | "demo">("production");
  return (
    <>
      <Field label="Данные подборки">
        <select
          value={mode}
          onChange={(e) => setMode(e.target.value as typeof mode)}
        >
          <option value="production">Рабочие подтверждённые данные</option>
          <option value="demo">Демонстрационные данные сервера</option>
        </select>
      </Field>
      <Button
        disabled={command.disabled || need.status === "closed"}
        onClick={() =>
          void command.run(async () => {
            const result = await api.request<Match>("matching", "/v1/matches", {
              method: "POST",
              body: {
                organization_id: need.organization_id,
                need_id: need.need_id,
                mode,
              },
              intent: `match:${need.need_id}`,
            });
            saved(result.snapshot_id, need.need_id);
          }, "Подборка получена.")
        }
      >
        Подобрать кандидатов
      </Button>
      <CommandStatus command={command} />
    </>
  );
}
function MatchResults({
  id,
  organization,
}: {
  id: string;
  organization: string;
}) {
  const [params, setParams] = useSearchParams();
  const command = useCommand();
  const { api } = useBackend();
  const resource = useResource((signal) =>
    api.request<Match>("matching", `/v1/matches/${encodeURIComponent(id)}`, {
      signal,
    }),
  );
  return (
    <section className="api-card">
      <h2>Результаты подбора</h2>
      <LoadState resource={resource} />
      {resource.status === "ready" && resource.data && (
        <>
          <p>
            {resource.data.mode === "demo"
              ? "ДЕМО · тестовые результаты сервера"
              : "Рабочая подборка"}
          </p>
          {!resource.data.matches.length && (
            <p>Совпадений нет. Измените критерии потребности.</p>
          )}
          {resource.data.matches.map((candidate) => (
            <article className="api-card" key={candidate.candidate_id}>
              <h3>{candidate.display_name}</h3>
              <p>
                {candidate.specialization} ·{" "}
                {candidate.confirmed_grade ?? "Грейд не подтверждён"}
              </p>
              <p>
                Заявленные навыки:{" "}
                {candidate.declared_skills?.join(", ") || "не указаны"}
              </p>
              <p>{candidate.explanation}</p>
              <p>Соответствие: {candidate.score} / 100</p>
              {candidate.demo && <p>Демо-доказательства</p>}
              <Link
                className="button button-primary"
                to={`/employer/invitation/new?candidate=${candidate.candidate_id}&organization=${organization}`}
              >
                Пригласить кандидата
              </Link>
            </article>
          ))}
          {resource.data.next_cursor && (
            <Button
              disabled={command.disabled || !params.get("need")}
              onClick={() =>
                void command.run(async () => {
                  const result = await api.request<Match>(
                    "matching",
                    "/v1/matches",
                    {
                      method: "POST",
                      body: {
                        organization_id: organization,
                        need_id: params.get("need"),
                        mode: resource.data!.mode,
                        after: resource.data!.next_cursor,
                      },
                      intent: `match-page:${id}`,
                    },
                  );
                  setParams((current) => {
                    current.set("snapshot", result.snapshot_id);
                    return current;
                  });
                }, "Следующая подборка получена.")
              }
            >
              Следующие кандидаты
            </Button>
          )}
        </>
      )}
      <CommandStatus command={command} />
    </section>
  );
}
function EmployerInvitations({ organization }: { organization: string }) {
  const { api } = useBackend();
  const [params] = useSearchParams();
  const [after, setAfter] = useState("");
  return (
    <>
      <InvitationForm
        organization={organization}
        candidate={params.get("candidate") ?? ""}
      />
      <EmployerInvitationList
        key={after}
        organization={organization}
        after={after}
        next={setAfter}
        api={api}
      />
    </>
  );
}
function InvitationForm({
  organization,
  candidate,
}: {
  organization: string;
  candidate: string;
}) {
  const { api } = useBackend();
  const command = useCommand();
  const [candidateId, setCandidate] = useState(candidate);
  const [description, setDescription] = useState("");
  const [contact, setContact] = useState("");
  const [min, setMin] = useState("");
  const [max, setMax] = useState("");
  const [tax, setTax] = useState<"gross" | "net">("gross");
  const [days, setDays] = useState(14);
  const [created, setCreated] = useState<Invitation>();
  return (
    <form
      className="api-card api-form"
      onSubmit={(e) => {
        e.preventDefault();
        void command.run(
          async () =>
            setCreated(
              await api.request<Invitation>("hiring", "/v1/invitations", {
                method: "POST",
                body: {
                  organization_id: organization,
                  candidate_id: candidateId,
                  description: description.trim(),
                  employer_contact: contact.trim(),
                  salary: {
                    minimum: Number(min),
                    maximum: Number(max),
                    currency: "RUB",
                    period: "month",
                    tax_basis: tax,
                  },
                  expires_in_days: days,
                },
                intent: `invite:${organization}:${candidateId}`,
              }),
            ),
          "Приглашение отправлено сервером.",
        );
      }}
    >
      <h2>Новое приглашение</h2>
      <Field label="Кандидат">
        <input
          required
          pattern={uuidPattern}
          value={candidateId}
          onChange={(e) => setCandidate(e.target.value)}
        />
      </Field>
      <Field label="Описание предложения">
        <textarea
          required
          maxLength={5000}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
      </Field>
      <Field label="Контакт работодателя">
        <input
          required
          maxLength={300}
          value={contact}
          onChange={(e) => setContact(e.target.value)}
        />
      </Field>
      <Field label="Зарплата от, ₽">
        <input
          required
          type="number"
          min="1"
          step="1"
          value={min}
          onChange={(e) => setMin(e.target.value)}
        />
      </Field>
      <Field label="Зарплата до, ₽">
        <input
          required
          type="number"
          min={min || "1"}
          step="1"
          value={max}
          onChange={(e) => setMax(e.target.value)}
        />
      </Field>
      <Field label="Налоги">
        <select
          value={tax}
          onChange={(e) => setTax(e.target.value as typeof tax)}
        >
          <option value="gross">До вычета налогов</option>
          <option value="net">На руки</option>
        </select>
      </Field>
      <Field label="Действует, дней">
        <input
          required
          type="number"
          min="1"
          max="90"
          value={days}
          onChange={(e) => setDays(Number(e.target.value))}
        />
      </Field>
      <Button
        type="submit"
        disabled={
          command.disabled ||
          !!created ||
          !description.trim() ||
          !contact.trim() ||
          Number(max) < Number(min)
        }
      >
        Отправить приглашение
      </Button>
      <CommandStatus command={command} />
      {created && (
        <Link
          to={`/messages?dialog=${created.invitation_id}&organization=${organization}`}
        >
          Открыть переписку после принятия
        </Link>
      )}
    </form>
  );
}
function EmployerInvitationList({
  organization,
  after,
  next,
  api,
}: {
  organization: string;
  after: string;
  next: (v: string) => void;
  api: ReturnType<typeof useBackend>["api"];
}) {
  const resource = useResource((signal) =>
    api.request<Invitation[]>(
      "hiring",
      `/v1/invitations?organization_id=${organization}${after ? `&after=${after}` : ""}`,
      { signal },
    ),
  );
  return (
    <>
      <h2>Отправленные приглашения</h2>
      <LoadState resource={resource} />
      {resource.data?.map((item) => (
        <EmployerInvitation
          key={`${item.invitation_id}:${item.version}`}
          item={item}
          reload={resource.reload}
        />
      ))}
      {resource.status === "ready" && !resource.data?.length && (
        <p>На этой странице приглашений нет.</p>
      )}
      <div className="api-actions">
        <Button variant="secondary" onClick={resource.reload}>
          Обновить приглашения
        </Button>
        {after && (
          <Button variant="secondary" onClick={() => next("")}>
            К началу
          </Button>
        )}
        {!!resource.data?.length && (
          <Button
            variant="secondary"
            onClick={() => next(resource.data!.at(-1)!.invitation_id)}
          >
            Следующая страница
          </Button>
        )}
      </div>
    </>
  );
}
function EmployerInvitation({
  item,
  reload,
}: {
  item: Invitation;
  reload: () => void;
}) {
  const { api } = useBackend();
  const command = useCommand();
  const [showContacts, setShowContacts] = useState(false);
  const [confirm, setConfirm] = useState(false);
  return (
    <article className="api-card">
      <InvitationSummary invitation={item} />
      <p>Кандидат {item.candidate_id}</p>
      {["sent", "viewed", "accepted"].includes(item.status) && (
        <>
          <label className="consent">
            <input
              type="checkbox"
              checked={confirm}
              onChange={(e) => setConfirm(e.target.checked)}
            />
            <span>Подтверждаю отзыв приглашения</span>
          </label>
          <Button
            variant="secondary"
            disabled={command.disabled || !confirm}
            onClick={() =>
              void command.run(async () => {
                await api.request(
                  "hiring",
                  `/v1/invitations/${item.invitation_id}/revoke`,
                  {
                    method: "POST",
                    version: item.version,
                    intent: `revoke-invitation:${item.invitation_id}`,
                  },
                );
                reload();
              })
            }
          >
            Отозвать приглашение
          </Button>
        </>
      )}
      {item.status === "accepted" && (
        <>
          <div className="api-actions">
            <Button
              variant="secondary"
              onClick={() => setShowContacts((v) => !v)}
            >
              {showContacts
                ? "Скрыть контакты"
                : "Проверить доступ к контактам"}
            </Button>
            <Link
              to={`/messages?dialog=${item.invitation_id}&organization=${item.organization_id}`}
            >
              Переписка
            </Link>
          </div>
          {showContacts && <Contacts id={item.invitation_id} />}
        </>
      )}
      <CommandStatus command={command} refresh={reload} />
    </article>
  );
}
function Contacts({ id }: { id: string }) {
  const { api } = useBackend();
  const resource = useResource((signal) =>
    api.request<Hiring["schemas"]["ContactView"]>(
      "hiring",
      `/v1/invitations/${id}/contacts`,
      { signal },
    ),
  );
  return (
    <section>
      <LoadState resource={resource} />
      {resource.data && (
        <>
          <p>Email: {resource.data.email}</p>
          <p>Телефон: {resource.data.phone ?? "не указан"}</p>
          <Button variant="secondary" onClick={resource.reload}>
            Перепроверить доступ
          </Button>
        </>
      )}
    </section>
  );
}
