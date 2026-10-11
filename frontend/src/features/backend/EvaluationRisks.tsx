import { useEffect, useState } from "react";
import { useBackend } from "../../state/BackendContext";
import { Button } from "../../components/Button";
import { CommandStatus, Field, LoadState, useCommand } from "./ApiUI";
import { useResource } from "./Resource";
const codes: Record<string, string> = {
  instruction_override: "Попытка отменить инструкции", role_spoofing: "Подмена роли ИИ",
  system_exfiltration: "Запрос скрытых инструкций", grade_manipulation: "Попытка навязать оценку",
  proctoring_concern: "Проблема условий прохождения",
};
type Risk = { stage_id: string; candidate_id: string; version: number; codes: string[]; status: string };
export function EvaluationRisks() {
  const { api } = useBackend();
  const [after, setAfter] = useState<string>();
  const rows = useResource(signal => api.request<{ items: Risk[]; next_cursor: string | null }>("evaluation", `/v1/evaluation-risks/queue${after ? `?after=${after}` : ""}`, { signal }));
  useEffect(() => { rows.reload(); }, [after, rows.reload]);
  return <section className="api-card"><h2>Сигналы риска и дополнительная проверка</h2>
    <p>Сигнал — подозрение, включая возможный учебный пример. Он не меняет грейд. При необходимости назначьте отдельное прохождение и проверьте его вручную.</p>
    <Button variant="secondary" onClick={rows.reload}>Обновить сигналы</Button><LoadState resource={rows} />
    {rows.data?.items.map(row => <RiskDecision key={`${row.stage_id}:${row.version}`} row={row} reload={rows.reload} />)}
    {rows.data?.next_cursor && <Button variant="secondary" onClick={() => setAfter(rows.data?.next_cursor ?? undefined)}>Следующая страница сигналов</Button>}
    {after && <Button variant="secondary" onClick={() => setAfter(undefined)}>В начало очереди</Button>}
  </section>;
}
function RiskDecision({ row, reload }: { row: Risk; reload: () => void }) {
  const { api } = useBackend(); const command = useCommand();
  const [reason, setReason] = useState(""); const [stage, setStage] = useState("");
  const [action, setAction] = useState("require_verification");
  return <form className="api-form" onSubmit={e => { e.preventDefault(); void command.run(async () => {
    await api.request("evaluation", `/v1/evaluation-risks/${row.stage_id}/decision`, {
      method: "POST", version: row.version, intent: `risk-decision:${row.stage_id}`,
      body: { action, reason, verification_stage_id: action === "complete_verification" ? stage : null },
    }); reload();
  }); }}>
    <p>Этап {row.stage_id}: {row.codes.map(code => codes[code] ?? "Дополнительный сигнал").join(", ")}</p>
    <Field label="Решение"><select value={action} onChange={e => setAction(e.target.value)}>
      <option value="require_verification">Требуется отдельная проверка</option><option value="dismiss">Отклонить подозрение</option><option value="complete_verification">Подтвердить завершение проверки</option>
    </select></Field>
    {action === "complete_verification" && <Field label="ID другого этапа, проверенного человеком"><input required value={stage} onChange={e => setStage(e.target.value)} /></Field>}
    <Field label="Обоснование"><textarea required minLength={10} maxLength={2000} value={reason} onChange={e => setReason(e.target.value)} /></Field>
    <Button type="submit" disabled={command.disabled}>Сохранить решение</Button><CommandStatus command={command} refresh={reload} />
  </form>;
}
