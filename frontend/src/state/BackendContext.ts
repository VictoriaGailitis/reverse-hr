import { createContext, useContext } from 'react';
import type { BackendApi } from '../api/client';
import type { SessionState } from '../auth/session';

export type BackendMode = 'demo' | 'api';
export interface BackendContextValue {
  mode: BackendMode;
  setMode: (mode: BackendMode) => void;
  session: SessionState;
  api: BackendApi;
}
export const BackendContext = createContext<BackendContextValue | null>(null);
export function useBackend() {
  const context = useContext(BackendContext);
  if (!context) throw new Error('BackendProvider is required');
  return context;
}
