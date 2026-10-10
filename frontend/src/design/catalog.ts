import rawScreens from './screens.json';
import rawLinks from './links.json';
import type { Screen } from './types';

export const screens = rawScreens as unknown as Screen[];
export const screenByKey = new Map(screens.map(screen => [screen.key, screen]));
export const screenByRoute = new Map(screens.map(screen => [screen.route, screen]));
export const linkByNode = new Map(rawLinks.map(link => [link.nodeId, link.target]));

export function destination(nodeId: string): string | undefined {
  return linkByNode.get(nodeId) ?? linkByNode.get(nodeId.split(';').at(-1) ?? '');
}

export function routeFor(key: string): string {
  return screenByKey.get(key)?.route ?? '/';
}

export const navigation = {
  candidate: [['Обзор', 'dashboard'], ['Профиль', 'profile'], ['Достижения', 'achievements'], ['Оценка навыков', 'assessment'], ['Приглашения · 2', 'invitations'], ['Вакансии', 'vacancies'], ['Сообщения', 'messages'], ['Приватность', 'privacy']],
  employer: [['Обзор компании', 'organization'], ['Потребность', 'need'], ['Поиск кандидатов', 'search'], ['Приглашения', 'offer'], ['Вакансии', 'vacancies'], ['Сообщения', 'messages'], ['Конструктор', 'constructor'], ['Интеграции · ATS', 'ats']],
  admin: [['Очередь проверки', 'admin'], ['Материалы оценки', 'review'], ['Банк заданий', 'constructor'], ['Компании', 'organization'], ['Вакансии', 'vacancies'], ['Источники и импорт', 'achievements'], ['Обращения', 'privacy']],
} as const;
