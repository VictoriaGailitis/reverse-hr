import { test, expect } from "@playwright/test";
import {
  oauth,
  login,
  json,
  subject,
  orgId,
  consentId,
  profile,
  organization,
} from "./helpers/backend";
test.use({
  launchOptions: {
    executablePath:
      "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    args: [
      "--use-fake-device-for-media-stream",
      "--use-fake-ui-for-media-stream",
    ],
  },
});
const sessionId = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const stageId = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const resourceId = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
const snapshotId = "dddddddd-dddd-4ddd-8ddd-dddddddddddd";

test("пожелания: первая версия 0, явное подтверждение и отдельное разрешение на подбор", async ({
  page,
}) => {
  await oauth(page);
  let saved: unknown;
  await page.route("**/api/candidate/**", (route) => {
    if (route.request().url().endsWith("/preferences")) {
      if (route.request().method() === "PUT") {
        expect(route.request().headers()["if-match"]).toBe('"0"');
        saved = route.request().postDataJSON();
      }
      return json(route, {
        version: 0,
        preferences: null,
        share_in_matching: false,
      });
    }
    return json(route, profile);
  });
  await login(page);
  await page
    .getByRole("button", { name: "Пожелания к работе", exact: true })
    .click();
  await page.getByLabel("Желаемая зарплата от, ₽ в месяц").fill("150000");
  await page.getByLabel("Желаемая зарплата до, ₽ в месяц").fill("200000");
  await page.getByRole("checkbox", { name: "Удалённо", exact: true }).check();
  await expect(
    page.getByRole("button", { name: "Сохранить пожелания" }),
  ).toBeDisabled();
  await page
    .getByRole("checkbox", { name: "Подтверждаю актуальность пожеланий" })
    .check();
  await page.getByRole("button", { name: "Сохранить пожелания" }).click();
  await expect
    .poll(() => saved)
    .toEqual({
      salary: {
        minimum: 150000,
        maximum: 200000,
        currency: "RUB",
        period: "month",
        tax_basis: "gross",
      },
      work_formats: ["remote"],
      start_window: null,
      salary_tolerance_percent: 0,
      share_in_matching: false,
      confirmed: true,
    });
});

test("отменить подписку можно без активного согласия, версия проверяется", async ({
  page,
}) => {
  await oauth(page);
  let cancelled = false;
  await page.route("**/api/privacy/**", (route) =>
    json(
      route,
      route.request().url().endsWith("/policies")
        ? { company_task_subscription: "v1" }
        : [],
    ),
  );
  await page.route("**/api/assessment/**", (route) => {
    if (route.request().url().includes("/company-task-subscriptions")) {
      if (route.request().method() === "PUT") {
        expect(route.request().headers()["if-match"]).toBe('"3"');
        expect(route.request().postDataJSON()).toEqual({
          status: "cancelled",
          min_interval_seconds: 604800,
        });
        cancelled = true;
      }
      const row = {
        organization_id: orgId,
        status: cancelled ? "cancelled" : "active",
        min_interval_seconds: 604800,
        consent_id: consentId,
        version: cancelled ? 4 : 3,
      };
      return json(
        route,
        route.request().url().endsWith("/company-task-subscriptions")
          ? [row]
          : row,
      );
    }
    return json(route, []);
  });
  await login(page, "/candidate/assessment?tab=company");
  await page
    .getByRole("button", { name: "Отменить подписку", exact: true })
    .click();
  await expect(
    page.getByText("Подписка отменена", { exact: true }),
  ).toBeVisible();
  expect(cancelled).toBe(true);
});

test("владелец добавляет сотрудника и отзывает его доступ по разным версиям", async ({
  page,
}) => {
  await oauth(page);
  let added = false;
  let revoked = false;
  let orgVersion = 1;
  await page.route("**/api/employer/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    const owner = {
      membership_id: sessionId,
      organization_id: orgId,
      subject,
      role: "owner",
      status: "active",
      version: 1,
    };
    const member = {
      membership_id: resourceId,
      organization_id: orgId,
      subject: stageId,
      role: "technical_expert",
      status: revoked ? "revoked" : "active",
      version: revoked ? 3 : 2,
    };
    if (path.endsWith("/revoke")) {
      expect(route.request().headers()["if-match"]).toBe('"2"');
      revoked = true;
      orgVersion++;
      return json(route, { ...member, status: "revoked", version: 3 });
    }
    if (path.endsWith("/members")) {
      if (route.request().method() === "POST") {
        expect(route.request().headers()["if-match"]).toBe('"1"');
        expect(route.request().postDataJSON()).toEqual({
          subject: stageId,
          role: "technical_expert",
        });
        added = true;
        orgVersion++;
        return json(route, member, 201);
      }
      return json(route, added ? [owner, member] : [owner]);
    }
    return json(route, [{ ...organization, version: orgVersion }]);
  });
  await login(page, "/employer");
  await page
    .getByLabel("Идентификатор учётной записи сотрудника")
    .fill(stageId);
  await page.getByLabel("Роль сотрудника").selectOption("technical_expert");
  await page
    .getByRole("button", { name: "Добавить сотрудника", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Отозвать доступ сотрудника", exact: true })
    .click();
  expect(revoked).toBe(false);
  await page
    .getByRole("button", { name: "Подтвердить отзыв доступа", exact: true })
    .click();
  await expect.poll(() => revoked).toBe(true);
});

