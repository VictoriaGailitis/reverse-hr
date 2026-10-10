import { useState, type CSSProperties } from 'react';
import type { DesignNode, Screen } from '../design/types';
import { useScreenActions } from '../hooks/useScreenActions';
import { useDemo } from '../state/DemoContext';
import { Badge } from './Badge';
import { Button } from './Button';
import { FormField, isField } from './FormField';
import { CodeEditor } from '../workspaces/CodeEditor';
import { Board } from '../workspaces/Board';
import { RecordingClock } from '../workspaces/RecordingClock';

interface NodeProps {
  node: DesignNode;
  screen: Screen;
  parent?: DesignNode;
  headingId: string;
  perform: ReturnType<typeof useScreenActions>['perform'];
  search: string;
}

function isSearchCard(node: DesignNode, screen: Screen) {
  return (screen.key === 'search' && node.type === 'layout' && node.children[0]?.text?.startsWith('Кандидат'))
    || (screen.key === 'vacancies' && node.type === 'layout' && node.children[0]?.text === 'Frontend-разработчик');
}

function textOf(node: DesignNode): string {
  return [node.text ?? '', ...node.children.map(textOf)].join(' ').toLowerCase();
}

function matchingCards(node: DesignNode, screen: Screen, search: string): number {
  if (isSearchCard(node, screen)) return Number(textOf(node).includes(search.trim().toLowerCase()));
  return node.children.reduce((total, child) => total + matchingCards(child, screen, search), 0);
}

function sizing(node: DesignNode, parent?: DesignNode): CSSProperties {
  if (!parent) return { width: '100%' };
  if (parent.dir === 'row') return { flex: `${node.w} 1 0%`, minWidth: 0 };
  const inner = parent.w - Number(parent.style.paddingLeft ?? 0) - Number(parent.style.paddingRight ?? 0);
  if (node.type === 'button') return { width: node.w, maxWidth: '100%' };
  return { width: node.w >= inner - 2 ? '100%' : `${Math.min(100, node.w / inner * 100)}%`, maxWidth: '100%' };
}

function Consent({ node, screen }: { node: DesignNode; screen: Screen }) {
  const { state, update } = useDemo();
  const text = (node.text ?? '').replace(/^□\s*/, '');
  const key = text.includes('условия') ? 'terms' : text.includes('Согласна') ? 'recording' : `visibility:${node.id}`;
  return <label className="consent" style={node.style}><input type="checkbox" checked={!!state.consents[key]}
    required={(screen.key === 'login' && key === 'terms') || (screen.key.startsWith('equipment') && key === 'recording')}
    onChange={event => update(current => ({ consents: { ...current.consents, [key]: event.target.checked } }))} /><span>{text}</span></label>;
}

