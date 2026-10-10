import { useState } from "react";
import type { components as P } from "../../api/generated/privacy";
import type { components as N } from "../../api/generated/notification";
import { useBackend } from "../../state/BackendContext";
import { Button } from "../../components/Button";
import { useResource } from "./Resource";
import { CommandStatus, Field, LoadState, useCommand } from "./ApiUI";
import { ConsentGate } from "./ConsentGate";
type Request = P["schemas"]["RequestView"];
export function PrivacyExtras() {
  const [tab, setTab] = useState("");
  return (
    <>
      <div className="api-actions">
        <Button
          variant="secondary"
          onClick={() => setTab(tab === "rights" ? "" : "rights")}
        >
          Запросы о моих данных
        </Button>
        <Button
          variant="secondary"
          onClick={() => setTab(tab === "notifications" ? "" : "notifications")}
        >
          Настроить уведомления
        </Button>
      </div>
      {tab === "rights" && <RightsRequests />}
      {tab === "notifications" && <NotificationSettings />}
    </>
  );
}
export function RightsRequests({ officer = false }: { officer?: boolean }) {
  const { api } = useBackend();
  const [after, setAfter] = useState("");
  return (
    <RightsList
      key={after}
      after={after}
      next={setAfter}
      officer={officer}
      api={api}
    />
  );
}
function RightsList({
  after,
  next,
  officer,
  api,
}: {
  after: string;
  next: (v: string) => void;
  officer: boolean;
  api: ReturnType<typeof useBackend>["api"];
}) {
  const resource = useResource((signal) =>
    api.request<Request[]>(
      "privacy",
      `/v1/data-subject-requests${officer ? "/queue" : ""}${after ? `?after=${after}` : ""}`,
      { signal },
    ),
  );
  return (
    <section className="screen-form">
      <h2>{officer ? "Обращения о данных" : "Мои обращения о данных"}</h2>
      {!officer && <RightsForm saved={resource.reload} />}
      <LoadState resource={resource} />
      {resource.data?.map((item) => (
        <RightsCard
          key={`${item.request_id}:${item.version}`}
          item={item}
          officer={officer}
          reload={resource.reload}
        />
      ))}
      {resource.status === "ready" && !resource.data?.length && (
        <p>На этой странице обращений нет.</p>
      )}
      <Button variant="secondary" onClick={resource.reload}>
        Обновить обращения
      </Button>
      {!!resource.data?.length && (
        <Button
          variant="secondary"
          onClick={() => next(resource.data!.at(-1)!.request_id)}
        >
          Следующие обращения
        </Button>
      )}
      {after && (
        <Button variant="secondary" onClick={() => next("")}>
          В начало обращений
        </Button>
      )}
    </section>
  );
}
function RightsForm({ saved }: { saved: () => void }) {
  const { api } = useBackend();
  const command = useCommand();
  const [kind, setKind] = useState<"access" | "restriction" | "correction">(
    "access",
  );
  const [reason, setReason] = useState("");
  const [name, setName] = useState("");
  const [specialization, setSpecialization] = useState("");
  const [grade, setGrade] = useState("junior");
  return (
    <form
      className="api-card api-form"
      onSubmit={(e) => {
        e.preventDefault();
        void command.run(async () => {
          let body: unknown = { kind, reason: reason.trim() };
          if (kind === "correction") {
            const profile = await api.profile();
            body = {
              kind,
              reason: reason.trim(),
              domain: "candidate",
              target: "profile",
              source_version: profile.version,
              proposed_changes: {
                display_name: name.trim(),
                specialization: specialization.trim(),
                declared_grade: grade,
              },
            };
          }
          await api.request("privacy", "/v1/data-subject-requests", {
            method: "POST",
            body,
            intent: "rights-request",
          });
          setReason("");
          saved();
        }, "Обращение зарегистрировано.");
      }}
    >
      <h3>Новое обращение</h3>
      <Field label="Тип обращения">
        <select
          value={kind}
          onChange={(e) => setKind(e.target.value as typeof kind)}
        >
          <option value="access">Получить копию данных</option>
          <option value="correction">Запросить исправление профиля</option>
          <option value="restriction">Ограничить обработку данных</option>
        </select>
      </Field>
      {kind === "restriction" && (
        <p>
          Ограничение может закрыть доступ к связанным функциям. Статус и
          решение будут показаны в обращении.
        </p>
      )}
      {kind === "correction" && (
        <>
          <Field label="Правильное имя">
            <input
              required
              maxLength={100}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </Field>
          <Field label="Правильная специализация">
            <input
              required
              maxLength={100}
              value={specialization}
              onChange={(e) => setSpecialization(e.target.value)}
            />
          </Field>
          <Field label="Заявленный грейд для исправления">
            <select value={grade} onChange={(e) => setGrade(e.target.value)}>
              {["junior", "middle", "senior", "lead"].map((x) => (
                <option key={x}>{x}</option>
              ))}
            </select>
          </Field>
        </>
      )}
      <Field label="Причина обращения о данных">
        <textarea
          required
          maxLength={2000}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
        />
      </Field>
      <Button type="submit" disabled={command.disabled || !reason.trim()}>
        Отправить обращение о данных
      </Button>
      <CommandStatus command={command} />
    </form>
  );
}
const requestStatuses: Record<Request["status"], string> = {
  submitted: "Зарегистрировано",
  in_review: "На рассмотрении",
  approved: "Одобрено",
  applying: "Исполняется",
  rejected: "Отклонено",
  completed: "Завершено",
  withdrawn: "Отозвано",
};
function RightsCard({
  item,
  officer,
  reload,
}: {
  item: Request;
  officer: boolean;
  reload: () => void;
}) {
  const { api } = useBackend();
  const command = useCommand();
  const [reason, setReason] = useState("");
  const [outcome, setOutcome] = useState("approved");
  const [archive, setArchive] = useState(false);
  const act = (suffix: string, body?: unknown) =>
    command.run(async () => {
      await api.request(
        "privacy",
        `/v1/data-subject-requests/${item.request_id}/${suffix}`,
        {
          method: "POST",
          body,
          version: item.version,
          intent: `rights:${item.request_id}:${suffix}`,
        },
      );
      reload();
    });
  return (
    <article className="api-card">
      <h3>
        {
          {
            access: "Копия данных",
            correction: "Исправление",
            restriction: "Ограничение обработки",
          }[item.kind]
        }
      </h3>
      <p>{requestStatuses[item.status]}</p>
      <p>Ответ до {new Date(item.due_at).toLocaleString("ru-RU")}</p>
      {typeof item.data.reason === "string" && <p>{item.data.reason}</p>}
      {item.kind === "correction" && (
        <details>
          <summary>Предлагаемые изменения</summary>
          <pre className="api-code">{JSON.stringify(item.data, null, 2)}</pre>
        </details>
      )}
      {item.restriction_active && <p>Обработка ограничена.</p>}
      {officer ? (
        <>
          {item.status === "submitted" && (
            <Button
              disabled={command.disabled}
              onClick={() => void act("claim")}
            >
              Взять обращение
            </Button>
          )}
          {item.status === "in_review" && (
            <>
              <Field label="Решение по обращению">
                <select
                  value={outcome}
                  onChange={(e) => setOutcome(e.target.value)}
                >
                  <option value="approved">Одобрить</option>
                  <option value="rejected">Отклонить</option>
                </select>
              </Field>
              <Field label="Причина решения по данным">
                <textarea
                  maxLength={2000}
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                />
              </Field>
              <Button
                disabled={command.disabled || !reason.trim()}
                onClick={() => void act("decision", { outcome, reason })}
              >
                Сохранить решение по данным
              </Button>
            </>
          )}
          {item.kind === "correction" &&
            ["approved", "applying"].includes(item.status) && (
              <Button
                disabled={command.disabled}
                onClick={() => void act("execute")}
              >
                Выполнить одобренное исправление
              </Button>
            )}
        </>
      ) : (
        <>
          {["submitted", "in_review", "approved"].includes(item.status) && (
            <Button
              variant="secondary"
              disabled={command.disabled}
              onClick={() => void act("withdraw")}
            >
              Отозвать обращение
            </Button>
          )}
          {item.kind === "access" &&
            ["approved", "completed"].includes(item.status) && (
              <>
                <Button onClick={() => setArchive((v) => !v)}>
                  Открыть архив данных
                </Button>
                {archive && <DataArchive requestId={item.request_id} />}
              </>
            )}
        </>
      )}
      <CommandStatus command={command} refresh={reload} />
    </article>
  );
}
type Archive = {
  archive_id: string;
  status: "building" | "ready" | "failed";
  version: number;
  manifest: { complete?: boolean; page_count?: number };
};
function DataArchive({ requestId }: { requestId: string }) {
  const { api } = useBackend();
  const command = useCommand();
  const [archive, setArchive] = useState<Archive>();
  const [cursor, setCursor] = useState<string>();
  const [number, setNumber] = useState(0);
  const [finished, setFinished] = useState(false);
  const base = `/v1/data-subject-requests/${requestId}/archives`;
  return (
    <section className="api-card">
      <p>
        {archive?.status === "ready"
          ? archive.manifest.complete
            ? "Архив собран полностью."
            : "Архив содержит доступную часть данных."
          : "Подготовка архива выполняется по шагам."}
      </p>
      {!archive ? (
        <Button
          disabled={command.disabled}
          onClick={() =>
            void command.run(
              async () =>
                setArchive(
                  await api.request<Archive>("privacy", base, {
                    method: "POST",
                  }),
                ),
              "Архив открыт.",
            )
          }
        >
          Подготовить архив
        </Button>
      ) : archive.status === "building" ? (
        <Button
          disabled={command.disabled}
          onClick={() =>
            void command.run(
              async () =>
                setArchive(
                  await api.request<Archive>(
                    "privacy",
                    `${base}/${archive.archive_id}/advance`,
                    { method: "POST" },
                  ),
                ),
              "Состояние архива обновлено.",
            )
          }
        >
          Продолжить сборку архива
        </Button>
      ) : (
        archive.status === "ready" && (
          <Button
            disabled={command.disabled || finished}
            onClick={() =>
              void command.run(async () => {
                const page = await api.request<{
                  next_cursor: string | null;
                  [key: string]: unknown;
                }>(
                  "privacy",
                  `${base}/${archive.archive_id}/pages${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ""}`,
                );
                const blob = new Blob([JSON.stringify(page, null, 2)], {
                  type: "application/json",
                });
                const url = URL.createObjectURL(blob);
                const link = document.createElement("a");
                link.href = url;
                link.download = `my-data-page-${number + 1}.json`;
                link.click();
                setTimeout(() => URL.revokeObjectURL(url), 1000);
                setNumber((n) => n + 1);
                setCursor(page.next_cursor ?? undefined);
                setFinished(!page.next_cursor);
              }, "Страница архива скачана.")
            }
          >
            {finished
              ? "Все страницы скачаны"
              : `Скачать страницу ${number + 1}`}
          </Button>
        )
      )}
      <CommandStatus command={command} />
    </section>
  );
}
function NotificationSettings() {
  const { api } = useBackend();
  const command = useCommand();
  const [email, setEmail] = useState("");
  const [challenge, setChallenge] = useState<{
    challenge_id: string;
    expires_at: string;
  }>();
  const [code, setCode] = useState("");
  const resource = useResource(async (signal) => {
    const [preferences, target] = await Promise.all([
      api.request<N["schemas"]["PreferenceView"]>(
        "notification",
        "/v1/notifications/preferences",
        { signal },
      ),
      api.request<{ email: string | null; verified: boolean; version: number }>(
        "notification",
        "/v1/notifications/email",
        { signal },
      ),
    ]);
    return { preferences, target };
  });
  return (
    <section className="api-card">
      <h2>Уведомления</h2>
      <LoadState resource={resource} />
      {resource.data && (
        <>
          <p>
            В приложении:{" "}
            {resource.data.preferences.in_app ? "включены" : "выключены"}
          </p>
          <Button
            variant="secondary"
            disabled={command.disabled}
            onClick={() =>
              void command.run(async () => {
                await api.request(
                  "notification",
                  "/v1/notifications/preferences",
                  {
                    method: "PUT",
                    body: {
                      in_app: !resource.data!.preferences.in_app,
                      marketing_in_app:
                        resource.data!.preferences.marketing_in_app ?? false,
                    },
                    version: resource.data!.preferences.version,
                    intent: "notification-preferences",
                  },
                );
                resource.reload();
              })
            }
          >
            {resource.data.preferences.in_app
              ? "Отключить уведомления в приложении"
              : "Включить уведомления в приложении"}
          </Button>
          <p>
            Email: {resource.data.target.email ?? "не указан"} ·{" "}
            {resource.data.target.verified ? "подтверждён" : "не подтверждён"}
          </p>
        </>
      )}
      <ConsentGate purpose="external_service_notifications">
        {(consent) => (
          <>
            <form
              className="api-form"
              onSubmit={(e) => {
                e.preventDefault();
                void command.run(
                  async () =>
                    setChallenge(
                      await api.request(
                        "notification",
                        "/v1/notifications/email",
                        {
                          method: "POST",
                          body: { email: email.trim(), consent_id: consent },
                          intent: "email-target",
                        },
                      ),
                    ),
                  "Запрос подтверждения принят. Введите код из письма.",
                );
              }}
            >
              <Field label="Email для уведомлений">
                <input
                  required
                  type="email"
                  maxLength={254}
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />
              </Field>
              <Button type="submit" disabled={command.disabled}>
                Запросить код подтверждения
              </Button>
            </form>
            {resource.data?.target.verified && (
              <EmailPreferences consent={consent} />
            )}
          </>
        )}
      </ConsentGate>
      {challenge && (
        <form
          className="api-form"
          onSubmit={(e) => {
            e.preventDefault();
            void command.run(async () => {
              const result = await api.request<{ verified: boolean }>(
                "notification",
                "/v1/notifications/email/verify",
                {
                  method: "POST",
                  body: { challenge_id: challenge.challenge_id, code },
                },
              );
              if (!result.verified) throw new Error("Код не подтверждён");
              setChallenge(undefined);
              setCode("");
              resource.reload();
            }, "Email подтверждён.");
          }}
        >
          <Field label="Код из письма">
            <input
              required
              inputMode="numeric"
              pattern="[0-9]{6}"
              value={code}
              onChange={(e) => setCode(e.target.value)}
            />
          </Field>
          <p>
            Код действует до{" "}
            {new Date(challenge.expires_at).toLocaleString("ru-RU")}
          </p>
          <Button type="submit" disabled={command.disabled}>
            Подтвердить email
          </Button>
        </form>
      )}
      <CommandStatus command={command} refresh={resource.reload} />
    </section>
  );
}
function EmailPreferences({ consent }: { consent: string }) {
  const { api } = useBackend();
  const command = useCommand();
  const resource = useResource((signal) =>
    api.request<{
      service_email: boolean;
      marketing_email: boolean;
      version: number;
    }>("notification", "/v1/notifications/email/preferences", { signal }),
  );
  return (
    <>
      <LoadState resource={resource} />
      {resource.data && (
        <>
          <p>
            Сервисные письма:{" "}
            {resource.data.service_email ? "включены" : "выключены"}
          </p>
          <Button
            disabled={command.disabled}
            onClick={() =>
              void command.run(async () => {
                const [policies, consents] = await Promise.all([
                  api.policies(),
                  api.consents(),
                ]);
                const marketing = consents.find(
                  (c) =>
                    c.purpose === "external_marketing_notifications" &&
                    c.status === "active" &&
                    c.document_version ===
                      policies.external_marketing_notifications,
                );
                await api.request(
                  "notification",
                  "/v1/notifications/email/preferences",
                  {
                    method: "PUT",
                    version: resource.data!.version,
                    body: {
                      service_email: !resource.data!.service_email,
                      marketing_email: resource.data!.marketing_email,
                      service_consent_id: consent,
                      marketing_consent_id: marketing?.consent_id ?? null,
                    },
                    intent: "email-preferences",
                  },
                );
                resource.reload();
              })
            }
          >
            {resource.data.service_email
              ? "Отключить письма"
              : "Включить сервисные письма"}
          </Button>
          <p>Рекламные письма не включаются вместе с сервисными.</p>
        </>
      )}
      <CommandStatus command={command} refresh={resource.reload} />
    </>
  );
}