test("проверяющий подтверждает грейд с текущим digest доказательств", async ({
  page,
}) => {
  await oauth(page, false, ["assessment_reviewer"]);
  let decided = false;
  await page.route("**/api/assessment/**", (route) => {
    if (route.request().url().includes("assessment-appeals"))
      return json(route, []);
    if (route.request().method() === "POST") {
      expect(route.request().postDataJSON()).toEqual({
        action: "confirm",
        evidence_digest: "a".repeat(64),
        reason: "Каждый критерий проверен по материалам",
      });
      decided = true;
    }
    return json(route, {
      session_id: sessionId,
      policy_id: resourceId,
      status: decided ? "confirmed" : "review_pending",
      score: 82,
      competency_scores: { coding: 82 },
      recommended_grade: "middle",
      confirmed_grade: decided ? "middle" : null,
      evidence_digest: "a".repeat(64),
      decision_id: decided ? snapshotId : null,
    });
  });
  await login(page, "/admin");
  await page
    .getByLabel("Идентификатор сессии для решения о грейде")
    .fill(sessionId);
  await page.getByRole("button", { name: "Загрузить итоговую оценку" }).click();
  await page
    .getByLabel("Итоговое решение", { exact: true })
    .selectOption("confirm");
  await page
    .getByLabel("Обоснование итогового решения")
    .fill("Каждый критерий проверен по материалам");
  await page
    .getByRole("button", { name: "Сохранить решение о грейде" })
    .click();
  await expect(
    page.getByText("Состояние: Подтверждено", { exact: true }),
  ).toBeVisible();
  expect(decided).toBe(true);
});

test.describe("настоящий MediaRecorder с тестовым устройством Chrome", () => {
  test("видео: допуск, захват, части с digest и отправка только финального снимка", async ({
    page,
  }) => {
    await oauth(page);
    let admission = false;
    let finalized = false;
    let submitted = false;
    const chunks: number[] = [];
    let version = 1;
    const session = () => ({
      session_id: sessionId,
      plan_version_id: resourceId,
      status: submitted ? "submitted" : "in_progress",
      current_stage_id: submitted ? null : stageId,
      version: 3,
      demo: true,
      stages: [
        {
          stage_id: stageId,
          revision_id: resourceId,
          task_key: "video",
          format: "vcv",
          instruction: "Расскажите о решении",
          duration_seconds: 600,
        },
      ],
      progress: [
        {
          stage_id: stageId,
          status: submitted ? "submitted" : "active",
          version: 1,
          deadline: null,
        },
      ],
    });
    await page.route("**/api/privacy/**", (r) =>
      json(
        r,
        r.request().url().endsWith("/policies")
          ? { recording: "v1" }
          : [
              {
                consent_id: consentId,
                purpose: "recording",
                document_version: "v1",
                status: "active",
                version: 1,
              },
            ],
      ),
    );
    await page.route("**/api/proctoring/**", (r) => json(r, {}));
    await page.route("**/api/assessment/**", (r) => {
      if (r.request().url().endsWith("/submit")) {
        expect(finalized).toBe(true);
        expect(r.request().postDataJSON()).toEqual({
          workspace_id: resourceId,
          snapshot_id: snapshotId,
        });
        submitted = true;
      }
      if (r.request().url().endsWith("/evaluation"))
        return json(r, {
          session_id: sessionId,
          policy_id: null,
          status: "awaiting_evidence",
        });
      return json(r, session());
    });
    await page.route("**/api/media/**", async (r) => {
      const path = new URL(r.request().url()).pathname;
      if (path.endsWith("/admission")) {
        admission = true;
        expect(r.request().postDataJSON().recording_consent_id).toBe(consentId);
        return json(r, {});
      }
      if (path.endsWith("/recordings") && r.request().method() === "POST") {
        expect(admission).toBe(true);
        expect(r.request().postDataJSON().size).toBeGreaterThan(0);
        expect(r.request().postDataJSON().mime).toBe("video/webm");
      }
      if (path.includes("/chunks/")) {
        const body = r.request().postDataJSON();
        const { createHash } = await import("node:crypto");
        expect(
          createHash("sha256")
            .update(Buffer.from(body.data_base64, "base64"))
            .digest("hex"),
        ).toBe(body.digest);
        expect(r.request().headers()["if-match"]).toBe(`"${version}"`);
        chunks.push(Number(path.split("/").at(-1)));
        version++;
      }
      if (path.endsWith("/finalize")) {
        expect(chunks.length).toBeGreaterThan(0);
        finalized = true;
        version++;
      }
      return json(r, {
        recording_id: resourceId,
        snapshot_id: finalized ? snapshotId : null,
        received_chunks: chunks,
        version,
        status: finalized ? "finalized" : "uploading",
      });
    });
    await login(page, `/candidate/session/video?session=${sessionId}`);
    await page.getByRole("button", { name: "Открыть рабочую среду" }).click();
    await page
      .getByRole("button", { name: "Начать запись", exact: true })
      .click();
    await expect(page.getByText("Идёт запись", { exact: true })).toBeVisible();
    await expect
      .poll(() =>
        page.locator("video").evaluate((v: HTMLVideoElement) => v.videoWidth),
      )
      .toBeGreaterThan(0);
    await expect.poll(() => page.locator("video").evaluate((v: HTMLVideoElement) => v.currentTime)).toBeGreaterThan(1);
    await page
      .getByRole("button", { name: "Остановить запись", exact: true })
      .click();
    await expect(
      page.getByText("Запись готова. Просмотрите её перед отправкой.", {
        exact: true,
      }),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "Сохранить запись", exact: true })
      .click();
    await expect(
      page.getByText("Запись сохранена", { exact: true }),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "Отправить сохранённый ответ и продолжить" })
      .click();
    await expect(
      page.getByText("Материалы обрабатываются", { exact: true }),
    ).toBeVisible();
    expect(submitted).toBe(true);
  });
});
