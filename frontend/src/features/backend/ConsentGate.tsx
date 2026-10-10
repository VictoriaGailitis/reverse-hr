import { Link } from "react-router-dom";
import { useBackend } from "../../state/BackendContext";
import type { Purpose } from "../../api/types";
import { useResource } from "./Resource";
import { LoadState } from "./ApiUI";
import type { ReactNode } from "react";
export function ConsentGate({
  purpose,
  children,
}: {
  purpose: Purpose;
  children: (id: string) => ReactNode;
}) {
  const { api } = useBackend();
  const resource = useResource(async (signal) => {
    const [policies, consents] = await Promise.all([
      api.policies(signal),
      api.consents(signal),
    ]);
    return consents.find(
      (x) =>
        x.purpose === purpose &&
        x.status === "active" &&
        x.document_version === policies[purpose],
    );
  });
  return (
    <>
      <LoadState resource={resource} />
      {resource.status === "ready" &&
        (resource.data ? (
          children(resource.data.consent_id)
        ) : (
          <p>
            Для этого действия нужно отдельное действующее согласие.{" "}
            <Link to="/candidate/privacy">Открыть настройки приватности</Link>
          </p>
        ))}
    </>
  );
}
