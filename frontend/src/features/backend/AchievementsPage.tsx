import { useState } from "react";
import type { components as A } from "../../api/generated/achievements";
import type { components as I } from "../../api/generated/integration";
import { useBackend } from "../../state/BackendContext";
import { Button } from "../../components/Button";
import { useResource } from "./Resource";
import { CommandStatus, Field, LoadState, useCommand } from "./ApiUI";
import { ConsentGate } from "./ConsentGate";
type Achievement = A["schemas"]["AchievementView"];
type Source = A["schemas"]["SourceView"];
type Connection = A["schemas"]["ConnectionView"];
export function AchievementsPage() {
  const { api } = useBackend();
  const resource = useResource(async (signal) => {
    const [sources, connections, items] = await Promise.all([
      api.request<Source[]>("achievements", "/v1/achievement-sources", {
        signal,
      }),
      api.request<Connection[]>(
        "achievements",
        "/v1/achievement-connections/me",
        { signal },
      ),
      api.request<Achievement[]>("achievements", "/v1/achievements/me", {
        signal,
      }),
    ]);
    return { sources, connections, items };
  });
  return (
    <div className="screen-form">
      <h1>Достижения и источники</h1>
      <LoadState resource={resource} />
      {resource.data && (
        <>
          <ConsentGate purpose="achievement_import">
            {(consent) => (
              <>
                {resource
                  .data!.sources.filter(
                    (s) => s.enabled && s.adapter !== "self",
                  )
                  .map((source) => (
                    <SourceConnection
                      key={`${source.source_id}:${resource.data!.connections.find((c) => c.source_id === source.source_id)?.version ?? 0}`}
                      source={source}
                      connection={resource.data!.connections.find(
                        (c) => c.source_id === source.source_id,
                      )}
                      consent={consent}
                      reload={resource.reload}
                    />
                  ))}
                <DeclaredAchievement
                  consent={consent}
                  reload={resource.reload}
                />
              </>
            )}
          </ConsentGate>
          <h2>Ваши достижения</h2>
          {!resource.data.items.length && <p>Достижений пока нет.</p>}
          {resource.data.items.map((item) => (
            <AchievementCard
              key={`${item.achievement_id}:${item.version}`}
              item={item}
              reload={resource.reload}
            />
          ))}
        </>
      )}
      <Button variant="secondary" onClick={resource.reload}>
        Обновить достижения
      </Button>
    </div>
  );
}
function SourceConnection({
  source,
  connection,
  consent,
  reload,
}: {
  source: Source;
  connection?: Connection;
  consent: string;
  reload: () => void;
}) {
  const { api } = useBackend();
  const command = useCommand();
  const [job, setJob] = useState<I["schemas"]["JobView"]>();
  const [confirm, setConfirm] = useState(false);
  return (
    <section className="api-card">
      <h2>{source.name}</h2>
      {source.demo && (
        <p>ДЕМО · тестовая привязка и синтетические результаты</p>
      )}
      <p>
        {connection?.status === "active"
          ? "Источник подключён"
          : connection?.status === "pending"
            ? "Ожидает подтверждения источником"
            : "Не подключён"}
      </p>
      {connection?.last_synced_at && (
        <p>
          Обновление:{" "}
          {new Date(connection.last_synced_at).toLocaleString("ru-RU")}
        </p>
      )}
      {!connection || connection.status === "disconnected" ? (
        <Button
          disabled={command.disabled}
          onClick={() =>
            void command.run(async () => {
              await api.request("achievements", "/v1/achievement-connections", {
                method: "POST",
                body: { source_id: source.source_id, consent_id: consent },
                intent: `connect:${source.source_id}`,
              });
              reload();
            })
          }
        >
          Подключить источник
        </Button>
      ) : (
        <>
          {connection.status === "active" && (
            <Button
              disabled={command.disabled}
              onClick={() =>
                void command.run(
                  async () =>
                    setJob(
                      await api.request<I["schemas"]["JobView"]>(
                        "integration",
                        "/v1/integrations/syncs",
                        {
                          method: "POST",
                          body: { connection_id: connection.connection_id },
                          intent: `sync:${connection.connection_id}`,
                        },
                      ),
                    ),
                  "Импорт поставлен в очередь.",
                )
              }
            >
              Импортировать достижения
            </Button>
          )}
          <label className="consent">
            <input
              type="checkbox"
              checked={confirm}
              onChange={(e) => setConfirm(e.target.checked)}
            />
            <span>Подтверждаю отключение источника</span>
          </label>
          <Button
            variant="secondary"
            disabled={command.disabled || !confirm}
            onClick={() =>
              void command.run(async () => {
                await api.request(
                  "achievements",
                  `/v1/achievement-connections/${connection.connection_id}/disconnect`,
                  {
                    method: "POST",
                    version: connection.version,
                    intent: `disconnect:${connection.connection_id}`,
                  },
                );
                reload();
              })
            }
          >
            Отключить источник
          </Button>
        </>
      )}
      <CommandStatus command={command} refresh={reload} />
      {job && <IntegrationJob key={job.job_id} id={job.job_id} />}
    </section>
  );
}
export function IntegrationJob({ id }: { id: string }) {
  const { api } = useBackend();
  const resource = useResource((signal) =>
    api.request<I["schemas"]["JobView"]>(
      "integration",
      `/v1/integrations/jobs/${id}`,
      { signal },
    ),
  );
  const labels = {
    pending: "В очереди",
    running: "Выполняется",
    completed: "Выполнено",
    failed: "Не удалось выполнить",
    cancelled: "Отменено",
  };
  return (
    <section className="api-card">
      <h3>Состояние обмена</h3>
      <LoadState resource={resource} />
      {resource.data && (
        <>
          <p>{labels[resource.data.status]}</p>
          <p>Попыток: {resource.data.attempts}</p>
          {resource.data.error_code && (
            <p role="alert">Ошибка обмена: {resource.data.error_code}</p>
          )}
        </>
      )}
      <Button variant="secondary" onClick={resource.reload}>
        Проверить обмен
      </Button>
    </section>
  );
}
function AchievementCard({
  item,
  reload,
}: {
  item: Achievement;
  reload: () => void;
}) {
  const { api } = useBackend();
  const command = useCommand();
  const statuses = {
    declared: "Заявлено кандидатом",
    imported_pending: "Импортировано, ожидает проверки",
    confirmed: "Подтверждено",
    revoked: "Подтверждение отозвано",
  };
  const visibility = (published: boolean, consent?: string) =>
    command.run(async () => {
      await api.request(
        "achievements",
        `/v1/achievements/${item.achievement_id}/visibility`,
        {
          method: "PUT",
          version: item.version,
          body: { published, consent_id: consent ?? null },
          intent: `visibility:${item.achievement_id}`,
        },
      );
      reload();
    });
  return (
    <article className="api-card">
      <h3>{item.result.event}</h3>
      <p>
        {item.result.discipline} · {item.result.occurred_on} ·{" "}
        {item.result.format === "team" ? "Команда" : "Лично"}
      </p>
      <p>
        {statuses[item.status]}
        {item.demo ? " · ДЕМО" : ""}
      </p>
      {item.result.place != null && <p>Место: {item.result.place}</p>}
      {item.result.points != null && <p>Баллы: {item.result.points}</p>}
      <p>{item.published ? "Видно в профиле" : "Скрыто"}</p>
      {item.published ? (
        <Button
          variant="secondary"
          disabled={command.disabled}
          onClick={() => void visibility(false)}
        >
          Скрыть достижение
        </Button>
      ) : (
        <ConsentGate purpose="achievement_publication">
          {(consent) => (
            <Button
              disabled={command.disabled}
              onClick={() => void visibility(true, consent)}
            >
              Опубликовать достижение
            </Button>
          )}
        </ConsentGate>
      )}
      <CommandStatus command={command} refresh={reload} />
    </article>
  );
}
function DeclaredAchievement({
  consent,
  reload,
}: {
  consent: string;
  reload: () => void;
}) {
  const { api } = useBackend();
  const command = useCommand();
  const [event, setEvent] = useState("");
  const [discipline, setDiscipline] = useState("");
  const [date, setDate] = useState("");
  const [format, setFormat] = useState("individual");
  return (
    <form
      className="api-card api-form"
      onSubmit={(e) => {
        e.preventDefault();
        void command.run(async () => {
          await api.request("achievements", "/v1/achievements/declared", {
            method: "POST",
            body: {
              event: event.trim(),
              discipline: discipline.trim(),
              occurred_on: date,
              format,
              consent_id: consent,
            },
            intent: "declare-achievement",
          });
          reload();
        });
      }}
    >
      <h2>Добавить своё достижение</h2>
      <p>Самостоятельно добавленная запись не считается подтверждённой.</p>
      <Field label="Событие">
        <input
          required
          maxLength={200}
          value={event}
          onChange={(e) => setEvent(e.target.value)}
        />
      </Field>
      <Field label="Дисциплина">
        <input
          required
          maxLength={100}
          value={discipline}
          onChange={(e) => setDiscipline(e.target.value)}
        />
      </Field>
      <Field label="Дата события">
        <input
          required
          type="date"
          value={date}
          onChange={(e) => setDate(e.target.value)}
        />
      </Field>
      <Field label="Формат участия">
        <select value={format} onChange={(e) => setFormat(e.target.value)}>
          <option value="individual">Лично</option>
          <option value="team">В команде</option>
        </select>
      </Field>
      <Button
        type="submit"
        disabled={command.disabled || !event.trim() || !discipline.trim()}
      >
        Добавить достижение
      </Button>
      <CommandStatus command={command} />
    </form>
  );
}
