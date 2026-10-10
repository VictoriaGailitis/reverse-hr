import { useId } from 'react';
import type { DesignNode, Screen } from '../design/types';
import { useDemo } from '../state/DemoContext';

const editableScreens = new Set(['login', 'profile', 'need', 'offer', 'constructor', 'review', 'privacy', 'organization', 'ats', 'messages']);
const choices: Record<string, string[]> = {
  'Предполагаемый уровень': ['Junior', 'Middle', 'Senior'],
  'Формат работы': ['Удалённо', 'Гибрид', 'Офис'],
  'Формат': ['Удалённо', 'Гибрид', 'Офис'],
  'Контакты': ['Закрыты', 'Только после приглашения'],
};

export function isField(node: DesignNode): boolean {
  return node.type === 'layout' && node.children.length === 2 && node.children[0].type === 'text'
    && node.children[0].style.fontSize === 12 && node.children[1].type === 'layout'
    && node.children[1].children.length === 1 && node.children[1].children[0].type === 'text';
}

export function FormField({ node, screen, style }: { node: DesignNode; screen: Screen; style: React.CSSProperties }) {
  const { state, update } = useDemo();
  const generatedId = useId();
  const label = node.children[0].text ?? '';
  const initial = node.children[1].children[0].text ?? '';
  const scope = `${screen.key}:${label}`;
  const value = state.fields[scope] ?? (label === 'Пароль' ? '' : initial === 'Введите сообщение…' ? '' : initial);
  const readOnly = !editableScreens.has(screen.key) || ['Профиль', 'Внешний ID', 'Название', 'Роль сотрудника'].includes(label);
  const isSalary = label.startsWith('Зарплата ') && label.includes('₽');
  const type = label === 'Пароль' ? 'password' : label === 'Email' ? 'email' : 'text';
  const options = choices[label];
  const onChange = (next: string) => update(current => ({ fields: { ...current.fields, [scope]: next } }));
  return <label className="form-field" htmlFor={generatedId} style={style}>
    <span style={node.children[0].style}>{label}</span>
    {options && !readOnly ? <select id={generatedId} value={value} onChange={event => onChange(event.target.value)}>
      {!options.includes(value) && <option value={value}>{value}</option>}
      {options.map(option => <option key={option}>{option}</option>)}
    </select> : <input id={generatedId} name={scope} type={type} value={value} readOnly={readOnly}
      placeholder={label === 'Пароль' ? 'Не менее 8 символов' : initial}
      minLength={type === 'password' ? 8 : undefined} required={screen.key === 'login' || isSalary}
      inputMode={isSalary ? 'numeric' : undefined} autoComplete={type === 'password' ? 'new-password' : type === 'email' ? 'email' : 'off'}
      onChange={event => onChange(event.target.value)} />}
  </label>;
}
