import { createContext, useContext, useRef, type ReactNode } from 'react';
import type { CommercialError, PreparedAction } from './client';
import type { Action, Receipt } from './types';

export interface RefusedAction { inputKey: string; prepared: PreparedAction; error: CommercialError }
export interface RememberedAction { inputKey: string; prepared: PreparedAction | null; receipt: Receipt | null; refused?: RefusedAction | null }
class RememberedActions extends Map<string, RememberedAction> {
  readonly refused = new Map<string, RefusedAction[]>();
}
const Context = createContext<RememberedActions | null>(null);
export const memoryKey = (action: Action, id: string) => `${action}:${id}`;
export function CommercialMemory({ children }: { children: ReactNode }) {
  const records = useRef(new RememberedActions());
  return <Context.Provider value={records.current}>{children}</Context.Provider>;
}
export function useCommercialMemory() {
  const records = useContext(Context);
  if (!records) throw new Error('A commercial action requires its current person and scope.');
  return records;
}
