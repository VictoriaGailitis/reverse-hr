import { PrivacyExtras } from "./PrivacyExtras";
import { useState } from "react";
import type { Consent, ContactGrant, Purpose } from "../../api/types";
import { useBackend } from "../../state/BackendContext";
import { Button } from "../../components/Button";
import { missingAsNull, ResourceError, useResource } from "./Resource";

const purposes: Record<Purpose, string> = {
  achievement_import: "Импорт достижений",
  achievement_publication: "Публикация достижений",
  company_task_subscription: "Подписка на задания компаний",
  resume_publication: "Публикация резюме",
  external_service_notifications: "Сервисные уведомления по email",
  external_marketing_notifications: "Рекламные уведомления по email",
  company_result_disclosure: "Передача результата компании",
  assessment: "Оценка навыков",
  recording: "Запись этапа",
  profile_publication: "Публикация профиля",
  ats_export: "Экспорт в ATS",
  contact_disclosure: "Раскрытие контактов",
};

export function PrivacyPage() {
  const { api, session } = useBackend();
  const resource = useResource(async (signal) => {
    // Deletion restricts the other reads. Its status endpoint remains available.
    const deletion = await missingAsNull(api.deletion(signal));
    if (deletion)
      return {
        policies: {} as Record<string, string>,
        consents: [] as Consent[],
        grants: [] as ContactGrant[],
        deletion,
      };
    const [policies, consents, grants] = await Promise.all([
      api.policies(signal),
      api.consents(signal),
      api.grants(signal),
    ]);
    return { policies, consents, grants, deletion };
  });
  const [checks, setChecks] = useState<Partial<Record<Purpose, string>>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>();
  const [notice, setNotice] = useState("");
  const [confirmDeletion, setConfirmDeletion] = useState(false);
  const data = resource.data;
  async function command(action: () => Promise<unknown>, message: string) {
    if (busy || session.status !== "authenticated") return;
    setBusy(true);
    setError(undefined);
    setNotice("");
    try {
      await action();
      setNotice(message);
      resource.reload();
    } catch (next) {
      setError(next);
    } finally {
      setBusy(false);
    }
  }
  const disabled = busy || session.status !== "authenticated";
  return (
    <div className="screen-form">
      <h1>Приватность и доступ</h1>
      <p>Ваши согласия и разрешения на доступ</p>
      {notice && (
        <p className="api-note" role="status">
          {notice}
        </p>
      )}
      {error !== undefined && (
        <ResourceError
          error={error}
          retry={() => {
            setError(undefined);
            resource.reload();
          }}
        />
      )}
      {resource.status === "loading" && (
        <p role="status">Загружаем настройки…</p>
      )}
      {resource.status === "error" && (
        <ResourceError error={resource.error} retry={resource.reload} />
      )}
      {resource.status === "ready" && data && (
        <>
          {!data.deletion && (
            <section className="api-card">
              <h2>Согласия</h2>
              <p className="api-muted">
                Версии документов предоставляет сервер. Политика demo-v1 —
                техническая политика демостенда; тексты рабочих документов ещё
                не подключены.
              </p>
              {Object.entries(purposes).map(([key, title]) => {
                const purpose = key as Purpose;
                const policy = data.policies[purpose];
                const active = data.consents.find(
                  (consent) =>
                    consent.purpose === purpose &&
                    consent.status === "active" &&
                    consent.document_version === policy,
                );
                return (
                  <div className="api-list-row" key={purpose}>
                    <div>
                      <strong>{title}</strong>
                      <p>Документ: {policy ?? "недоступен"}</p>
                      {active ? (
                        <p>Активно · версия {active.version}</p>
                      ) : (
                        <label className="consent">
                          <input
                            type="checkbox"
                            disabled={!policy}
                            checked={!!policy && checks[purpose] === policy}
                            onChange={(event) =>
                              setChecks((current) => ({
                                ...current,
                                [purpose]: event.target.checked
                                  ? policy
                                  : undefined,
                              }))
                            }
                          />
                          <span>
                            Разрешаю: {title.toLowerCase()} ·{" "}
                            {policy ?? "документ не получен"}
                          </span>
                        </label>
                      )}
                    </div>
                    {active ? (
                      <Button
                        variant="secondary"
                        disabled={disabled}
                        onClick={() =>
                          void command(
                            () => api.revokeConsent(active),
                            "Отзыв согласия подтверждён сервером.",
                          )
                        }
                      >
                        Отозвать: {title}
                      </Button>
                    ) : (
                      <Button
                        disabled={
                          disabled || !policy || checks[purpose] !== policy
                        }
                        onClick={() =>
                          void command(async () => {
                            await api.consent({
                              purpose,
                              document_version: policy,
                            });
                            setChecks((current) => ({
                              ...current,
                              [purpose]: undefined,
                            }));
                          }, "Согласие подтверждено сервером.")
                        }
                      >
                        Разрешить: {title}
                      </Button>
                    )}
                  </div>
                );
              })}
              {!!data.consents.length && (
                <details>
                  <summary>История согласий</summary>
                  {data.consents.map((consent: Consent) => (
                    <p key={consent.consent_id}>
                      {purposes[consent.purpose]} · {consent.document_version} ·{" "}
                      {consent.status === "active" ? "активно" : "отозвано"} · v
                      {consent.version}
                    </p>
                  ))}
                </details>
              )}
            </section>
          )}
          {!data.deletion && (
            <section className="api-card">
              <h2>Компании с доступом</h2>
              {!data.grants.length && (
                <p>Действующих разрешений нет. Контакты закрыты.</p>
              )}
              {data.grants.map((grant: ContactGrant) => (
                <div className="api-list-row" key={grant.grant_id}>
                  <div>
                    <strong>Организация {grant.organization_id}</strong>
                    <p>
                      {grant.status === "active"
                        ? "Доступ разрешён"
                        : grant.status === "revoked"
                          ? "Доступ отозван"
                          : "Срок доступа истёк"}
                    </p>
                    <p>
                      До {new Date(grant.expires_at).toLocaleString("ru-RU")}
                    </p>
                  </div>
                  <Button
                    variant="secondary"
                    disabled={disabled || grant.status !== "active"}
                    onClick={() =>
                      void command(
                        () => api.revokeGrant(grant),
                        "Отзыв доступа подтверждён сервером.",
                      )
                    }
                  >
                    Отозвать доступ
                  </Button>
                </div>
              ))}
            </section>
          )}
          <PrivacyExtras />
          <section className="api-card">
            <h2>Удаление данных</h2>
            {data.deletion ? (
              <>
                <p role="status">
                  {data.deletion.status === "completed"
                    ? "Удаление подтверждено сервером"
                    : "Удаление выполняется"}
                </p>
                {Object.entries(data.deletion.services).map(
                  ([service, status]) => (
                    <p key={service}>
                      {service}:{" "}
                      {status === "deleted"
                        ? "удалено"
                        : status === "restricted"
                          ? "обработка ограничена"
                          : "ожидает обработки"}
                    </p>
                  ),
                )}
                <Button variant="secondary" onClick={resource.reload}>
                  Обновить статус удаления
                </Button>
              </>
            ) : (
              <>
                <p>
                  Запрос ограничит обработку данных и начнёт их удаление в
                  сервисах. Это действие выполняется на сервере.
                </p>
                <label className="consent">
                  <input
                    type="checkbox"
                    checked={confirmDeletion}
                    onChange={(event) =>
                      setConfirmDeletion(event.target.checked)
                    }
                  />
                  <span>Подтверждаю запрос удаления моих данных</span>
                </label>
                <Button
                  variant="secondary"
                  disabled={disabled || !confirmDeletion}
                  onClick={() =>
                    void command(
                      () => api.requestDeletion(),
                      "Запрос принят сервером. Завершение проверяется отдельно.",
                    )
                  }
                >
                  Запросить удаление
                </Button>
              </>
            )}
          </section>
        </>
      )}
    </div>
  );
}
