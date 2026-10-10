import { AtsPermission } from "./AtsPage";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ApiError } from "../../api/client";
import type { Invitation } from "../../api/types";
import { Button } from "../../components/Button";
import { useBackend } from "../../state/BackendContext";
import { ResourceError, useResource } from "./Resource";

const statuses: Record<Invitation["status"], string> = {
  draft: "Черновик",
  viewed: "Просмотрено",
  sent: "Ждёт ответа",
  accepted: "Принято",
  declined: "Отклонено",
  revoked: "Отозвано компанией",
  expired: "Срок истёк",
};
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const money = new Intl.NumberFormat("ru-RU");

export function InvitationSummary({ invitation }: { invitation: Invitation }) {
  return (
    <>
      <p className="api-muted">Организация {invitation.organization_id}</p>
      <p className="invitation-description">{invitation.description}</p>
      <p>
        <strong>
          {money.format(invitation.salary.minimum)}–
          {money.format(invitation.salary.maximum)} ₽ / месяц
        </strong>{" "}
        ·{" "}
        {invitation.salary.tax_basis === "gross"
          ? "до вычета налогов"
          : "на руки"}
      </p>
      <p>Статус: {statuses[invitation.status]}</p>
      <p>
        Ответить до {new Date(invitation.expires_at).toLocaleString("ru-RU")}
      </p>
    </>
  );
}

export function InvitationsPage() {
  const [params] = useSearchParams();
  const selected = params.get("invitation");
  const after = params.get("after");
  if ((selected && !uuid.test(selected)) || (after && !uuid.test(after)))
    return (
      <div className="screen-form">
        <h1>Приглашения</h1>
        <p role="alert">Некорректная ссылка на приглашение.</p>
        <Link to="/candidate/invitations">К списку приглашений</Link>
      </div>
    );
  return selected ? (
    <InvitationDetails key={selected} id={selected} />
  ) : (
    <InvitationList key={after ?? "first"} after={after ?? undefined} />
  );
}

