import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useBackend } from "../../state/BackendContext";
import { Button } from "../../components/Button";
import { ConsentGate } from "./ConsentGate";
import { CommandStatus, Field, LoadState, useCommand } from "./ApiUI";
import { useResource } from "./Resource";

type Subscription = { version: number; enabled: boolean; declared_skills: string[]; interval_hours: number };
type Recommendation = { version_id: string; notice_id: string; name: string; specialization: string; grade: string; stack_tags: string[] };
export function TaskRecommendations() {
  const { api } = useBackend();
  const command = useCommand();
  const subscription = useResource(signal => api.request<Subscription>("candidate", "/v1/candidates/me/task-subscription", { signal }));
  const [after, setAfter] = useState<string>();
  const recommendations = useResource(signal => api.request<{ items: Recommendation[]; next_cursor: string | null }>("candidate", `/v1/candidates/me/task-recommendations${after ? `?after=${after}` : ""}`, { signal }));
  const risk = useResource(signal => api.request<{ additional_verification_required: boolean; signal_count: number }>("evaluation", "/v1/evaluation-risks/me", { signal }));
  useEffect(() => { recommendations.reload(); }, [after, recommendations.reload]);
  const [skills, setSkills] = useState<string | undefined>();
  const [hours, setHours] = useState<number | undefined>();
  const current = subscription.data;
  async function save(enabled: boolean, consent?: string) {
    if (!current) return;
    await command.run(async () => {
      await api.request("candidate", "/v1/candidates/me/task-subscription", {
        method: "PUT", version: current.version, intent: "task-subscription",
        body: { enabled, consent_id: consent ?? null,
          declared_skills: (skills ?? current.declared_skills.join(", ")).split(",").map(x => x.trim()).filter(Boolean),
          interval_hours: hours ?? current.interval_hours },
      });
      subscription.reload(); recommendations.reload();
    });
  }
  return <section className="api-card">
    <h2>Подходящие новые задания</h2>
    {risk.data?.additional_verification_required && <p role="status">Нужна дополнительная проверка условий прохождения. Обнаружено сигналов: {risk.data.signal_count}. Это подозрение, а не установленное нарушение; грейд автоматически не снижается.</p>}
    <p>Все ваши специализации, подтверждённый уровень (или заявленный, если проверки ещё нет) и стек. Получение рекомендации не подтверждает грейд.</p>
    <LoadState resource={subscription} />
    {current && <>
      <p>{current.enabled ? "Подписка включена" : "Подписка выключена"}</p>
      <Field label="Стек для подбора, через запятую"><input value={skills ?? current.declared_skills.join(", ")} onChange={e => setSkills(e.target.value)} /></Field>
      <Field label="Минимальный интервал уведомлений, часов"><input type="number" min={1} max={168} value={hours ?? current.interval_hours} onChange={e => setHours(Number(e.target.value))} /></Field>
      <ConsentGate purpose="task_recommendations">{consent => <Button disabled={command.disabled} onClick={() => void save(true, consent)}>Сохранить и включить подписку</Button>}</ConsentGate>
      {current.enabled && <Button variant="secondary" disabled={command.disabled} onClick={() => void save(false)}>Отменить подписку</Button>}
      <p>Для уведомлений включите рекомендации в <Link to="/candidate/privacy">настройках уведомлений</Link>. Отзыв согласия останавливает подбор.</p>
    </>}
    <Button variant="secondary" onClick={() => { subscription.reload(); recommendations.reload(); }}>Обновить рекомендации</Button>
    <LoadState resource={recommendations} />
    {recommendations.data?.items.map(item => <p key={item.notice_id}>{item.name} · {item.specialization} · {item.grade} · {item.stack_tags.join(", ") || "Общее задание"}</p>)}
    {!!recommendations.data?.next_cursor && <Button variant="secondary" onClick={() => setAfter(recommendations.data?.next_cursor ?? undefined)}>Следующая страница рекомендаций</Button>}
    {after && <Button variant="secondary" onClick={() => setAfter(undefined)}>В начало рекомендаций</Button>}
    <CommandStatus command={command} refresh={subscription.reload} />
  </section>;
}
