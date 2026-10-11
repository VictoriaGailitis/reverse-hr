import { EvaluationRisks } from "./EvaluationRisks";
import { Link } from "react-router-dom";
import { useBackend } from "../../state/BackendContext";
import { Button } from "../../components/Button";
import { useResource } from "./Resource";
import { CommandStatus, LoadState, useCommand } from "./ApiUI";
const reasons: Record<string, string> = {
  grade_boundary: "Результат у границы грейда",
  competency_boundary: "Результат у границы компетенции",
  incomplete_evidence: "Не хватает проверяемых доказательств",
  grade_cooldown: "Изменение грейда во время cooldown",
  quality_sample: "Выборочная проверка качества",
  additional_verification_required: "Нужна дополнительная проверка сигналов риска",
  integrity_review: "Проверка условий прохождения",
  model_unavailable: "Модель недоступна",
  model_disagreement: "Оценки модели расходятся",
};
export function AutomaticQueues() {
  const { api } = useBackend();
  const command = useCommand();
  type StageItem = { stage_id: string; reason: string };
  type SessionItem = {
    session_id: string;
    reasons: string[];
    appeal_id?: string;
    evaluation: { origin?: string };
  };
  const stages = useResource(async (signal) => {
    const rows = await api.request<StageItem[]>(
      "evaluation",
      "/v1/evaluation-automatic/queue",
      { signal },
    );
    if (
      !Array.isArray(rows) ||
      rows.some(
        (row) =>
          !row ||
          typeof row.stage_id !== "string" ||
          typeof row.reason !== "string",
      )
    ) {
      throw new Error("Некорректный ответ очереди проверки этапов");
    }
    return rows;
  });
  const sessions = useResource(async (signal) => {
    const rows = await api.request<SessionItem[]>(
      "assessment",
      "/v1/assessment-automatic/queue",
      { signal },
    );
    if (
      !Array.isArray(rows) ||
      rows.some(
        (row) =>
          !row ||
          typeof row.session_id !== "string" ||
          !Array.isArray(row.reasons) ||
          row.reasons.some((reason) => typeof reason !== "string") ||
          !row.evaluation,
      )
    ) {
      throw new Error("Некорректный ответ очереди проверки грейдов");
    }
    return rows;
  });
  return (
    <>
    <EvaluationRisks />
    <section className="api-card">
      <h2>Автоматическая оценка: нужна перепроверка</h2>
      <Button
        variant="secondary"
        onClick={() => {
          stages.reload();
          sessions.reload();
        }}
      >
        Обновить очередь
      </Button>
      <LoadState resource={stages} />
      <LoadState resource={sessions} />
      {stages.data?.map((row) => (
        <p key={row.stage_id}>
          {reasons[row.reason] ?? "Проверка доказательств"} ·{" "}
          <Link to={`/admin/assessments/1042?stage=${row.stage_id}`}>
            Материалы этапа
          </Link>
        </p>
      ))}
      {sessions.data?.map((row) => (
        <div key={row.session_id}>
          <p>
            {row.reasons.map((r) => reasons[r] ?? "Перепроверка").join(", ")}
          </p>
          <p>Сессия: {row.session_id}</p>
          {row.appeal_id ? (
            <p>Независимая проверка открыта в очереди апелляций.</p>
          ) : row.evaluation.origin === "automatic" ? (
            <Button
              disabled={command.disabled}
              onClick={() =>
                void command.run(async () => {
                  await api.request(
                    "assessment",
                    `/v1/assessment-automatic/${row.session_id}/recheck`,
                    {
                      method: "POST",
                      body: {},
                      intent: `automatic-recheck:${row.session_id}`,
                    },
                  );
                  sessions.reload();
                }, "Независимая перепроверка открыта.")
              }
            >
              Открыть независимую перепроверку
            </Button>
          ) : (
            <p>Откройте эту сессию в форме проверки грейда ниже.</p>
          )}
        </div>
      ))}
      <CommandStatus command={command} />
    </section>
    </>
  );
}
