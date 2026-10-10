import { useRef, useState } from 'react';
import { Button } from '../components/Button';
import { readStorage, writeStorage } from '../lib/storage';
import { useDemo } from '../state/DemoContext';

interface Block { id: string; title: string; description: string; x: number; y: number }
const initial: Block[] = [
  { id: 'ui', title: 'UI', description: 'Фильтры', x: 0, y: 64 },
  { id: 'api', title: 'API', description: 'Поиск', x: 228, y: 64 },
  { id: 'db', title: 'БД', description: 'Профили', x: 456, y: 64 },
];

export function Board() {
  const { toast } = useDemo();
  const [blocks, setBlocks] = useState<Block[]>(() => readStorage<Block[] | null>('board', null) ?? initial);
  const [selected, setSelected] = useState<string | null>(null);
  const [history, setHistory] = useState<Block[][]>([]);
  const dragging = useRef<{ id: string; x: number; y: number; originX: number; originY: number; before: Block[] } | null>(null);
  const canvas = useRef<HTMLDivElement>(null);
  const [operation, setOperation] = useState(28);

  function save(next: Block[], previous = blocks) {
    setHistory(current => [...current.slice(-19), previous]);
    setBlocks(next);
    setOperation(current => current + 1);
    if (!writeStorage('board', next)) toast('Не удалось сохранить доску локально.');
  }
  return <div className="board-workspace">
    <div className="board-toolbar" role="toolbar" aria-label="Инструменты доски">
      <Button variant="secondary" onClick={() => {
        const width = canvas.current?.clientWidth ?? 648;
        const next: Block = { id: crypto.randomUUID(), title: 'Новый блок', description: 'Двойной клик: подпись', x: Math.max(0, (width - 180) / 2), y: 200 };
        save([...blocks, next]); setSelected(next.id);
      }}>+ Блок</Button>
      <Button variant="secondary" disabled={!selected} onClick={() => save(blocks.filter(block => block.id !== selected))}>Удалить</Button>
      <Button variant="secondary" disabled={!history.length} onClick={() => {
        const previous = history.at(-1)!;
        setBlocks(previous); setHistory(current => current.slice(0, -1)); writeStorage('board', previous);
      }}>Отменить</Button>
    </div>
    <div ref={canvas} className="board-canvas" aria-label="Доска проектирования">
      <svg className="board-connections" aria-hidden="true">
        <defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M 0 0 L 10 5 L 0 10 z" fill="var(--color-brand)" /></marker></defs>
        {blocks.slice(0, -1).map((block, index) => <line key={block.id} x1={block.x + 180} y1={block.y + 55} x2={blocks[index + 1].x - 8} y2={blocks[index + 1].y + 55} stroke="var(--color-brand)" strokeWidth="2" markerEnd="url(#arrow)" />)}
      </svg>
      {blocks.map(block => <button key={block.id} type="button" className={`board-block ${selected === block.id ? 'selected' : ''}`} style={{ left: block.x, top: block.y }}
        aria-label={`Блок ${block.title}`} onClick={() => setSelected(block.id)}
        onDoubleClick={() => {
          const title = window.prompt('Название блока', block.title);
          if (title?.trim()) save(blocks.map(value => value.id === block.id ? { ...value, title: title.trim() } : value));
        }}
        onPointerDown={event => {
          setSelected(block.id); event.currentTarget.setPointerCapture(event.pointerId);
          dragging.current = { id: block.id, x: event.clientX, y: event.clientY, originX: block.x, originY: block.y, before: blocks };
        }}
        onPointerMove={event => {
          const drag = dragging.current;
          if (!drag || drag.id !== block.id) return;
          const maxX = (canvas.current?.clientWidth ?? 648) - 180;
          const x = Math.max(0, Math.min(maxX, drag.originX + event.clientX - drag.x));
          const y = Math.max(0, Math.min(220, drag.originY + event.clientY - drag.y));
          setBlocks(current => current.map(value => value.id === block.id ? { ...value, x, y } : value));
        }}
        onPointerUp={() => { if (dragging.current) { save(blocks, dragging.current.before); dragging.current = null; } }}
        onKeyDown={event => {
          const direction = { ArrowLeft: [-8, 0], ArrowRight: [8, 0], ArrowUp: [0, -8], ArrowDown: [0, 8] }[event.key];
          if (!direction) return;
          event.preventDefault();
          save(blocks.map(value => value.id === block.id ? { ...value, x: Math.max(0, Math.min((canvas.current?.clientWidth ?? 648) - 180, value.x + direction[0])), y: Math.max(0, Math.min(220, value.y + direction[1])) } : value));
        }}>
        <strong>{block.title}</strong><span>{block.description}</span>
      </button>)}
    </div>
    <p>Запрос → загрузка → результат<br />Ошибка → повтор<br />Нет данных → измените фильтры</p>
    <div className="board-status" role="status">История: операция #{operation} сохранена локально · Демо</div>
  </div>;
}
