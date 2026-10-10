import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import type { components as I } from "../../api/generated/integration";
import type { components as D } from "../../api/generated/demo-ats";
import type { components as H } from "../../api/generated/hiring";
import { useBackend } from "../../state/BackendContext";
import type { Invitation } from "../../api/types";
import { Button } from "../../components/Button";
import { useResource } from "./Resource";
import { CommandStatus, Field, LoadState, useCommand, isUuid } from "./ApiUI";
import { ConsentGate } from "./ConsentGate";
const statuses: Record<string, string> = {
  pending: "В очереди",
  running: "Доставляется",
  completed: "Доставка завершена",
  failed: "Ошибка доставки",
  cancelled: "Отменено",
  received: "Получено ATS",
  interview: "Собеседование",
  offer: "Предложение",
  hired: "Принят на работу",
  rejected: "Отклонено",
};
export function AtsPermission({ invitation }: { invitation: Invitation }) {
  const [visible, setVisible] = useState(false);
  return (
    <section className="api-card">
      <h2>Передача в демо-ATS</h2>
      <p>
        Это отдельный экспорт профиля и контактов в систему компании.
        Передавайте ссылку только компании, которой разрешаете экспорт.
      </p>
      <ConsentGate purpose="ats_export">
        {(consent) => (
          <>
            <Button variant="secondary" onClick={() => setVisible(true)}>
              Подготовить ссылку для компании
            </Button>
            {visible && (
              <Field label="Ссылка разрешения для компании">
                <input
                  readOnly
                  value={`${location.origin}/employer/integrations/ats?invitation=${invitation.invitation_id}&consent=${consent}`}
                  onFocus={(e) => e.target.select()}
                />
              </Field>
            )}
          </>
        )}
      </ConsentGate>
    </section>
  );
}
export function AtsPage() {
  const [params] = useSearchParams();
  const invitation = params.get("invitation");
  const consent = params.get("consent");
  const job = params.get("job");
  return (
    <div className="screen-form">
      <h1>Интеграция с демо-ATS</h1>
      <p>
        Тестовый приёмник. Доставка и обратные статусы подтверждаются отдельными
        ответами сервера.
      </p>
      {job && isUuid(job) ? (
        <AtsJob id={job} />
      ) : invitation && consent && isUuid(invitation) && isUuid(consent) ? (
        <AtsExport id={invitation} consent={consent} />
      ) : (
        <>
          <p>
            Откройте ссылку, которую кандидат подготовил в принятом приглашении
            после согласия на экспорт в ATS.
          </p>
          <Link to="/employer/invitation/new">
            Открыть приглашения компании
          </Link>
        </>
      )}
    </div>
  );
}
function AtsExport({ id, consent }: { id: string; consent: string }) {
  const { api } = useBackend();
  const [, setParams] = useSearchParams();
  const command = useCommand();
  const [checked, setChecked] = useState(false);
  const resource = useResource((signal) => api.invitation(id, signal));
  const item = resource.data;
  return (
    <>
      <LoadState resource={resource} />
      {item && (
        <section className="api-card">
          <h2>Экспорт кандидата</h2>
          <p>{item.description}</p>
          <p>Компания: {item.organization_id}</p>
          <p>Кандидат: {item.candidate_id}</p>
          <p>
            Сервер повторно проверит согласие, принятие приглашения и ваши права
            в компании.
          </p>
          <label className="consent">
            <input
              type="checkbox"
              checked={checked}
              onChange={(e) => setChecked(e.target.checked)}
            />
            <span>
              Подтверждаю передачу разрешённого профиля и контактов в демо-ATS
            </span>
          </label>
          <Button
            disabled={
              command.disabled || !checked || item.status !== "accepted"
            }
            onClick={() =>
              void command.run(async () => {
                const job = await api.request<I["schemas"]["JobView"]>(
                  "integration",
                  "/v1/integrations/ats-exports",
                  {
                    method: "POST",
                    body: {
                      candidate_id: item.candidate_id,
                      organization_id: item.organization_id,
                      invitation_id: id,
                      consent_id: consent,
                    },
                    intent: `ats:${id}:${consent}`,
                  },
                );
                setParams({ job: job.job_id });
              }, "Экспорт поставлен в очередь.")
            }
          >
            Начать экспорт
          </Button>
        </section>
      )}
      <CommandStatus command={command} refresh={resource.reload} />
    </>
  );
}
function AtsJob({ id }: { id: string }) {
  const { api } = useBackend();
  const resource = useResource((signal) =>
    api.request<I["schemas"]["JobView"]>(
      "integration",
      `/v1/integrations/jobs/${id}`,
      { signal },
    ),
  );
  const job = resource.data;
  return (
    <>
      <LoadState resource={resource} />
      {job && (
        <section className="api-card">
          <h2>{statuses[job.status]}</h2>
          <p>Попыток доставки: {job.attempts}</p>
          {job.error_code && <p role="alert">Ошибка: {job.error_code}</p>}
          {job.external_status && (
            <p>
              Последний подтверждённый статус ATS:{" "}
              {statuses[job.external_status]}
            </p>
          )}
          {job.status === "completed" && job.external_id && (
            <AtsReceiver id={job.external_id} />
          )}
        </section>
      )}
      <Button variant="secondary" onClick={resource.reload}>
        Обновить доставку и обратный статус
      </Button>
    </>
  );
}
type Received = {
  external_id: string;
  version: number;
  status: string;
  demo: true;
  profile: H["schemas"]["CandidateCard"];
  contacts: H["schemas"]["ContactView"];
};
function AtsReceiver({ id }: { id: string }) {
  const { api } = useBackend();
  const command = useCommand();
  const [status, setStatus] =
    useState<D["schemas"]["StatusCommand"]["status"]>("interview");
  const resource = useResource((signal) =>
    api.request<Received>("demo-ats", `/v1/ats/candidates/${id}`, { signal }),
  );
  const row = resource.data;
  return (
    <section className="api-card">
      <h2>Принимающая демо-ATS</h2>
      <LoadState resource={resource} />
      {row && (
        <>
          <h3>{row.profile.display_name}</h3>
          <p>
            {row.profile.specialization} ·{" "}
            {row.profile.confirmed_grade ?? "Нет подтверждённого грейда"}
          </p>
          <p>Email: {row.contacts.email}</p>
          <p>Телефон: {row.contacts.phone ?? "не указан"}</p>
          <p>Статус: {statuses[row.status]}</p>
          <Field label="Новый статус в ATS">
            <select
              value={status}
              onChange={(e) => setStatus(e.target.value as typeof status)}
            >
              {["interview", "offer", "hired", "rejected"].map((s) => (
                <option key={s} value={s}>
                  {statuses[s]}
                </option>
              ))}
            </select>
          </Field>
          <Button
            disabled={command.disabled}
            onClick={() =>
              void command.run(async () => {
                await api.request(
                  "demo-ats",
                  `/v1/ats/candidates/${id}/status`,
                  {
                    method: "POST",
                    body: { status },
                    version: row.version,
                    intent: `ats-status:${id}`,
                  },
                );
                resource.reload();
              }, "Статус изменён в ATS. Обратная доставка проверяется отдельно.")
            }
          >
            Изменить статус в ATS
          </Button>
        </>
      )}
      <CommandStatus command={command} refresh={resource.reload} />
    </section>
  );
}
