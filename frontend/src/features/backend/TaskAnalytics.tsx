import { useState, type FormEvent } from "react";
import { useBackend } from "../../state/BackendContext";
import { Button } from "../../components/Button";
import { errorMessage } from "../../api/client";
import type { components as A } from "../../api/generated/assessment";

type Report = A["schemas"]["AnalyticsReport"];
type Distribution = A["schemas"]["GradeDistribution"];
const grades = ["junior", "middle", "senior", "lead"] as const;
const labels = {
  poor: "Не решена / решена плохо",
  normal: "Решена нормально",
  good: "Решена хорошо",
};
function DistributionBars({
  rows,
  prefix,
}: {
  rows: Distribution[];
  prefix: string;
}) {
  return (
    <div className="analytics-distributions">
      {rows.map((row) => (
        <div key={row.grade} className="api-card">
          <h3>
            {row.grade} · {row.count} результатов
          </h3>
          <p>
            Нормально: {row.bands.normal_from}–{row.bands.good_from - 1};
            хорошо: {row.bands.good_from}–100 баллов.
          </p>
          {row.count ? (
            <div
              className="analytics-bar"
              aria-label={`Распределение ${row.grade}`}
            >
              {row.buckets
                .filter((bucket) => bucket.count > 0)
                .map((bucket) => {
                  const tooltip = `${labels[bucket.quality]}: ${bucket.count} из ${row.count} (${bucket.percent}%)`;
                  const id = `${prefix}-${row.grade}-${bucket.quality}`;
                  return (
                    <button
                      key={bucket.quality}
                      type="button"
                      className={`analytics-segment analytics-${bucket.quality}`}
                      style={{ width: `${bucket.percent}%` }}
                      aria-label={tooltip}
                      aria-describedby={id}
                    >
                      <span
                        id={id}
                        role="tooltip"
                        className="analytics-tooltip"
                      >
                        {tooltip}
                      </span>
                    </button>
                  );
                })}
            </div>
          ) : (
            <p>Результатов пока нет</p>
          )}
          <p>
            {row.buckets
              .map(
                (bucket) =>
                  `${labels[bucket.quality]}: ${bucket.count} (${bucket.percent}%)`,
              )
              .join(" · ")}
          </p>
          {!row.sufficient && (
            <p className="api-muted">
              Недостаточно данных для устойчивого сравнения.
            </p>
          )}
        </div>
      ))}
    </div>
  );
}
export function TaskAnalytics() {
  const { api } = useBackend();
  const [source, setSource] = useState("live");
  const [scope, setScope] = useState("task");
  const [id, setId] = useState("");
  const [task, setTask] = useState("");
  const [since, setSince] = useState(() =>
    new Date(Date.now() - 180 * 86400000).toISOString().slice(0, 10),
  );
  const [until, setUntil] = useState(() =>
    new Date(Date.now() + 86400000).toISOString().slice(0, 10),
  );
  const [bands, setBands] = useState(() =>
    Object.fromEntries(
      grades.map((grade) => [grade, { normal_from: 50, good_from: 80 }]),
    ),
  );
  const [minimum, setMinimum] = useState(10);
  const [samples, setSamples] = useState("[]");
  const [report, setReport] = useState<Report>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>();
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(undefined);
    setReport(undefined);
    try {
      const scale = { by_grade: bands, minimum_group_size: minimum };
      const next = await api.request<Report>(
        "assessment",
        `/v1/task-analytics/${source === "live" ? "report" : "simulate"}`,
        {
          method: "POST",
          body:
            source === "live"
              ? {
                  scope,
                  scope_id: id.trim(),
                  task_key: scope === "task" ? task.trim() : null,
                  since: `${since}T00:00:00Z`,
                  until: `${until}T00:00:00Z`,
                  scale,
                }
              : {
                  scale,
                  observations: JSON.parse(samples),
                  label_source: source,
                  reason: "Operator analytic preview; no grade changes",
                },
        },
      );
      if (
        !Array.isArray(next.target_distributions) ||
        !Array.isArray(next.independent_distributions) ||
        [...next.target_distributions, ...next.independent_distributions].some(
          (row) =>
            !Array.isArray(row.buckets) ||
            row.buckets.some(
              (bucket) =>
                !Number.isFinite(bucket.percent) ||
                bucket.percent < 0 ||
                bucket.percent > 100 ||
                !(bucket.quality in labels),
            ),
        )
      ) {
        throw new Error("Некорректный ответ аналитики");
      }
      setReport(next);
    } catch (next) {
      setError(next);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section>
      <h2>Качество заданий</h2>
      <p>
        Аналитика не меняет грейды и не снимает задания с публикации. Шкала
        задаётся отдельно для каждого целевого уровня.
      </p>
      <form
        className="api-card api-form"
        onSubmit={(event) => void submit(event)}
      >
        <label className="form-field">
          Источник
          <select value={source} onChange={(e) => setSource(e.target.value)}>
            <option value="live">Результаты платформы · demo</option>
            <option value="synthetic">Синтетическая выборка</option>
            <option value="expert">Экспертная выборка оператора</option>
          </select>
        </label>
        {source === "live" ? (
          <>
            <label className="form-field">
              Единица анализа
              <select value={scope} onChange={(e) => setScope(e.target.value)}>
                <option value="task">Версия задания</option>
                <option value="reference_version">Версия референса</option>
                <option value="reference_family">Семейство референса</option>
              </select>
            </label>
            <label className="form-field">
              UUID редакции / версии / семейства
              <input
                required
                value={id}
                onChange={(e) => setId(e.target.value)}
              />
            </label>
            {scope === "task" && (
              <label className="form-field">
                Ключ задания
                <input
                  required
                  maxLength={100}
                  value={task}
                  onChange={(e) => setTask(e.target.value)}
                />
              </label>
            )}
            <label className="form-field">
              Начало периода (UTC)
              <input
                type="date"
                required
                value={since}
                onChange={(e) => setSince(e.target.value)}
              />
            </label>
            <label className="form-field">
              Конец периода, не включительно (UTC)
              <input
                type="date"
                required
                value={until}
                onChange={(e) => setUntil(e.target.value)}
              />
            </label>
          </>
        ) : (
          <>
            <label className="form-field">
              Наблюдения JSON
              <textarea
                required
                rows={8}
                value={samples}
                onChange={(e) => setSamples(e.target.value)}
              />
            </label>
            <p>
              Массив объектов: profile_key (обезличенный ключ), target_grade,
              independent_grade, score (0–100), rest_score (средний балл
              остальных заданий или null). Один результат на профиль. Не
              добавляйте контакты. Выборка используется только для расчёта и не
              сохраняется.
            </p>
          </>
        )}
        <label className="form-field">
          Минимум результатов в группе
          <input
            required
            type="number"
            min={5}
            max={1000}
            value={minimum}
            onChange={(e) => setMinimum(Number(e.target.value))}
          />
        </label>
        {grades.map((grade) => (
          <fieldset key={grade}>
            <legend>Шкала {grade}</legend>
            <label className="form-field">
              Нормально от ({grade})
              <input
                required
                type="number"
                min={1}
                max={99}
                value={bands[grade].normal_from}
                onChange={(e) =>
                  setBands((old) => ({
                    ...old,
                    [grade]: {
                      ...old[grade],
                      normal_from: Number(e.target.value),
                    },
                  }))
                }
              />
            </label>
            <label className="form-field">
              Хорошо от ({grade})
              <input
                required
                type="number"
                min={bands[grade].normal_from + 1}
                max={100}
                value={bands[grade].good_from}
                onChange={(e) =>
                  setBands((old) => ({
                    ...old,
                    [grade]: {
                      ...old[grade],
                      good_from: Number(e.target.value),
                    },
                  }))
                }
              />
            </label>
          </fieldset>
        ))}
        <Button type="submit" disabled={busy}>
          {busy ? "Рассчитываем…" : "Рассчитать статистику"}
        </Button>
      </form>
      {error !== undefined && (
        <p role="alert">
          {error instanceof SyntaxError
            ? "Проверьте формат JSON выборки."
            : errorMessage(error)}
        </p>
      )}
      {report && (
        <div aria-live="polite">
          <p>
            Источник: {report.source} · {report.sample_count} профилей ·
            независимых меток: {report.independent_label_count}.
          </p>
          <h2>По целевому грейду</h2>
          <p>
            Описание попыток. Целевой уровень не доказывает подготовку
            кандидата.
          </p>
          <DistributionBars
            rows={report.target_distributions}
            prefix="target"
          />
          <h2>По независимому грейду</h2>
          <p>
            На платформе — грейд, подтверждённый до начала этой сессии. В
            проверочной выборке — метка оператора.
          </p>
          <DistributionBars
            rows={report.independent_distributions}
            prefix="independent"
          />
          <h2>Разделяющая сила</h2>
          <p>
            Разница долей успешных решений старшей и младшей групп. Для обеих
            используется одна шкала старшего грейда; отрицательное значение —
            повод изучить задание.
          </p>
          {report.contrasts.map((item) => (
            <p key={`${item.lower_grade}-${item.upper_grade}`}>
              {item.lower_grade} → {item.upper_grade}:{" "}
              {item.status === "available"
                ? `нормально или лучше ${((item.normal_or_better_difference ?? 0) * 100).toFixed(1)} п.п.; хорошо ${((item.good_difference ?? 0) * 100).toFixed(1)} п.п.`
                : "недостаточно данных"}{" "}
              · группы {item.lower_count} / {item.upper_count}
            </p>
          ))}
          <p>
            Связь с остальными заданиями:{" "}
            {report.corrected_item_total_correlation ??
              (report.correlation_status === "constant_scores"
                ? "все баллы одинаковы"
                : "недостаточно данных")}{" "}
            · {report.correlation_count} пар.
          </p>
          <p className="api-muted">
            Повторы одного профиля не увеличивают выборку. Технические сбои не
            считаются плохими решениями. Варианты генерации не считаются
            автоматически равноценными; сравнения описательные и не подтверждают
            калибровку.
          </p>
        </div>
      )}
    </section>
  );
}
