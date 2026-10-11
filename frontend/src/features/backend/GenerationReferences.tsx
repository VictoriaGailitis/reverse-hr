import { GenerationCalibration } from "./GenerationCalibration";
import { useState } from "react";
import type { components as A } from "../../api/generated/assessment";
import { useBackend } from "../../state/BackendContext";
import { Button } from "../../components/Button";
import { useResource } from "./Resource";
import { CommandStatus, Field, LoadState, useCommand, isUuid } from "./ApiUI";
type Reference = A["schemas"]["ReferenceView"];
type Command = A["schemas"]["ReferenceCommand"];
type Preview = A["schemas"]["PreviewView"];
type Job = A["schemas"]["GenerationView"];
const formats = {
  code: "Код",
  sql: "SQL",
  vcv: "Видео",
  voice: "Голос",
  whiteboard: "Архитектура и доска",
};
const statuses: Record<string, string> = {
  pending: "В очереди",
  running: "Генерируется",
  validating: "Проверяется Runner",
  ready: "Проверено",
  rejected: "Отклонено проверкой",
  technical_failure: "Техническая ошибка",
  cancelled: "Отменено",
};
const lines = (text: string) =>
  text
    .split("\n")
    .map((x) => x.trim())
    .filter(Boolean);

export function GenerationReferences({
  organization,
}: {
  organization?: string;
}) {
  const { api } = useBackend();
  const [editing, setEditing] = useState<Reference>();
  const refs = useResource((signal) =>
    api.request<Reference[]>(
      "assessment",
      `/v1/assessment-generation/references${organization ? `?organization_id=${organization}` : ""}`,
      { signal },
    ),
  );
  return (
    <section className="api-card">
      <h2>Собственные референсы заданий</h2>
      <p>
        Напишите исходные требования, критерии и допустимые изменения. Сначала
        просмотрите спецификацию и проверьте пробный вариант. Публикация
        включает пополнение пула по этой версии.
      </p>
      {organization && (
        <p>
          Задания оценивают кандидата для компании и не изменяют общий грейд.
        </p>
      )}
      <ReferenceForm
        key={editing?.version_id ?? "new"}
        initial={editing}
        organization={organization}
        saved={() => {
          setEditing(undefined);
          refs.reload();
        }}
      />
      <Button variant="secondary" onClick={refs.reload}>
        Обновить референсы
      </Button>
      <LoadState resource={refs} />
      {refs.data?.map((ref) => (
        <ReferenceTrial
          key={`${ref.version_id}:${ref.version}`}
          reference={ref}
          updated={refs.reload}
          edit={() => setEditing(ref)}
        />
      ))}
    </section>
  );
}
function ReferenceForm({
  initial,
  organization,
  saved,
}: {
  initial?: Reference;
  organization?: string;
  saved: () => void;
}) {
  const { api } = useBackend();
  const command = useCommand();
  const [name, setName] = useState(initial?.name ?? "");
  const [format, setFormat] = useState<Command["format"]>(
    initial?.format ?? "code",
  );
  const [specialization, setSpecialization] = useState(
    initial?.specialization ?? "backend",
  );
  const [grade, setGrade] = useState<Command["grade"]>(
    initial?.grade ?? "junior",
  );
  const [stack, setStack] = useState(initial?.stack_tags?.join(", ") ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [required, setRequired] = useState(
    initial?.required_constraints.join("\n") ?? "",
  );
  const [allowed, setAllowed] = useState(
    initial?.allowed_variations.join("\n") ?? "",
  );
  const [forbidden, setForbidden] = useState(
    initial?.forbidden_changes.join("\n") ?? "",
  );
  const [parameters, setParameters] = useState(
    JSON.stringify(initial?.parameters ?? {}, null, 2),
  );
  const [competency, setCompetency] = useState(
    initial?.competencies[0].description ?? "",
  );
  const [rubric, setRubric] = useState<Command["rubric"]>(
    initial?.rubric ?? [
      {
        key: "quality",
        competency: "primary",
        description: "Корректность решения",
        points: 100,
        evidence: "test_result",
      },
    ],
  );
  const [minutes, setMinutes] = useState(
    (initial?.duration_seconds ?? 1200) / 60,
  );
  const [pool, setPool] = useState(initial?.pool_size ?? 3);
  const [exposures, setExposures] = useState(initial?.max_exposures ?? 100);
  const evidence =
    format === "code" || format === "sql"
      ? "test_result"
      : format === "whiteboard"
        ? "board_snapshot"
        : "timestamped_recording";
  return (
    <form
      className="api-form"
      onSubmit={(event) => {
        event.preventDefault();
        void command.run(async () => {
          const body: Command = {
            organization_id: organization ?? null,
            stack_tags: stack.split(",").map(x => x.trim()).filter(Boolean),
            name,
            format,
            specialization,
            grade,
            description,
            required_constraints: lines(required),
            allowed_variations: lines(allowed),
            forbidden_changes: lines(forbidden),
            parameters: JSON.parse(parameters),
            competencies: initial?.competencies.map((c, i) =>
              i === 0 ? { ...c, description: competency } : c,
            ) ?? [{ key: "primary", description: competency }],
            rubric,
            duration_seconds: minutes * 60,
            pool_size: pool,
            max_exposures: exposures,
          };
          await api.request(
            "assessment",
            `/v1/assessment-generation/references${initial ? `/${initial.version_id}/versions` : ""}`,
            {
              method: "POST",
              body,
              version: initial?.version,
              intent: `generation-reference:${initial?.version_id ?? organization ?? "platform"}`,
            },
          );
          saved();
        }, "Черновик референса сохранён.");
      }}
    >
      <h3>{initial ? `Новая версия «${initial.name}»` : "Новый референс"}</h3>
      <Field label="Название">
        <input
          required
          maxLength={200}
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </Field>
      <Field label="Теги стека, через запятую"><input value={stack} onChange={e => setStack(e.target.value)} /></Field>
      <Field label="Формат">
        <select
          value={format}
          disabled={!!initial}
          onChange={(e) => {
            const f = e.target.value as Command["format"];
            setFormat(f);
            setRubric(
              rubric.map((r) => ({
                ...r,
                evidence:
                  f === "code" || f === "sql"
                    ? "test_result"
                    : f === "whiteboard"
                      ? "board_snapshot"
                      : "timestamped_recording",
              })),
            );
          }}
        >
          {Object.entries(formats).map(([key, label]) => (
            <option key={key} value={key}>
              {label}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Специализация">
        <input
          required
          disabled={!!initial}
          value={specialization}
          onChange={(e) => setSpecialization(e.target.value)}
        />
      </Field>
      <Field label="Уровень">
        <select
          disabled={!!initial}
          value={grade}
          onChange={(e) => setGrade(e.target.value as Command["grade"])}
        >
          {["junior", "middle", "senior", "lead"].map((x) => (
            <option key={x}>{x}</option>
          ))}
        </select>
      </Field>
      <Field label="Собственное описание принципа задания">
        <textarea
          required
          minLength={20}
          maxLength={12000}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
      </Field>
      <Field label="Обязательные ограничения, по одному на строку">
        <textarea
          required
          value={required}
          onChange={(e) => setRequired(e.target.value)}
        />
      </Field>
      <Field label="Что разрешено менять, по одному на строку">
        <textarea
          required
          value={allowed}
          onChange={(e) => setAllowed(e.target.value)}
        />
      </Field>
      <Field label="Что запрещено менять, по одному на строку">
        <textarea
          required
          value={forbidden}
          onChange={(e) => setForbidden(e.target.value)}
        />
      </Field>
      <Field label="Компетенция">
        <input
          required
          value={competency}
          onChange={(e) => setCompetency(e.target.value)}
        />
      </Field>
      <fieldset>
        <legend>Критерии: сумма баллов должна быть 100</legend>
        {rubric.map((r, i) => (
          <div key={i}>
            <Field label={`Ключ критерия ${i + 1}`}>
              <input
                required
                pattern="[a-z][a-z0-9_]*"
                value={r.key}
                onChange={(e) =>
                  setRubric(
                    rubric.map((x, j) =>
                      j === i ? { ...x, key: e.target.value } : x,
                    ),
                  )
                }
              />
            </Field>
            <Field label={`Описание критерия ${i + 1}`}>
              <input
                required
                value={r.description}
                onChange={(e) =>
                  setRubric(
                    rubric.map((x, j) =>
                      j === i ? { ...x, description: e.target.value } : x,
                    ),
                  )
                }
              />
            </Field>
            <Field label={`Баллы критерия ${i + 1}`}>
              <input
                required
                type="number"
                min={1}
                max={100}
                value={r.points}
                onChange={(e) =>
                  setRubric(
                    rubric.map((x, j) =>
                      j === i ? { ...x, points: Number(e.target.value) } : x,
                    ),
                  )
                }
              />
            </Field>
            <Field label={`Доказательство критерия ${i + 1}`}>
              <select
                value={r.evidence}
                onChange={(e) =>
                  setRubric(
                    rubric.map((x, j) =>
                      j === i
                        ? {
                            ...x,
                            evidence: e.target.value as typeof r.evidence,
                          }
                        : x,
                    ),
                  )
                }
              >
                {[
                  evidence,
                  ...(format === "code" || format === "sql"
                    ? ["artifact"]
                    : []),
                ].map((x) => (
                  <option key={x} value={x}>
                    {x === "test_result"
                      ? "Скрытые тесты"
                      : x === "artifact"
                        ? "Код и объяснение (LLM)"
                        : x === "board_snapshot"
                          ? "Снимок доски (LLM)"
                          : "Запись с отметками времени (LLM)"}
                  </option>
                ))}
              </select>
            </Field>
            {rubric.length > 1 && (
              <Button
                variant="secondary"
                onClick={() => setRubric(rubric.filter((_, j) => j !== i))}
              >
                Удалить критерий {i + 1}
              </Button>
            )}
          </div>
        ))}
        <Button
          variant="secondary"
          onClick={() =>
            setRubric([
              ...rubric,
              {
                key: `criterion_${rubric.length + 1}`,
                competency: initial?.competencies[0].key ?? "primary",
                description: "",
                points: 1,
                evidence,
              },
            ])
          }
        >
          Добавить критерий
        </Button>
      </fieldset>
      <Field label="Параметры и разрешённые значения (JSON)">
        <textarea
          value={parameters}
          onChange={(e) => setParameters(e.target.value)}
        />
      </Field>
      <Field label="Длительность, минут">
        <input
          required
          type="number"
          min={1}
          max={60}
          value={minutes}
          onChange={(e) => setMinutes(Number(e.target.value))}
        />
      </Field>
      <Field label="Размер пула">
        <input
          type="number"
          min={1}
          max={20}
          value={pool}
          onChange={(e) => setPool(Number(e.target.value))}
        />
      </Field>
      <Field label="Максимум выдач одного варианта">
        <input
          type="number"
          min={1}
          max={10000}
          value={exposures}
          onChange={(e) => setExposures(Number(e.target.value))}
        />
      </Field>
      <Button type="submit" disabled={command.disabled}>
        Сохранить черновик
      </Button>
      <CommandStatus command={command} />
    </form>
  );
}
function ReferenceTrial({
  reference: ref,
  updated,
  edit,
}: {
  reference: Reference;
  updated: () => void;
  edit: () => void;
}) {
  const { api } = useBackend();
  const command = useCommand();
  const [scenario, setScenario] = useState("");
  const [parameters, setParameters] = useState<Record<string, string>>(
    Object.fromEntries(
      Object.entries(ref.parameters ?? {}).map(([key, values]) => [
        key,
        values[0],
      ]),
    ),
  );
  const [preview, setPreview] = useState<Preview>();
  const [policy, setPolicy] = useState("");
  const jobs = useResource((signal) =>
    api.request<Job[]>(
      "assessment",
      `/v1/assessment-generation/references/${ref.version_id}/jobs`,
      { signal },
    ),
  );
  const action = (kind: string, body: unknown) =>
    command.run(async () => {
      await api.request(
        "assessment",
        `/v1/assessment-generation/references/${ref.version_id}/${kind}`,
        {
          method: "POST",
          body,
          version: ref.version,
          intent: `${kind}:${ref.version_id}`,
        },
      );
      updated();
    });
  return (
    <section className="api-card">
      <h3>
        {ref.name} · версия {ref.number}
      </h3>
      <p>
        {formats[ref.format]} · {ref.specialization} · {ref.grade} ·{" "}
        {ref.status === "draft"
          ? "Черновик"
          : ref.status === "published"
            ? "Опубликован"
            : "Отозван"}
      </p>
      <p>{ref.description}</p>
      <Button variant="secondary" onClick={edit}>
        Изменить в новой версии
      </Button>
      {ref.status !== "retired" && (
        <>
          <form
            className="api-form"
            onSubmit={(e) => {
              e.preventDefault();
              void command.run(async () => {
                setPreview(
                  await api.request<Preview>(
                    "assessment",
                    `/v1/assessment-generation/references/${ref.version_id}/preview`,
                    {
                      method: "POST",
                      body: { scenario, parameters },
                      intent: `preview:${ref.version_id}`,
                    },
                  ),
                );
              });
            }}
          >
            <Field label="Конкретный сценарий пробного задания">
              <textarea
                required
                minLength={10}
                maxLength={2000}
                value={scenario}
                onChange={(e) => {
                  setScenario(e.target.value);
                  setPreview(undefined);
                }}
              />
            </Field>
            {Object.entries(ref.parameters ?? {}).map(([key, values]) => (
              <Field key={key} label={key}>
                <select
                  value={parameters[key]}
                  onChange={(e) => {
                    setParameters({ ...parameters, [key]: e.target.value });
                    setPreview(undefined);
                  }}
                >
                  {values.map((value) => (
                    <option key={value}>{value}</option>
                  ))}
                </select>
              </Field>
            ))}
            <Button type="submit" disabled={command.disabled}>
              Подготовить спецификацию
            </Button>
          </form>
          {preview && (
            <div>
              <h4>Перед генерацией</h4>
              <p>Сценарий: {scenario}</p>
              <p>
                Длительность: {ref.duration_seconds / 60} минут. Критерии и
                ограничения закреплены в версии {ref.number}.
              </p>
              <ul>
                {ref.required_constraints.map((x) => (
                  <li key={x}>{x}</li>
                ))}
                {Object.entries(parameters).map(([k, v]) => (
                  <li key={k}>
                    {k}: {v}
                  </li>
                ))}
              </ul>
              <h4>Допустимые изменения</h4>
              <ul>
                {ref.allowed_variations.map((x) => (
                  <li key={x}>{x}</li>
                ))}
              </ul>
              <h4>Неизменяемые условия</h4>
              <ul>
                {ref.forbidden_changes.map((x) => (
                  <li key={x}>{x}</li>
                ))}
              </ul>
              <h4>Критерии оценки</h4>
              <ul>
                {ref.rubric.map((c) => (
                  <li key={c.key}>
                    {c.description}: {c.points} баллов
                  </li>
                ))}
              </ul>
              <p>
                Спецификация действует до{" "}
                {new Date(preview.expires_at).toLocaleString("ru-RU")}.
              </p>
              <Button
                disabled={command.disabled}
                onClick={() =>
                  void command.run(async () => {
                    await api.request(
                      "assessment",
                      "/v1/assessment-generation/generate",
                      {
                        method: "POST",
                        body: {
                          preview_id: preview.preview_id,
                          specification_digest: preview.digest,
                        },
                        intent: `generate:${preview.preview_id}`,
                      },
                    );
                    setPreview(undefined);
                    jobs.reload();
                  }, "Пробная генерация поставлена в очередь.")
                }
              >
                Генерировать пробное задание
              </Button>
            </div>
          )}
          {ref.status === "draft" && (
            <>
              {!ref.organization_id && (
                <>
                  <p>
                    Для общего грейда нужна калиброванная политика, привязанная
                    именно к этой версии. Без неё опубликованные задания
                    доступны для практики.
                  </p>
                  <Field label="Идентификатор утверждённой политики оценки">
                    <input
                      value={policy}
                      onChange={(e) => setPolicy(e.target.value)}
                    />
                  </Field>
                  <Button
                    disabled={command.disabled || !isUuid(policy)}
                    onClick={() =>
                      void action("grading-policy", { grade_policy_id: policy })
                    }
                  >
                    Привязать политику
                  </Button>
                </>
              )}
              <Button
                disabled={
                  command.disabled ||
                  !jobs.data?.some((j) => j.status === "ready")
                }
                onClick={() =>
                  void action("publish", {
                    reason:
                      "Утверждены собственный референс и проверенный пробный вариант",
                  })
                }
              >
                Опубликовать референс
              </Button>
              {!ref.organization_id && (
                <p>
                  Референс платформы утверждает другой администратор контента.
                </p>
              )}
            </>
          )}
          <Button
            variant="secondary"
            disabled={command.disabled}
            onClick={() =>
              void action("retire", { reason: "Референс отозван владельцем" })
            }
          >
            Отозвать версию
          </Button>
        </>
      )}
      <Button variant="secondary" onClick={jobs.reload}>
        Обновить результаты генерации
      </Button>
      <LoadState resource={jobs} />
      {jobs.data?.map((job) => (
        <details key={job.generation_id}>
          <summary>
            {statuses[job.status]} · попыток: {job.attempts}
          </summary>
          {job.error && <p>Причина: {job.error}</p>}
          {ref.organization_id && job.plan_version_id && (
            <p>
              План для назначения задания: <code>{job.plan_version_id}</code>
            </p>
          )}
          {job.task && (
            <>
              <p>{job.task.instruction}</p>
              <h4>Эталон для автора</h4>
              <pre>{job.task.reference_answer}</pre>
            </>
          )}
        </details>
      ))}
      {!ref.organization_id &&
        ref.status === "draft" &&
        jobs.data?.find((j) => j.status === "ready" && j.plan_version_id) && (
          <GenerationCalibration
            reference={ref}
            plan={
              jobs.data.find((j) => j.status === "ready" && j.plan_version_id)!
                .plan_version_id!
            }
          />
        )}
      <CommandStatus command={command} refresh={updated} />
    </section>
  );
}
