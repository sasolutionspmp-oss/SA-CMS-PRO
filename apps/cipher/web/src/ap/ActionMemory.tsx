import { createContext, useContext, useRef, type ReactNode } from 'react';
import type { ActionOutcome, APAction, WorkerPendingOutcome } from './types';

export interface PreparedAction {
  action: APAction; id: string; version: string; repeatabilityId: string; body: Record<string, unknown>;
}
export interface RememberedAction {
  inputKey: string; prepared: PreparedAction | null; outcome: ActionOutcome | null;
  unfinished?: WorkerPendingOutcome | null;
}
const Context = createContext<Map<string, RememberedAction> | null>(null);
export const memoryKey = (action: APAction, id: string) => `${action}:${id}`;
// Memory belongs to one current person and scope. No cookies/CSRF are stored.
// A navigation retains a request; changing person or scope discards this map.
export function ActionMemory({ children }: { children: ReactNode }) {
  const records = useRef(new Map<string, RememberedAction>());
  return <Context.Provider value={records.current}>{children}</Context.Provider>;
}
export function useActionMemory() {
  const memory = useContext(Context);
  if (!memory) throw new Error('A practice action requires its current session context.');
  return memory;
}
