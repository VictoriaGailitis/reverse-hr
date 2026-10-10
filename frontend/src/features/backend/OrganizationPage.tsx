import { useState, type FormEvent } from "react";
import type { Membership, Organization } from "../../api/types";
import { errorMessage } from "../../api/client";
import { useBackend } from "../../state/BackendContext";
import { Button } from "../../components/Button";
import { ResourceError, useResource } from "./Resource";
import { CommandStatus, Field, useCommand, uuidPattern } from "./ApiUI";

function Members({
  organization,
  refreshOrganization,
}: {
  organization: Organization;
  refreshOrganization: () => void;
}) {
  const { api, session } = useBackend();
  const resource = useResource((signal) =>
    api.members(organization.organization_id, signal),
  );
  const command = useCommand();
  const [subject, setSubject] = useState("");
  const [role, setRole] = useState<"recruiter" | "technical_expert">(
    "recruiter",
  );
  const [revoke, setRevoke] = useState("");
  const owner = resource.data?.some(
    (member) =>
      member.subject === session.subject &&
      member.role === "owner" &&
      member.status === "active",
  );
  const refresh = () => {
    resource.reload();
    refreshOrganization();
  };
  const labels = {
    owner: "Владелец",
    recruiter: "Рекрутер",
    technical_expert: "Технический эксперт",
  };
  return (
    <div className="api-card">
      <h2>Сотрудники</h2>
      {resource.status === "loading" && (
        <p role="status">Загружаем членства…</p>
      )}
      {resource.status === "error" && (
        <ResourceError error={resource.error} retry={resource.reload} />
      )}
      {resource.status === "ready" &&
        resource.data?.map((member: Membership) => (
          <article key={member.membership_id}>
            <p>
              {member.subject} · {labels[member.role]} ·{" "}
              {member.status === "active" ? "активно" : "отозвано"}
            </p>
            {owner && member.status === "active" && member.role !== "owner" && (
              <>
                {revoke === member.membership_id ? (
                  <>
                    <p>
                      Сотрудник потеряет доступ к данным и действиям этой
                      компании.
                    </p>
                    <Button
                      disabled={command.disabled}
                      onClick={() =>
                        void command.run(async () => {
                          await api.request(
                            "employer",
                            `/v1/organizations/${organization.organization_id}/members/${member.membership_id}/revoke`,
                            {
                              method: "POST",
                              version: member.version,
                              intent: `revoke-member:${member.membership_id}`,
                            },
                          );
                          setRevoke("");
                          refresh();
                        }, "Доступ сотрудника отозван.")
                      }
                    >
                      Подтвердить отзыв доступа
                    </Button>
                    <Button variant="secondary" onClick={() => setRevoke("")}>
                      Оставить доступ
                    </Button>
                  </>
                ) : (
                  <Button
                    variant="secondary"
                    onClick={() => setRevoke(member.membership_id)}
                  >
                    Отозвать доступ сотрудника
                  </Button>
                )}
              </>
            )}
          </article>
        ))}
      {owner && (
        <form
          className="api-form"
          onSubmit={(event) => {
            event.preventDefault();
            void command.run(async () => {
              await api.addMember(organization, { subject, role });
              setSubject("");
              refresh();
            }, "Сотрудник добавлен.");
          }}
        >
          <h3>Добавить сотрудника</h3>
          <Field label="Идентификатор учётной записи сотрудника">
            <input
              required
              pattern={uuidPattern}
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
            />
          </Field>
          <Field label="Роль сотрудника">
            <select
              value={role}
              onChange={(e) => setRole(e.target.value as typeof role)}
            >
              <option value="recruiter">Рекрутер</option>
              <option value="technical_expert">Технический эксперт</option>
            </select>
          </Field>
          <Button type="submit" disabled={command.disabled}>
            Добавить сотрудника
          </Button>
        </form>
      )}
      <CommandStatus command={command} refresh={refresh} />
    </div>
  );
}

export function OrganizationPage() {
  const { api, session } = useBackend();
  const resource = useResource((signal) => api.organizations(signal));
  const [name, setName] = useState("");
  const [selected, setSelected] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>();
  const [notice, setNotice] = useState("");
  const organization =
    resource.data?.find((item) => item.organization_id === selected) ??
    resource.data?.[0];
  async function create(event: FormEvent) {
    event.preventDefault();
    if (busy || session.status !== "authenticated") return;
    setBusy(true);
    setError(undefined);
    try {
      const result = await api.createOrganization({ name: name.trim() });
      setSelected(result.organization_id);
      setName("");
      setNotice(
        "Организация создана на сервере. Статус верификации проверяется отдельно.",
      );
      resource.reload();
    } catch (next) {
      setError(next);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="screen-form">
      <h1>Кабинет компании</h1>
      <p>Ваши доступные организации</p>
      {notice && (
        <p className="api-note" role="status">
          {notice}
        </p>
      )}
      {resource.status === "loading" && (
        <p role="status">Загружаем организации…</p>
      )}
      {resource.status === "error" && (
        <ResourceError error={resource.error} retry={resource.reload} />
      )}
      {resource.status === "ready" && (
        <>
          {!resource.data?.length && (
            <p className="empty-state">У вас пока нет доступных организаций.</p>
          )}
          {organization && (
            <>
              <section className="api-card">
                <h2>Организация</h2>
                <label className="form-field">
                  <span>Выберите организацию</span>
                  <select
                    value={organization.organization_id}
                    onChange={(event) => setSelected(event.target.value)}
                  >
                    {resource.data?.map((item) => (
                      <option
                        key={item.organization_id}
                        value={item.organization_id}
                      >
                        {item.name}
                      </option>
                    ))}
                  </select>
                </label>
                <p>
                  Верификация:{" "}
                  {organization.verification_status === "verified"
                    ? "подтверждена"
                    : organization.verification_status === "rejected"
                      ? "отклонена"
                      : "ожидает проверки"}
                </p>
                {organization.verification_reason && (
                  <p>{organization.verification_reason}</p>
                )}
                <Button variant="secondary" onClick={resource.reload}>
                  Обновить статус компании
                </Button>
              </section>
              <Members
                key={organization.organization_id}
                organization={organization}
                refreshOrganization={resource.reload}
              />
            </>
          )}
          <form
            className="api-card api-form"
            onSubmit={(event) => void create(event)}
          >
            <h2>Создать организацию</h2>
            <label className="form-field">
              <span>Название организации</span>
              <input
                required
                maxLength={200}
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
            </label>
            <Button
              type="submit"
              disabled={busy || session.status !== "authenticated"}
            >
              {busy ? "Создаём…" : "Создать организацию"}
            </Button>
            {error !== undefined && <p role="alert">{errorMessage(error)}</p>}
          </form>
        </>
      )}
    </div>
  );
}
