import { useState } from "react";
import type { components as A } from "../../api/generated/assessment";
import { useBackend } from "../../state/BackendContext";
import { Button } from "../../components/Button";
import { useResource } from "./Resource";
import {
  CommandStatus,
  Field,
  LoadState,
  useCommand,
  uuidPattern,
} from "./ApiUI";
import { ConsentGate } from "./ConsentGate";
type Subscription = A["schemas"]["SubscriptionView"];

export function CompanySubscriptions() {
  const { api } = useBackend();
  const [after, setAfter] = useState("");
  const [organization, setOrganization] = useState("");
  const [selected, setSelected] = useState("");
  return (
    <section className="api-card">
      <h2>Подписки на задания компаний</h2>
      <p>
        Вы выбираете компании и частоту заданий. Отмена подписки останавливает
        будущие отправки.
      </p>
      <form
        className="api-form"
        onSubmit={(e) => {
          e.preventDefault();
          setSelected(organization);
        }}
      >
        <Field label="Идентификатор компании для подписки">
          <input
            required
            pattern={uuidPattern}
            value={organization}
            onChange={(e) => setOrganization(e.target.value)}
          />
        </Field>
        <Button type="submit">Настроить подписку</Button>
      </form>
      {selected && (
        <SubscriptionEditor key={selected} organization={selected} />
      )}
      <SubscriptionList key={after} after={after} next={setAfter} api={api} />
    </section>
  );
}
function SubscriptionList({
  after,
  next,
  api,
}: {
  after: string;
  next: (value: string) => void;
  api: ReturnType<typeof useBackend>["api"];
}) {
  const resource = useResource((signal) =>
    api.request<Subscription[]>(
      "assessment",
      `/v1/company-task-subscriptions${after ? `?after=${after}` : ""}`,
      { signal },
    ),
  );
  return (
    <>
      <LoadState resource={resource} />
      {resource.data?.map((row) => (
        <SubscriptionEditor
          key={`${row.organization_id}:${row.version}`}
          organization={row.organization_id}
        />
      ))}
      {resource.data?.length === 50 && (
        <Button
          variant="secondary"
          onClick={() => next(resource.data!.at(-1)!.organization_id)}
        >
          Следующие подписки
        </Button>
      )}
      {after && (
        <Button variant="secondary" onClick={() => next("")}>
          В начало подписок
        </Button>
      )}
      <Button variant="secondary" onClick={resource.reload}>
        Обновить подписки
      </Button>
    </>
  );
}
export function SubscriptionEditor({ organization }: { organization: string }) {
  const { api } = useBackend();
  const resource = useResource((signal) =>
    api.request<Subscription>(
      "assessment",
      `/v1/company-task-subscriptions/${organization}`,
      { signal },
    ),
  );
  return (
    <>
      <LoadState resource={resource} />
      {resource.data && (
        <SubscriptionForm
          key={resource.data.version}
          row={resource.data}
          reload={resource.reload}
        />
      )}
    </>
  );
}
function SubscriptionForm({
  row,
  reload,
}: {
  row: Subscription;
  reload: () => void;
}) {
  const { api } = useBackend();
  const command = useCommand();
  const [days, setDays] = useState(row.min_interval_seconds / 86400);
  const [checked, setChecked] = useState(false);
  const save = (status: Subscription["status"], consent?: string) =>
    command.run(
      async () => {
        await api.request(
          "assessment",
          `/v1/company-task-subscriptions/${row.organization_id}`,
          {
            method: "PUT",
            version: row.version,
            body: {
              status,
              min_interval_seconds: days * 86400,
              ...(consent ? { consent_id: consent } : {}),
            },
            intent: `subscription:${row.organization_id}`,
          },
        );
        reload();
      },
      status === "active"
        ? "Подписка сохранена."
        : "Будущие отправки отменены.",
    );
  return (
    <article className="api-card">
      <h3>Компания {row.organization_id}</h3>
      <p>
        {row.status === "active"
          ? "Подписка активна"
          : row.status === "declined"
            ? "Подписка отклонена"
            : "Подписка отменена"}
      </p>
      <Field label="Не чаще одного задания за указанное число дней">
        <input
          type="number"
          min="1"
          max="90"
          step="1"
          value={days}
          onChange={(e) => setDays(Number(e.target.value))}
        />
      </Field>
      <ConsentGate purpose="company_task_subscription">
        {(consent) => (
          <>
            <label className="consent">
              <input
                type="checkbox"
                checked={checked}
                onChange={(e) => setChecked(e.target.checked)}
              />
              <span>
                Хочу получать задания этой компании с указанной частотой
              </span>
            </label>
            <Button
              disabled={
                command.disabled ||
                !checked ||
                days < 1 ||
                days > 90 ||
                !Number.isInteger(days)
              }
              onClick={() => void save("active", consent)}
            >
              Сохранить подписку
            </Button>
          </>
        )}
      </ConsentGate>
      {row.status === "active" && (
        <Button
          variant="secondary"
          disabled={command.disabled}
          onClick={() => void save("cancelled")}
        >
          Отменить подписку
        </Button>
      )}
      <CommandStatus command={command} refresh={reload} />
    </article>
  );
}
export function CompanySchedules({ organization }: { organization: string }) {
  const [after, setAfter] = useState("");
  return (
    <ScheduleList
      key={after}
      organization={organization}
      after={after}
      next={setAfter}
    />
  );
}
function ScheduleList({
  organization,
  after,
  next,
}: {
  organization: string;
  after: string;
  next: (value: string) => void;
}) {
  const { api } = useBackend();
  const resource = useResource((signal) =>
    api.request<A["schemas"]["ScheduleView"][]>(
      "assessment",
      `/v1/company-task-schedules?organization_id=${organization}${after ? `&after=${after}` : ""}`,
      { signal },
    ),
  );
  return (
    <section className="api-card">
      <h2>Расписания отправки</h2>
      <LoadState resource={resource} />
      {resource.data?.map((row) => (
        <ScheduleCard
          key={`${row.schedule_id}:${row.version}`}
          row={row}
          reload={resource.reload}
        />
      ))}
      {resource.status === "ready" && !resource.data?.length && (
        <p>На этой странице расписаний нет.</p>
      )}
      <Button variant="secondary" onClick={resource.reload}>
        Обновить расписания
      </Button>
      {resource.data?.length === 50 && (
        <Button
          variant="secondary"
          onClick={() => next(resource.data!.at(-1)!.schedule_id)}
        >
          Следующие расписания
        </Button>
      )}
      {after && (
        <Button variant="secondary" onClick={() => next("")}>
          В начало расписаний
        </Button>
      )}
    </section>
  );
}
function ScheduleCard({
  row,
  reload,
}: {
  row: A["schemas"]["ScheduleView"];
  reload: () => void;
}) {
  const { api } = useBackend();
  const command = useCommand();
  const [jobs, setJobs] = useState<A["schemas"]["JobView"][]>();
  return (
    <article className="api-card">
      <h3>Кандидат {row.candidate_id}</h3>
      <p>
        {
          { active: "Активно", cancelled: "Отменено", completed: "Завершено" }[
            row.status
          ]
        }{" "}
        · отправлено {row.issued_count} из {row.max_occurrences}
      </p>
      <p>
        Начало: {new Date(row.starts_at).toLocaleString("ru-RU")}
        {row.interval_seconds
          ? ` · каждые ${row.interval_seconds / 86400} дн.`
          : ""}
      </p>
      {row.status === "active" && (
        <Button
          variant="secondary"
          disabled={command.disabled}
          onClick={() =>
            void command.run(async () => {
              await api.request(
                "assessment",
                `/v1/company-task-schedules/${row.schedule_id}/cancel`,
                {
                  method: "POST",
                  version: row.version,
                  intent: `cancel-schedule:${row.schedule_id}`,
                },
              );
              reload();
            }, "Будущие отправки отменены.")
          }
        >
          Отменить будущие отправки
        </Button>
      )}
      <Button
        variant="secondary"
        disabled={command.disabled}
        onClick={() =>
          void command.run(
            async () =>
              setJobs(
                await api.request(
                  "assessment",
                  `/v1/company-task-schedules/${row.schedule_id}/jobs`,
                ),
              ),
            "Статусы отправки обновлены.",
          )
        }
      >
        Проверить отправки
      </Button>
      {jobs?.map((job) => (
        <p key={job.job_id}>
          {
            { pending: "Ожидает", done: "Выполнено", cancelled: "Отменено" }[
              job.status
            ]
          }{" "}
          · попыток: {job.attempts}
          {job.error
            ? ` · ${{ permission_unavailable: "Нет действующего разрешения", evidence_pending: "Материалы ещё проверяются", rate_limited: "Ожидание разрешённого интервала" }[job.error]}`
            : ""}
        </p>
      ))}
      <CommandStatus command={command} refresh={reload} />
    </article>
  );
}
export function AssignmentResult({
  assignment,
  employer,
  reload,
}: {
  assignment: A["schemas"]["AssignmentView"];
  employer: boolean;
  reload: () => void;
}) {
  const { api } = useBackend();
  const command = useCommand();
  const resource = useResource((signal) =>
    api.request<A["schemas"]["AssignmentResult"]>(
      "assessment",
      `/v1/company-assignments/${assignment.assignment_id}/result`,
      { signal },
    ),
  );
  return (
    <section>
      <h3>Результат задания</h3>
      <LoadState resource={resource} />
      {resource.data && (
        <>
          <p>
            {resource.data.status === "reviewed"
              ? "Все этапы проверены"
              : "Ожидается проверка материалов"}
          </p>
          {resource.data.stages.map((stage) => (
            <article key={stage.stage_id}>
              <h4>
                {stage.format} · {stage.score ?? "нет оценки"}
              </h4>
              {stage.criteria.map((criterion) => (
                <p key={criterion.criterion_key}>
                  {criterion.competency}: {criterion.points ?? "нет оценки"} /{" "}
                  {criterion.max_points}
                </p>
              ))}
            </article>
          ))}
          {!employer &&
            assignment.status === "accepted" &&
            resource.data.status === "reviewed" && (
              <Button
                disabled={command.disabled}
                onClick={() =>
                  void command.run(async () => {
                    await api.request(
                      "assessment",
                      `/v1/company-assignments/${assignment.assignment_id}/complete`,
                      {
                        method: "POST",
                        version: assignment.version,
                        intent: `complete-assignment:${assignment.assignment_id}`,
                      },
                    );
                    reload();
                  })
                }
              >
                Завершить проверенное задание
              </Button>
            )}
        </>
      )}
      <Button variant="secondary" onClick={resource.reload}>
        Обновить результат задания
      </Button>
      <CommandStatus command={command} refresh={resource.reload} />
    </section>
  );
}
