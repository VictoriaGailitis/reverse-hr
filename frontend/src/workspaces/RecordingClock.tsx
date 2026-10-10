import { useEffect, useState } from 'react';
import { useDemo } from '../state/DemoContext';

export function RecordingClock({ preview = false }: { preview?: boolean }) {
  const { state } = useDemo();
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (preview || !state.recordingStartedAt) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [preview, state.recordingStartedAt]);
  const seconds = Math.max(0, Math.min(180, state.recordingStartedAt ? Math.floor((now - state.recordingStartedAt) / 1000) : state.recordingSeconds));
  const formatted = `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
  return <span aria-live="off">{formatted} {preview ? '· Демоответ готов к отправке' : '/ 03:00 · Демозапись'}</span>;
}
