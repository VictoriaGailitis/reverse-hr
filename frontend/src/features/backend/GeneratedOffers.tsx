import { TaskRecommendations } from "./TaskRecommendations";
import type { components as A } from "../../api/generated/assessment";
import { useBackend } from "../../state/BackendContext";
import { Button } from "../../components/Button";
import { ConsentGate } from "./ConsentGate";
import { CommandStatus, LoadState, useCommand } from "./ApiUI";
import { useResource } from "./Resource";
export function GeneratedOffers({
  created,
}: {
  created: (id: string) => void;
}) {
  const { api } = useBackend();
  const command = useCommand();
  const offers = useResource((signal) =>
    api.request<A["schemas"]["GeneratedOffer"][]>(
      "assessment",
      "/v1/assessment-generation/offers",
      { signal },
    ),
  );
  return (
    <>
    <TaskRecommendations />
    <section className="api-card">
      <h2>Задания по собственным референсам</h2>
      <LoadState resource={offers} />
      <Button variant="secondary" onClick={offers.reload}>
        Обновить доступные задания
      </Button>
      {!!offers.data?.length && (
        <ConsentGate purpose="assessment">
          {(consent) => (
            <>
              {!offers.data?.length && (
                <p>Новые направления пока не опубликованы.</p>
              )}
              {offers.data?.map((offer) => (
                <section key={offer.version_id}>
                  <h3>{offer.name}</h3>
                  <p>
                    {offer.specialization} · {offer.grade} ·{" "}
                    {offer.duration_seconds / 60} минут
                  </p>
                  <p>
                    {offer.scored
                      ? "Оценка по утверждённой шкале"
                      : "Практика: общий грейд не изменяется"}
                  </p>
                  <p>
                    ДЕМО · механизм оценки ещё требует подтверждения на реальных
                    данных.
                  </p>
                  <Button
                    disabled={command.disabled}
                    onClick={() =>
                      void command.run(async () => {
                        const result = await api.request<
                          A["schemas"]["SessionView"]
                        >("assessment", "/v1/assessment-generation/sessions", {
                          method: "POST",
                          body: {
                            version_id: offer.version_id,
                            assessment_consent_id: consent,
                          },
                          intent: `generated-session:${offer.version_id}`,
                        });
                        created(result.session_id);
                      })
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
      {offers.status === "ready" && !offers.data?.length && (
        <p>Новые направления пока не опубликованы.</p>
      )}
      <CommandStatus command={command} refresh={offers.reload} />
    </section>
    </>
  );
}
