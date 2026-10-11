import { test, expect, type Page } from '@playwright/test';
import { oauth, login, json, consentId, policies } from './helpers/backend';
const policyId = '88888888-8888-4888-8888-888888888888';
const sessionId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
async function setup(page: Page) {
  await oauth(page);
  await page.route('**/api/privacy/**', (r) => json(r, r.request().url().endsWith('/policies') ? policies : [{consent_id: consentId, purpose: 'assessment', document_version: 'demo-v1', status: 'active', version: 1}]));
}
const offer = {policy_id: policyId, name: 'Практика Python', specialization: 'backend', grade: 'middle', demo: true};

test.beforeEach(async ({ page }) => {
  await page.route("**/api/assessment/v1/assessment-generation/offers", route => json(route, []));
  await page.route("**/api/candidate/v1/candidates/me/task-subscription", route => json(route, { enabled: false, version: 0, declared_skills: [], interval_hours: 24 }));
  await page.route("**/api/candidate/v1/candidates/me/task-recommendations", route => json(route, { items: [], next_cursor: null }));
  await page.route("**/api/evaluation/v1/evaluation-risks/me", route => json(route, { additional_verification_required: false, signal_count: 0 }));
});

test('сервер выбирает вариант; повтор после 503 сохраняет ключ и не передаёт план или шкалу', async ({ page }) => {
  await setup(page);
  const keys: string[] = [];
  await page.route('**/api/assessment/**', async (r) => {
    const url = new URL(r.request().url());
    if (url.pathname.endsWith('/assessment-selection-policies')) return json(r, [offer]);
    if (url.pathname.endsWith('/assessment-task-history')) return json(r, []);
    if (url.pathname.endsWith('/assessment-selected-sessions')) {
      expect(r.request().postDataJSON()).toEqual({selection_policy_id: policyId, assessment_consent_id: consentId});
      keys.push(r.request().headers()['idempotency-key']);
      return json(r, keys.length === 1 ? {detail: 'Unavailable'} : {session_id: sessionId}, keys.length === 1 ? 503 : 201);
    }
    if (url.pathname.endsWith('/assessment-generation/offers')) return json(r, []);
    expect(url.pathname).toContain(`/assessment-sessions/${sessionId}`);
    return json(r, {session_id: sessionId, plan_version_id: policyId, status: 'preflight', version: 1, demo: true, stages: [], progress: []});
  });
  await login(page, '/candidate/assessment?gradePolicy=untrusted');
  await expect(page.getByLabel('Шкала оценки из приглашения (необязательно)')).toHaveCount(0);
  await page.getByRole('button', { name: 'Начать подготовку', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('Сервис временно недоступен');
  await page.getByRole('button', { name: 'Начать подготовку', exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`session=${sessionId}`));
  expect(keys).toHaveLength(2);
  expect(keys[0]).toBeTruthy();
  expect(keys[1]).toBe(keys[0]);
});

test('исчерпанный банк не запускает фиксированный план, обновление снимает конфликт', async ({ page }) => {
  await setup(page);
  let commands = 0;
  await page.route('**/api/assessment/**', (r) => {
    const url = new URL(r.request().url());
    if (url.pathname.endsWith('/assessment-selection-policies')) return json(r, [offer]);
    if (url.pathname.endsWith('/assessment-task-history')) return json(r, []);
    if (url.pathname.endsWith('/assessment-generation/offers')) return json(r, []);
    expect(url.pathname).toMatch(/assessment-selected-sessions$/);
    commands++;
    return json(r, {detail: 'Rotation limit reached'}, 409);
  });
  await login(page, '/candidate/assessment');
  await page.getByRole('button', { name: 'Начать подготовку', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Начать подготовку', exact: true })).toBeDisabled();
  expect(commands).toBe(1);
  await page.getByRole('button', { name: 'Обновить данные', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Начать подготовку', exact: true })).toBeEnabled();
});

test('история использует курсор сервера и позволяет открыть выданную попытку', async ({ page }) => {
  await setup(page);
  const cursors: (string | null)[] = [];
  await page.route('**/api/assessment/**', (r) => {
    const url = new URL(r.request().url());
    if (url.pathname.endsWith('/assessment-selection-policies')) return json(r, []);
    if (url.pathname.endsWith('/assessment-task-history')) {
      const cursor = url.searchParams.get('after'); cursors.push(cursor);
      expect(url.searchParams.get('limit')).toBe('20');
      return json(r, cursor ? [] : Array.from({length: 20}, (_, i) => ({session_id: i === 19 ? sessionId : `bbbbbbbb-bbbb-4bbb-8bbb-${String(i).padStart(12, '0')}`, plan_version_id: policyId, issued_at: '2026-10-10T10:00:00Z', status: 'cancelled', family_ids: [], revision_ids: []})));
    }
    return json(r, {});
  });
  await login(page, '/candidate/assessment');
  await page.getByRole('button', { name: 'Более ранние попытки', exact: true }).click();
  await expect(page.getByText('На этой странице нет попыток.', {exact: true})).toBeVisible();
  expect(cursors).toEqual([null, sessionId]);
  await page.getByRole('button', { name: 'Более новые попытки', exact: true }).click();
  await page.getByRole('button', {name: 'Открыть попытку', exact: true}).last().click();
  await expect(page).toHaveURL(new RegExp(`session=${sessionId}`));
});
