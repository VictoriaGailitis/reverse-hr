import { useState } from "react";
import type { components as A } from "../../api/generated/assessment";
import { useBackend } from "../../state/BackendContext";
import { Button } from "../../components/Button";
import { useResource } from "./Resource";
import {
  CommandStatus,
  Field,
  LoadState,
  useCommand,
  uuidPattern,
} from "./ApiUI";
export function GradeReview() {
  const [input, setInput] = useState("");
  const [id, setId] = useState("");
  return (
    <section className="api-card">
      <h2>Итоговое решение о грейде</h2>
      <form
        className="api-form"
        onSubmit={(e) => {
          e.preventDefault();
          setId(input);
        }}
      >
        <Field label="Идентификатор сессии для решения о грейде">
          <input
            required
            pattern={uuidPattern}
            value={input}
            onChange={(e) => setInput(e.target.value)}
          />
        </Field>
        <Button type="submit">Загрузить итоговую оценку</Button>
      </form>
      {id && <GradeDecision key={id} id={id} />}
    </section>
  );
}
function GradeDecision({ id }: { id: string }) {
  const { api } = useBackend();
  const command = useCommand();
  const [reason, setReason] = useState("");
  const [action, setAction] = useState<
    A["schemas"]["DecisionCommand"]["action"] | ""
  >("");
  const resource = useResource((signal) =>
    api.request<A["schemas"]["SessionEvaluation"]>(
      "assessment",
      `/v1/assessment-grade-reviews/${id}`,
      { signal },
    ),
  );
  const row = resource.data;
  return (
    <>
      <LoadState resource={resource} />
      {row && (
        <>
          <p>
            Состояние:{" "}
            {
              {
                awaiting_calibration: "Требуется шкала оценки",
                awaiting_evidence: "Ожидаются материалы",
                review_pending: "Готово к решению",
                confirmed: "Подтверждено",
                rejected: "Отклонено",
                technical_failure: "Техническая ошибка",
              }[row.status]
            }
          </p>
          <p>
            Баллы: {row.score ?? "нет оценки"} · рекомендованный грейд:{" "}
            {row.recommended_grade ?? "нет"}
          </p>
          {Object.entries(row.competency_scores ?? {}).map(([name, score]) => (
            <p key={name}>
              {name}: {score}
            </p>
          ))}
          {!row.decision_id && (
            <form
              className="api-form"
              onSubmit={(e) => {
                e.preventDefault();
                if (!action) return;
                void command.run(async () => {
                  await api.request(
                    "assessment",
                    `/v1/assessment-grade-reviews/${id}/decisions`,
                    {
                      method: "POST",
                      body: {
                        action,
                        evidence_digest: row.evidence_digest,
                        reason: reason.trim(),
                      },
                      intent: `grade-decision:${id}`,
                    },
                  );
                  resource.reload();
                }, "Итоговое решение сохранено.");
              }}
            >
              <Field label="Итоговое решение">
                <select
                  required
                  value={action}
                  onChange={(e) => setAction(e.target.value as typeof action)}
                >
                  <option value="">Выберите решение</option>
                  <option
                    value="confirm"
                    disabled={
                      row.status !== "review_pending" || !row.recommended_grade
                    }
                  >
                    Подтвердить рекомендованный грейд
                  </option>
                  <option
                    value="reject"
                    disabled={row.status !== "review_pending"}
                  >
                    Не подтверждать грейд
                  </option>
                  <option value="technical_failure">
                    Зафиксировать техническую ошибку
                  </option>
                </select>
              </Field>
              <Field label="Обоснование итогового решения">
                <textarea
                  required
                  maxLength={2000}
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                />
              </Field>
              <Button
                type="submit"
                disabled={
                  command.disabled ||
                  !action ||
                  !reason.trim() ||
                  (action !== "technical_failure" &&
                    row.status !== "review_pending")
                }
              >
                Сохранить решение о грейде
              </Button>
            </form>
          )}
        </>
      )}
      <CommandStatus command={command} refresh={resource.reload} />
      <Button variant="secondary" onClick={resource.reload}>
        Обновить итоговую оценку
      </Button>
    </>
  );
}
