import { useRef, useState } from 'react';
import { ApiError, isUnknownResult } from './api/client';

// Mounted-view recovery only. Once uncertain, later failures cannot disprove an
// earlier effect; only the matching successful server receipt clears the lock.
export function useMutation<I extends { operation_id?: string }, O extends { operation: { id: string; status: string; replayed: boolean } }>(send: (input: I & { operation_id: string }) => Promise<O>, validate?: (result: O, input: I & { operation_id: string }) => boolean) {
  const pending = useRef<(I & { operation_id: string }) | undefined>(undefined);
  const inFlight = useRef(false);
  const [busy, setBusy] = useState(false); const [unknown, setUnknown] = useState(false); const [error, setError] = useState<ApiError>();
  const perform = async (input?: I): Promise<O | undefined> => {
    if (inFlight.current) return;
    if (!pending.current) { if (!input) return; pending.current = structuredClone({ ...input, operation_id: crypto.randomUUID() }); }
    inFlight.current = true; setBusy(true); setError(undefined);
    try {
      const result = await send(pending.current);
      if (result?.operation?.id !== pending.current.operation_id || result.operation.status !== 'succeeded' || typeof result.operation.replayed !== 'boolean' || (validate && !validate(result, pending.current))) throw new ApiError('The operation receipt is incomplete. Recover the original request.', 'INVALID_CONTRACT', 200);
      pending.current = undefined; setUnknown(false); return result;
    } catch (failure) {
      setError(failure instanceof ApiError ? failure : new ApiError('The operation result could not be verified. Recover the original request.', 'INVALID_CONTRACT', 200));
      if (unknown || isUnknownResult(failure)) setUnknown(true); else pending.current = undefined;
    } finally { inFlight.current = false; setBusy(false); }
  };
  return { run: (input: I) => perform(input), recover: () => perform(), busy, unknown, error, locked: busy || unknown };
}
