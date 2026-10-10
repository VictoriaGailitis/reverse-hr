import { useEffect } from 'react';
import { useDemo } from '../state/DemoContext';
import { writeStorage } from '../lib/storage';

export function CodeEditor({ initialCode }: { initialCode: string }) {
  const { state, update, toast } = useDemo();
  const initial = initialCode.split('\n').map(line => line.replace(/^\d+(?:\s+|$)/, '')).join('\n');
  const code = state.code ?? initial;
  useEffect(() => {
    const timer = window.setTimeout(() => {
      const saved = writeStorage('code', { code, version: state.codeVersion });
      update({ codeSaved: saved });
      if (!saved) toast('Не удалось сохранить код локально. Скопируйте работу перед выходом.');
    }, 350);
    return () => clearTimeout(timer);
  }, [code, state.codeVersion, update, toast]);
  return <div className="code-editor">
    <div className="line-numbers" aria-hidden="true">{code.split('\n').map((_, index) => <div key={index}>{String(index + 1).padStart(2, '0')}</div>)}</div>
    <textarea aria-label="Код solution.ts" spellCheck={false} value={code} rows={Math.max(10, code.split('\n').length)}
      onChange={event => update(current => ({ code: event.target.value, codeVersion: current.codeVersion + 1, codeSaved: false }))}
      onKeyDown={event => {
        if (event.key !== 'Tab') return;
        event.preventDefault();
        const target = event.currentTarget;
        const position = target.selectionStart;
        const next = code.slice(0, position) + '  ' + code.slice(target.selectionEnd);
        update(current => ({ code: next, codeVersion: current.codeVersion + 1, codeSaved: false }));
        requestAnimationFrame(() => { target.selectionStart = target.selectionEnd = position + 2; });
      }} />
  </div>;
}
