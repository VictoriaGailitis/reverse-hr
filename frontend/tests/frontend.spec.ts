import { test, expect } from "@playwright/test";
import screens from "../src/design/screens.json" with { type: "json" };

for (const screen of screens) {
  test(`экран ${screen.key}: маршрут, ресурсы, границы`, async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.setViewportSize(
      screen.mobile
        ? { width: 390, height: 844 }
        : { width: 1440, height: 1000 },
    );
    await page.goto(screen.route);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await page.evaluate(() => document.fonts.ready);
    const resources = await page.evaluate(() => ({
      overflow: document.documentElement.scrollWidth > innerWidth,
      broken: Array.from(document.images)
        .filter((image) => !image.complete || image.naturalWidth === 0)
        .map((image) => image.src),
      font: getComputedStyle(document.querySelector("h1")!).fontFamily,
    }));
    expect(resources.overflow).toBe(false);
    expect(resources.broken).toEqual([]);
    expect(resources.font).toContain("JetBrains Mono");
    expect(errors).toEqual([]);
    await page.screenshot({
      path: `test-results/screens/${screen.key}.png`,
      fullPage: true,
    });
  });
}

test("регистрация требует пароль и явное согласие", async ({ page }) => {
  await page.goto("/auth/register");
  await page
    .getByRole("button", { name: "Зарегистрироваться", exact: true })
    .click();
  await expect(page).toHaveURL(/register/);
  await page.getByLabel("Пароль", { exact: true }).fill("demopassword123");
  await page
    .getByRole("checkbox", { name: "Принимаю условия использования" })
    .check();
  await page
    .getByRole("button", { name: "Зарегистрироваться", exact: true })
    .click();
  await expect(page).toHaveURL(/\/candidate$/);
});

