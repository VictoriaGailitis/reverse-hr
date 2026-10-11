import { useResource } from "./Resource";
import { useState } from "react";
import type { components as A } from "../../api/generated/assessment";
import { useBackend } from "../../state/BackendContext";
import { Button } from "../../components/Button";
import { CommandStatus, Field, LoadState, useCommand, isUuid } from "./ApiUI";
export function GenerationCalibration({
  reference,
  plan,
}: {
  reference: A["schemas"]["ReferenceView"];
  plan: string;
}) {
  const { api } = useBackend();
  const command = useCommand();
  const requiresModel = reference.rubric.some(
    (c) => c.evidence !== "test_result",
  );
  const model = useResource((signal) =>
    api.request<{
      enabled: boolean;
      model: string | null;
      prompt_digest: string;
    }>("evaluation", "/v1/evaluation-automatic/configuration", { signal }),
  );
  const [weights, setWeights] = useState(
    JSON.stringify(
      Object.fromEntries(
        reference.competencies.map((c, i) => [
          c.key,
          Math.floor(100 / reference.competencies.length) +
            (i === 0 ? 100 % reference.competencies.length : 0),
        ]),
      ),
    ),
  );
  const [minimums, setMinimums] = useState(
    JSON.stringify(
      Object.fromEntries(reference.competencies.map((c) => [c.key, 60])),
    ),
  );
  const [threshold, setThreshold] = useState(70);
  const [margin, setMargin] = useState(5);
  const [sample, setSample] = useState(10);
  const [retry, setRetry] = useState(24);
  const [cooldown, setCooldown] = useState(90);
  const [id, setId] = useState("");
  const [calibration, setCalibration] = useState("");
  return (
    <details>
      <summary>Шкала автоматического грейда и калибровка</summary>
      <p>
        Настройте шкалу на проверенном пробном плане. Для утверждения нужны
        реальные экспертные данные: не менее 20 независимых примеров с
        согласованными метками двух экспертов и обеими группами результатов.
        Политику утверждает другой администратор.
      </p>
      {requiresModel && (
        <>
          <LoadState resource={model} />
          <p>
            Шкала закрепит модель {model.data?.model ?? "пока не настроена"} и
            текущую версию её инструкции. Изменение модели требует новой
            калибровки.
          </p>
        </>
      )}
      <form
        className="api-form"
        onSubmit={(e) => {
          e.preventDefault();
          void command.run(async () => {
            const result = await api.request<A["schemas"]["PolicyView"]>(
              "assessment",
              "/v1/grade-policies",
              {
                method: "POST",
                body: {
                  plan_version_id: plan,
                  rules: {
                    weights: JSON.parse(weights),
                    minimums: JSON.parse(minimums),
                    pass_score: threshold,
                    retry_seconds: retry * 3600,
                    grade_change_seconds: cooldown * 86400,
                    automatic_decisions: true,
                    required_llm_model: requiresModel
                      ? model.data?.model
                      : null,
                    required_llm_prompt_digest: requiresModel
                      ? model.data?.prompt_digest
                      : null,
                    generation_reference_id: reference.version_id,
                    review_margin: margin,
                    audit_percent: sample,
                  },
                },
                intent: `generation-policy:${reference.version_id}`,
              },
            );
            setId(result.policy_id);
          }, "Черновик шкалы создан. Утвердите калибровку и привяжите политику к референсу.");
        }}
      >
        <Field label="Веса компетенций (JSON, сумма 100)">
          <textarea
            required
            value={weights}
            onChange={(e) => setWeights(e.target.value)}
          />
        </Field>
        <Field label="Минимальные баллы компетенций (JSON)">
          <textarea
            required
            value={minimums}
            onChange={(e) => setMinimums(e.target.value)}
          />
        </Field>
        <Field label="Проходной балл">
          <input
            type="number"
            required
            min={1}
            max={100}
            value={threshold}
            onChange={(e) => setThreshold(Number(e.target.value))}
          />
        </Field>
        <Field label="Зона перепроверки вокруг порога, баллов">
          <input
            type="number"
            required
            min={0}
            max={30}
            value={margin}
            onChange={(e) => setMargin(Number(e.target.value))}
          />
        </Field>
        <Field label="Выборочная проверка, %">
          <input
            type="number"
            required
            min={0}
            max={100}
            value={sample}
            onChange={(e) => setSample(Number(e.target.value))}
          />
        </Field>
        <Field label="Повторная попытка через, часов">
          <input
            type="number"
            required
            min={1}
            max={2160}
            value={retry}
            onChange={(e) => setRetry(Number(e.target.value))}
          />
        </Field>
        <Field label="Изменение грейда через, дней">
          <input
            type="number"
            required
            min={1}
            max={365}
            value={cooldown}
            onChange={(e) => setCooldown(Number(e.target.value))}
          />
        </Field>
        <Button
          type="submit"
          disabled={command.disabled || (requiresModel && !model.data?.enabled)}
        >
          Создать шкалу
        </Button>
      </form>
      <form
        className="api-form"
        onSubmit={(e) => {
          e.preventDefault();
          void command.run(async () => {
            const policy = await api.request<A["schemas"]["PolicyView"]>(
              "assessment",
              `/v1/grade-policies/${id}`,
            );
            await api.request(
              "assessment",
              `/v1/grade-policies/${id}/approve`,
              {
                method: "POST",
                body: JSON.parse(calibration),
                version: policy.version,
                intent: `generation-calibration:${id}`,
              },
            );
          }, "Калибровка утверждена. Привяжите политику к референсу перед публикацией.");
        }}
      >
        <Field label="Идентификатор политики для утверждения">
          <input required value={id} onChange={(e) => setId(e.target.value)} />
        </Field>
        <Field label="Экспертная калибровка (JSON)">
          <textarea
            required
            value={calibration}
            onChange={(e) => setCalibration(e.target.value)}
          />
        </Field>
        <p>
          Формат данных описан в документации автоматической оценки. Не
          используйте искусственные метки вместо экспертных результатов.
        </p>
        <Button type="submit" disabled={command.disabled || !isUuid(id)}>
          Проверить и утвердить калибровку
        </Button>
      </form>
      <CommandStatus command={command} />
    </details>
  );
}
