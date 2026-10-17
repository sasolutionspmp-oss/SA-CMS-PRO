import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { Button, MessageStrip } from '@ui5/webcomponents-react';
import { ApiError } from './api/client';
import { documentControlNext, type NextDocumentCommand, type NextDocumentReply } from './api/document-control-next';
import type { Actor } from './api/engineering';
import type { Project } from './api/types';
import { Failure } from './components';
import { useMutation } from './useMutation';

export type NextDocumentSubmit = (input: NextDocumentCommand) => Promise<NextDocumentReply | undefined>;
export type NextDocumentViewProps = { company: string; project: Project; user: string; personId: string; tail: string[]; locked: boolean; revision: number; submit: NextDocumentSubmit; onDenied: () => void; onPacket: (id: string) => void; navigate: (path: string) => void };
type Options = { active: boolean; company: string; project?: string; user: string; personId: string; navigationLocked: boolean; onLockedChange: (locked: boolean) => void };
export const projectDocumentPath = (project: string) => `/projects/${encodeURIComponent(project)}/document-control`;
export const companyLibraryPath = (company: string, tail = '') => `/company/library${tail ? `/${tail}` : ''}?company=${encodeURIComponent(company)}`;
export const nextRecordPath = (project: string, kind: string, id: string) => `${projectDocumentPath(project)}/${['clause_use', 'redline', 'clause_application'].includes(kind) ? 'clauses' : kind === 'adoption_request' || kind === 'adoption' ? 'shared' : 'issued'}/record/${kind}/${encodeURIComponent(id)}`;

export function useDocumentNextOperation(options: Options) {
  const current = useRef(options); current.current = options;
  const captured = useRef<(Actor & { company: string; project?: string }) | undefined>(undefined);
  const command = useMutation<NextDocumentCommand & { operation_id?: string }, NextDocumentReply>(input => {
    if (!captured.current) throw new ApiError('The original document request is unavailable.', 'INVALID_CONTRACT', 200);
    return documentControlNext.send(input, captured.current);
  });
  const currentCommand = useRef(command); currentCommand.current = command;
  const [dismissedError, setDismissedError] = useState<ApiError>();
  const clearKnownError = useCallback(() => { if (!currentCommand.current.locked) setDismissedError(currentCommand.current.error); }, []);
  const [revision, setRevision] = useState(0); const [notice, setNotice] = useState(''); const [saved, setSaved] = useState<{ kind: string; id: string }>(); const [packetId, setPacketId] = useState<string>();
  const authority = JSON.stringify([options.company, options.project, options.user, options.personId]);
  useEffect(() => { setNotice(''); setSaved(undefined); setPacketId(undefined); }, [authority]);
  useEffect(() => { options.onLockedChange(command.locked); }, [command.locked, options.onLockedChange]);
  useEffect(() => () => options.onLockedChange(false), [options.onLockedChange]);
  const sameActor = Boolean(captured.current && captured.current.company === options.company && captured.current.project === options.project && captured.current.user === options.user && captured.current.personId === options.personId);
  const finish = (reply: NextDocumentReply | undefined) => {
    if (!reply) return;
    const original = captured.current, live = current.current;
    if (original && original.company === live.company && original.project === live.project && original.user === live.user && original.personId === live.personId) {
      setRevision(value => value + 1); setNotice(reply.operation.replayed ? 'Original save recovered.' : 'Saved.');
      if ('packet' in reply) setPacketId(reply.packet.id);
      else { const row = Object.entries(reply).find(([key, value]) => !['history_id', 'operation'].includes(key) && value && typeof value === 'object' && 'id' in value); if (row) setSaved({ kind: row[0], id: String((row[1] as { id: string }).id) }); }
    }
    captured.current = undefined;
    return reply;
  };
  const submit: NextDocumentSubmit = async input => {
    if (!options.active || options.navigationLocked || command.locked) return;
    captured.current = { company: options.company, project: options.project, user: options.user, personId: options.personId }; setNotice(''); setSaved(undefined);
    return finish(await command.run(input));
  };
  return { command, revision, notice, saved, packetId, setPacketId, submit, state: { ...command, error: command.error === dismissedError ? undefined : command.error, clearKnownError, recoverable: sameActor && options.active && !options.navigationLocked, recover: async () => { if (sameActor && options.active && !options.navigationLocked) return finish(await command.recover()); } } };
}
type CommandState = { error?: ApiError; unknown: boolean; busy: boolean; recoverable: boolean; recover: () => void; clearKnownError: () => void };
export const DocumentNextCommandContext = createContext<CommandState>({ unknown: false, busy: false, recoverable: false, recover: () => {}, clearKnownError: () => {} });
export function useDocumentFormState() {
  const state = useContext(DocumentNextCommandContext), inheritedError = useRef(state.error);
  useEffect(() => state.clearKnownError(), [state.clearKnownError]);
  return { ...state, error: !state.unknown && !state.busy && state.error === inheritedError.current ? undefined : state.error };
}
export function DocumentNextCommandState() {
  const state = useContext(DocumentNextCommandContext);
  return <>{state.error && <Failure error={state.error} />}{state.unknown && <><MessageStrip design="Critical" hideCloseButton>The save result is unknown. Recover this request before editing or leaving.</MessageStrip><Button disabled={state.busy || !state.recoverable} onClick={state.recover}>Recover document save</Button></>}</>;
}