function InvitationList({ after }: { after?: string }) {
  const { api } = useBackend();
  const resource = useResource((signal) => api.invitations(after, signal));
  const items = resource.data;
  return (
    <div className="screen-form">
      <h1>Приглашения</h1>
      <p>Предложения компаний и ваши ответы</p>
      {resource.status === "loading" && (
        <p role="status">Загружаем приглашения…</p>
      )}
      {resource.status === "error" && (
        <ResourceError error={resource.error} retry={resource.reload} />
      )}
      {resource.status === "ready" && items && (
        <>
          {items.length === 0 && (
            <p>
              {after
                ? "На этой странице приглашений нет."
                : "Приглашений пока нет."}
            </p>
          )}
          {items.map((item) => (
            <article className="api-card" key={item.invitation_id}>
              <h2>Приглашение</h2>
              <InvitationSummary invitation={item} />
              <Link
                className="button button-primary"
                to={`/candidate/invitations?invitation=${item.invitation_id}`}
              >
                Посмотреть приглашение
              </Link>
            </article>
          ))}
          <div className="api-actions">
            <Button variant="secondary" onClick={resource.reload}>
              Обновить список
            </Button>
            {after && (
              <Link
                className="button button-secondary"
                to="/candidate/invitations"
              >
                К началу списка
              </Link>
            )}
            {/* Hiring filters restricted rows after its 50-row page: a short page can still have a successor. */}
            {!!items.length && (
              <Link
                className="button button-secondary"
                to={`/candidate/invitations?after=${items.at(-1)!.invitation_id}`}
              >
                Следующая страница
              </Link>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function InvitationDetails({ id }: { id: string }) {
  const { api } = useBackend();
  const resource = useResource((signal) => api.invitation(id, signal));
  return (
    <div className="screen-form">
      <Link to="/candidate/invitations">← Все приглашения</Link>
      <h1>Приглашение компании</h1>
      {resource.status === "loading" && (
        <p role="status">Загружаем приглашение…</p>
      )}
      {resource.status === "error" && (
        <ResourceError error={resource.error} retry={resource.reload} />
      )}
      {resource.status === "ready" && resource.data && (
        <InvitationActions initial={resource.data} reload={resource.reload} />
      )}
    </div>
  );
}

function InvitationActions({
  initial,
  reload,
}: {
  initial: Invitation;
  reload: () => void;
}) {
  const { api, session } = useBackend();
  const [invitation, setInvitation] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>();
  const [decline, setDecline] = useState(false);
  const conflict = error instanceof ApiError && error.status === 409;
  const disabled = busy || conflict || session.status !== "authenticated";
  async function command(action: () => Promise<Invitation>) {
    if (disabled) return;
    setBusy(true);
    setError(undefined);
    try {
      setInvitation(await action());
      setDecline(false);
    } catch (next) {
      setError(next);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <section className="api-card">
        <InvitationSummary invitation={invitation} />
        <p className="invitation-description">
          Контакт работодателя: {invitation.employer_contact}
        </p>
      </section>
      {error !== undefined && <ResourceError error={error} retry={reload} />}
      {["sent", "viewed"].includes(invitation.status) && (
        <>
          <AcceptancePanel
            invitation={invitation}
            disabled={disabled}
            accept={(consent) =>
              command(() =>
                api.acceptInvitation(invitation, {
                  disclosure_consent_id: consent,
                }),
              )
            }
          />
          <section className="api-card">
            <h2>Отказаться от приглашения</h2>
            <label className="consent">
              <input
                type="checkbox"
                checked={decline}
                disabled={disabled}
                onChange={(event) => setDecline(event.target.checked)}
              />
              <span>Подтверждаю отказ от этого приглашения</span>
            </label>
            <Button
              variant="secondary"
              disabled={disabled || !decline}
              onClick={() =>
                void command(() => api.declineInvitation(invitation))
              }
            >
              Отклонить приглашение
            </Button>
          </section>
        </>
      )}
      {invitation.status === "accepted" && (
        <>
          <ContactAccess invitation={invitation} />
          <AtsPermission invitation={invitation} />
          <Link
            className="button button-primary"
            to={`/messages?dialog=${invitation.invitation_id}`}
          >
            Открыть переписку
          </Link>
        </>
      )}
      {!["sent", "viewed"].includes(invitation.status) && (
        <p role="status">
          Ответ сервера: {statuses[invitation.status].toLowerCase()}.
        </p>
      )}
      <Button variant="secondary" disabled={busy} onClick={reload}>
        Обновить приглашение
      </Button>
    </>
  );
}

function AcceptancePanel({
  invitation,
  disabled,
  accept,
}: {
  invitation: Invitation;
  disabled: boolean;
  accept: (consent: string) => Promise<void>;
}) {
  const { api } = useBackend();
  const resource = useResource(async (signal) => {
    const [policies, consents] = await Promise.all([
      api.policies(signal),
      api.consents(signal),
    ]);
    return { policy: policies.contact_disclosure, consents };
  });
  const [confirmed, setConfirmed] = useState<string>();
  const data = resource.data;
  const consent = data?.consents.find(
    (item) =>
      item.purpose === "contact_disclosure" &&
      item.status === "active" &&
      item.document_version === data.policy,
  );
  const binding = consent
    ? `${invitation.version}:${consent.consent_id}:${consent.version}:${data?.policy}`
    : undefined;
  return (
    <section className="api-card">
      <h2>Принять приглашение</h2>
      {resource.status === "loading" && (
        <p role="status">Проверяем согласие на раскрытие контактов…</p>
      )}
      {resource.status === "error" && (
        <ResourceError
          error={resource.error}
          retry={() => {
            setConfirmed(undefined);
            resource.reload();
          }}
        />
      )}
      {resource.status === "ready" && (
        <>
          {!consent ? (
            <p>
              Для принятия нужно действующее согласие на раскрытие контактов
              текущей версии.{" "}
              <Link to="/candidate/privacy">Управлять согласиями</Link>
            </p>
          ) : (
            <>
              <p>
                При принятии компания получит разрешение на доступ к вашим
                контактам. Согласие: {consent.document_version}. Доступ можно
                отозвать в настройках приватности.
              </p>
              <label className="consent">
                <input
                  type="checkbox"
                  disabled={disabled}
                  checked={confirmed === binding}
                  onChange={(event) =>
                    setConfirmed(event.target.checked ? binding : undefined)
                  }
                />
                <span>
                  Принимаю приглашение и разрешаю этой компании доступ к моим
                  контактам
                </span>
              </label>
            </>
          )}
          <Button
            disabled={disabled || !consent || !binding || confirmed !== binding}
            onClick={() => {
              if (consent) void accept(consent.consent_id);
            }}
          >
            Принять приглашение
          </Button>
        </>
      )}
    </section>
  );
}

function ContactAccess({ invitation }: { invitation: Invitation }) {
  const { api } = useBackend();
  const resource = useResource((signal) => api.grants(signal));
  const grant = resource.data?.find(
    (item) =>
      item.invitation_id === invitation.invitation_id &&
      item.organization_id === invitation.organization_id &&
      item.candidate_id === invitation.candidate_id,
  );
  return (
    <section className="api-card">
      <h2>Доступ к контактам</h2>
      {resource.status === "loading" && (
        <p role="status">Проверяем разрешение на доступ…</p>
      )}
      {resource.status === "error" && (
        <ResourceError error={resource.error} retry={resource.reload} />
      )}
      {resource.status === "ready" && (
        <>
          <p role="status">
            {!grant
              ? "Приглашение принято. Разрешение на доступ к контактам пока не подтверждено."
              : grant.status === "revoked"
                ? "Доступ к контактам отозван."
                : grant.status === "expired" ||
                    Date.parse(grant.expires_at) <= Date.now()
                  ? "Срок доступа к контактам истёк."
                  : "Разрешение на доступ к контактам подтверждено сервером."}
          </p>
          {grant && (
            <p>
              Срок разрешения:{" "}
              {new Date(grant.expires_at).toLocaleString("ru-RU")}
            </p>
          )}
          <div className="api-actions">
            <Button variant="secondary" onClick={resource.reload}>
              Проверить доступ
            </Button>
            <Link to="/candidate/privacy">Управлять доступом</Link>
          </div>
        </>
      )}
    </section>
  );
}
