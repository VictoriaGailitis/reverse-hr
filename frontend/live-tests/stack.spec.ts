import { test, expect, type Page } from '@playwright/test';
import { readFileSync } from 'node:fs';

// Opt in with a private JSON file containing synthetic candidate/employer accounts.
// These tests write real data to the configured local stack; no network interception.
test.skip(!process.env.HR_LIVE_ACCOUNTS_FILE, 'Synthetic live accounts not configured');

async function login(page: Page, role: 'candidate' | 'employer', path: string) {
  const accounts = JSON.parse(readFileSync(process.env.HR_LIVE_ACCOUNTS_FILE!, 'utf8'));
  await page.goto(path);
  await page.getByRole('button', { name: 'Войти через Keycloak', exact: true }).click();
  await page.locator('#username').fill(accounts[role].username);
  await page.locator('#password').fill(accounts[role].password);
  await page.locator('#kc-login').click();
  await expect(page).toHaveURL(new RegExp(path + '$'));
}

test('candidate: profile persistence, contacts, preferences and explicit consents', async ({ page }) => {
  await login(page, 'candidate', '/candidate/profile');
  const name = 'Synthetic live candidate ' + Date.now();
  await page.getByLabel('Имя для отображения', { exact: true }).fill(name);
  await page.getByLabel('Специализация', { exact: true }).fill('backend');
  await page.getByRole('button', { name: 'Сохранить профиль', exact: true }).click();
  await expect(page.getByText(/Профиль сохранён на сервере/)).toBeVisible();
  // This realm deliberately requires password authentication on a fresh page load.
  await login(page, 'candidate', '/candidate/profile');
  await expect(page.getByLabel('Имя для отображения', { exact: true })).toHaveValue(name);

  await page.getByRole('button', { name: 'Контакты и публикация', exact: true }).click();
  await page.getByLabel('Email для связи', { exact: true }).fill('synthetic@reverse-hr.invalid');
  await page.getByRole('button', { name: 'Сохранить контакты', exact: true }).click();
  await expect(page.getByText('Контакты сохранены.', { exact: true })).toBeVisible();

  await page.getByRole('button', { name: 'Пожелания к работе', exact: true }).click();
  await page.getByLabel('Желаемая зарплата от, ₽ в месяц', { exact: true }).fill('100000');
  await page.getByLabel('Желаемая зарплата до, ₽ в месяц', { exact: true }).fill('180000');
  await page.getByLabel('Удалённо', { exact: true }).check();
  await page.getByLabel('Подтверждаю актуальность пожеланий', { exact: true }).check();
  const saved = page.waitForResponse(r => r.url().endsWith('/v1/candidates/me/preferences') && r.request().method() === 'PUT');
  await page.getByRole('button', { name: 'Сохранить пожелания', exact: true }).click();
  expect((await saved).status()).toBe(200);
  await expect(page.getByLabel('Желаемая зарплата от, ₽ в месяц', { exact: true })).toHaveValue('100000');

  await page.getByRole('link', { name: 'Согласия и приватность', exact: true }).click();
  for (const title of ['Публикация профиля', 'Оценка навыков', 'Импорт достижений']) {
    await expect(page.getByRole('heading', { name: 'Согласия', exact: true })).toBeVisible();
    const revoke = page.getByRole('button', { name: 'Отозвать: ' + title, exact: true });
    if (await revoke.count()) {
      await revoke.click();
      await expect(page.getByRole('button', { name: 'Разрешить: ' + title, exact: true })).toBeVisible();
    }
    await page.getByLabel('Разрешаю: ' + title.toLowerCase(), { exact: false }).check();
    await page.getByRole('button', { name: 'Разрешить: ' + title, exact: true }).click();
    await expect(revoke).toBeVisible();
  }
});

test('employer: create organization and read owner membership', async ({ page }) => {
  await login(page, 'employer', '/employer');
  const name = 'Synthetic live company ' + Date.now();
  await page.getByLabel('Название организации', { exact: true }).fill(name);
  await page.getByRole('button', { name: 'Создать организацию', exact: true }).click();
  await expect(page.getByText('Организация создана на сервере. Статус верификации проверяется отдельно.', { exact: true })).toBeVisible();
  await expect(page.getByRole('combobox', { name: 'Выберите организацию', exact: true }).locator('option:checked')).toHaveText(name);
  await expect(page.getByText(/Верификация: ожидает проверки/)).toBeVisible();
  await expect(page.getByText(/Владелец · активно/)).toBeVisible();
});
