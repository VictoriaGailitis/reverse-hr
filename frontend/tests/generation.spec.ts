import { test, expect } from "@playwright/test";
import { oauth, login, json } from "./helpers/backend";
const version = "55555555-5555-4555-8555-555555555555";
const previewId = "66666666-6666-4666-8666-666666666666";
const generation = "77777777-7777-4777-8777-777777777777";
const ref = {
  version_id: version,
  reference_id: version,
  number: 1,
  status: "draft",
  version: 1,
  digest: "a".repeat(64),
  organization_id: null,
  grade_policy_id: null,
  name: "Оригинальное задание",
  format: "code",
  specialization: "backend",
  grade: "junior",
  description:
    "Собственное описание алгоритма обработки уведомлений с повторными попытками.",
  required_constraints: ["Не раскрывать контакты"],
  allowed_variations: ["Предметная область"],
  forbidden_changes: ["Критерии и сложность"],
  competencies: [{ key: "primary", description: "Корректность алгоритма" }],
  rubric: [
    {
      key: "quality",
      competency: "primary",
      description: "Корректность решения",
      points: 100,
      evidence: "test_result",
    },
  ],
  parameters: {},
  duration_seconds: 1200,
  pool_size: 3,
  max_exposures: 100,
};
test("собственный референс: спецификация до вызова модели и явное подтверждение", async ({
  page,
}) => {
  await oauth(page, false, ["content_admin"]);
  let generated = 0;
  await page.route(
    "**/api/assessment/v1/assessment-generation/references",
    (r) => json(r, [ref]),
  );
  await page.route(
    `**/api/assessment/v1/assessment-generation/references/${version}/jobs`,
    (r) => json(r, []),
  );
  await page.route(
    `**/api/assessment/v1/assessment-generation/references/${version}/preview`,
    (r) => {
      expect(r.request().postDataJSON()).toEqual({
        scenario: "Доставка собственных сообщений с повторной обработкой",
        parameters: {},
      });
      return json(
        r,
        {
          preview_id: previewId,
          version_id: version,
          specification: {
            reference: ref,
            scenario: "Доставка собственных сообщений с повторной обработкой",
          },
          digest: "b".repeat(64),
          expires_at: "2027-01-01T00:00:00Z",
        },
        201,
      );
    },
  );
  await page.route(
    "**/api/assessment/v1/assessment-generation/generate",
    (r) => {
      generated++;
      expect(r.request().postDataJSON()).toEqual({
        preview_id: previewId,
        specification_digest: "b".repeat(64),
      });
      expect(r.request().headers()["idempotency-key"]).toBeTruthy();
      return json(
        r,
        {
          generation_id: generation,
          version_id: version,
          status: "pending",
          attempts: 0,
          error: null,
        },
        202,
      );
    },
  );
  await login(page, "/admin?tab=generation");
  await page
    .getByLabel("Конкретный сценарий пробного задания")
    .fill("Доставка собственных сообщений с повторной обработкой");
  await page
    .getByRole("button", { name: "Подготовить спецификацию", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Перед генерацией" }),
  ).toBeVisible();
  expect(generated).toBe(0);
  await page
    .getByRole("button", { name: "Генерировать пробное задание", exact: true })
    .click();
  await expect(
    page.getByText("Пробная генерация поставлена в очередь.", { exact: true }),
  ).toBeVisible();
  expect(generated).toBe(1);
});