test("контакты закрыты до принятия, подтверждение и отзыв", async ({
  page,
}) => {
  await page.goto("/employer/integrations/ats");
  await expect(
    page.getByText("Контакты закрыты", { exact: false }),
  ).toBeVisible();
  await expect(
    page.getByText("Контакты: синтетические данные", { exact: false }),
  ).toHaveCount(0);
  await page.goto("/candidate/invitations/accept");
  await page
    .getByRole("button", { name: "Принять и разрешить", exact: true })
    .click();
  await expect(page).toHaveURL(/pending/);
  await expect(
    page.getByText("Демо: раскрытие подтверждено.", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Показать демоподтверждение", exact: true })
    .click();
  await expect(
    page.getByText("Демо: доставка подтверждена", { exact: true }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Сменить роль", exact: true }).click();
  await page.getByRole("link", { name: "Приватность", exact: true }).click();
  await page
    .getByRole("button", { name: "Отозвать доступ", exact: true })
    .click();
  await expect(
    page.getByText("Доступ отозван", { exact: false }),
  ).toBeVisible();
});

test("зарплатный диапазон валидируется до отправки", async ({ page }) => {
  await page.goto("/employer/invitation/new");
  await page.getByLabel("Зарплата от, ₽").fill("300000");
  await page.getByLabel("Зарплата до, ₽").fill("200000");
  await page
    .getByRole("button", { name: "Отправить демоприглашение", exact: true })
    .click();
  await expect(page.getByRole("status")).toContainText("корректный диапазон");
  await expect(page).toHaveURL(/invitation\/new/);
  await page.getByLabel("Зарплата до, ₽").fill("400000");
  await page
    .getByRole("button", { name: "Отправить демоприглашение", exact: true })
    .click();
  await expect(page).toHaveURL(/candidate\/invitations$/);
});

test("код сохраняется после перезагрузки и запуск привязан к версии", async ({
  page,
}) => {
  await page.goto("/candidate/session/code");
  const code = page.getByRole("textbox", {
    name: "Код solution.ts",
    exact: true,
  });
  await code.fill("const value = 42;");
  await expect(
    page.getByText("Версия 13 сохранена локально", { exact: false }),
  ).toBeVisible();
  await page.reload();
  await expect(code).toHaveValue("const value = 42;");
  await page
    .getByRole("button", { name: "Запустить v13", exact: true })
    .click();
  await expect(page).toHaveURL(/#queued/);
  await expect(page).toHaveURL(/\/code$/);
  await expect(
    page.getByText("Демопроверка версии 13 завершена.", { exact: false }),
  ).toBeVisible();
  await code.fill("const changed = 43;");
  await expect(
    page.getByText("проверка текущей версии ещё не выполнялась", {
      exact: false,
    }),
  ).toBeVisible();
});

test("фильтр подборки и отправка сообщения", async ({ page }) => {
  await page.goto("/employer/search");
  await page.getByRole("searchbox").fill("1042");
  await expect(
    page.getByRole("heading", { name: "Кандидат №1042" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Кандидат №1087" }),
  ).toHaveCount(0);
  await page.getByRole("searchbox").fill("неизвестный навык");
  await expect(
    page.getByText("Ничего не найдено.", { exact: false }),
  ).toBeVisible();
  await page.goto("/messages");
  await page.getByLabel("Короткое сообщение").fill("Когда удобно встретиться?");
  await page
    .getByRole("button", { name: "Отправить сообщение", exact: true })
    .click();
  await expect(
    page.getByText("Когда удобно встретиться?", { exact: true }),
  ).toBeVisible();
});

test("доска: блок, клавиатура, сохранение и отмена", async ({ page }) => {
  await page.goto("/candidate/session/board");
  await page.getByRole("button", { name: "+ Блок", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Блок Новый блок", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Блок UI", exact: true }).focus();
  await page.keyboard.press("ArrowDown");
  await page.reload();
  await expect(
    page.getByRole("button", { name: "Блок Новый блок", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Блок Новый блок", exact: true })
    .click();
  await page.getByRole("button", { name: "Удалить", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Блок Новый блок", exact: true }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "Отменить", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Блок Новый блок", exact: true }),
  ).toBeVisible();
});

test("оборудование: согласие, запись, остановка и отправка", async ({
  page,
}) => {
  await page.goto("/candidate/session/setup");
  await page
    .getByRole("button", { name: "Проверить устройства", exact: true })
    .click();
  await expect(page).toHaveURL(/#ready/);
  await page
    .getByRole("checkbox", {
      name: "Согласна / согласен на запись",
      exact: false,
    })
    .check();
  await page
    .getByRole("button", { name: "Согласиться и начать", exact: true })
    .click();
  await expect(page).toHaveURL(/\/code$/);
  await page
    .getByRole("button", { name: "Отправить код", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Начать запись", exact: true })
    .click();
  await expect(page).toHaveURL(/#recording/);
  await page
    .getByRole("button", { name: "Остановить запись", exact: true })
    .click();
  await expect(page).toHaveURL(/#preview/);
  await page
    .getByRole("button", { name: "Отправить ответ", exact: true })
    .click();
  await expect(page).toHaveURL(/\/board$/);
});

test("все десктопные экраны адаптируются без горизонтального переполнения", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  for (const screen of screens.filter((screen) => !screen.mobile)) {
    await page.goto(screen.route);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
      screen.key,
    ).toBe(true);
  }
});

test("неизвестный маршрут даёт понятный выход", async ({ page }) => {
  await page.goto("/missing");
  await expect(
    page.getByRole("heading", { name: "Экран не найден" }),
  ).toBeVisible();
  await page.getByRole("link", { name: "На главную", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Работа находит вас" }),
  ).toBeVisible();
});

test("пустой код сохраняется, переход к содержимому не меняет маршрут", async ({
  page,
}) => {
  await page.goto("/candidate/session/code");
  const code = page.getByRole("textbox", {
    name: "Код solution.ts",
    exact: true,
  });
  await code.fill("");
  await expect(
    page.getByText("Версия 13 сохранена локально", { exact: false }),
  ).toBeVisible();
  await page.reload();
  await expect(code).toHaveValue("");
  await page.keyboard.press("Tab");
  await page
    .getByRole("link", { name: "К содержимому", exact: true })
    .press("Enter");
  await expect(page).toHaveURL(/\/code$/);
  await expect(page.locator("main")).toBeFocused();
});
