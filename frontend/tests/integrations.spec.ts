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
  policies,
} from "./helpers/backend";
const needId = "88888888-8888-4888-8888-888888888888";
const snapshotId = "99999999-9999-4999-8999-999999999999";
const sessionId = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const stageId = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const workspaceId = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
const invitationId = "dddddddd-dddd-4ddd-8ddd-dddddddddddd";
const need = {
  need_id: needId,
  organization_id: orgId,
  specialization: "Frontend",
  confirmed_grade: "middle",
  required_skills: ["React"],
  status: "published",
  version: 1,
  created_by: subject,
};
const invitation = {
  invitation_id: invitationId,
  organization_id: orgId,
  candidate_id: subject,
  description: "Разработка интерфейсов",
  employer_contact: "hr@example.test",
  salary: {
    minimum: 180000,
    maximum: 250000,
    currency: "RUB",
    period: "month",
    tax_basis: "gross",
  },
  status: "sent",
  version: 1,
  expires_at: "2027-01-01T00:00:00Z",
};

test("работодатель: потребность, подбор, приглашение и правильная организация", async ({
  page,
}) => {
  await oauth(page);
  let needs: unknown[] = [];
  let sent = 0;
  await page.route("**/api/employer/v1/organizations", (r) =>
    json(r, [{ ...organization, verification_status: "verified" }]),
  );
  await page.route("**/api/hiring/v1/hiring-needs*", (r) => {
    if (r.request().method() === "POST") {
      expect(r.request().postDataJSON()).toMatchObject({
        organization_id: orgId,
        specialization: "Frontend",
        confirmed_grade: "middle",
        required_skills: ["React"],
        status: "published",
      });
      needs = [need];
      return json(r, need, 201);
    }
    return json(r, needs);
  });
  const result = {
    snapshot_id: snapshotId,
    mode: "production",
    next_cursor: null,
    matches: [
      {
        candidate_id: subject,
        display_name: "Кандидат из API",
        specialization: "Frontend",
        confirmed_grade: "middle",
        decision_id: needId,
        version: 1,
        explanation: "Подтверждены необходимые навыки",
        score: 90,
        declared_skills: ["React"],
        demo: true,
      },
    ],
  };
  await page.route("**/api/matching/**", (r) => {
    if (r.request().method() === "POST")
      expect(r.request().postDataJSON()).toEqual({
        organization_id: orgId,
        need_id: needId,
        mode: "production",
      });
    return json(r, result, r.request().method() === "POST" ? 201 : 200);
  });
  await page.route("**/api/hiring/v1/invitations*", (r) => {
    if (r.request().method() === "POST") {
      expect(r.request().postDataJSON()).toMatchObject({
        candidate_id: subject,
        organization_id: orgId,
        salary: invitation.salary,
      });
      sent++;
      return json(r, invitation, 201);
    }
    return json(r, []);
  });
  await login(page, "/employer/need");
  await page.getByLabel("Специализация", { exact: true }).fill("Frontend");
  await page
    .getByLabel("Минимальный подтверждённый грейд")
    .selectOption("middle");
  await page.getByLabel("Обязательные навыки через запятую").fill("React");
  await page.getByLabel("Статус потребности").selectOption("published");
  await page
    .getByRole("button", { name: "Сохранить потребность", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Frontend · middle", exact: true }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Перейти к подбору" }).click();
  await page.getByRole("button", { name: "Подобрать кандидатов" }).click();
  await page.getByRole("link", { name: "Пригласить кандидата" }).click();
  await expect(page.getByLabel("Кандидат", { exact: true })).toHaveValue(
    subject,
  );
  await page.getByLabel("Описание предложения").fill(invitation.description);
  await page
    .getByLabel("Контакт работодателя")
    .fill(invitation.employer_contact);
  await page.getByLabel("Зарплата от, ₽").fill("180000");
  await page.getByLabel("Зарплата до, ₽").fill("250000");
  await page
    .getByRole("button", { name: "Отправить приглашение", exact: true })
    .click();
  await expect(
    page.getByText("Приглашение отправлено сервером.", { exact: true }),
  ).toBeVisible();
  expect(sent).toBe(1);
  await page.screenshot({
    path: "design/previews/frontend-api-employer.png",
    fullPage: true,
  });
});

