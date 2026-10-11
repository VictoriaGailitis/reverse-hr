import { TaskAnalytics } from "./TaskAnalytics";
import { GenerationReferences } from "./GenerationReferences";
import { AutomaticQueues } from "./AutomaticQueues";
import { GradeReview } from "./GradeReview";
import { RightsRequests } from "./PrivacyExtras";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import type { components as H } from "../../api/generated/hiring";
import type { components as A } from "../../api/generated/assessment";
import type { components as E } from "../../api/generated/evaluation";
import { useBackend } from "../../state/BackendContext";
import { Button } from "../../components/Button";
import { useResource } from "./Resource";
import {
  CommandStatus,
  Field,
  LoadState,
  useCommand,
  uuidPattern,
  isUuid,
} from "./ApiUI";
import type { Service } from "../../api/client";
type Review = E["schemas"]["ReviewWorkspace"];
export function AdminPage() {
  const { session } = useBackend();
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") ?? "vacancies";
  const setTab = (value: string) => setParams({ tab: value });
  const [stage, setStage] = useState("");
  const options = [
    ["vacancies", "Вакансии", "company_moderator"],
    ["complaints", "Жалобы", "company_moderator"],
    ["content", "Задания компаний", "content_admin"],
    ["generation", "Генерация заданий", "content_admin"],
    ["analytics", "Качество заданий", "content_admin"],
    ["reviews", "Оценки и апелляции", "assessment_reviewer"],
    ["rights", "Обращения о данных", "privacy_officer"],
  ].filter((x) => session.roles?.includes(x[2]));
  const active = options.some((x) => x[0] === tab) ? tab : options[0]?.[0];
  return (
    <div className="screen-form">
      <h1>Кабинет проверяющего</h1>
      {!options.length ? (
        <p>
          У вашей учётной записи нет роли проверяющего. Доступ к
          административным данным проверяет сервер.
        </p>
      ) : (
        <>
          <div className="api-actions">
            {options.map(([key, label]) => (
              <Button key={key} variant="secondary" onClick={() => setTab(key)}>
                {label}
              </Button>
            ))}
          </div>
          {active === "analytics" ? (
            <TaskAnalytics />
          ) : active === "generation" ? (
            <GenerationReferences />
          ) : active === "rights" ? (
            <RightsRequests officer />
          ) : active === "reviews" ? (
            <>
              <form className="api-form" onSubmit={(e) => e.preventDefault()}>
                <Field label="Идентификатор этапа для проверки">
                  <input
                    pattern={uuidPattern}
                    value={stage}
                    onChange={(e) => setStage(e.target.value)}
                  />
                </Field>
                {isUuid(stage) && (
                  <Link
                    className="button button-primary"
                    to={`/admin/assessments/1042?stage=${stage}`}
                  >
                    Открыть материалы этапа
                  </Link>
                )}
              </form>
              <AutomaticQueues />
              <GradeReview />
              <AppealQueue />
            </>
          ) : (
            <ModerationQueue key={active} kind={active} />
          )}
        </>
      )}
    </div>
  );
}
function ModerationQueue({ kind }: { kind: string }) {
  const [after, setAfter] = useState("");
  return (
    <ModerationItems key={after} kind={kind} after={after} next={setAfter} />
  );
}
type QueueItem = {
  vacancy_id?: string;
  complaint_id?: string;
  proposal_id?: string;
  title?: string;
  name?: string;
};
function ModerationItems({
  kind,
  after,
  next,
}: {
  kind: string;
  after: string;
  next: (id: string) => void;
}) {
  const { api } = useBackend();
  const service: Service = kind === "content" ? "assessment" : "hiring";
  const path =
    kind === "content"
      ? "/v1/company-task-proposals?status=submitted"
      : kind === "complaints"
        ? "/v1/hiring-complaints?status=open"
        : "/v1/vacancy-reviews?";
  const resource = useResource((signal) =>
    api.request<QueueItem[]>(
      service,
      `${path}${after ? `&after=${after}` : ""}`,
      { signal },
    ),
  );
  return (
    <>
      <LoadState resource={resource} />
      {resource.status === "ready" && !resource.data?.length && (
        <p>В этой части очереди нет записей.</p>
      )}
      {resource.data?.map((item) => {
        const id = item.vacancy_id ?? item.complaint_id ?? item.proposal_id!;
        return (
          <ModerationCase
            key={id}
            id={id}
            kind={kind}
            reload={resource.reload}
          />
        );
      })}
      <Button variant="secondary" onClick={resource.reload}>
        Обновить очередь
      </Button>
      {!!resource.data?.length && (
        <Button
          variant="secondary"
          onClick={() => {
            const last = resource.data!.at(-1)!;
            next(last.vacancy_id ?? last.complaint_id ?? last.proposal_id!);
          }}
        >
          Следующая страница очереди
        </Button>
      )}
      {after && (
        <Button variant="secondary" onClick={() => next("")}>
          В начало очереди
        </Button>
      )}
    </>
  );
}
function ModerationCase({
  id,
  kind,
  reload,
}: {
  id: string;
  kind: string;
  reload: () => void;
}) {
  const { api } = useBackend();
  const command = useCommand();
  const [reason, setReason] = useState("");
  const [positive, setPositive] = useState(false);
  const service: Service = kind === "content" ? "assessment" : "hiring";
  const path =
    kind === "content"
      ? `/v1/company-task-proposals/${id}`
      : kind === "complaints"
        ? `/v1/hiring-complaints/${id}`
        : `/v1/vacancies/${id}`;
  type Item = Partial<
    Omit<H["schemas"]["VacancyView"], "status"> &
      Omit<H["schemas"]["CaseDetail"], "status"> &
      Omit<A["schemas"]["ProposalView"], "status">
  > & { version: number };
  const resource = useResource((signal) =>
    api.request<Item>(service, path, { signal }),
  );
  const item = resource.data;
  return (
    <form
      className="api-card api-form"
      onSubmit={(e) => {
        e.preventDefault();
        if (!item) return;
        void command.run(async () => {
          const outcome =
            kind === "content"
              ? positive
                ? "approve"
                : "reject"
              : kind === "complaints"
                ? positive
                  ? "upheld"
                  : "dismissed"
                : positive
                  ? "approved"
                  : "rejected";
          await api.request(
            service,
            `${path}/${kind === "complaints" ? "decisions" : "review"}`,
            {
              method: "POST",
              body: {
                outcome,
                reason: reason.trim(),
                ...(kind === "content" ? { digest: item.digest } : {}),
              },
              version: item.version,
              intent: `moderate:${kind}:${id}`,
            },
          );
          reload();
        }, "Решение зарегистрировано.");
      }}
    >
      <LoadState resource={resource} />
      {item && (
        <>
          <h2>{item.title ?? item.name ?? "Жалоба"}</h2>
          {item.description && (
            <p className="invitation-description">{item.description}</p>
          )}
          {item.reason && <p>Причина обращения: {item.reason}</p>}
          {item.message && <blockquote>{item.message.text}</blockquote>}
          {item.salary && (
            <p>
              Зарплата: {item.salary.minimum}–{item.salary.maximum} ₽ ·{" "}
              {item.salary.tax_basis}
            </p>
          )}
          {item.content?.tasks.map((task) => (
            <section key={task.key}>
              <h3>{task.format}</h3>
              <p>{task.instruction}</p>
              <p>Эталон: {task.reference_answer}</p>
              {task.rubric.map((r) => (
                <p key={r.key}>
                  {r.description} · {r.points} баллов
                </p>
              ))}
            </section>
          ))}
          <Field label="Решение модератора">
            <select
              value={positive ? "yes" : "no"}
              onChange={(e) => setPositive(e.target.value === "yes")}
            >
              <option value="no">
                {kind === "complaints" ? "Отклонить жалобу" : "Отклонить"}
              </option>
              <option value="yes">
                {kind === "complaints" ? "Удовлетворить жалобу" : "Одобрить"}
              </option>
            </select>
          </Field>
          <Field label="Обоснование решения">
            <textarea
              required
              maxLength={2000}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          </Field>
          <Button type="submit" disabled={command.disabled || !reason.trim()}>
            Сохранить решение модератора
          </Button>
        </>
      )}
      <CommandStatus command={command} refresh={resource.reload} />
    </form>
  );
}
export function ReviewPage() {
  const [params] = useSearchParams();
  const id = params.get("stage");
  return (
    <div className="screen-form">
      <h1>Проверка материалов оценки</h1>
      <Link to="/admin">К кабинету проверяющего</Link>
      {isUuid(id) ? (
        <ReviewStage key={id} id={id} />
      ) : (
        <p>Выберите реальный этап в кабинете проверяющего.</p>
      )}
    </div>
  );
}
function ReviewStage({ id }: { id: string }) {
  const { api } = useBackend();
  const resource = useResource((signal) =>
    api.request<Review>("evaluation", `/v1/evaluation-reviews/stages/${id}`, {
      signal,
    }),
  );
  return (
    <>
      <LoadState resource={resource} />
      {resource.data && (
        <ReviewForm
          key={resource.data.version}
          row={resource.data}
          reload={resource.reload}
        />
      )}
      <Button variant="secondary" onClick={resource.reload}>
        Обновить материалы
      </Button>
    </>
  );
}
async function sha(text: string) {
  const bytes = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(text),
  );
  return Array.from(new Uint8Array(bytes), (x) =>
    x.toString(16).padStart(2, "0"),
  ).join("");
}
function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value && typeof value === "object")
    return `{${Object.entries(value)
      .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
      .map(([k, v]) => `${JSON.stringify(k)}:${canonical(v)}`)
      .join(",")}}`;
  return JSON.stringify(value);
}
function ReviewForm({ row, reload }: { row: Review; reload: () => void }) {
  const { api } = useBackend();
  const command = useCommand();
  const [reason, setReason] = useState("");
  const [decisions, setDecisions] = useState<
    Record<
      string,
      {
        points: string;
        reason: string;
        reference: string;
        start: number;
        end: number;
      }
    >
  >({});
  const source = row.source;
  const files = "files" in source ? source.files : [];
  const practical = "format" in source ? source : undefined;
  async function save() {
    const output: E["schemas"]["CriterionDecision"][] = [];
    for (const criterion of row.material.task.rubric) {
      const entry = decisions[criterion.key];
      const decision: E["schemas"]["CriterionDecision"] = {
        criterion_key: criterion.key,
        points: entry?.points === "" || !entry ? null : Number(entry.points),
        reason: entry?.reason?.trim() ?? "",
      };
      if (criterion.evidence === "test_result") {
        decision.points = row.trusted_test_points?.[criterion.key] ?? null;
        decision.test_proof_digest = row.test_proof_digest ?? null;
      } else if (decision.points !== null) {
        if (files.length) {
          const file = files.find((f) => f.path === entry.reference);
          if (!file) throw new Error("Choose evidence");
          decision.citations = [
            {
              path: file.path,
              file_digest: await sha(file.content),
              start_line: entry.start,
              end_line: entry.end,
            },
          ];
        } else if (practical?.board) {
          const object = practical.board.state.find(
            (x) => x.id === entry.reference,
          );
          if (!object) throw new Error("Choose evidence");
          decision.board_citations = [
            {
              snapshot_id: practical.snapshot_id,
              snapshot_digest: practical.digest,
              object_id: object.id,
              object_digest: await sha(canonical(object)),
            },
          ];
        } else if (
          practical?.transcript &&
          practical.transcript_id &&
          practical.transcript_digest
        ) {
          const segment = practical.transcript.segments.find(
            (x) => x.key === entry.reference,
          );
          if (!segment) throw new Error("Choose evidence");
          decision.recording_citations = [
            {
              snapshot_id: practical.snapshot_id,
              recording_digest: practical.digest,
              transcript_id: practical.transcript_id,
              transcript_digest: practical.transcript_digest,
              segment_key: segment.key,
              start_ms: segment.start_ms,
              end_ms: segment.end_ms,
            },
          ];
        } else throw new Error("Evidence unavailable");
      }
      output.push(decision);
    }
    await api.request(
      "evaluation",
      `/v1/evaluation-reviews/stages/${row.stage_id}/reviews`,
      {
        method: "POST",
        body: { decisions: output, reason: reason.trim() },
        version: row.version,
        intent: `review:${row.stage_id}`,
      },
    );
    reload();
  }
  return (
    <>
      <section className="api-card">
        <h2>Задание</h2>
        <p>{row.material.task.instruction}</p>
        <h3>Эталон</h3>
        <p>{row.material.task.reference_answer}</p>
        <h3>Материалы кандидата</h3>
        {files.map((file) => (
          <div key={file.path}>
            <h4>{file.path}</h4>
            <pre className="api-code">
              {file.content
                .split("\n")
                .map((line, i) => `${i + 1}  ${line}`)
                .join("\n")}
            </pre>
          </div>
        ))}
        {practical?.transcript?.segments.map((segment) => (
          <p key={segment.key}>
            {(segment.start_ms / 1000).toFixed(1)}–
            {(segment.end_ms / 1000).toFixed(1)} сек. · {segment.text}
          </p>
        ))}
        {practical?.board && (
          <svg
            viewBox="0 0 1000 600"
            role="img"
            aria-label="Доска кандидата"
            className="review-board"
          >
            {practical.board.state.map((shape) => {
              const first = shape.points[0],
                last = shape.points.at(-1)!;
              const props = {
                stroke: shape.color,
                strokeWidth: shape.width,
                fill: "none",
              };
              return shape.kind === "text" ? (
                <text key={shape.id} x={first.x} y={first.y} fill={shape.color}>
                  {shape.text}
                </text>
              ) : shape.kind === "rectangle" ? (
                <rect
                  key={shape.id}
                  x={Math.min(first.x, last.x)}
                  y={Math.min(first.y, last.y)}
                  width={Math.abs(last.x - first.x)}
                  height={Math.abs(last.y - first.y)}
                  {...props}
                />
              ) : shape.kind === "ellipse" ? (
                <ellipse
                  key={shape.id}
                  cx={(first.x + last.x) / 2}
                  cy={(first.y + last.y) / 2}
                  rx={Math.abs(last.x - first.x) / 2}
                  ry={Math.abs(last.y - first.y) / 2}
                  {...props}
                />
              ) : (
                <polyline
                  key={shape.id}
                  points={shape.points.map((p) => `${p.x},${p.y}`).join(" ")}
                  {...props}
                />
              );
            })}
          </svg>
        )}
        {practical && !practical.board && !practical.transcript && (
          <p>Материал ещё не готов. Не выставляйте баллы без доказательств.</p>
        )}
      </section>
      <form
        className="api-card api-form"
        onSubmit={(e) => {
          e.preventDefault();
          void command.run(
            save,
            "Проверка сохранена. Общий грейд подтверждается отдельно.",
          );
        }}
      >
        <h2>Оценка по критериям</h2>
        {row.material.task.rubric.map((criterion) => {
          const entry = decisions[criterion.key] ?? {
            points: "",
            reason: "",
            reference: "",
            start: 1,
            end: 1,
          };
          const update = (patch: Partial<typeof entry>) =>
            setDecisions((v) => ({
              ...v,
              [criterion.key]: { ...entry, ...patch },
            }));
          return (
            <fieldset key={criterion.key}>
              <legend>
                {criterion.description} · максимум {criterion.points}
              </legend>
              {criterion.evidence === "test_result" ? (
                <p>
                  Баллы доверенных тестов:{" "}
                  {row.trusted_test_points?.[criterion.key] ??
                    "нет доказательства"}
                </p>
              ) : (
                <>
                  <Field label={`Баллы: ${criterion.description}`}>
                    <input
                      type="number"
                      min="0"
                      max={criterion.points}
                      value={entry.points}
                      onChange={(e) => update({ points: e.target.value })}
                    />
                  </Field>
                  <p>Оставьте поле пустым, если доказательств недостаточно.</p>
                  <Field label={`Доказательство: ${criterion.description}`}>
                    <select
                      value={entry.reference}
                      onChange={(e) => update({ reference: e.target.value })}
                    >
                      <option value="">Выберите материал</option>
                      {files.map((f) => (
                        <option key={f.path} value={f.path}>
                          {f.path}
                        </option>
                      ))}
                      {practical?.board?.state.map((s, i) => (
                        <option key={s.id} value={s.id}>
                          Объект {i + 1}: {s.kind}
                        </option>
                      ))}
                      {practical?.transcript?.segments.map((s) => (
                        <option key={s.key} value={s.key}>
                          {s.start_ms / 1000}–{s.end_ms / 1000} сек.
                        </option>
                      ))}
                    </select>
                  </Field>
                  {!!files.length && (
                    <>
                      <Field label="Первая строка">
                        <input
                          type="number"
                          min="1"
                          value={entry.start}
                          onChange={(e) =>
                            update({ start: Number(e.target.value) })
                          }
                        />
                      </Field>
                      <Field label="Последняя строка">
                        <input
                          type="number"
                          min={entry.start}
                          value={entry.end}
                          onChange={(e) =>
                            update({ end: Number(e.target.value) })
                          }
                        />
                      </Field>
                    </>
                  )}
                </>
              )}
              <Field label={`Обоснование: ${criterion.description}`}>
                <textarea
                  required
                  maxLength={2000}
                  value={entry.reason}
                  onChange={(e) => update({ reason: e.target.value })}
                />
              </Field>
            </fieldset>
          );
        })}
        <Field label="Общее обоснование проверки">
          <textarea
            required
            maxLength={2000}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
        </Field>
        <Button type="submit" disabled={command.disabled || !reason.trim()}>
          Сохранить содержательную проверку
        </Button>
        <CommandStatus command={command} refresh={reload} />
      </form>
    </>
  );
}
function AppealQueue() {
  const { api } = useBackend();
  const resource = useResource((signal) =>
    api.request<A["schemas"]["AppealView"][]>(
      "assessment",
      "/v1/assessment-appeals/queue",
      { signal },
    ),
  );
  return (
    <section className="screen-form">
      <h2>Апелляции</h2>
      <LoadState resource={resource} />
      {resource.data?.map((item) => (
        <AppealCard
          key={`${item.appeal_id}:${item.version}`}
          item={item}
          reload={resource.reload}
        />
      ))}
      {resource.status === "ready" && !resource.data?.length && (
        <p>Апелляций пока нет.</p>
      )}
    </section>
  );
}
function AppealCard({
  item,
  reload,
}: {
  item: A["schemas"]["AppealView"];
  reload: () => void;
}) {
  const { api } = useBackend();
  const command = useCommand();
  const [evidence, setEvidence] = useState<A["schemas"]["AppealEvidence"]>();
  const [reason, setReason] = useState("");
  const [action, setAction] = useState("uphold");
  const [status, setStatus] = useState("confirmed");
  return (
    <article className="api-card">
      <h3>Апелляция</h3>
      <p>{item.reason}</p>
      <p>
        Срок рассмотрения:{" "}
        {new Date(item.review_due_at).toLocaleString("ru-RU")}
        {item.overdue ? " · просрочено" : ""}
      </p>
      {item.status === "submitted" && (
        <Button
          disabled={command.disabled}
          onClick={() =>
            void command.run(async () => {
              await api.request(
                "assessment",
                `/v1/assessment-appeals/${item.appeal_id}/claim`,
                {
                  method: "POST",
                  version: item.version,
                  intent: `claim:${item.appeal_id}`,
                },
              );
              reload();
            })
          }
        >
          Взять на рассмотрение
        </Button>
      )}
      {item.status === "in_review" && (
        <>
          <Button
            variant="secondary"
            disabled={command.disabled}
            onClick={() =>
              void command.run(
                async () =>
                  setEvidence(
                    await api.request<A["schemas"]["AppealEvidence"]>(
                      "assessment",
                      `/v1/assessment-appeals/${item.appeal_id}/evidence`,
                    ),
                  ),
                "Материалы загружены.",
              )
            }
          >
            Загрузить повторную оценку
          </Button>
          {evidence && (
            <>
              <p>
                Повторная проверка:{" "}
                {evidence.repeated_review_complete
                  ? "завершена"
                  : "не завершена"}
              </p>
              <p>Баллы: {evidence.score ?? "не определены"}</p>
              {Object.entries(evidence.competency_scores).map(
                ([key, value]) => (
                  <p key={key}>
                    {key}: {value}
                  </p>
                ),
              )}
              <Field label="Решение по апелляции">
                <select
                  value={action}
                  onChange={(e) => setAction(e.target.value)}
                >
                  <option value="uphold">Оставить решение</option>
                  <option value="change">Изменить решение</option>
                </select>
              </Field>
              <Field label="Итог повторной оценки">
                <select
                  value={status}
                  onChange={(e) => setStatus(e.target.value)}
                >
                  <option value="confirmed">Подтверждён</option>
                  <option value="rejected">Не подтверждён</option>
                  <option value="technical_failure">Техническая ошибка</option>
                </select>
              </Field>
              <Field label="Обоснование апелляции">
                <textarea
                  maxLength={2000}
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                />
              </Field>
              <Button
                disabled={
                  command.disabled ||
                  !reason.trim() ||
                  !evidence.repeated_review_complete
                }
                onClick={() =>
                  void command.run(async () => {
                    await api.request(
                      "assessment",
                      `/v1/assessment-appeals/${item.appeal_id}/resolve`,
                      {
                        method: "POST",
                        version: item.version,
                        body: {
                          action,
                          status,
                          reason,
                          evidence_digest: evidence.evidence_digest,
                        },
                        intent: `resolve:${item.appeal_id}`,
                      },
                    );
                    reload();
                  }, "Решение по апелляции сохранено.")
                }
              >
                Завершить рассмотрение
              </Button>
            </>
          )}
        </>
      )}
      <CommandStatus command={command} refresh={reload} />
    </article>
  );
}
