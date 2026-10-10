export type DisclosureStatus = 'closed' | 'pending' | 'open' | 'revoked';
export type DeliveryStatus = 'idle' | 'pending' | 'delivered' | 'failed';

/** Demo transport boundary. Replace this adapter when the OpenAPI contract is ready. */
export const demoApi = {
  async acceptInvitation(): Promise<{ status: 'open'; externalId: string }> {
    await delay(700);
    return { status: 'open', externalId: 'DEMO-ATS-1042' };
  },
  async deliverProfile(allowed: boolean): Promise<{ status: 'delivered' }> {
    if (!allowed) throw new Error('Сначала кандидат должен разрешить раскрытие данных.');
    await delay(450);
    return { status: 'delivered' };
  },
  async sendInvitation(min: number, max: number): Promise<{ status: 'sent' }> {
    if (!Number.isFinite(min) || min <= 0 || !Number.isFinite(max) || max < min) {
      throw new Error('Укажите корректный диапазон зарплаты: от должно быть не больше до.');
    }
    await delay(350);
    return { status: 'sent' };
  },
  async runCode(version: number): Promise<{ version: number; message: string }> {
    await delay(700);
    return { version, message: `Демопроверка версии ${version} завершена. Серверное исполнение ещё не подключено.` };
  },
  async revokeAccess(): Promise<{ status: 'revoked' }> {
    await delay(350);
    return { status: 'revoked' };
  },
};

export function delay(ms: number): Promise<void> {
  return new Promise(resolve => window.setTimeout(resolve, ms));
}
