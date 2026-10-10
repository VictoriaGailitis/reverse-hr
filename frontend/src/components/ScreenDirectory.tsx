import { useState } from 'react';
import { Link } from 'react-router-dom';
import { screens } from '../design/catalog';
import { useDemo } from '../state/DemoContext';

export function ScreenDirectory() {
  const [open, setOpen] = useState(false);
  const { reset } = useDemo();
  return <details className="screen-directory" open={open} onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>Все экраны · {screens.length}</summary>
    <nav aria-label="Карта экранов">
      {screens.map(screen => <Link key={screen.key} to={screen.route} onClick={() => setOpen(false)}>{screen.name}</Link>)}
      <button type="button" onClick={reset}>Сбросить демосценарий</button>
    </nav>
  </details>;
}
