import { useEffect, useMemo, useState, useSyncExternalStore, type ReactNode } from 'react';
import { BackendApi } from '../api/client';
import { accessToken, expireSession, initializeSession, sessionSnapshot, subscribeSession } from '../auth/session';
import { BackendContext, type BackendMode } from './BackendContext';

export function BackendProvider({ children }: { children: ReactNode }) {
  const [mode, updateMode] = useState<BackendMode>(() => {
    try { if (sessionStorage.getItem('fsp:backend-mode') === 'api') return 'api'; } catch { /* Storage may be disabled. */ }
    return import.meta.env.VITE_BACKEND_MODE === 'api' || location.pathname === '/auth/callback' ? 'api' : 'demo';
  });
  const session = useSyncExternalStore(subscribeSession, sessionSnapshot);
  const api = useMemo(() => new BackendApi(accessToken, expireSession), []);
  const setMode = (next: BackendMode) => {
    try { sessionStorage.setItem('fsp:backend-mode', next); } catch { /* Mode still works for this page. */ }
    updateMode(next);
  };
  useEffect(() => { if (mode === 'api') void initializeSession(); }, [mode]);
  return <BackendContext.Provider value={{ mode, setMode, session, api }}>{children}</BackendContext.Provider>;
}
