import { test, expect } from "@playwright/test";
import {
  oauth,
  login,
  json,
  subject,
  orgId,
  consentId,
  grantId,
  profile,
  organization,
  policies,
} from "./helpers/backend";

test("PKCE-вход, чтение и сохранение профиля по актуальной версии", async ({
  page,
}) => {
  await oauth(page);
  let saved = profile;
  let puts = 0;
  await page.route("**/api/candidate/v1/candidates/me", async (route) => {
    expect(route.request().headers().authorization).toMatch(/^Bearer /);
    if (route.request().method() === "GET") return json(route, saved);
    expect(route.request().method()).toBe("PUT");
    expect(route.request().headers()["if-match"]).toBe('"3"');
    expect(route.request().headers()["idempotency-key"]).toMatch(
      /^[a-f0-9-]{36}$/,
    );
    expect(route.request().postDataJSON()).toEqual({
      display_name: "Новый тестовый кандидат",
      specialization: "Frontend",
      declared_grade: "senior",
    });
    puts++;
    saved = { ...saved, ...route.request().postDataJSON(), version: 4 };
    return json(route, saved);
  });
  await login(page);
  await expect(page.getByLabel("Имя для отображения")).toHaveValue(
    profile.display_name,
  );
  await expect(
    page.getByText("Подтверждённый уровень: ещё не подтверждён"),
  ).toBeVisible();
  await page.getByLabel("Имя для отображения").fill("Новый тестовый кандидат");
  await page.getByLabel("Заявленный уровень").selectOption("senior");
  await page
    .getByRole("button", { name: "Сохранить профиль", exact: true })
    .click();
  await expect(page.getByRole("status")).toContainText("версия 4");
  expect(puts).toBe(1);
  await page.screenshot({
    path: "design/previews/frontend-api-profile.png",
    fullPage: true,
  });
  const storage = await page.evaluate(() =>
    Object.entries(localStorage).concat(Object.entries(sessionStorage)),
  );
  expect(
    storage.some(([, value]) => value.includes("synthetic-signature")),
  ).toBe(false);
  await expect(
    page.getByRole("link", { name: "Приглашения · 2", exact: true }),
  ).toHaveCount(0);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "design/previews/frontend-api-profile-mobile.png",
    fullPage: true,
  });
});

test("404 профиля открывает создание через POST, без фиктивных полей", async ({
  page,
}) => {
  await oauth(page);
  await page.route("**/api/candidate/v1/candidates/me", async (route) => {
    if (route.request().method() === "GET")
      return json(route, { code: "not_found" }, 404);
    expect(route.request().method()).toBe("POST");
    expect(route.request().headers()["if-match"]).toBeUndefined();
    expect(route.request().postDataJSON()).toEqual({
      display_name: "Новый",
      specialization: "SQL",
      declared_grade: "junior",
    });
    return json(
      route,
      { ...profile, ...route.request().postDataJSON(), version: 1 },
      201,
    );
  });
  await login(page);
  await expect(page.getByLabel("Имя для отображения")).toBeEmpty();
  await page.getByLabel("Имя для отображения").fill("Новый");
  await page.getByLabel("Специализация", { exact: true }).fill("SQL");
  await page
    .getByRole("button", { name: "Сохранить профиль", exact: true })
    .click();
  await expect(page.getByRole("status")).toContainText("версия 1");
});

