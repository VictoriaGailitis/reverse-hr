import { test, expect } from "@playwright/test";
import { oauth, login, json, consentId, subject } from "./helpers/backend";
const stage = "55555555-5555-4555-8555-555555555555";

test("подписка на задания: отдельное согласие, стек, частота и отмена", async ({ page }) => {
  await oauth(page, false, ["candidate"]);
  let subscription = { enabled: false, version: 0, declared_skills: [] as string[], interval_hours: 24 };
  await page.route("**/api/privacy/v1/consents/policies", route => json(route, { assessment: "demo-v1", task_recommendations: "demo-v1" }));
  await page.route("**/api/privacy/v1/consents", route => json(route, [{ consent_id: consentId, purpose: "task_recommendations", document_version: "demo-v1", status: "active", version: 1 }]));
  await page.route("**/api/candidate/v1/candidates/me/task-subscription", async route => {
    if (route.request().method() === "PUT") {
      const body = route.request().postDataJSON();
      expect(route.request().headers()["if-match"]).toBe(`"${subscription.version}"`);
      expect(body.consent_id).toBe(body.enabled ? consentId : null);
      subscription = { ...body, version: subscription.version + 1 };
    }
    await json(route, subscription);
  });
  await page.route("**/api/candidate/v1/candidates/me/task-recommendations", route => json(route, { items: [], next_cursor: null }));
  await page.route("**/api/evaluation/v1/evaluation-risks/me", route => json(route, { additional_verification_required: true, signal_count: 2 }));
  await page.route("**/api/assessment/v1/assessment-generation/offers", route => json(route, []));
  await page.route("**/api/assessment/v1/assessment-task-history**", route => json(route, []));
  await page.route("**/api/assessment/v1/assessment-selection-policies", route => json(route, []));
  await page.route("**/api/assessment/v1/assessment-sessions/me", route => json(route, []));
  await login(page, "/candidate/assessment");
  await expect(page.getByRole("heading", { name: "Подходящие новые задания" })).toBeVisible();
  await expect(page.getByText(/Обнаружено сигналов: 2/)).toBeVisible();
  await page.getByLabel("Стек для подбора, через запятую").fill("python, postgres");
  await page.getByLabel("Минимальный интервал уведомлений, часов").fill("12");
  await page.getByRole("button", { name: "Сохранить и включить подписку" }).click();
  await expect(page.getByText("Подписка включена", { exact: true })).toBeVisible();
  expect(subscription.declared_skills).toEqual(["python", "postgres"]);
  expect(subscription.interval_hours).toBe(12);
  await page.getByRole("button", { name: "Отменить подписку", exact: true }).click();
  await expect(page.getByText("Подписка выключена", { exact: true })).toBeVisible();
});

test("проверяющий отклоняет подозрение с обоснованием и версией", async ({ page }) => {
  await oauth(page, false, ["assessment_reviewer"]);
  let resolved = false;
  await page.route("**/api/evaluation/v1/evaluation-risks/queue", route => json(route, { items: resolved ? [] : [{ stage_id: stage, candidate_id: subject, version: 1, codes: ["instruction_override"], status: "review_pending" }], next_cursor: null }));
  await page.route(`**/api/evaluation/v1/evaluation-risks/${stage}/decision`, async route => {
    expect(route.request().headers()["if-match"]).toBe('"1"');
    expect(route.request().postDataJSON()).toEqual({ action: "dismiss", reason: "Это допустимый пример защиты от инъекций", verification_stage_id: null });
    resolved = true; await json(route, { status: "dismissed", version: 2 });
  });
  await page.route("**/api/evaluation/v1/evaluation-automatic/queue", route => json(route, []));
  await page.route("**/api/assessment/v1/assessment-automatic/queue", route => json(route, []));
  await page.route("**/api/assessment/v1/assessment-appeals/queue", route => json(route, []));
  await login(page, "/admin?tab=reviews");
  await expect(page.getByRole("heading", { name: "Сигналы риска и дополнительная проверка" })).toBeVisible();
  await page.getByLabel("Решение", { exact: true }).selectOption("dismiss");
  await page.getByLabel("Обоснование", { exact: true }).fill("Это допустимый пример защиты от инъекций");
  await page.getByRole("button", { name: "Сохранить решение", exact: true }).click();
  await expect(page.getByLabel("Решение", { exact: true })).toHaveCount(0);
  expect(resolved).toBe(true);
});
