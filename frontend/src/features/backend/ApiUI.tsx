import { useSearchParams } from "react-router-dom";
import {
  cloneElement,
  useId,
  useRef,
  useState,
  type ReactElement,
  type ReactNode,
} from "react";
import { ApiError, errorMessage } from "../../api/client";
import { useBackend } from "../../state/BackendContext";
import { Button } from "../../components/Button";
import { useResource, ResourceError } from "./Resource";
import type { Organization } from "../../api/types";

export function useCommand() {
  const { session } = useBackend();
  const lock = useRef(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>();
  const [notice, setNotice] = useState("");
  const conflict = error instanceof ApiError && error.status === 409;
  async function run(
    work: () => Promise<unknown>,
    message = "Сохранено на сервере.",
  ) {
    if (lock.current || session.status !== "authenticated" || conflict) return;
    lock.current = true;
    setBusy(true);
    setError(undefined);
    setNotice("");
    try {
      await work();
      setNotice(message);
    } catch (next) {
      setError(next);
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }
  return {
    run,
    busy,
    error,
    notice,
    disabled: busy || conflict || session.status !== "authenticated",
    reset: () => {
      setError(undefined);
      setNotice("");
    },
  };
}
export function CommandStatus({
  command,
  refresh,
}: {
  command: ReturnType<typeof useCommand>;
  refresh?: () => void;
}) {
  return (
    <>
      {command.notice && <p role="status">{command.notice}</p>}
      {command.error !== undefined && (
        <div role="alert">
          <p>{errorMessage(command.error)}</p>
          {refresh && (
            <Button
              variant="secondary"
              disabled={command.busy}
              onClick={() => {
                command.reset();
                refresh();
              }}
            >
              Обновить данные
            </Button>
          )}
        </div>
      )}
    </>
  );
}
export function LoadState({
  resource,
}: {
  resource: { status: string; error?: unknown; reload: () => void };
}) {
  return (
    <>
      {resource.status === "loading" && <p role="status">Загрузка…</p>}
      {resource.status === "error" && (
        <ResourceError error={resource.error} retry={resource.reload} />
      )}
    </>
  );
}
export function OrganizationScope({
  children,
}: {
  children: (organization: Organization) => ReactNode;
}) {
  const { api } = useBackend();
  const resource = useResource((signal) => api.organizations(signal));
  const [params, setParams] = useSearchParams();
  const [selected, setSelected] = useState(params.get("organization") ?? "");
  const organization = selected
    ? resource.data?.find((item) => item.organization_id === selected)
    : resource.data?.[0];
  return (
    <>
      <LoadState resource={resource} />
      {resource.status === "ready" &&
        (!organization ? (
          <p>
            Организация недоступна. Откройте кабинет компании и выберите
            доступную организацию.
          </p>
        ) : (
          <>
            <label className="form-field">
              <span>Организация</span>
              <select
                value={organization.organization_id}
                onChange={(event) => {
                  setSelected(event.target.value);
                  setParams((current) => {
                    current.set("organization", event.target.value);
                    current.delete("snapshot");
                    current.delete("candidate");
                    return current;
                  });
                }}
              >
                {resource.data?.map((item) => (
                  <option
                    key={item.organization_id}
                    value={item.organization_id}
                  >
                    {item.name}
                  </option>
                ))}
              </select>
            </label>
            <div key={organization.organization_id} className="screen-form">
              {children(organization)}
            </div>
          </>
        ))}
    </>
  );
}
export function Field({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  const id = useId();
  return (
    <div className="form-field">
      <label id={id}>{label}</label>
      {cloneElement(children as ReactElement<{ "aria-labelledby"?: string }>, {
        "aria-labelledby": id,
      })}
    </div>
  );
}
export const uuidPattern =
  "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}";
export const isUuid = (value: string | null): value is string =>
  !!value && new RegExp(`^${uuidPattern}$`).test(value);