test("409 сохраняет черновик, повтор требует свежей версии", async ({
  page,
}) => {
  await oauth(page);
  let conflict = false;
  await page.route("**/api/candidate/v1/candidates/me", async (route) => {
    if (route.request().method() === "GET")
      return json(route, { ...profile, version: conflict ? 5 : 3 });
    if (!conflict) {
      conflict = true;
      return json(route, { code: "version_conflict" }, 409);
    }
    expect(route.request().headers()["if-match"]).toBe('"5"');
    return json(route, {
      ...profile,
      ...route.request().postDataJSON(),
      version: 6,
    });
  });
  await login(page);
  await page.getByLabel("Имя для отображения").fill("Мой черновик");
  await page
    .getByRole("button", { name: "Сохранить профиль", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText("Данные изменились");
  await expect(page.getByLabel("Имя для отображения")).toHaveValue(
    "Мой черновик",
  );
  await page
    .getByRole("button", { name: "Обновить версию, сохранив правки" })
    .click();
  await expect(page.getByRole("status")).toContainText("Ваши правки сохранены");
  await page
    .getByRole("button", { name: "Сохранить профиль", exact: true })
    .click();
  await expect(page.getByRole("status")).toContainText("версия 6");
});

test("401 требует повторного входа и сохраняет правки в открытой форме", async ({
  page,
}) => {
  await oauth(page);
  await page.route("**/api/candidate/v1/candidates/me", async (route) =>
    route.request().method() === "GET"
      ? json(route, profile)
      : json(route, { code: "unauthorized" }, 401),
  );
  await login(page);
  await page.getByLabel("Имя для отображения").fill("Несохранённая правка");
  await page
    .getByRole("button", { name: "Сохранить профиль", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Войти через Keycloak" }),
  ).toBeVisible();
  await expect(page.getByLabel("Имя для отображения")).toHaveValue(
    "Несохранённая правка",
  );
  await expect(
    page.getByRole("button", { name: "Сохранить профиль", exact: true }),
  ).toBeDisabled();
});

test("ошибка чтения API остаётся ошибкой, синтетический профиль не отображается", async ({
  page,
}) => {
  await oauth(page);
  await page.route("**/api/candidate/v1/candidates/me", (route) =>
    json(route, { code: "dependency_unavailable" }, 503),
  );
  await login(page);
  await expect(page.getByRole("alert")).toContainText(
    "Сервис временно недоступен",
  );
  await expect(page.getByLabel("Имя для отображения")).toHaveCount(0);
  await expect(page.getByText("Кандидат №1042", { exact: true })).toHaveCount(
    0,
  );
});

test("nonce проверяется адаптером, неуспешный вход не открывает API", async ({
  page,
}) => {
  await oauth(page, true);
  let calls = 0;
  await page.route(
    (url) => url.pathname.startsWith("/api/"),
    async (route) => {
      calls++;
      await json(route, profile);
    },
  );
  await page.goto("/candidate/profile");
  await page.getByRole("button", { name: "Войти через Keycloak" }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Не удалось подключиться",
  );
  expect(calls).toBe(0);
});

test("согласие явно подтверждается, отзыв и удаление ждут ответа сервера", async ({
  page,
}) => {
  await oauth(page);
  let consents: Record<string, unknown>[] = [];
  let grant = {
    grant_id: grantId,
    invitation_id: "55555555-5555-4555-8555-555555555555",
    candidate_id: subject,
    organization_id: orgId,
    consent_id: consentId,
    status: "active",
    version: 2,
    expires_at: "2027-01-01T00:00:00Z",
  };
  let deleted = false;
  const deletion = {
    request_id: "66666666-6666-4666-8666-666666666666",
    candidate_id: subject,
    status: "in_progress",
    requested_at: "2026-10-07T00:00:00Z",
    completed_at: null,
    services: { candidate: "restricted", employer: "pending" },
  };
  await page.route("**/api/privacy/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path.endsWith("/deletion-requests/me"))
      return deleted
        ? json(route, deletion)
        : json(route, { code: "not_found" }, 404);
    if (path.endsWith("/deletion-requests")) {
      expect(request.headers()["idempotency-key"]).toBeTruthy();
      deleted = true;
      return json(route, deletion, 202);
    }
    if (deleted) return json(route, { code: "processing_restricted" }, 409);
    if (path.endsWith("/policies")) return json(route, policies);
    if (path.endsWith("/consents") && request.method() === "GET")
      return json(route, consents);
    if (path.endsWith("/consents")) {
      expect(request.postDataJSON()).toEqual({
        purpose: "assessment",
        document_version: "demo-v1",
      });
      const consent = {
        ...request.postDataJSON(),
        consent_id: consentId,
        status: "active",
        version: 1,
      };
      consents = [consent];
      return json(route, consent, 201);
    }
    if (path.endsWith(`/consents/${consentId}/revoke`)) {
      expect(request.headers()["if-match"]).toBe('"1"');
      consents = [{ ...consents[0], status: "revoked", version: 2 }];
      return json(route, consents[0]);
    }
    if (path.endsWith(`/contact-grants/${grantId}/revoke`)) {
      expect(request.headers()["if-match"]).toBe('"2"');
      grant = { ...grant, status: "revoked", version: 3 };
      return json(route, grant);
    }
    if (path.endsWith("/contact-grants")) return json(route, [grant]);
    return json(route, {}, 404);
  });
  await login(page, "/candidate/privacy");
  await expect(
    page.getByRole("button", {
      name: "Разрешить: Оценка навыков",
      exact: true,
    }),
  ).toBeDisabled();
  await page
    .getByRole("checkbox", {
      name: "Разрешаю: оценка навыков · demo-v1",
      exact: true,
    })
    .check();
  await page
    .getByRole("button", { name: "Разрешить: Оценка навыков", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Отозвать: Оценка навыков", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Отозвать: Оценка навыков", exact: true })
    .click();
  await expect(
    page.getByRole("button", {
      name: "Разрешить: Оценка навыков",
      exact: true,
    }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Отозвать доступ", exact: true })
    .click();
  await expect(page.getByText("Доступ отозван", { exact: true })).toBeVisible();
  await page
    .getByRole("checkbox", { name: "Подтверждаю запрос удаления моих данных" })
    .check();
  await page
    .getByRole("button", { name: "Запросить удаление", exact: true })
    .click();
  await expect(
    page.getByText("Удаление выполняется", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Удаление подтверждено сервером", { exact: true }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "Обновить статус удаления" }).click();
  await expect(
    page.getByText("Удаление выполняется", { exact: true }),
  ).toBeVisible();
});

test("повтор запроса согласия после 503 сохраняет ключ идемпотентности", async ({
  page,
}) => {
  await oauth(page);
  const keys: string[] = [];
  await page.route("**/api/privacy/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/policies")) return json(route, policies);
    if (path.endsWith("/deletion-requests/me")) return json(route, {}, 404);
    if (path.endsWith("/consents") && route.request().method() === "POST") {
      keys.push(route.request().headers()["idempotency-key"]);
      if (keys.length === 1) return json(route, { code: "unavailable" }, 503);
      return json(
        route,
        {
          ...route.request().postDataJSON(),
          consent_id: consentId,
          status: "active",
          version: 1,
        },
        201,
      );
    }
    return json(route, []);
  });
  await login(page, "/candidate/privacy");
  await page
    .getByRole("checkbox", {
      name: "Разрешаю: оценка навыков · demo-v1",
      exact: true,
    })
    .check();
  await page
    .getByRole("button", { name: "Разрешить: Оценка навыков", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText(
    "Сервис временно недоступен",
  );
  await page
    .getByRole("button", { name: "Разрешить: Оценка навыков", exact: true })
    .click();
  await expect(
    page.getByText("Согласие подтверждено сервером.", { exact: true }),
  ).toBeVisible();
  expect(keys).toHaveLength(2);
  expect(keys[1]).toBe(keys[0]);
});

test("организация создаётся через API и не получает выдуманную верификацию", async ({
  page,
}) => {
  await oauth(page);
  let organizations: unknown[] = [];
  await page.route("**/api/employer/**", async (route) => {
    if (route.request().url().endsWith("/members"))
      return json(route, [
        {
          membership_id: "77777777-7777-4777-8777-777777777777",
          organization_id: orgId,
          subject,
          role: "owner",
          status: "active",
          version: 1,
        },
      ]);
    if (route.request().method() === "POST") {
      expect(route.request().postDataJSON()).toEqual({
        name: "Тестовая организация",
      });
      organizations = [organization];
      return json(route, organization, 201);
    }
    return json(route, organizations);
  });
  await login(page, "/employer");
  await page.getByLabel("Название организации").fill("Тестовая организация");
  await page
    .getByRole("button", { name: "Создать организацию", exact: true })
    .click();
  await expect(
    page.getByText("Верификация: ожидает проверки", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Сотрудники", exact: true }),
  ).toBeVisible();
});

test("неподключённые API-экраны не показывают синтетические контакты и успех ATS", async ({
  page,
}) => {
  await oauth(page);
  await login(page, "/ui/states");
  await expect(
    page.getByText("В первом этапе подключены", { exact: false }),
  ).toBeVisible();
  await expect(
    page.getByText("Контакты: синтетические данные", { exact: false }),
  ).toHaveCount(0);
  await expect(
    page.getByText("Демо: доставка подтверждена", { exact: true }),
  ).toHaveCount(0);
});

const invitationId = "55555555-5555-4555-8555-555555555555";
const invitation = {
  invitation_id: invitationId,
  organization_id: orgId,
  candidate_id: subject,
  description: "Разработка интерфейсов команды",
  employer_contact: "hr@example.test",
  salary: {
    minimum: 180000,
    maximum: 250000,
    currency: "RUB",
    period: "month",
    tax_basis: "gross",
  },
  status: "sent",
  version: 3,
  expires_at: "2027-01-01T00:00:00Z",
};
const activeDisclosure = {
  consent_id: consentId,
  purpose: "contact_disclosure",
  document_version: "demo-v1",
  status: "active",
  version: 1,
};
const invitationPath = `/candidate/invitations?invitation=${invitationId}`;

async function invitationPrivacy(
  page: Page,
  consents: unknown[] = [activeDisclosure],
) {
  await page.route("**/api/privacy/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/policies")) return json(route, policies);
    if (path.endsWith("/consents")) return json(route, consents);
    return json(route, []);
  });
}

test("приглашения: данные API, курсор следующей страницы и пустая выдача", async ({
  page,
}) => {
  await oauth(page);
  await page.route("**/api/hiring/v1/invitations*", async (route) => {
    const url = new URL(route.request().url());
    expect(url.searchParams.has("organization_id")).toBe(false);
    if (url.searchParams.has("after")) {
      expect(url.searchParams.get("after")).toBe(invitationId);
      return json(route, []);
    }
    return json(route, [invitation]);
  });
  await login(page, "/candidate/invitations");
  await expect(
    page.getByText(invitation.description, { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("до вычета налогов", { exact: false }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Следующая страница" }).click();
  await expect(
    page.getByText("На этой странице приглашений нет.", { exact: true }),
  ).toBeVisible();
  await page.getByRole("link", { name: "К началу списка" }).click();
  await expect(
    page.getByText(invitation.description, { exact: true }),
  ).toBeVisible();
});

test("приглашения: явное принятие, идемпотентный повтор и отдельное подтверждение доступа", async ({
  page,
}) => {
  await oauth(page);
  await invitationPrivacy(page);
  const keys: string[] = [];
  let grantVisible = false;
  await page.route("**/api/privacy/v1/contact-grants", (route) =>
    json(
      route,
      grantVisible
        ? [
            {
              grant_id: grantId,
              invitation_id: invitationId,
              candidate_id: subject,
              organization_id: orgId,
              consent_id: consentId,
              status: "active",
              version: 1,
              expires_at: "2027-01-01T00:00:00Z",
            },
          ]
        : [],
    ),
  );
  await page.route("**/api/hiring/**", async (route) => {
    if (route.request().method() === "GET") return json(route, invitation);
    expect(route.request().url()).toContain("/accept");
    expect(route.request().headers()["if-match"]).toBe('"3"');
    expect(route.request().postDataJSON()).toEqual({
      disclosure_consent_id: consentId,
    });
    keys.push(route.request().headers()["idempotency-key"]);
    if (keys.length === 1) return json(route, { code: "unavailable" }, 503);
    return json(route, { ...invitation, status: "accepted", version: 4 });
  });
  await login(page, invitationPath);
  const accept = page.getByRole("button", {
    name: "Принять приглашение",
    exact: true,
  });
  await expect(accept).toBeDisabled();
  expect(keys).toHaveLength(0);
  await page.getByRole("checkbox", { name: "Принимаю приглашение" }).check();
  await accept.click();
  await expect(page.getByRole("alert")).toContainText(
    "Сервис временно недоступен",
  );
  await accept.click();
  await expect(
    page.getByText(
      "Приглашение принято. Разрешение на доступ к контактам пока не подтверждено.",
      { exact: true },
    ),
  ).toBeVisible();
  expect(keys).toHaveLength(2);
  expect(keys[1]).toBe(keys[0]);
  await expect(
    page.getByText("Разрешение на доступ к контактам подтверждено сервером.", {
      exact: true,
    }),
  ).toHaveCount(0);
  grantVisible = true;
  await page.getByRole("button", { name: "Проверить доступ" }).click();
  await expect(
    page.getByText("Разрешение на доступ к контактам подтверждено сервером.", {
      exact: true,
    }),
  ).toBeVisible();
  await page.screenshot({
    path: "design/previews/frontend-api-invitation.png",
    fullPage: true,
  });
});

test("приглашения: старое или отозванное согласие не разрешает принятие", async ({
  page,
}) => {
  await oauth(page);
  await invitationPrivacy(page, [
    { ...activeDisclosure, status: "revoked" },
    { ...activeDisclosure, consent_id: grantId, document_version: "old-v1" },
  ]);
  let commands = 0;
  await page.route("**/api/hiring/**", (route) => {
    if (route.request().method() !== "GET") commands++;
    return json(route, invitation);
  });
  await login(page, invitationPath);
  await expect(
    page.getByRole("button", { name: "Принять приглашение", exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByRole("link", { name: "Управлять согласиями" }),
  ).toBeVisible();
  expect(commands).toBe(0);
});

test("приглашения: конфликт отказа требует обновления, затем используется свежая версия", async ({
  page,
}) => {
  await oauth(page);
  await invitationPrivacy(page);
  let commands = 0;
  await page.route("**/api/hiring/**", (route) => {
    if (route.request().method() === "GET")
      return json(route, { ...invitation, version: commands ? 5 : 3 });
    expect(route.request().url()).toContain("/decline");
    commands++;
    if (commands === 1) return json(route, { code: "version_conflict" }, 409);
    expect(route.request().headers()["if-match"]).toBe('"5"');
    return json(route, { ...invitation, status: "declined", version: 6 });
  });
  await login(page, invitationPath);
  await page.getByRole("checkbox", { name: "Подтверждаю отказ" }).check();
  await page
    .getByRole("button", { name: "Отклонить приглашение", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText("Данные изменились");
  await expect(
    page.getByRole("button", { name: "Отклонить приглашение", exact: true }),
  ).toBeDisabled();
  expect(commands).toBe(1);
  await page
    .getByRole("button", { name: "Обновить с сервера", exact: true })
    .click();
  await expect(
    page.getByRole("checkbox", { name: "Подтверждаю отказ" }),
  ).not.toBeChecked();
  await page.getByRole("checkbox", { name: "Подтверждаю отказ" }).check();
  await page
    .getByRole("button", { name: "Отклонить приглашение", exact: true })
    .click();
  await expect(
    page.getByText("Ответ сервера: отклонено.", { exact: true }),
  ).toBeVisible();
});

test("приглашения: отозванный grant не показывается как выданный доступ", async ({
  page,
}) => {
  await oauth(page);
  await page.route("**/api/hiring/**", (route) =>
    json(route, { ...invitation, status: "accepted", version: 4 }),
  );
  await page.route("**/api/privacy/v1/contact-grants", (route) =>
    json(route, [
      {
        grant_id: grantId,
        invitation_id: invitationId,
        candidate_id: subject,
        organization_id: orgId,
        consent_id: consentId,
        status: "revoked",
        version: 2,
        expires_at: "2027-01-01T00:00:00Z",
      },
    ]),
  );
  await login(page, invitationPath);
  await expect(
    page.getByText("Доступ к контактам отозван.", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Принять приглашение", exact: true }),
  ).toHaveCount(0);
});

test("приглашения: 503 выдачи показывает ошибку, а не пустой список или демо", async ({
  page,
}) => {
  await oauth(page);
  await page.route("**/api/hiring/**", (route) =>
    json(route, { code: "unavailable" }, 503),
  );
  await login(page, "/candidate/invitations");
  await expect(page.getByRole("alert")).toContainText(
    "Сервис временно недоступен",
  );
  await expect(
    page.getByText("Приглашений пока нет.", { exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("link", { name: "Посмотреть приглашение" }),
  ).toHaveCount(0);
});
