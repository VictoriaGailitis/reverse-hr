import { useState } from "react";
import { PreferencesPage } from "./PreferencesPage";
import { Link } from "react-router-dom";
import type { components as C } from "../../api/generated/candidate";
import { useBackend } from "../../state/BackendContext";
import { Button } from "../../components/Button";
import { missingAsNull, useResource } from "./Resource";
import { CommandStatus, Field, LoadState, useCommand } from "./ApiUI";
import { ConsentGate } from "./ConsentGate";
type Resume = C["schemas"]["ResumeView"];
type Import = C["schemas"]["ImportView"];
type Fields = C["schemas"]["ResumeFields"];
export function ProfileExtras() {
  const [tab, setTab] = useState("");
  return (
    <section className="screen-form">
      <div className="api-actions">
        {[
          ["contacts", "Контакты и публикация"],
          ["resume", "Резюме PDF"],
          ["history", "История грейда"],
          ["preferences", "Пожелания к работе"],
        ].map(([key, label]) => (
          <Button
            key={key}
            variant="secondary"
            onClick={() => setTab(tab === key ? "" : key)}
            aria-expanded={tab === key}
          >
            {label}
          </Button>
        ))}
      </div>
      {tab === "contacts" && <ContactSettings />}
      {tab === "resume" && <ResumePage />}
      {tab === "history" && <GradeHistory />}
      {tab === "preferences" && <PreferencesPage />}
    </section>
  );
}
function ContactSettings() {
  const { api } = useBackend();
  const command = useCommand();
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [skills, setSkills] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const profile = useResource((signal) => api.profile(signal));
  return (
    <>
      <form
        className="api-card api-form"
        onSubmit={(e) => {
          e.preventDefault();
          void command.run(
            () =>
              api.request("candidate", "/v1/candidates/me/contacts", {
                method: "PUT",
                body: { email: email.trim(), phone: phone.trim() || null },
                intent: "contacts",
              }),
            "Контакты сохранены.",
          );
        }}
      >
        <h2>Контакты для компаний</h2>
        <p>
          Контакты открываются компании только после вашего разрешения. Введите
          данные для сохранения или замены.
        </p>
        <Field label="Email для связи">
          <input
            type="email"
            required
            maxLength={320}
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </Field>
        <Field label="Телефон для связи">
          <input
            type="tel"
            maxLength={30}
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
          />
        </Field>
        <Button type="submit" disabled={command.disabled}>
          Сохранить контакты
        </Button>
      </form>
      <section className="api-card">
        <h2>Публикация в подборе</h2>
        <LoadState resource={profile} />
        <p>
          Текущее состояние публикации сервер отдельно не возвращает. Здесь
          можно явно опубликовать или скрыть профиль.
        </p>
        <Field label="Заявленные навыки через запятую">
          <input value={skills} onChange={(e) => setSkills(e.target.value)} />
        </Field>
        <ConsentGate purpose="profile_publication">
          {(consent) => (
            <>
              <label className="consent">
                <input
                  type="checkbox"
                  checked={confirmed}
                  onChange={(e) => setConfirmed(e.target.checked)}
                />
                <span>
                  Разрешаю показывать профиль и указанные навыки в подборе
                </span>
              </label>
              <Button
                disabled={command.disabled || !confirmed || !profile.data}
                onClick={() =>
                  void command.run(async () => {
                    await api.request(
                      "candidate",
                      "/v1/candidates/me/publication",
                      {
                        method: "PUT",
                        version: profile.data!.version,
                        body: {
                          published: true,
                          consent_id: consent,
                          declared_skills: skills
                            .split(",")
                            .map((x) => x.trim())
                            .filter(Boolean),
                        },
                        intent: "profile-publication",
                      },
                    );
                    setConfirmed(false);
                    profile.reload();
                  }, "Публикация подтверждена сервером.")
                }
              >
                Опубликовать профиль
              </Button>
            </>
          )}
        </ConsentGate>
        <Button
          variant="secondary"
          disabled={command.disabled || !profile.data}
          onClick={() =>
            void command.run(async () => {
              await api.request("candidate", "/v1/candidates/me/publication", {
                method: "PUT",
                version: profile.data!.version,
                body: { published: false },
                intent: "profile-publication",
              });
              profile.reload();
            }, "Профиль скрыт из подбора.")
          }
        >
          Скрыть профиль
        </Button>
      </section>
      <CommandStatus command={command} refresh={profile.reload} />
    </>
  );
}
function GradeHistory() {
  const { api } = useBackend();
  const resource = useResource((signal) =>
    api.request<C["schemas"]["HistoryItem"][]>(
      "candidate",
      "/v1/candidates/me/grade-history",
      { signal },
    ),
  );
  return (
    <section className="api-card">
      <h2>История подтверждения уровня</h2>
      <LoadState resource={resource} />
      {resource.status === "ready" && !resource.data?.length && (
        <p>Решений пока нет.</p>
      )}
      {resource.data?.map((item) => (
        <article key={item.decision_id}>
          <p>
            {item.specialization} · {item.target_grade} ·{" "}
            {item.status === "confirmed"
              ? "подтверждён"
              : item.status === "rejected"
                ? "не подтверждён"
                : "техническая ошибка"}
          </p>
          <p>
            {new Date(item.decided_at).toLocaleString("ru-RU")}
            {item.demo ? " · ДЕМО" : ""}
          </p>
          <Link to={`/candidate/assessment/result?session=${item.session_id}`}>
            Результат и апелляция
          </Link>
        </article>
      ))}
    </section>
  );
}
function ResumePage() {
  const { api } = useBackend();
  const command = useCommand();
  const [file, setFile] = useState<File>();
  const [key, setKey] = useState(() => crypto.randomUUID());
  const [selected, setSelected] = useState<Import>();
  const [after, setAfter] = useState("");
  const resource = useResource(async (signal) => {
    const [resume, profile] = await Promise.all([
      missingAsNull(
        api.request<Resume>("candidate", "/v1/candidates/me/resume", {
          signal,
        }),
      ),
      missingAsNull(api.profile(signal)),
    ]);
    return { resume, profile };
  });
  async function download(variant: "full" | "anonymous") {
    if (!resource.data?.profile) return;
    const blob = await api.request<Blob>(
      "candidate",
      `/v1/candidates/${resource.data.profile.candidate_id}/resume.pdf?variant=${variant}`,
      { response: "blob" },
    );
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `resume-${variant}.pdf`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return (
    <>
      <form
        className="api-card api-form"
        onSubmit={(e) => {
          e.preventDefault();
          if (file)
            void command.run(async () => {
              setSelected(
                await api.request<Import>(
                  "candidate",
                  "/v1/candidates/me/resume-imports",
                  {
                    method: "POST",
                    body: new Blob([file], { type: "application/pdf" }),
                    key,
                  },
                ),
              );
            }, "Файл загружен. Обработка проверяется отдельно.");
        }}
      >
        <h2>Загрузить резюме</h2>
        <Field label="PDF до 2 МБ">
          <input
            type="file"
            accept="application/pdf,.pdf"
            onChange={(e) => {
              setFile(e.target.files?.[0]);
              setKey(crypto.randomUUID());
            }}
          />
        </Field>
        {file && file.size > 2 * 1024 * 1024 && (
          <p role="alert">Файл превышает 2 МБ.</p>
        )}
        <Button
          type="submit"
          disabled={
            command.disabled ||
            !file ||
            file.size > 2 * 1024 * 1024 ||
            file.size === 0
          }
        >
          Загрузить PDF
        </Button>
        <CommandStatus command={command} />
      </form>
      <ResumeImports
        key={after}
        after={after}
        next={setAfter}
        selected={setSelected}
      />
      {selected && (
        <ResumeImport
          key={selected.import_id}
          initial={selected}
          done={() => {
            setSelected(undefined);
            resource.reload();
          }}
        />
      )}
      <LoadState resource={resource} />
      {resource.data?.resume && resource.status === "ready" && (
        <>
          <ResumeForm
            key={resource.data.resume.version}
            initial={resource.data.resume.fields}
            profileVersion={resource.data.profile?.version ?? 0}
            save={(body) =>
              api.request("candidate", "/v1/candidates/me/resume", {
                method: "PUT",
                body,
                version: resource.data!.resume!.version,
                intent: "resume-save",
              })
            }
            saved={resource.reload}
          />
          <section className="api-card">
            <h2>Видимость и PDF</h2>
            <p>
              {resource.data.resume.published
                ? "Резюме опубликовано"
                : "Резюме скрыто"}
            </p>
            {resource.data.resume.published ? (
              <Button
                disabled={command.disabled}
                onClick={() =>
                  void command.run(async () => {
                    await api.request(
                      "candidate",
                      "/v1/candidates/me/resume/publication",
                      {
                        method: "PUT",
                        body: { published: false },
                        version: resource.data!.resume!.version,
                        intent: "resume-publication",
                      },
                    );
                    resource.reload();
                  })
                }
              >
                Скрыть резюме
              </Button>
            ) : (
              <ConsentGate purpose="resume_publication">
                {(consent) => (
                  <Button
                    disabled={command.disabled}
                    onClick={() =>
                      void command.run(async () => {
                        await api.request(
                          "candidate",
                          "/v1/candidates/me/resume/publication",
                          {
                            method: "PUT",
                            body: { published: true, consent_id: consent },
                            version: resource.data!.resume!.version,
                            intent: "resume-publication",
                          },
                        );
                        resource.reload();
                      })
                    }
                  >
                    Опубликовать резюме
                  </Button>
                )}
              </ConsentGate>
            )}
            <div className="api-actions">
              <Button
                variant="secondary"
                disabled={command.disabled}
                onClick={() =>
                  void command.run(() => download("full"), "PDF скачан.")
                }
              >
                Скачать полный PDF
              </Button>
              <Button
                variant="secondary"
                disabled={command.disabled}
                onClick={() =>
                  void command.run(() => download("anonymous"), "PDF скачан.")
                }
              >
                Скачать обезличенный PDF
              </Button>
            </div>
          </section>
        </>
      )}
    </>
  );
}
function ResumeImports({
  after,
  next,
  selected,
}: {
  after: string;
  next: (v: string) => void;
  selected: (v: Import) => void;
}) {
  const { api } = useBackend();
  const resource = useResource((signal) =>
    api.request<Import[]>(
      "candidate",
      `/v1/candidates/me/resume-imports${after ? `?after=${after}` : ""}`,
      { signal },
    ),
  );
  return (
    <section className="api-card">
      <h2>Загруженные резюме</h2>
      <LoadState resource={resource} />
      {resource.data?.map((item) => (
        <Button
          key={item.import_id}
          variant="secondary"
          onClick={() => selected(item)}
        >
          Открыть загрузку · {importStatus[item.status]}
        </Button>
      ))}
      {resource.status === "ready" && !resource.data?.length && (
        <p>На этой странице загрузок нет.</p>
      )}
      <Button variant="secondary" onClick={resource.reload}>
        Обновить загрузки
      </Button>
      {resource.data?.length === 20 && (
        <Button
          variant="secondary"
          onClick={() => next(resource.data!.at(-1)!.import_id)}
        >
          Следующие загрузки
        </Button>
      )}
      {after && (
        <Button variant="secondary" onClick={() => next("")}>
          В начало загрузок
        </Button>
      )}
    </section>
  );
}
const importStatus: Record<Import["status"], string> = {
  pending: "В очереди",
  processing: "Обрабатывается",
  review_ready: "Проверьте распознанные поля",
  confirmed: "Подтверждено",
  failed: "Ошибка обработки",
};
function ResumeImport({
  initial,
  done,
}: {
  initial: Import;
  done: () => void;
}) {
  const { api } = useBackend();
  const command = useCommand();
  const resource = useResource(async (signal) => {
    const [item, profile] = await Promise.all([
      api.request<Import>(
        "candidate",
        `/v1/candidates/me/resume-imports/${initial.import_id}`,
        { signal },
      ),
      missingAsNull(api.profile(signal)),
    ]);
    return { item, profile };
  });
  const item = resource.data?.item;
  return (
    <section className="api-card">
      <h2>Обработка PDF</h2>
      <LoadState resource={resource} />
      {item && (
        <>
          <p>{importStatus[item.status]}</p>
          {item.error && (
            <p role="alert">Не удалось обработать документ: {item.error}</p>
          )}
          {item.status === "review_ready" && item.proposal && (
            <ResumeForm
              key={`${item.import_id}:${item.version}`}
              initial={item.proposal}
              profileVersion={resource.data?.profile?.version ?? 0}
              save={(body) =>
                api.request(
                  "candidate",
                  `/v1/candidates/me/resume-imports/${item.import_id}/confirm`,
                  {
                    method: "POST",
                    body,
                    version: item.version,
                    intent: `resume-confirm:${item.import_id}`,
                  },
                )
              }
              saved={done}
            />
          )}
          <Button variant="secondary" onClick={resource.reload}>
            Проверить обработку
          </Button>
          {item.status === "failed" && (
            <Button
              disabled={command.disabled}
              onClick={() =>
                void command.run(async () => {
                  await api.request(
                    "candidate",
                    `/v1/candidates/me/resume-imports/${item.import_id}/retry`,
                    {
                      method: "POST",
                      version: item.version,
                      intent: `resume-retry:${item.import_id}`,
                    },
                  );
                  resource.reload();
                })
              }
            >
              Повторить обработку
            </Button>
          )}
        </>
      )}
      <CommandStatus command={command} refresh={resource.reload} />
    </section>
  );
}
function ResumeForm({
  initial,
  profileVersion,
  save,
  saved,
}: {
  initial: Fields;
  profileVersion: number;
  save: (body: C["schemas"]["ResumeConfirmation"]) => Promise<unknown>;
  saved: () => void;
}) {
  const command = useCommand();
  const [fields, setFields] = useState(initial);
  const [checked, setChecked] = useState(false);
  const update = <K extends keyof Fields>(key: K, value: Fields[K]) => {
    setFields((x) => ({ ...x, [key]: value }));
    setChecked(false);
  };
  return (
    <form
      className="api-form"
      onSubmit={(e) => {
        e.preventDefault();
        void command.run(async () => {
          await save({ ...fields, profile_version: profileVersion });
          saved();
        }, "Резюме подтверждено.");
      }}
    >
      <h3>Проверьте данные резюме</h3>
      <Field label="Имя в резюме">
        <input
          required
          maxLength={100}
          value={fields.display_name}
          onChange={(e) => update("display_name", e.target.value)}
        />
      </Field>
      <Field label="Специализация в резюме">
        <input
          required
          maxLength={100}
          value={fields.specialization}
          onChange={(e) => update("specialization", e.target.value)}
        />
      </Field>
      <Field label="Заявленный грейд резюме">
        <select
          value={fields.declared_grade}
          onChange={(e) =>
            update("declared_grade", e.target.value as Fields["declared_grade"])
          }
        >
          {["junior", "middle", "senior", "lead"].map((x) => (
            <option key={x}>{x}</option>
          ))}
        </select>
      </Field>
      <Field label="О себе">
        <textarea
          maxLength={2000}
          value={fields.summary ?? ""}
          onChange={(e) => update("summary", e.target.value)}
        />
      </Field>
      {(["declared_skills", "experience", "education"] as const).map(
        (key, i) => (
          <Field
            key={key}
            label={
              [
                "Навыки, по одному на строку",
                "Опыт, по одному пункту на строку",
                "Образование, по одному пункту на строку",
              ][i]
            }
          >
            <textarea
              value={fields[key]?.join("\n") ?? ""}
              onChange={(e) => update(key, e.target.value.split("\n"))}
            />
          </Field>
        ),
      )}
      <Field label="Email из резюме">
        <input
          type="email"
          value={fields.contacts?.email ?? ""}
          onChange={(e) =>
            update(
              "contacts",
              e.target.value
                ? {
                    email: e.target.value,
                    phone: fields.contacts?.phone ?? null,
                  }
                : null,
            )
          }
        />
      </Field>
      <Field label="Телефон из резюме">
        <input
          value={fields.contacts?.phone ?? ""}
          onChange={(e) =>
            update("contacts", {
              email: fields.contacts?.email ?? "",
              phone: e.target.value || null,
            })
          }
        />
      </Field>
      <label className="consent">
        <input
          type="checkbox"
          checked={checked}
          onChange={(e) => setChecked(e.target.checked)}
        />
        <span>Проверила или проверил данные, подтверждаю сохранение</span>
      </label>
      <Button type="submit" disabled={command.disabled || !checked}>
        Подтвердить данные резюме
      </Button>
      <CommandStatus command={command} refresh={saved} />
    </form>
  );
}
