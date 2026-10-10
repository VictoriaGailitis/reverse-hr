import { createContext, useCallback, useContext, useState, type ReactNode } from 'react';
import type { DeliveryStatus, DisclosureStatus } from '../lib/demo-api';
import { readStorage, writeStorage } from '../lib/storage';

export interface DemoState {
  fields: Record<string, string>;
  consents: Record<string, boolean>;
  disclosure: DisclosureStatus;
  delivery: DeliveryStatus;
  invitationSent: boolean;
  messages: string[];
  code: string | null;
  codeVersion: number;
  codeSaved: boolean;
  runVersion: number | null;
  runMessage: string;
  running: boolean;
  recordingStartedAt: number | null;
  recordingSeconds: number;
  deletion: 'none' | 'pending';
  imported: boolean;
}

const initial: DemoState = {
  fields: {}, consents: {}, disclosure: 'closed', delivery: 'idle', invitationSent: false,
  messages: [], code: null, codeVersion: 12, codeSaved: true, runVersion: null,
  runMessage: '', running: false, recordingStartedAt: null, recordingSeconds: 0,
  deletion: 'none', imported: false,
};

interface DemoContextValue {
  state: DemoState;
  update: (change: Partial<DemoState> | ((current: DemoState) => Partial<DemoState>)) => void;
  toast: (message: string) => void;
  notice: string;
  busy: boolean;
  setBusy: (busy: boolean) => void;
  reset: () => void;
}

const DemoContext = createContext<DemoContextValue | null>(null);

export function DemoProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<DemoState>(() => {
    const saved = readStorage<{ code: string | null; version: number }>('code', { code: null, version: 12 });
    return { ...initial, code: saved.code, codeVersion: saved.version };
  });
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const update: DemoContextValue['update'] = useCallback(change => setState(current => ({ ...current, ...(typeof change === 'function' ? change(current) : change) })), []);
  const reset = () => {
    setState(initial);
    writeStorage('code', { code: null, version: 12 });
    writeStorage('board', null);
    setNotice('Демосценарий сброшен.');
  };
  return <DemoContext.Provider value={{ state, update, notice, toast: setNotice, busy, setBusy, reset }}>{children}</DemoContext.Provider>;
}

export function useDemo() {
  const value = useContext(DemoContext);
  if (!value) throw new Error('DemoProvider is required');
  return value;
}
