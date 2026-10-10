import { useState } from "react";
import {
  CompanySchedules,
  CompanySubscriptions,
  SubscriptionEditor,
  AssignmentResult,
} from "./CompanySchedules";
import { Link, useNavigate } from "react-router-dom";
import type { components as A } from "../../api/generated/assessment";
import type { components as P } from "../../api/generated/privacy";
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
import { ConsentGate } from "./ConsentGate";
import type { Invitation } from "../../api/types";
type Proposal = A["schemas"]["ProposalView"];
type Assignment = A["schemas"]["AssignmentView"];
export function CompanyTasksPage({
  candidate = false,
}: {
  candidate?: boolean;
}) {
  return (
    <div className="screen-form">
      <h1>{candidate ? "Задания компаний" : "Конструктор заданий компании"}</h1>
      {candidate ? (
        <>
          <Assignments />
          <CompanySubscriptions />
        </>
      ) : (
        <OrganizationScope>
          {(org) => (
            <>
              <ProposalEditor organization={org.organization_id} />
              <Proposals organization={org.organization_id} />
              <AssignmentForm organization={org.organization_id} />
              <Assignments organization={org.organization_id} />
              <CompanySchedules organization={org.organization_id} />
            </>
          )}
        </OrganizationScope>
      )}
    </div>
  );
}
function ProposalEditor({
  organization,
  initial,
  saved,
}: {
  organization: string;
  initial?: Proposal;
  saved?: () => void;
}) {
  const { api } = useBackend();
  const command = useCommand();
  const [name, setName] = useState(initial?.name ?? "");
  const [specialization, setSpecialization] = useState(
    initial?.content.specialization ?? "",
  );
  const [grade, setGrade] = useState(initial?.content.grade ?? "junior");
  const [format, setFormat] = useState<A["schemas"]["Task"]["format"]>(
    initial?.content.tasks[0]?.format ?? "code",
  );
  const [instruction, setInstruction] = useState(
    initial?.content.tasks[0]?.instruction ?? "",
  );
  const [answer, setAnswer] = useState(
    initial?.content.tasks[0]?.reference_answer ?? "",
  );
  const [competency, setCompetency] = useState(
    initial?.content.competencies[0]?.description ?? "",
  );
  const [criterion, setCriterion] = useState(
    initial?.content.tasks[0]?.rubric[0]?.description ?? "",
  );
  const [minutes, setMinutes] = useState(
    (initial?.content.tasks[0]?.duration_seconds ?? 900) / 60,
  );
  const [created, setCreated] = useState(false);
  return (
    <form
      className="api-card api-form"
      onSubmit={(e) => {
        e.preventDefault();
        void command.run(async () => {
          const evidence =
            format === "code" || format === "sql"
              ? "artifact"
              : format === "whiteboard"
                ? "board_snapshot"
                : "timestamped_recording";
          const content = {
            specialization,
            grade,
            source_dataset:
              initial?.content.source_dataset ?? "company-authored",
            source_version: initial?.content.source_version ?? "1",
            demo: true,
            competencies: initial
              ? initial.content.competencies.map((item, index) =>
                  index === 0 ? { ...item, description: competency } : item,
                )
              : [{ key: "primary", description: competency }],
            tasks: [
              {
                ...(initial?.content.tasks[0] ?? {}),
                key: initial?.content.tasks[0]?.key ?? "task",
                format,
                instruction,
                duration_seconds: minutes * 60,
                reference_answer: answer,
                rubric: [
                  {
                    ...(initial?.content.tasks[0]?.rubric[0] ?? {}),
                    key: initial?.content.tasks[0]?.rubric[0]?.key ?? "quality",
                    competency:
                      initial?.content.tasks[0]?.rubric[0]?.competency ??
                      "primary",
                    description: criterion,
                    points: initial?.content.tasks[0]?.rubric[0]?.points ?? 100,
                    evidence,
                  },
                  ...(initial?.content.tasks[0]?.rubric.slice(1) ?? []),
                ],
              },
              ...(initial?.content.tasks.slice(1) ?? []),
            ],
          };
          await api.request(
            "assessment",
            `/v1/company-task-proposals${initial ? `/${initial.proposal_id}` : ""}`,
            {
              method: initial ? "PUT" : "POST",
              body: { organization_id: organization, name, content },
              version: initial?.version,
              intent: `proposal:${initial?.proposal_id ?? organization}`,
            },
          );
          setCreated(true);
          saved?.();
        }, "Предложение сохранено. Обновите список, чтобы отправить его на проверку.");
      }}
    >
      <h2>{initial ? "Изменить задание" : "Новое задание"}</h2>
      <p>
        Задание сначала проверит модератор. Оно оценивает навыки для компании и
        не меняет общий грейд. Текущий банк работает в деморежиме.
      </p>
      <Field label="Название задания">
        <input
          required
          maxLength={200}
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </Field>
      <Field label="Специализация задания">
        <input
          required
          maxLength={100}
          value={specialization}
          onChange={(e) => setSpecialization(e.target.value)}
        />
      </Field>
      <Field label="Грейд задания">
        <select
          value={grade}
          onChange={(e) => setGrade(e.target.value as typeof grade)}
        >
          {["junior", "middle", "senior", "lead"].map((x) => (
            <option key={x}>{x}</option>
          ))}
        </select>
      </Field>
      <Field label="Формат задания">
        <select
          value={format}
          onChange={(e) => setFormat(e.target.value as typeof format)}
        >
          {[
            ["code", "Код"],
            ["sql", "SQL"],
            ["voice", "Аудио"],
            ["vcv", "Видео"],
            ["whiteboard", "Доска"],
          ].map(([key, label]) => (
            <option key={key} value={key}>
              {label}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Длительность задания, минут">
        <input
          type="number"
          required
          min="1"
          max="60"
          value={minutes}
          onChange={(e) => setMinutes(Number(e.target.value))}
        />
      </Field>
      {[
        ["Инструкция кандидату", instruction, setInstruction, 20000],
        ["Эталон ответа", answer, setAnswer, 20000],
        ["Проверяемая компетенция", competency, setCompetency, 2000],
        ["Критерий оценки", criterion, setCriterion, 2000],
      ].map(([label, value, setter, max]) => (
        <Field key={String(label)} label={String(label)}>
          <textarea
            required
            maxLength={Number(max)}
            value={String(value)}
            onChange={(e) => (setter as (v: string) => void)(e.target.value)}
          />
        </Field>
      ))}
      <Button type="submit" disabled={command.disabled || created}>
        Сохранить задание
      </Button>
      <CommandStatus command={command} refresh={saved} />
    </form>
  );
}
function Proposals({ organization }: { organization: string }) {
  const { api } = useBackend();
  const resource = useResource((signal) =>
    api.request<A["schemas"]["ProposalSummary"][]>(
      "assessment",
      `/v1/company-task-proposals?organization_id=${organization}`,
      { signal },
    ),
  );
  return (
    <section className="screen-form">
      <h2>Предложения компании</h2>
      <LoadState resource={resource} />
      {resource.data?.map((p) => (
        <ProposalCard
          key={`${p.proposal_id}:${p.version}`}
          id={p.proposal_id}
          reload={resource.reload}
        />
      ))}
      {resource.status === "ready" && !resource.data?.length && (
        <p>Предложений пока нет.</p>
      )}
      <Button variant="secondary" onClick={resource.reload}>
        Обновить предложения
      </Button>
    </section>
  );
}
function ProposalCard({ id, reload }: { id: string; reload: () => void }) {
  const { api } = useBackend();
  const command = useCommand();
  const [edit, setEdit] = useState(false);
  const resource = useResource((signal) =>
    api.request<Proposal>("assessment", `/v1/company-task-proposals/${id}`, {
      signal,
    }),
  );
  const p = resource.data;
  return (
    <article className="api-card">
      <LoadState resource={resource} />
      {p && (
        <>
          <h3>{p.name}</h3>
          <p>
            {
              {
                draft: "Черновик",
                submitted: "На проверке",
                approved: "Одобрено",
                rejected: "Отклонено",
                withdrawn: "Отозвано",
              }[p.status]
            }
          </p>
          {p.review_reason && <p>Решение: {p.review_reason}</p>}
          {p.content.tasks.map((t) => (
            <div key={t.key}>
              <p className="invitation-description">{t.instruction}</p>
              <p>Критерии: {t.rubric.map((r) => r.description).join("; ")}</p>
            </div>
          ))}
          {["draft", "rejected"].includes(p.status) && (
            <>
              <Button variant="secondary" onClick={() => setEdit((v) => !v)}>
                Изменить задание
              </Button>
              <Button
                disabled={command.disabled}
                onClick={() =>
                  void command.run(async () => {
                    await api.request(
                      "assessment",
                      `/v1/company-task-proposals/${id}/submit`,
                      {
                        method: "POST",
                        version: p.version,
                        intent: `proposal-submit:${id}`,
                      },
                    );
                    reload();
                  })
                }
              >
                Отправить задание на проверку
              </Button>
              {edit && (
                <ProposalEditor
                  organization={p.organization_id}
                  initial={p}
                  saved={reload}
                />
              )}
            </>
          )}
        </>
      )}
      <CommandStatus command={command} refresh={resource.reload} />
    </article>
  );
}
function AssignmentForm({ organization }: { organization: string }) {
  const { api } = useBackend();
  const command = useCommand();
  const resource = useResource(async (signal) => {
    const [proposals, plans, invitations] = await Promise.all([
      api.request<A["schemas"]["ProposalSummary"][]>(
        "assessment",
        `/v1/company-task-proposals?organization_id=${organization}&status=approved`,
        { signal },
      ),
      api.request<A["schemas"]["PlanView"][]>(
        "assessment",
        "/v1/assessment-plans",
        { signal },
      ),
      api.request<Invitation[]>(
        "hiring",
        `/v1/invitations?organization_id=${organization}`,
        { signal },
      ),
    ]);
    return { proposals, plans, invitations };
  });
  const [proposal, setProposal] = useState("");
  const [plan, setPlan] = useState("");
  const [candidate, setCandidate] = useState("");
  const [schedule, setSchedule] = useState("");
  const [interval, setInterval] = useState(7);
  const [count, setCount] = useState(1);
  return (
    <form
      className="api-card api-form"
      onSubmit={(e) => {
        e.preventDefault();
        void command.run(
          () =>
            api.request(
              "assessment",
              schedule
                ? "/v1/company-task-schedules"
                : "/v1/company-assignments",
              {
                method: "POST",
                body: {
                  organization_id: organization,
                  candidate_id: candidate,
                  proposal_id: proposal,
                  plan_version_id: plan,
                  ...(schedule
                    ? {
                        starts_at: new Date(schedule).toISOString(),
                        max_occurrences: count,
                        interval_seconds: count > 1 ? interval * 86400 : null,
                      }
                    : {}),
                },
                intent: `assignment:${organization}:${candidate}:${proposal}`,
              },
            ),
          schedule
            ? "Расписание сохранено. Отправка выполняется в назначенное время."
            : "Задание назначено.",
        );
      }}
    >
      <h2>Назначить задание</h2>
      <LoadState resource={resource} />
      {resource.data && (
        <>
          <Field label="Одобренное задание">
            <select
              required
              value={proposal}
              onChange={(e) => setProposal(e.target.value)}
            >
              <option value="">Выберите</option>
              {resource.data.proposals.map((x) => (
                <option key={x.proposal_id} value={x.proposal_id}>
                  {x.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="План для задания">
            <select
              required
              value={plan}
              onChange={(e) => setPlan(e.target.value)}
            >
              <option value="">Выберите</option>
              {resource.data.plans
                .filter((x) => x.status === "published")
                .map((x) => (
                  <option key={x.plan_version_id} value={x.plan_version_id}>
                    {x.name}
                  </option>
                ))}
            </select>
          </Field>
          <Field label="Получатель задания">
            <select
              required
              value={candidate}
              onChange={(e) => setCandidate(e.target.value)}
            >
              <option value="">Выберите</option>
              {[
                ...new Set(
                  resource.data.invitations
                    .filter((x) => x.status === "accepted")
                    .map((x) => x.candidate_id),
                ),
              ].map((x) => (
                <option key={x} value={x}>
                  {x}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Отправить позже (необязательно)">
            <input
              type="datetime-local"
              value={schedule}
              onChange={(e) => setSchedule(e.target.value)}
            />
          </Field>
          {schedule && (
            <>
              <Field label="Количество отправок">
                <input
                  type="number"
                  min="1"
                  max="52"
                  value={count}
                  onChange={(e) => setCount(Number(e.target.value))}
                />
              </Field>
              <Field label="Интервал в днях">
                <input
                  type="number"
                  min="1"
                  max="90"
                  value={interval}
                  onChange={(e) => setInterval(Number(e.target.value))}
                />
              </Field>
              <p>
                Отправка по расписанию требует действующей подписки кандидата.
              </p>
            </>
          )}
          <Button
            type="submit"
            disabled={command.disabled || !proposal || !plan || !candidate}
          >
            Подтвердить назначение
          </Button>
        </>
      )}
      <CommandStatus command={command} />
    </form>
  );
}
function Assignments({ organization }: { organization?: string }) {
  const { api } = useBackend();
  const [after, setAfter] = useState("");
  return (
    <AssignmentList
      key={after}
      api={api}
      organization={organization}
      after={after}
      next={setAfter}
    />
  );
}
function AssignmentList({
  api,
  organization,
  after,
  next,
}: {
  api: ReturnType<typeof useBackend>["api"];
  organization?: string;
  after: string;
  next: (v: string) => void;
}) {
  const q = new URLSearchParams();
  if (organization) q.set("organization_id", organization);
  if (after) q.set("after", after);
  const resource = useResource((signal) =>
    api.request<Assignment[]>("assessment", `/v1/company-assignments?${q}`, {
      signal,
    }),
  );
  return (
    <>
      <h2>Назначенные задания</h2>
      <LoadState resource={resource} />
      {resource.data?.map((item) => (
        <AssignmentCard
          key={`${item.assignment_id}:${item.version}`}
          item={item}
          employer={!!organization}
          reload={resource.reload}
        />
      ))}
      {resource.status === "ready" && !resource.data?.length && (
        <p>На этой странице заданий нет.</p>
      )}
      <Button variant="secondary" onClick={resource.reload}>
        Обновить задания
      </Button>
      {!!resource.data?.length && (
        <Button
          variant="secondary"
          onClick={() => next(resource.data!.at(-1)!.assignment_id)}
        >
          Следующие задания
        </Button>
      )}
      {after && (
        <Button variant="secondary" onClick={() => next("")}>
          В начало заданий
        </Button>
      )}
    </>
  );
}
function AssignmentCard({
  item,
  employer,
  reload,
}: {
  item: Assignment;
  employer: boolean;
  reload: () => void;
}) {
  const { api } = useBackend();
  const command = useCommand();
  const navigate = useNavigate();
  const [checked, setChecked] = useState(false);
  const [showResult, setShowResult] = useState(false);
  const [subscription, setSubscription] = useState(false);
  const [grant, setGrant] = useState<P["schemas"]["GrantView"]>();
  const statuses: Record<string, string> = {
    assigned: "Назначено",
    accepted: "Принято",
    declined: "Отклонено",
    revoked: "Отозвано",
    expired: "Истёк срок",
    cancelled: "Отменено",
    in_progress: "Выполняется",
    submitted: "На оценке",
    completed: "Завершено",
  };
  return (
    <article className="api-card">
      <h3>Задание компании {item.organization_id}</h3>
      <p>
        {statuses[item.status]} · {Math.ceil(item.duration_seconds / 60)} мин. ·{" "}
        {item.formats.join(", ")}
      </p>
      <p>Ответить до {new Date(item.expires_at).toLocaleString("ru-RU")}</p>
      <p>
        Компания получит проверенные оценки. Общий грейд не меняется, контакты
        не раскрываются.
      </p>
      {!employer && item.status === "assigned" && (
        <>
          <ConsentGate purpose="assessment">
            {(assessmentConsent) => (
              <ConsentGate purpose="company_result_disclosure">
                {(resultConsent) => (
                  <>
                    <label className="consent">
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={(e) => setChecked(e.target.checked)}
                      />
                      <span>
                        Принимаю задание и разрешаю передать проверенные оценки
                        этой компании
                      </span>
                    </label>
                    <Button
                      disabled={command.disabled || !checked}
                      onClick={() =>
                        void command.run(async () => {
                          const permission =
                            grant ??
                            (await api.request<P["schemas"]["GrantView"]>(
                              "privacy",
                              "/v1/company-result-grants",
                              {
                                method: "POST",
                                body: {
                                  assignment_id: item.assignment_id,
                                  organization_id: item.organization_id,
                                  consent_id: resultConsent,
                                },
                                intent: `result-grant:${item.assignment_id}`,
                              },
                            ));
                          setGrant(permission);
                          const result = await api.request<
                            A["schemas"]["SessionView"]
                          >(
                            "assessment",
                            `/v1/company-assignments/${item.assignment_id}/accept`,
                            {
                              method: "POST",
                              body: {
                                assessment_consent_id: assessmentConsent,
                                result_grant_id: permission.grant_id,
                              },
                              version: item.version,
                              intent: `assignment-accept:${item.assignment_id}`,
                            },
                          );
                          navigate(
                            `/candidate/assessment?session=${result.session_id}`,
                          );
                        })
                      }
                    >
                      Принять и перейти к заданию
                    </Button>
                  </>
                )}
              </ConsentGate>
            )}
          </ConsentGate>
          <Button
            variant="secondary"
            disabled={command.disabled}
            onClick={() =>
              void command.run(async () => {
                await api.request(
                  "assessment",
                  `/v1/company-assignments/${item.assignment_id}/decline`,
                  {
                    method: "POST",
                    version: item.version,
                    intent: `assignment-decline:${item.assignment_id}`,
                  },
                );
                reload();
              }, "Отказ сохранён без штрафа.")
            }
          >
            Отказаться от задания без штрафа
          </Button>
        </>
      )}
      {grant && (
        <Button
          variant="secondary"
          disabled={command.disabled}
          onClick={() =>
            void command.run(async () => {
              await api.request(
                "privacy",
                `/v1/company-result-grants/${grant.grant_id}/revoke`,
                {
                  method: "POST",
                  version: grant.version,
                  intent: `revoke-result:${grant.grant_id}`,
                },
              );
              setGrant(undefined);
            }, "Доступ к результату отозван.")
          }
        >
          Отозвать разрешение на результат
        </Button>
      )}
      {item.session_id && !employer && (
        <Link to={`/candidate/assessment?session=${item.session_id}`}>
          Открыть прохождение
        </Link>
      )}
      {employer &&
        ["assigned", "accepted", "in_progress"].includes(item.status) && (
          <Button
            variant="secondary"
            disabled={command.disabled}
            onClick={() =>
              void command.run(async () => {
                await api.request(
                  "assessment",
                  `/v1/company-assignments/${item.assignment_id}/revoke`,
                  {
                    method: "POST",
                    version: item.version,
                    intent: `assignment-revoke:${item.assignment_id}`,
                  },
                );
                reload();
              })
            }
          >
            Отозвать задание
          </Button>
        )}
      {item.session_id && (
        <>
          <Button variant="secondary" onClick={() => setShowResult((v) => !v)}>
            Показать результат задания
          </Button>
          {showResult && (
            <AssignmentResult
              assignment={item}
              employer={employer}
              reload={reload}
            />
          )}
        </>
      )}
      {!employer && (
        <>
          <Button
            variant="secondary"
            onClick={() => setSubscription((v) => !v)}
          >
            Задания от этой компании
          </Button>
          {subscription && (
            <SubscriptionEditor organization={item.organization_id} />
          )}
        </>
      )}
      <CommandStatus command={command} refresh={reload} />
    </article>
  );
}