test("контакты работодателю не запрашиваются до принятия приглашения", async ({
  page,
}) => {
  await oauth(page);
  let contactCalls = 0;
  await page.route("**/api/employer/v1/organizations", (r) =>
    json(r, [organization]),
  );
  await page.route("**/api/hiring/**", (r) => {
    if (r.request().url().endsWith("/contacts")) {
      contactCalls++;
      return json(r, {}, 403);
    }
    return json(r, [invitation]);
  });
  await login(page, "/employer/invitation/new");
  await expect(
    page.getByText(invitation.description, { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Проверить доступ к контактам" }),
  ).toHaveCount(0);
  expect(contactCalls).toBe(0);
});

test("переписка: конфликт сохраняет текст, отправка требует актуальной версии", async ({
  page,
}) => {
  await oauth(page);
  let version = 2;
  let posts = 0;
  const messages: unknown[] = [];
  await page.route("**/api/notification/**", (r) => json(r, []));
  await page.route("**/api/hiring/v1/dialogs/**", (r) => {
    const path = new URL(r.request().url()).pathname;
    if (path.endsWith("/messages")) {
      if (r.request().method() === "GET") return json(r, messages);
      posts++;
      if (posts === 1) {
        version = 3;
        return json(r, { code: "conflict" }, 409);
      }
      expect(r.request().headers()["if-match"]).toBe('"3"');
      const message = {
        message_id: needId,
        dialog_id: invitationId,
        author_id: subject,
        sequence: 1,
        created_at: "2026-10-10T10:00:00Z",
        text: r.request().postDataJSON().text,
      };
      messages.push(message);
      version++;
      return json(r, message, 201);
    }
    return json(r, {
      dialog_id: invitationId,
      organization_id: orgId,
      candidate_id: subject,
      blocked: false,
      version,
      last_sequence: messages.length,
    });
  });
  await login(page, `/messages?dialog=${invitationId}`);
  await page
    .getByLabel("Сообщение", { exact: true })
    .fill("Текст для работодателя");
  await page
    .getByRole("button", { name: "Отправить сообщение", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText("Данные изменились");
  await expect(page.getByLabel("Сообщение", { exact: true })).toHaveValue(
    "Текст для работодателя",
  );
  await page
    .getByRole("button", { name: "Обновить данные", exact: true })
    .click();
  await expect(page.getByRole("alert")).toHaveCount(0);
  await page
    .getByRole("button", { name: "Отправить сообщение", exact: true })
    .click();
  await expect(
    page.getByText("Сообщение отправлено.", { exact: true }),
  ).toBeVisible();
  expect(posts).toBe(2);
});

test("оценка: создание, этап, сохранение снимка и отправка текущей версии", async ({
  page,
}) => {
  await oauth(page);
  let state = "preflight";
  let stageStatus = "pending";
  let version = 1;
  let submitted = false;
  let saved = 0;
  const stage = {
    stage_id: stageId,
    revision_id: needId,
    task_key: "code",
    format: "code",
    instruction: "Верните сумму двух чисел",
    duration_seconds: 600,
  };
  const session = () => ({
    session_id: sessionId,
    plan_version_id: needId,
    status: state,
    current_stage_id: state === "in_progress" ? stageId : null,
    version,
    demo: true,
    stages: [stage],
    progress: [
      {
        stage_id: stageId,
        status: stageStatus,
        version: 1,
        started_at: null,
        deadline: null,
        submitted_at: null,
        workspace_id: null,
        snapshot_id: null,
        snapshot_version: null,
        digest: null,
      },
    ],
  });
  await page.route("**/api/privacy/**", (r) =>
    json(
      r,
      r.request().url().endsWith("/policies")
        ? policies
        : [
            {
              consent_id: consentId,
              purpose: "assessment",
              document_version: "demo-v1",
              status: "active",
              version: 1,
            },
          ],
    ),
  );
  await page.route("**/api/assessment/**", (r) => {
    const path = new URL(r.request().url()).pathname;
    if (path.endsWith("/assessment-plans"))
      return json(r, [
        {
          plan_version_id: needId,
          name: "Тестовый план",
          specialization: "Python",
          grade: "junior",
          duration_seconds: 600,
          formats: ["code"],
          status: "published",
          version: 1,
          demo: true,
        },
      ]);
    if (
      path.endsWith("/assessment-sessions") &&
      r.request().method() === "POST"
    ) {
      expect(r.request().postDataJSON().assessment_consent_id).toBe(consentId);
      return json(r, session(), 201);
    }
    if (path.endsWith("/evaluation"))
      return json(r, {
        session_id: sessionId,
        policy_id: null,
        status: "awaiting_evidence",
      });
    if (r.request().method() === "POST") {
      expect(r.request().headers()["if-match"]).toBe(`"${version}"`);
      if (path.includes("/submit")) {
        expect(r.request().postDataJSON()).toEqual({
          workspace_id: workspaceId,
          snapshot_id: snapshotId,
        });
        state = "submitted";
        stageStatus = "submitted";
        submitted = true;
      } else if (path.includes("/stages/")) stageStatus = "active";
      else state = "in_progress";
      version++;
    }
    return json(r, session());
  });
  await page.route("**/api/proctoring/**", (r) => json(r, {}));
  await page.route("**/api/coding-workspace/**", (r) => {
    if (r.request().method() === "POST") saved++;
    return json(
      r,
      {
        workspace_id: workspaceId,
        snapshot_id: snapshotId,
        version: 1,
        digest: "digest",
        created_at: "2026-10-10T10:00:00Z",
        format: "code",
        files: [{ path: "main.py", content: "print(1 + 2)" }],
      },
      r.request().method() === "POST" ? 201 : 200,
    );
  });
  await login(page, "/candidate/assessment");
  await page
    .getByRole("button", { name: "Начать подготовку", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Начать сессию", exact: true })
    .click();
  await page.getByRole("button", { name: "Начать этап", exact: true }).click();
  await page.getByLabel("Файл main.py").fill("print(1 + 2)");
  await expect(
    page.getByRole("button", {
      name: "Отправить сохранённый ответ и продолжить",
    }),
  ).toHaveCount(0);
  await page
    .getByRole("button", { name: "Сохранить код", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Отправить сохранённый ответ и продолжить" })
    .click();
  await expect(
    page.getByText("Материалы обрабатываются", { exact: true }),
  ).toBeVisible();
  expect(saved).toBe(1);
  expect(submitted).toBe(true);
});

test("PDF загружается бинарно; ожидание обработки не считается готовым резюме", async ({
  page,
}) => {
  await oauth(page);
  let uploaded = false;
  await page.route("**/api/candidate/**", (r) => {
    const path = new URL(r.request().url()).pathname;
    if (path.endsWith("/me")) return json(r, profile);
    if (path.endsWith("/resume")) return json(r, {}, 404);
    if (r.request().method() === "POST") {
      expect(r.request().headers()["content-type"]).toBe("application/pdf");
      expect(r.request().postDataBuffer()?.toString()).toContain("%PDF-");
      expect(r.request().headers()["idempotency-key"]).toBeTruthy();
      uploaded = true;
      return json(
        r,
        {
          import_id: needId,
          status: "pending",
          digest: "x",
          size: 15,
          version: 1,
          attempts: 0,
          error: null,
          extraction: null,
          requires_confirmation: true,
          proposal: null,
        },
        201,
      );
    }
    if (path.includes(`/resume-imports/${needId}`))
      return json(r, {
        import_id: needId,
        status: "processing",
        digest: "x",
        size: 15,
        version: 1,
        attempts: 1,
        error: null,
        extraction: null,
        requires_confirmation: true,
        proposal: null,
      });
    return json(r, []);
  });
  await login(page);
  await page.getByRole("button", { name: "Резюме PDF", exact: true }).click();
  await page.getByLabel("PDF до 2 МБ").setInputFiles({
    name: "resume.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.from("%PDF-1.4 test"),
  });
  await page
    .getByRole("button", { name: "Загрузить PDF", exact: true })
    .click();
  await expect(page.getByText("Обрабатывается", { exact: true })).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Подтвердить данные резюме" }),
  ).toHaveCount(0);
  expect(uploaded).toBe(true);
});

test("вакансия: отклик только после предпросмотра и явного подтверждения", async ({
  page,
}) => {
  await oauth(page);
  let applied = 0;
  const vacancy = {
    ...invitation,
    vacancy_id: needId,
    title: "Frontend-разработчик",
    requirements: need,
    need_id: needId,
    status: "published",
    revision: 1,
  };
  await page.route("**/api/hiring/**", (r) => {
    const path = new URL(r.request().url()).pathname;
    if (path.endsWith("/application-preview"))
      return json(r, {
        vacancy,
        shared_fields: ["display_name", "confirmed_grade"],
        contacts_disclosed: false,
        disclosure_requires_invitation_acceptance: true,
      });
    if (path.endsWith("/applications") && r.request().method() === "POST") {
      expect(r.request().postDataJSON()).toEqual({ vacancy_version: 1 });
      applied++;
      return json(r, { application_id: snapshotId }, 201);
    }
    return json(r, path.endsWith("/vacancies") ? [vacancy] : []);
  });
  await login(page, "/vacancies");
  await page
    .getByRole("button", { name: "Просмотреть условия отклика" })
    .click();
  await expect(
    page.getByText("Контакты при отклике не раскрываются.", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Отправить отклик", exact: true }),
  ).toBeDisabled();
  await page.getByRole("checkbox", { name: "Подтверждаю отклик" }).check();
  await page
    .getByRole("button", { name: "Отправить отклик", exact: true })
    .click();
  await expect(
    page.getByText("Отклик отправлен.", { exact: true }),
  ).toBeVisible();
  expect(applied).toBe(1);
});

test("достижения: тестовый источник маркируется, импорт остаётся в очереди", async ({
  page,
}) => {
  await oauth(page);
  const source = {
    source_id: needId,
    key: "fsp",
    name: "ФСП тестовый источник",
    adapter: "demo-fsp",
    demo: true,
    enabled: true,
    version: 1,
    capabilities: ["sync"],
  };
  let connected = false;
  let syncs = 0;
  await page.route("**/api/privacy/**", (r) =>
    json(
      r,
      r.request().url().endsWith("/policies")
        ? { achievement_import: "demo-v1" }
        : [
            {
              consent_id: consentId,
              purpose: "achievement_import",
              document_version: "demo-v1",
              status: "active",
              version: 1,
            },
          ],
    ),
  );
  await page.route("**/api/achievements/**", (r) => {
    const path = new URL(r.request().url()).pathname;
    if (path.endsWith("/achievement-sources")) return json(r, [source]);
    if (
      path.endsWith("/achievement-connections") &&
      r.request().method() === "POST"
    ) {
      expect(r.request().postDataJSON()).toEqual({
        source_id: needId,
        consent_id: consentId,
      });
      connected = true;
      return json(r, { connection_id: snapshotId }, 201);
    }
    if (path.endsWith("/achievement-connections/me"))
      return json(
        r,
        connected
          ? [
              {
                connection_id: snapshotId,
                source_id: needId,
                candidate_id: subject,
                status: "active",
                external_account: subject,
                version: 1,
                last_synced_at: null,
                last_sync_status: null,
              },
            ]
          : [],
      );
    return json(r, []);
  });
  await page.route("**/api/integration/**", (r) => {
    if (r.request().method() === "POST") {
      syncs++;
      expect(r.request().postDataJSON()).toEqual({ connection_id: snapshotId });
    }
    return json(r, {
      job_id: workspaceId,
      kind: "sync",
      status: "pending",
      attempts: 0,
      version: 1,
      candidate_id: subject,
      connection_id: snapshotId,
      organization_id: null,
      external_id: null,
      external_status: null,
      status_sequence: 0,
      error_code: null,
    });
  });
  await login(page, "/candidate/achievements");
  await expect(
    page.getByText("ДЕМО · тестовая привязка и синтетические результаты", {
      exact: true,
    }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Подключить источник", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Импортировать достижения", exact: true })
    .click();
  await expect(page.getByText("В очереди", { exact: true })).toBeVisible();
  expect(syncs).toBe(1);
  await expect(page.getByText("Выполнено", { exact: true })).toHaveCount(0);
});

test("ATS: экспорт ждёт доставки, приёмник читает реальные данные, обратный статус отдельный", async ({
  page,
}) => {
  await oauth(page);
  let completed = false;
  let received = 0;
  let exports = 0;
  let status = "received";
  await page.route("**/api/hiring/**", (r) =>
    json(r, { ...invitation, status: "accepted", version: 2 }),
  );
  await page.route("**/api/integration/**", (r) => {
    if (r.request().method() === "POST") {
      expect(r.request().postDataJSON()).toEqual({
        candidate_id: subject,
        organization_id: orgId,
        invitation_id: invitationId,
        consent_id: consentId,
      });
      exports++;
    }
    return json(r, {
      job_id: workspaceId,
      kind: "ats",
      status: completed ? "completed" : "pending",
      attempts: completed ? 1 : 0,
      version: 1,
      candidate_id: subject,
      connection_id: null,
      organization_id: orgId,
      external_id: completed ? snapshotId : null,
      external_status: completed ? "received" : null,
      status_sequence: 0,
      error_code: null,
    });
  });
  await page.route("**/api/demo-ats/**", (r) => {
    if (r.request().method() === "POST") {
      expect(r.request().headers()["if-match"]).toBe('"1"');
      status = r.request().postDataJSON().status;
      return json(r, { status, version: 2 });
    }
    received++;
    return json(r, {
      external_id: snapshotId,
      version: 1,
      status,
      demo: true,
      profile: {
        display_name: "Полученный кандидат",
        specialization: "Frontend",
        confirmed_grade: "middle",
      },
      contacts: { email: "candidate@example.test", phone: null },
    });
  });
  await login(
    page,
    `/employer/integrations/ats?invitation=${invitationId}&consent=${consentId}`,
  );
  await expect(
    page.getByRole("button", { name: "Начать экспорт" }),
  ).toBeDisabled();
  await page
    .getByRole("checkbox", {
      name: "Подтверждаю передачу разрешённого профиля",
    })
    .check();
  await page.getByRole("button", { name: "Начать экспорт" }).click();
  await expect(
    page.getByRole("heading", { name: "В очереди", exact: true }),
  ).toBeVisible();
  expect(received).toBe(0);
  completed = true;
  await page
    .getByRole("button", { name: "Обновить доставку и обратный статус" })
    .click();
  await expect(
    page.getByText("Email: candidate@example.test", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Изменить статус в ATS" }).click();
  await expect(
    page.getByText(
      "Статус изменён в ATS. Обратная доставка проверяется отдельно.",
      { exact: true },
    ),
  ).toBeVisible();
  expect(exports).toBe(1);
});

test("доска: изменение сохраняется, этап получает только запечатанный снимок", async ({
  page,
}) => {
  await oauth(page);
  let sealed = false;
  let operations = 0;
  let submitted = false;
  const board = {
    board_id: workspaceId,
    session_id: sessionId,
    stage_id: stageId,
    version: 1,
    status: "editing",
    snapshot_id: null,
    state: [] as unknown[],
  };
  const session = () => ({
    session_id: sessionId,
    plan_version_id: needId,
    status: submitted ? "submitted" : "in_progress",
    current_stage_id: submitted ? null : stageId,
    version: 3,
    demo: true,
    stages: [
      {
        stage_id: stageId,
        revision_id: needId,
        task_key: "board",
        format: "whiteboard",
        instruction: "Нарисуйте схему",
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
  await page.route("**/api/assessment/**", (r) => {
    if (r.request().url().endsWith("/submit")) {
      expect(sealed).toBe(true);
      expect(r.request().postDataJSON()).toEqual({
        workspace_id: workspaceId,
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
  await page.route("**/api/proctoring/**", (r) => json(r, {}));
  await page.route("**/api/whiteboard/**", (r) => {
    if (r.request().url().endsWith("/operations")) {
      operations++;
      expect(r.request().headers()["if-match"]).toBe('"1"');
      board.state = [r.request().postDataJSON().shape];
      board.version++;
    }
    if (r.request().url().endsWith("/seal")) {
      sealed = true;
      return json(r, {
        ...board,
        status: "sealed",
        snapshot_id: snapshotId,
        version: 3,
      });
    }
    return json(r, board);
  });
  await login(page, `/candidate/session/board?session=${sessionId}`);
  await page.getByRole("button", { name: "Открыть рабочую среду" }).click();
  await page.getByLabel("Текст на доске").fill("Архитектура");
  await page
    .getByRole("button", { name: "Добавить текст", exact: true })
    .click();
  await expect(
    page.getByText("Изменения сохранены", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Завершить доску" }).click();
  await page
    .getByRole("button", { name: "Отправить сохранённый ответ и продолжить" })
    .click();
  await expect(
    page.getByText("Материалы обрабатываются", { exact: true }),
  ).toBeVisible();
  expect(operations).toBe(1);
});

test("кандидат не видит административную очередь без роли", async ({
  page,
}) => {
  await oauth(page);
  let calls = 0;
  await page.route(
    (url) => url.pathname.startsWith("/api/"),
    (r) => {
      calls++;
      return json(r, []);
    },
  );
  await login(page, "/admin");
  await expect(
    page.getByText("У вашей учётной записи нет роли проверяющего.", {
      exact: false,
    }),
  ).toBeVisible();
  expect(calls).toBe(0);
});
