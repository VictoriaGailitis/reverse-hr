import { CompanyTasksPage } from "./CompanyTasksPage";
import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import type { components as A } from "../../api/generated/assessment";
import type { components as C } from "../../api/generated/coding-workspace";
import type { components as R } from "../../api/generated/code-runner";
import { useBackend } from "../../state/BackendContext";
import { Button } from "../../components/Button";
import { useResource } from "./Resource";
import {
  CommandStatus,
  Field,
  LoadState,
  useCommand,
  isUuid,
  uuidPattern,
} from "./ApiUI";
import { ConsentGate } from "./ConsentGate";
import {
  mountBoard,
  mountRecording,
  mountProctoring,
  type Snapshot,
} from "../../vendor/practical.mjs";
type Session = A["schemas"]["SessionView"];
type Stage = A["schemas"]["StageView"];
const formatNames: Record<string, string> = {
  code: "Код",
  sql: "SQL",
  vcv: "Видеоответ",
  voice: "Голосовой ответ",
  whiteboard: "Доска",
};
const statusNames: Record<string, string> = {
  preflight: "Подготовка",
  in_progress: "В процессе",
  submitted: "Отправлено на оценку",
  completed: "Завершено",
  cancelled: "Отменено",
  pending: "Ожидает начала",
  active: "Текущий этап",
};
export function AssessmentPage() {
  const [params, setParams] = useSearchParams();
  const id = params.get("session");
  if (params.get("tab") === "company") return <CompanyTasksPage candidate />;
  return (
    <div className="screen-form">
      <h1>Оценка навыков</h1>
      <Link to="/candidate/assessment?tab=company">Задания от компаний</Link>
      {id ? (
        isUuid(id) ? (
          <AssessmentSession key={id} id={id} />
        ) : (
          <p role="alert">Некорректная ссылка на сессию.</p>
        )
      ) : (
        <Plans created={(session) => setParams({ session })} />
      )}
    </div>
  );
}
function Plans({ created }: { created: (id: string) => void }) {
  const [params] = useSearchParams();
  const [policy, setPolicy] = useState(params.get("gradePolicy") ?? "");
  const { api } = useBackend();
  const command = useCommand();
  const resource = useResource((signal) =>
    api.request<A["schemas"]["PlanView"][]>(
      "assessment",
      "/v1/assessment-plans",
      { signal },
    ),
  );
  return (
    <>
      <Field label="Шкала оценки из приглашения (необязательно)">
        <input
          placeholder="Идентификатор утверждённой шкалы"
          pattern={uuidPattern}
          value={policy}
          onChange={(e) => setPolicy(e.target.value)}
        />
      </Field>
      <p>
        Для подтверждения грейда нужна утверждённая шкала, переданная
        организатором. Без неё можно пройти практику; общий грейд не будет
        подтверждён.
      </p>
      <LoadState resource={resource} />
      {resource.status === "ready" && (
        <ConsentGate purpose="assessment">
          {(consent) => (
            <>
              {!resource.data?.length && <p>Опубликованных планов пока нет.</p>}
              {resource.data
                ?.filter((x) => x.status === "published")
                .map((plan) => (
                  <section className="api-card" key={plan.plan_version_id}>
                    <h2>{plan.name}</h2>
                    <p>
                      {plan.specialization} · {plan.grade} ·{" "}
                      {Math.ceil(plan.duration_seconds / 60)} мин.
                    </p>
                    <p>
                      Этапы:{" "}
                      {plan.formats.map((x) => formatNames[x] ?? x).join(", ")}
                    </p>
                    {plan.demo && <p>ДЕМО · тестовый план сервера</p>}
                    <p>
                      В практических этапах сохраняются технические события
                      прохождения. Для камеры и микрофона потребуется отдельное
                      согласие и разрешение устройства.
                    </p>
                    <Button
                      disabled={
                        command.disabled || (!!policy && !isUuid(policy))
                      }
                      onClick={() =>
                        void command.run(async () => {
                          const result = await api.request<Session>(
                            "assessment",
                            "/v1/assessment-sessions",
                            {
                              method: "POST",
                              body: {
                                plan_version_id: plan.plan_version_id,
                                assessment_consent_id: consent,
                                ...(policy ? { grade_policy_id: policy } : {}),
                              },
                              intent: `session:${plan.plan_version_id}`,
                            },
                          );
                          created(result.session_id);
                        }, "Сессия создана.")
                      }
                    >
                      Начать подготовку
                    </Button>
                  </section>
                ))}
            </>
          )}
        </ConsentGate>
      )}
      <CommandStatus command={command} />
    </>
  );
}
function AssessmentSession({ id }: { id: string }) {
  const { api } = useBackend();
  const command = useCommand();
  const resource = useResource((signal) =>
    api.request<Session>("assessment", `/v1/assessment-sessions/${id}`, {
      signal,
    }),
  );
  const session = resource.data;
  const [cancel, setCancel] = useState(false);
  const change = (suffix: string, body?: unknown) =>
    command.run(async () => {
      await api.request<Session>(
        "assessment",
        `/v1/assessment-sessions/${id}${suffix}`,
        {
          method: "POST",
          body,
          version: session?.version,
          intent: `session:${id}:${suffix}`,
        },
      );
      resource.reload();
    });
  const stage = session?.stages.find(
    (s) => s.stage_id === session.current_stage_id,
  );
  const progress = session?.progress?.find(
    (s) => s.stage_id === stage?.stage_id,
  );
  return (
    <>
      <Link to="/candidate/assessment">Все планы оценки</Link>
      <LoadState resource={resource} />
      {session && resource.status === "ready" && (
        <>
          <section className="api-card">
            <p>Сессия: {statusNames[session.status]}</p>
            {session.demo && <p>ДЕМО · оценка на серверном стенде</p>}
            <ol>
              {session.stages.map((s) => (
                <li key={s.stage_id}>
                  {formatNames[s.format]} ·{" "}
                  {
                    statusNames[
                      session.progress?.find((p) => p.stage_id === s.stage_id)
                        ?.status ?? "pending"
                    ]
                  }
                </li>
              ))}
            </ol>
          </section>
          {session.status === "preflight" && (
            <Button
              disabled={command.disabled}
              onClick={() => void change("/start")}
            >
              Начать сессию
            </Button>
          )}
          {stage && session.status === "in_progress" && (
            <section className="api-card">
              <h2>{formatNames[stage.format]}</h2>
              <p className="invitation-description">{stage.instruction}</p>
              <p>
                Продолжительность: {Math.ceil(stage.duration_seconds / 60)} мин.
              </p>
              {progress?.deadline && (
                <p>
                  Срок отправки:{" "}
                  {new Date(progress.deadline).toLocaleString("ru-RU")}
                </p>
              )}
              {progress?.status === "pending" && (
                <Button
                  disabled={command.disabled}
                  onClick={() => void change(`/stages/${stage.stage_id}/start`)}
                >
                  Начать этап
                </Button>
              )}
              {progress?.status === "active" && (
                <StageWorkspace
                  key={stage.stage_id}
                  session={session}
                  stage={stage}
                  submitted={resource.reload}
                />
              )}
            </section>
          )}
          {["submitted", "completed"].includes(session.status) && (
            <SessionResult id={id} />
          )}
          {["preflight", "in_progress"].includes(session.status) && (
            <>
              <label className="consent">
                <input
                  type="checkbox"
                  checked={cancel}
                  onChange={(e) => setCancel(e.target.checked)}
                />
                <span>Подтверждаю отмену этой сессии</span>
              </label>
              <Button
                variant="secondary"
                disabled={command.disabled || !cancel}
                onClick={() => void change("/cancel")}
              >
                Отменить сессию
              </Button>
            </>
          )}
        </>
      )}
      <CommandStatus command={command} refresh={resource.reload} />
      <Button
        variant="secondary"
        disabled={command.busy}
        onClick={resource.reload}
      >
        Обновить состояние сессии
      </Button>
    </>
  );
}
function StageWorkspace({
  session,
  stage,
  submitted,
}: {
  session: Session;
  stage: Stage;
  submitted: () => void;
}) {
  const { api } = useBackend();
  const command = useCommand();
  const [snapshot, setSnapshot] = useState<Snapshot>();
  const telemetry =
    useRef<Promise<Awaited<ReturnType<typeof mountProctoring>>>>(undefined);
  useEffect(() => {
    if (stage.format !== "code" && stage.format !== "sql") return;
    const pending = mountProctoring({
      api: api.request.bind(api),
      sessionId: session.session_id,
      stageId: stage.stage_id,
    });
    telemetry.current = pending;
    void pending.catch(() => undefined);
    return () => {
      void pending.then(
        (stream) => stream.dispose(),
        () => undefined,
      );
    };
  }, [api, session.session_id, stage.stage_id, stage.format]);

  return (
    <div className="screen-form">
      {stage.format === "code" || stage.format === "sql" ? (
        <CodeWorkspace session={session} stage={stage} ready={setSnapshot} />
      ) : stage.format === "whiteboard" ? (
        <Practical session={session} stage={stage} ready={setSnapshot} />
      ) : (
        <ConsentGate purpose="recording">
          {(consent) => (
            <Practical
              session={session}
              stage={stage}
              consent={consent}
              ready={setSnapshot}
            />
          )}
        </ConsentGate>
      )}
      {snapshot && (
        <Button
          disabled={command.disabled}
          onClick={() =>
            void command.run(async () => {
              if (telemetry.current) {
                const stream = await telemetry.current;
                if (!(await stream.flush()))
                  throw new Error("Telemetry delivery pending");
              }
              await api.request<Session>(
                "assessment",
                `/v1/assessment-sessions/${session.session_id}/stages/${stage.stage_id}/submit`,
                {
                  method: "POST",
                  body: snapshot,
                  version: session.version,
                  intent: `submit:${stage.stage_id}`,
                },
              );
              submitted();
            }, "Ответ отправлен на оценку.")
          }
        >
          Отправить сохранённый ответ и продолжить
        </Button>
      )}
      <CommandStatus command={command} refresh={submitted} />
    </div>
  );
}
function Practical({
  session,
  stage,
  consent,
  ready,
}: {
  session: Session;
  stage: Stage;
  consent?: string;
  ready: (s: Snapshot) => void;
}) {
  const { api } = useBackend();
  const root = useRef<HTMLDivElement>(null);
  const readyRef = useRef(ready);
  readyRef.current = ready;
  const [error, setError] = useState("");
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    if (!mounted || !root.current) return;
    let disposed = false;
    let cleanup: (() => void | Promise<unknown>) | undefined;
    const options = {
      api: api.request.bind(api),
      sessionId: session.session_id,
      stageId: stage.stage_id,
      onReady: (s: Snapshot) => {
        if (!disposed) readyRef.current(s);
      },
    };
    const work =
      stage.format === "whiteboard"
        ? mountBoard(root.current, options)
        : Promise.resolve(
            mountRecording(root.current, {
              ...options,
              recordingConsentId: consent!,
              video: stage.format === "vcv",
            }),
          );
    void work.then(
      (dispose) => {
        if (disposed) void dispose();
        else cleanup = dispose;
      },
      () => {
        if (!disposed)
          setError(
            "Не удалось открыть рабочую среду. Обновите сессию и попробуйте снова.",
          );
      },
    );
    return () => {
      disposed = true;
      void cleanup?.();
    };
  }, [mounted, api, session.session_id, stage.stage_id, stage.format, consent]);
  return (
    <>
      <p>
        Изменения и технические события этапа сохраняются на сервере. Во время
        записи оставайтесь на странице до отправки.
      </p>
      {!mounted && (
        <Button onClick={() => setMounted(true)}>Открыть рабочую среду</Button>
      )}
      {error && <p role="alert">{error}</p>}
      <div className="practical-workspace" ref={root} />
    </>
  );
}
function CodeWorkspace({
  session,
  stage,
  ready,
}: {
  session: Session;
  stage: Stage;
  ready: (s: Snapshot | undefined) => void;
}) {
  const { api } = useBackend();
  const command = useCommand();
  const [params, setParams] = useSearchParams();
  const workspace =
    params.get("workspaceStage") === stage.stage_id
      ? params.get("workspace")
      : null;
  const [files, setFiles] = useState<C["schemas"]["File"][]>([
    { path: stage.format === "sql" ? "query.sql" : "main.py", content: "" },
  ]);
  const [snapshot, setSnapshot] = useState<C["schemas"]["SnapshotView"]>();
  const [run, setRun] = useState<C["schemas"]["RunView"]>();
  const [loaded, setLoaded] = useState(!workspace);
  useEffect(() => {
    if (!workspace) return;
    const controller = new AbortController();
    void api
      .request<
        C["schemas"]["SnapshotView"]
      >("coding-workspace", `/v1/workspaces/${encodeURIComponent(workspace)}`, { signal: controller.signal })
      .then(
        (row) => {
          if (!controller.signal.aborted) {
            setSnapshot(row);
            setFiles(row.files);
            setLoaded(true);
            ready({
              workspace_id: row.workspace_id,
              snapshot_id: row.snapshot_id,
            });
          }
        },
        () => {
          if (!controller.signal.aborted) setLoaded(false);
        },
      );
    return () => controller.abort();
  }, [api, workspace]);
  async function save() {
    const row = await api.request<C["schemas"]["SnapshotView"]>(
      "coding-workspace",
      snapshot
        ? `/v1/workspaces/${snapshot.workspace_id}/files`
        : "/v1/workspaces",
      {
        method: snapshot ? "PUT" : "POST",
        body: snapshot
          ? { files }
          : { files, session_id: session.session_id, stage_id: stage.stage_id },
        version: snapshot?.version,
        intent: `code:${stage.stage_id}`,
      },
    );
    setSnapshot(row);
    ready({ workspace_id: row.workspace_id, snapshot_id: row.snapshot_id });
    if (!workspace)
      setParams(
        (current) => {
          current.set("workspace", row.workspace_id);
          current.set("workspaceStage", stage.stage_id);
          return current;
        },
        { replace: true },
      );
  }
  const dirty =
    !snapshot || JSON.stringify(files) !== JSON.stringify(snapshot.files);
  return (
    <>
      {!loaded && (
        <p role="alert">
          Не удалось восстановить код. Обновите страницу для повторной загрузки.
        </p>
      )}
      {files.map((file, i) => (
        <Field key={i} label={`Файл ${file.path}`}>
          <textarea
            className="api-code"
            spellCheck={false}
            maxLength={65536}
            disabled={!loaded}
            value={file.content}
            onChange={(e) => {
              setFiles((values) =>
                values.map((f, j) =>
                  j === i ? { ...f, content: e.target.value } : f,
                ),
              );
              ready(undefined);
            }}
          />
        </Field>
      ))}
      <div className="api-actions">
        <Button
          disabled={command.disabled || !loaded}
          onClick={() => void command.run(save)}
        >
          Сохранить код
        </Button>
        <Button
          variant="secondary"
          disabled={command.disabled || dirty || !snapshot}
          onClick={() =>
            void command.run(async () => {
              setRun(
                await api.request<C["schemas"]["RunView"]>(
                  "coding-workspace",
                  `/v1/workspaces/${snapshot!.workspace_id}/runs`,
                  {
                    method: "POST",
                    body: { snapshot_id: snapshot!.snapshot_id },
                    version: snapshot!.version,
                    intent: `run:${snapshot!.snapshot_id}`,
                  },
                ),
              );
            }, "Запуск поставлен в очередь.")
          }
        >
          Запустить сохранённую версию
        </Button>
      </div>
      {dirty && <p>Есть несохранённые изменения.</p>}
      <CommandStatus
        command={command}
        refresh={() => {
          if (!snapshot) return;
          setLoaded(false);
          void api
            .request<
              C["schemas"]["SnapshotView"]
            >("coding-workspace", `/v1/workspaces/${snapshot.workspace_id}`)
            .then(
              (row) => {
                setSnapshot(row);
                ready(undefined);
                setLoaded(true);
              },
              () => setLoaded(false),
            );
        }}
      />
      {run && <RunResult key={run.run_id} run={run} />}
    </>
  );
}
function RunResult({ run }: { run: C["schemas"]["RunView"] }) {
  const { api } = useBackend();
  const resource = useResource((signal) =>
    api.request<R["schemas"]["JobView"]>(
      "code-runner",
      `/v1/runs/${run.run_id}`,
      { signal },
    ),
  );
  const done =
    resource.data &&
    !["pending_executor", "running"].includes(resource.data.status);
  return (
    <section className="api-card">
      <h3>Запуск версии {run.snapshot_version}</h3>
      <LoadState resource={resource} />
      {resource.data && <p>Состояние: {resource.data.status}</p>}
      {done && <RunOutput id={run.run_id} />}
      <Button variant="secondary" onClick={resource.reload}>
        Проверить выполнение
      </Button>
    </section>
  );
}
function RunOutput({ id }: { id: string }) {
  const { api } = useBackend();
  const resource = useResource((signal) =>
    api.request<R["schemas"]["ResultView"]>(
      "code-runner",
      `/v1/runs/${id}/result`,
      { signal },
    ),
  );
  return (
    <>
      <LoadState resource={resource} />
      {resource.data && (
        <>
          <p>Результат: {resource.data.status}</p>
          <pre className="api-code">
            {resource.data.stdout || "Нет стандартного вывода"}
          </pre>
          {resource.data.stderr && (
            <pre className="api-code">{resource.data.stderr}</pre>
          )}
        </>
      )}
    </>
  );
}
function SessionResult({ id }: { id: string }) {
  const { api } = useBackend();
  const command = useCommand();
  const [reason, setReason] = useState("");
  const resource = useResource((signal) =>
    api.request<A["schemas"]["SessionEvaluation"]>(
      "assessment",
      `/v1/assessment-sessions/${id}/evaluation`,
      { signal },
    ),
  );
  const result = resource.data;
  const labels: Record<string, string> = {
    awaiting_calibration: "Ожидает настройки шкалы оценки",
    awaiting_evidence: "Материалы обрабатываются",
    review_pending: "Ожидает проверки специалистом",
    confirmed: "Подтверждено",
    rejected: "Уровень не подтверждён",
    technical_failure: "Техническая ошибка оценки",
  };
  return (
    <section className="api-card">
      <h2>Результат оценки</h2>
      <LoadState resource={resource} />
      {result && (
        <>
          <p>{labels[result.status]}</p>
          <p>
            Подтверждённый грейд:{" "}
            {result.confirmed_grade ?? "пока не подтверждён"}
          </p>
          {result.score != null && <p>Баллы: {result.score}</p>}
          {Object.entries(result.competency_scores ?? {}).map(
            ([name, score]) => (
              <p key={name}>
                {name}: {score}
              </p>
            ),
          )}
          {result.next_attempt_at && (
            <p>
              Следующая попытка:{" "}
              {new Date(result.next_attempt_at).toLocaleString("ru-RU")}
            </p>
          )}
          {result.decision_id && (
            <form
              className="api-form"
              onSubmit={(e) => {
                e.preventDefault();
                void command.run(async () => {
                  await api.request("assessment", "/v1/assessment-appeals", {
                    method: "POST",
                    body: {
                      decision_id: result.decision_id,
                      reason: reason.trim(),
                    },
                    intent: `appeal:${result.decision_id}`,
                  });
                  setReason("");
                }, "Апелляция зарегистрирована.");
              }}
            >
              <Field label="Причина апелляции">
                <textarea
                  required
                  maxLength={5000}
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                />
              </Field>
              <Button
                type="submit"
                disabled={command.disabled || !reason.trim()}
              >
                Подать апелляцию
              </Button>
            </form>
          )}
        </>
      )}
      <CommandStatus command={command} />
      <Button variant="secondary" onClick={resource.reload}>
        Обновить результат
      </Button>
    </section>
  );
}
