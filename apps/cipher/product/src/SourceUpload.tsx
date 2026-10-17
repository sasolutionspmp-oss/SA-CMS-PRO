import { useState } from 'react';
import { Bar, Button, Dialog, Input, Label, MessageStrip } from '@ui5/webcomponents-react';
import { ApiError } from './api/client';
import { sourceApi, type SourceScope } from './api/sources';
import type { DocumentRecord } from './api/types';
import { useMutation } from './useMutation';
import { Failure } from './components';

export default function SourceUpload({ scope, existing, onClose, onSaved }: { scope: SourceScope; existing?: DocumentRecord; onClose: () => void; onSaved: (document: DocumentRecord) => void }) {
  const [title, setTitle] = useState(existing?.title || ''); const [file, setFile] = useState<File>(); const [preparing, setPreparing] = useState(false); const [error, setError] = useState<ApiError>();
  const command = useMutation(sourceApi(scope).upload, (result, input) => Boolean(result.document?.id && result.revision?.id && result.document.company === input.company && (!input.document_id || result.document.id === input.document_id) && result.document.current_revision === result.revision.id && result.revision.sha256 === input.sha256 && result.revision.byte_length === input.byte_length && result.document.sha256 === input.sha256 && result.document.byte_length === input.byte_length && (scope.type === 'Company' ? 'scope_type' in result.document && result.document.scope_type === 'Company' && result.document.project === null : result.document.project === scope.project))); const locked = preparing || command.locked;
  const submit = async () => {
    if (command.unknown) { const result = await command.recover(); if (result) onSaved(result.document); return; }
    if (!file || preparing || command.busy) return;
    setPreparing(true); setError(undefined);
    try {
      if (file.size > 10 * 1024 * 1024) throw new ApiError('Choose a PDF, text, JPEG or PNG file up to 10 MiB.', 'FILE_TOO_LARGE', 422);
      const bytes = new Uint8Array(await file.arrayBuffer()); const hash = await crypto.subtle.digest('SHA-256', bytes);
      const sha256 = [...new Uint8Array(hash)].map(value => value.toString(16).padStart(2, '0')).join(''); let binary = '';
      for (let offset = 0; offset < bytes.length; offset += 8192) binary += String.fromCharCode(...bytes.subarray(offset, offset + 8192));
      const result = await command.run({ company: scope.company, title: title.trim(), filename: file.name, content_base64: btoa(binary), sha256, byte_length: bytes.length, ...(existing ? { document_id: existing.id, expected_revision: existing.revision_number } : {}) });
      if (result) onSaved(result.document);
    } catch (failure) { setError(failure instanceof ApiError ? failure : new ApiError('This file could not be prepared. Choose it again.', 'FILE_READ_FAILED', 422)); }
    finally { setPreparing(false); }
  };
  return <Dialog open headerText={existing ? 'Add working source revision' : 'Add source document'} className="form-dialog" onBeforeClose={event => { if (locked) event.preventDefault(); }} onClose={onClose} footer={<Bar endContent={<><Button design="Emphasized" disabled={preparing || command.busy || !file || !title.trim()} onClick={submit}>{command.unknown ? 'Recover source upload' : preparing ? 'Preparing source…' : existing ? 'Save working revision' : 'Add document'}</Button><Button disabled={locked} onClick={onClose}>Cancel</Button></>} />}><div className="dialog-form">{error && <Failure error={error} />}{command.error && <Failure error={command.error} />}{command.unknown && <MessageStrip design="Critical" hideCloseButton>The upload result is unknown. Recover the original bytes and operation key before editing or closing. Recovery lasts while this dialog is open.</MessageStrip>}<Label required>Document title</Label><Input accessibleName="Document title" value={title} disabled={locked} onInput={event => setTitle(event.currentTarget!.value)} /><Label required>Source file</Label><input aria-label="Source file" type="file" accept=".pdf,.txt,.text,.jpg,.jpeg,.png,application/pdf,text/plain,image/jpeg,image/png" disabled={locked} onChange={event => { const next = event.target.files?.[0]; setFile(next); if (next && !title) setTitle(next.name.replace(/\.[^.]+$/, '')); }} />{existing && <p className="caption">Expected working revision: {existing.revision_number}. The previous stored bytes remain immutable; this is a new working revision.</p>}<p className="caption">PDF, plain text, JPEG or PNG · Up to 10 MiB. Images have no OCR or image interpretation. Retrieval follows the actual scan policy and current source permissions.</p></div></Dialog>;
}
