import { useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { destination, routeFor } from '../design/catalog';
import type { DesignNode, Screen } from '../design/types';
import { demoApi, delay } from '../lib/demo-api';
import { useDemo } from '../state/DemoContext';

function number(value: string) { return Number(value.replace(/[\s₽]/g, '')); }

export function useScreenActions(screen: Screen) {
  const navigate = useNavigate();
  const { state, update, toast, busy, setBusy } = useDemo();
  const inFlight = useRef(false);
  const go = (key: string) => navigate(routeFor(key));
  const field = (label: string, fallback = '') => state.fields[`${screen.key}:${label}`] ?? fallback;

  async function perform(node: DesignNode, form?: HTMLFormElement | null) {
    const label = node.label ?? '';
    const target = destination(node.id);
    if (inFlight.current || busy) return;
    toast('');
    if (['Зарегистрироваться', 'Сохранить и продолжить', 'Отправить демоприглашение'].includes(label) && form && !form.reportValidity()) return;
    if (label === 'Зарегистрироваться') {
      if (!state.consents.terms) { toast('Примите условия использования, чтобы продолжить.'); return; }
      update({ fields: { ...state.fields, 'login:Пароль': '' } });
    }
    if (label === 'Согласиться и начать' && !state.consents.recording) {
      toast('Нужно отдельное согласие на запись видео и аудио этапа.'); return;
    }
    if (label === 'Начать запись') {
      if (!state.consents.recording) { toast('Сначала дайте согласие на запись в настройке этапа.'); go('equipment'); return; }
      update({ recordingStartedAt: Date.now(), recordingSeconds: 0 });
    }
    if (label === 'Остановить запись' || label === 'Завершить запись' || (label === 'Предпросмотр' && screen.key === 'video-recording')) {
      update({ recordingSeconds: state.recordingStartedAt ? Math.floor((Date.now() - state.recordingStartedAt) / 1000) : 42, recordingStartedAt: null });
    }
    if (label === 'Записать заново') update({ recordingStartedAt: Date.now(), recordingSeconds: 0 });
    if (label === 'Текстовая альтернатива') {
      toast('Текстовая альтернатива включена. Введите короткое объяснение вместо демозаписи.');
      go('video-preview'); return;
    }
    if (label === 'Отправить демоприглашение') {
      await task(async () => {
        await demoApi.sendInvitation(number(field('Зарплата от, ₽', '180 000')), number(field('Зарплата до, ₽', '240 000')));
        update({ invitationSent: true }); toast('Демо-приглашение отправлено.'); go('invitations');
      }); return;
    }
    if (label === 'Принять и разрешить') {
      if (state.disclosure === 'open') { go('ats'); return; }
      update({ disclosure: 'pending' }); go('disclosure-pending');
      await task(async () => {
        await demoApi.acceptInvitation();
        update({ disclosure: 'open', delivery: 'pending' });
        await demoApi.deliverProfile(true);
        update({ delivery: 'delivered' }); toast('Демо: доступ разрешён, доставка в ATS подтверждена.');
      }); return;
    }
    if (label === 'Отозвать доступ') {
      await task(async () => { await demoApi.revokeAccess(); update({ disclosure: 'revoked', delivery: 'idle' }); toast('Демо: доступ компании отозван.'); }); return;
    }
    if (label === 'Запросить удаление') {
      update({ deletion: 'pending' }); toast('Демо: запрос удаления принят. Ожидается подтверждение завершения.'); return;
    }
    if (label === 'Запустить v12') {
      const version = state.codeVersion;
      update({ running: true }); go('code-queued');
      await task(async () => {
        const result = await demoApi.runCode(version);
        update({ running: false, runVersion: result.version, runMessage: result.message });
        go('editor');
      }); return;
    }
    if (label === 'Отправить код') {
      if (!state.codeSaved) { toast('Подождите завершения сохранения текущей версии.'); return; }
      go('video'); return;
    }
    if (label === 'Проверить статус' && screen.key === 'states') {
      toast('Демо: удаление ещё выполняется. Подтверждение завершения не получено.'); return;
    }
    if (label === 'Подключить демо' || label === 'Проверить статус') {
      await task(async () => { await delay(400); update({ imported: true }); toast('Демо-импорт завершён. Синтетические достижения доступны.'); }); return;
    }
    if (label === 'Сохранить подборку') { toast('Демо-подборка сохранена в текущей сессии.'); return; }
    if (label === 'Разобрать критерии') { toast('Демо: критерии распознаны. Проверьте специализацию, грейд и условия.'); return; }
    if (label === 'Сгенерировать демозадание') { toast('Демо-задание сформировано. Проверьте рубрику перед публикацией.'); return; }
    if (label === 'Подать апелляцию') { toast('Демо: обращение об апелляции зарегистрировано. Материалы остаются доступными.'); return; }
    if (label === 'Блокировать / жалоба') { toast('Демо: компания заблокирована, жалоба зарегистрирована.'); return; }
    if (label === 'Управлять сотрудниками') { toast('Демо-роли: рекрутер, администратор и наблюдатель.'); return; }
    if (label === 'Сохранить настройки') { toast('Настройки видимости сохранены в демосессии.'); return; }
    if (label === 'Проверить поля') { toast('Поля доступны для исправления в форме профиля.'); return; }
    if (label === 'Показать демоподтверждение' && state.disclosure !== 'open') { toast('Раскрытие ещё не подтверждено. Дождитесь завершения запроса.'); return; }
    if (label === 'Вернуть статус в платформу' && state.delivery !== 'delivered') { toast('Профиль ещё не доставлен в ATS.'); return; }
    if (label === 'Обезличенный PDF') {
      window.print(); return;
    }
    if (target) go(target);
    else toast('Демо: действие обработано в текущем экране.');
  }

  async function task(work: () => Promise<void>) {
    inFlight.current = true; setBusy(true);
    try { await work(); }
    catch (error) { update({ running: false }); toast(error instanceof Error ? error.message : 'Не удалось выполнить действие. Повторите попытку.'); }
    finally { inFlight.current = false; setBusy(false); }
  }
  return { perform, go, busy };
}
