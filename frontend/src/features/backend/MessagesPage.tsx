import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import type { components as Hiring } from "../../api/generated/hiring";
import type { components as Notification } from "../../api/generated/notification";
import { useBackend } from "../../state/BackendContext";
import { Button } from "../../components/Button";
import { useResource } from "./Resource";
import { CommandStatus, Field, LoadState, useCommand, isUuid } from "./ApiUI";
type Dialog = Hiring["schemas"]["DialogView"];
type Message = Hiring["schemas"]["MessageView"];
type Notice = Notification["schemas"]["NotificationView"];

export function MessagesPage() {
  const [params] = useSearchParams();
  const id = params.get("dialog");
  const organization = params.get("organization");
  return (
    <div className="screen-form">
      <h1>Сообщения и уведомления</h1>
      {id ? (
        isUuid(id) ? (
          <Conversation key={id} id={id} employer={!!organization} />
        ) : (
          <p role="alert">Некорректная ссылка на диалог.</p>
        )
      ) : (
        <>
          <p>Откройте переписку из принятого приглашения.</p>
          <Link to="/candidate/invitations">Приглашения кандидата</Link>
          <Link to="/employer/invitation/new">Приглашения компании</Link>
        </>
      )}
      <Notifications employer={!!organization} />
    </div>
  );
}
function Conversation({ id, employer }: { id: string; employer: boolean }) {
  const { api, session } = useBackend();
  const command = useCommand();
  const [text, setText] = useState("");
  const [confirmBlock, setConfirmBlock] = useState(false);
  const [reason, setReason] = useState("");
  const [after, setAfter] = useState(0);
  const resource = useResource((signal) =>
    api.request<Dialog>("hiring", `/v1/dialogs/${id}`, { signal }),
  );
  const dialog = resource.data;
  const refresh = () => {
    command.reset();
    resource.reload();
  };
  return (
    <>
      <LoadState resource={resource} />
      {dialog && resource.status === "ready" && (
        <>
          <h2>Переписка с организацией {dialog.organization_id}</h2>
          <p>
            {dialog.blocked
              ? "Компания заблокирована. Новые сообщения недоступны."
              : "Доступ проверяется сервером при каждом запросе."}
          </p>
          {!dialog.blocked && (
            <MessageList
              key={`${id}:${after}:${dialog.version}`}
              id={id}
              after={after}
              next={setAfter}
            />
          )}
          {!dialog.blocked && (
            <form
              className="api-card api-form"
              onSubmit={(e) => {
                e.preventDefault();
                void command.run(async () => {
                  await api.request<Message>(
                    "hiring",
                    `/v1/dialogs/${id}/messages`,
                    {
                      method: "POST",
                      body: { text: text.trim() },
                      version: dialog.version,
                      intent: `message:${id}`,
                    },
                  );
                  setText("");
                  resource.reload();
                }, "Сообщение отправлено.");
              }}
            >
              <Field label="Сообщение">
                <textarea
                  required
                  maxLength={4000}
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                />
              </Field>
              <Button type="submit" disabled={command.disabled || !text.trim()}>
                Отправить сообщение
              </Button>
            </form>
          )}
          {!employer &&
            session.roles?.includes("candidate") &&
            !dialog.blocked && (
              <section className="api-card">
                <h3>Блокировка компании</h3>
                <p>
                  Блокировка закроет сообщения, контакты и новые приглашения
                  этой компании. Снять её в текущей версии сервиса нельзя.
                </p>
                <label className="consent">
                  <input
                    type="checkbox"
                    checked={confirmBlock}
                    onChange={(e) => setConfirmBlock(e.target.checked)}
                  />
                  <span>Подтверждаю блокировку компании</span>
                </label>
                <Button
                  variant="secondary"
                  disabled={command.disabled || !confirmBlock}
                  onClick={() =>
                    void command.run(async () => {
                      await api.request("hiring", `/v1/dialogs/${id}/block`, {
                        method: "POST",
                        version: dialog.version,
                        intent: `block:${id}`,
                      });
                      resource.reload();
                    }, "Компания заблокирована.")
                  }
                >
                  Заблокировать компанию
                </Button>
              </section>
            )}
          <form
            className="api-card api-form"
            onSubmit={(e) => {
              e.preventDefault();
              void command.run(async () => {
                await api.request("hiring", `/v1/dialogs/${id}/complaints`, {
                  method: "POST",
                  body: { reason: reason.trim() },
                  intent: `complaint:${id}`,
                });
                setReason("");
              }, "Жалоба зарегистрирована.");
            }}
          >
            <h3>Сообщить о проблеме</h3>
            <Field label="Причина жалобы">
              <textarea
                required
                maxLength={2000}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
              />
            </Field>
            <Button type="submit" disabled={command.disabled || !reason.trim()}>
              Отправить жалобу
            </Button>
          </form>
        </>
      )}
      <CommandStatus command={command} refresh={refresh} />
      <Button variant="secondary" disabled={command.busy} onClick={refresh}>
        Обновить диалог
      </Button>
    </>
  );
}
function MessageList({
  id,
  after,
  next,
}: {
  id: string;
  after: number;
  next: (v: number) => void;
}) {
  const { api } = useBackend();
  const resource = useResource((signal) =>
    api.request<Message[]>(
      "hiring",
      `/v1/dialogs/${id}/messages?after=${after}`,
      { signal },
    ),
  );
  return (
    <section className="api-card">
      <LoadState resource={resource} />
      {resource.status === "ready" && (
        <>
          {!resource.data?.length && <p>На этой странице сообщений нет.</p>}
          {resource.data?.map((message) => (
            <article key={message.message_id}>
              <p className="api-muted">
                {message.author_id} ·{" "}
                {new Date(message.created_at).toLocaleString("ru-RU")}
              </p>
              <p className="invitation-description">{message.text}</p>
            </article>
          ))}
          <div className="api-actions">
            {after > 0 && (
              <Button variant="secondary" onClick={() => next(0)}>
                В начало переписки
              </Button>
            )}
            {resource.data?.length === 50 && (
              <Button
                variant="secondary"
                onClick={() => next(resource.data!.at(-1)!.sequence)}
              >
                Следующие сообщения
              </Button>
            )}
          </div>
        </>
      )}
    </section>
  );
}
const kinds: Record<string, string> = {
  task_available: "Новое подходящее задание",
  invitation_sent: "Новое приглашение",
  invitation_accepted: "Приглашение принято",
  invitation_declined: "Приглашение отклонено",
  invitation_revoked: "Приглашение отозвано",
  message_created: "Новое сообщение",
  message_sent: "Новое сообщение",
};
export function Notifications({ employer = false }: { employer?: boolean }) {
  const [after, setAfter] = useState("");
  return (
    <NotificationPage
      key={after}
      after={after}
      next={setAfter}
      employer={employer}
    />
  );
}
function NotificationPage({
  after,
  next,
  employer,
}: {
  after: string;
  next: (v: string) => void;
  employer: boolean;
}) {
  const { api } = useBackend();
  const command = useCommand();
  const resource = useResource((signal) =>
    api.request<Notice[]>(
      "notification",
      `/v1/notifications${after ? `?after=${after}` : ""}`,
      { signal },
    ),
  );
  return (
    <section className="api-card">
      <h2>Уведомления</h2>
      <LoadState resource={resource} />
      {resource.status === "ready" && (
        <>
          {!resource.data?.length && <p>Уведомлений нет.</p>}
          {resource.data?.map((notice) => (
            <article className="api-list-row" key={notice.notice_id}>
              <div>
                <strong>
                  {kinds[notice.kind] ?? "Обновление по вашему действию"}
                </strong>
                <p>{notice.read ? "Прочитано" : "Новое"}</p>
                {notice.kind === "task_available" && <Link to="/candidate/assessment">Посмотреть задания</Link>}
                {notice.invitation_id && (
                  <Link
                    to={
                      employer
                        ? "/employer/invitation/new"
                        : `/candidate/invitations?invitation=${notice.invitation_id}`
                    }
                  >
                    Открыть приглашение
                  </Link>
                )}
              </div>
              {!notice.read && (
                <Button
                  variant="secondary"
                  disabled={command.disabled}
                  onClick={() =>
                    void command.run(async () => {
                      await api.request(
                        "notification",
                        `/v1/notifications/${notice.notice_id}/read`,
                        {
                          method: "POST",
                          version: notice.version,
                          intent: `read:${notice.notice_id}`,
                        },
                      );
                      resource.reload();
                    }, "Прочитано.")
                  }
                >
                  Отметить прочитанным
                </Button>
              )}
            </article>
          ))}
          <div className="api-actions">
            <Button variant="secondary" onClick={resource.reload}>
              Обновить уведомления
            </Button>
            {after && (
              <Button variant="secondary" onClick={() => next("")}>
                В начало уведомлений
              </Button>
            )}
            {!!resource.data?.length && (
              <Button
                variant="secondary"
                onClick={() => next(resource.data!.at(-1)!.notice_id)}
              >
                Следующие уведомления
              </Button>
            )}
          </div>
        </>
      )}
      <CommandStatus command={command} refresh={resource.reload} />
    </section>
  );
}
