import { useState } from "react";
import type { components as C } from "../../api/generated/candidate";
import { useBackend } from "../../state/BackendContext";
import { Button } from "../../components/Button";
import { useResource } from "./Resource";
import { CommandStatus, Field, LoadState, useCommand } from "./ApiUI";
type Command = C["schemas"]["CandidatePreferenceCommand"];
type View = {
  version: number;
  preferences: Omit<Command, "confirmed" | "share_in_matching"> | null;
  share_in_matching: boolean;
};
export function PreferencesPage() {
  const { api } = useBackend();
  const resource = useResource((signal) =>
    api.request<View>("candidate", "/v1/candidates/me/preferences", { signal }),
  );
  return (
    <section className="api-card">
      <h2>Пожелания к работе</h2>
      <p>
        Это ваши пожелания, а не подтверждённые навыки. Вы сами выбираете,
        учитывать ли их в подборе.
      </p>
      <LoadState resource={resource} />
      {resource.data && (
        <PreferencesForm
          key={resource.data.version}
          row={resource.data}
          reload={resource.reload}
        />
      )}
    </section>
  );
}
function PreferencesForm({ row, reload }: { row: View; reload: () => void }) {
  const { api } = useBackend();
  const command = useCommand();
  const p = row.preferences;
  const [minimum, setMinimum] = useState(p?.salary?.minimum?.toString() ?? "");
  const [maximum, setMaximum] = useState(p?.salary?.maximum?.toString() ?? "");
  const [tax, setTax] = useState<"gross" | "net">(
    p?.salary?.tax_basis ?? "gross",
  );
  const [formats, setFormats] = useState<NonNullable<Command["work_formats"]>>(
    p?.work_formats ?? [],
  );
  const [earliest, setEarliest] = useState(p?.start_window?.earliest ?? "");
  const [latest, setLatest] = useState(p?.start_window?.latest ?? "");
  const [tolerance, setTolerance] = useState(p?.salary_tolerance_percent ?? 0);
  const [share, setShare] = useState(row.share_in_matching);
  const [confirmed, setConfirmed] = useState(false);
  return (
    <form
      className="api-form"
      onSubmit={(e) => {
        e.preventDefault();
        void command.run(async () => {
          await api.request("candidate", "/v1/candidates/me/preferences", {
            method: "PUT",
            version: row.version,
            intent: "preferences",
            body: {
              salary:
                minimum && maximum
                  ? {
                      minimum: Number(minimum),
                      maximum: Number(maximum),
                      currency: "RUB",
                      period: "month",
                      tax_basis: tax,
                    }
                  : null,
              work_formats: formats,
              start_window: earliest && latest ? { earliest, latest } : null,
              salary_tolerance_percent: minimum ? tolerance : 0,
              share_in_matching: share,
              confirmed: true,
            } satisfies Command,
          });
          reload();
        }, "Пожелания сохранены.");
      }}
    >
      <p>
        Необязательные поля можно оставить пустыми. Пустая зарплата не означает
        согласие на любую сумму.
      </p>
      <Field label="Желаемая зарплата от, ₽ в месяц">
        <input
          type="number"
          min="1"
          max="1000000000"
          required={!!maximum}
          value={minimum}
          onChange={(e) => setMinimum(e.target.value)}
        />
      </Field>
      <Field label="Желаемая зарплата до, ₽ в месяц">
        <input
          type="number"
          min={minimum || "1"}
          max="1000000000"
          required={!!minimum}
          value={maximum}
          onChange={(e) => setMaximum(e.target.value)}
        />
      </Field>
      <Field label="Налоги в зарплатных ожиданиях">
        <select
          value={tax}
          onChange={(e) => setTax(e.target.value as typeof tax)}
        >
          <option value="gross">До вычета налогов</option>
          <option value="net">На руки</option>
        </select>
      </Field>
      {!!minimum && (
        <Field label="Допустимое снижение нижней границы, %">
          <input
            type="number"
            min="0"
            max="25"
            value={tolerance}
            onChange={(e) => setTolerance(Number(e.target.value))}
          />
        </Field>
      )}
      <fieldset>
        <legend>Подходящие форматы работы</legend>
        {(["remote", "hybrid", "onsite"] as const).map((value) => (
          <label key={value} className="consent">
            <input
              type="checkbox"
              checked={formats.includes(value)}
              onChange={(e) =>
                setFormats((old) =>
                  e.target.checked
                    ? [...old, value]
                    : old.filter((x) => x !== value),
                )
              }
            />
            <span>
              {
                { remote: "Удалённо", hybrid: "Гибрид", onsite: "В офисе" }[
                  value
                ]
              }
            </span>
          </label>
        ))}
      </fieldset>
      <Field label="Готовность выйти: с">
        <input
          type="date"
          required={!!latest}
          value={earliest}
          onChange={(e) => setEarliest(e.target.value)}
        />
      </Field>
      <Field label="Готовность выйти: по">
        <input
          type="date"
          required={!!earliest}
          min={earliest}
          value={latest}
          onChange={(e) => setLatest(e.target.value)}
        />
      </Field>
      <label className="consent">
        <input
          type="checkbox"
          checked={share}
          onChange={(e) => setShare(e.target.checked)}
        />
        <span>Учитывать пожелания в подборе для компаний</span>
      </label>
      <label className="consent">
        <input
          type="checkbox"
          checked={confirmed}
          onChange={(e) => setConfirmed(e.target.checked)}
        />
        <span>Подтверждаю актуальность пожеланий</span>
      </label>
      <Button type="submit" disabled={command.disabled || !confirmed}>
        Сохранить пожелания
      </Button>
      <CommandStatus command={command} refresh={reload} />
    </form>
  );
}