function Node({ node, screen, parent, headingId, perform, search }: NodeProps) {
  const { state, update, busy } = useDemo();
  const [alternative, setAlternative] = useState('');
  const style = { ...node.style, ...sizing(node, parent) };
  if (node.type === 'button') {
    let label = node.label ?? 'Продолжить';
    if (label === 'Запустить v12') label = `Запустить v${state.codeVersion}`;
    if (label === 'Код сохранён · v12') label = `Код сохранён · v${state.codeVersion}`;
    return <Button variant={node.variant} style={sizing(node, parent)} disabled={busy}
      data-figma-id={node.id} onClick={event => void perform(node, event.currentTarget.closest('form'))}>{label}</Button>;
  }
  if (node.type === 'badge') return <Badge label={node.label} />;
  if (node.type === 'logo') return <img src="/brand/fsp-logo.svg" width="156" height="52.5" alt="ФСП" />;
  if (node.type === 'text') {
    if (node.text?.startsWith('□')) return <Consent node={node} screen={screen} />;
    if (node.text?.startsWith('01  type Candidate')) return <CodeEditor initialCode={node.text} />;
    if (screen.key === 'video-recording' && node.text?.includes('Демозапись') && !node.text.includes('Запись')) return <p style={style}><RecordingClock /></p>;
    if (screen.key === 'video-preview' && node.text?.includes('готов к отправке')) return <p style={style}><RecordingClock preview /></p>;
    let text = node.text ?? '';
    if (text.startsWith('● Подключено') && screen.key.startsWith('editor')) text = `● Подключено  /  Версия ${state.codeVersion} ${state.codeSaved ? 'сохранена локально' : 'сохраняется…'}  /  Камера выключена`;
    if (text === 'TypeScript · Версия 12') text = `TypeScript · Версия ${state.codeVersion}`;
    if (text.startsWith('Демо: открытые примеры')) text = state.runVersion === state.codeVersion ? state.runMessage : 'Демо: проверка текущей версии ещё не выполнялась.';
    if (screen.key === 'code-queued' && text.includes('Запуск версии')) text = `↻ Демозапуск версии ${state.codeVersion} в очереди`;
    if (screen.key === 'privacy' && text.includes('Доступ разрешён')) text = `Команда «Спектр»\nКонтакты и резюме · ${state.disclosure === 'open' ? 'Доступ разрешён' : state.disclosure === 'revoked' ? 'Доступ отозван' : 'Доступ закрыт'}`;
    if (screen.key === 'disclosure-pending' && text.includes('Раскрытие контактов')) text = state.disclosure === 'open' ? 'Демо: раскрытие подтверждено.' : 'Раскрытие контактов ещё обрабатывается.';
    if (screen.key === 'disclosure-pending' && text.includes('пока не получила')) text = state.disclosure === 'open' ? '✓ Компания получила разрешённые данные · Демо' : '↻ Компания пока не получила новые данные.';
    if (screen.key === 'ats' && text.includes('доставка подтверждена')) text = state.delivery === 'delivered' ? 'Демо: доставка подтверждена' : state.delivery === 'pending' ? 'Демо: доставка обрабатывается' : 'Демо: данные ещё не переданы';
    if (screen.key === 'ats' && text.includes('Контакты: синтетические')) text = state.disclosure === 'open' ? text : 'Кандидат №1042\nКонтакты закрыты\nНавыки: React, TypeScript\nКатегория: Middle · Демо';
    if (node.id === headingId) return <h1 style={style}>{text}</h1>;
    if (node.style.fontSize === 20 && node.style.fontWeight === 700) return <h2 style={style}>{text}</h2>;
    return <p className="design-text" data-figma-id={node.id} style={style}>{text}</p>;
  }
  if (isField(node)) return <FormField node={node} screen={screen} style={sizing(node, parent)} />;
  if (screen.key === 'board' && node.children[0]?.text === 'Схема поиска специалистов') return <section className="design-node" style={style}><h2 style={node.children[0].style}>Схема поиска специалистов</h2><Board /></section>;
  const isCamera = node.children.length === 1 && ['◉', '▶'].includes(node.children[0].text ?? '');
  if (isCamera) return <div className="video-viewport" style={{ ...style, minHeight: node.h }} aria-label="Область демовидео">
    <span style={node.children[0].style}>{node.children[0].text}</span>
  </div>;
  if (isSearchCard(node, screen)) {
    if (search && !textOf(node).includes(search.trim().toLowerCase())) return null;
  }
  const isPreviewPanel = screen.key === 'video-preview' && node.children[0]?.text === 'Вопрос';
  const isMessagePanel = screen.key === 'messages' && node.children[0]?.text === 'Команда «Спектр»';
  return <section className={`design-node ${node.dir === 'row' ? 'design-row' : ''}`} data-figma-id={node.id} style={style}>
    {node.children.map(child => <Node key={child.id} {...{ node: child, screen, parent: node, headingId, perform, search }} />)}
    {isPreviewPanel && <label className="form-field">Текстовое объяснение<textarea aria-label="Текстовая альтернатива видео" value={alternative} onChange={event => { setAlternative(event.target.value); update(current => ({ fields: { ...current.fields, 'video:text': event.target.value } })); }} rows={3} placeholder="Коротко объясните решение…" /></label>}
    {isMessagePanel && <>
      {state.messages.map((message, index) => <p key={index} className="message-bubble">{message}</p>)}
      <Button variant="secondary" onClick={() => {
        const message = state.fields['messages:Короткое сообщение']?.trim();
        if (message) update(current => ({ messages: [...current.messages, message.slice(0, 500)], fields: { ...current.fields, 'messages:Короткое сообщение': '' } }));
      }}>Отправить сообщение</Button>
    </>}
  </section>;
}

export function DesignContent({ screen }: { screen: Screen }) {
  const { perform } = useScreenActions(screen);
  const [search, setSearch] = useState('');
  const title = screen.mobile ? screen.content.children[1] : screen.content.children[0]?.children[0];
  const headingId = title?.id ?? '';
  const filters = screen.key === 'search' || screen.key === 'vacancies';
  return <form className="screen-form" aria-label={screen.name.replace(/^\d+ · /, '')} onSubmit={event => event.preventDefault()}>
    {screen.content.children.map((node, index) => <div className="section-slot" key={node.id}>
      {filters && index === 1 && <div className="search-filter"><label>Поиск по навыкам или кандидату<input type="search" value={search} onChange={event => setSearch(event.target.value)} placeholder="Например: React или №1042" /></label></div>}
      <Node {...{ node, screen, parent: screen.content, headingId, perform, search }} />
    </div>)}
    {filters && search && matchingCards(screen.content, screen, search) === 0 && <p className="empty-state">Ничего не найдено. Попробуйте изменить фильтры.</p>}
  </form>;
}
