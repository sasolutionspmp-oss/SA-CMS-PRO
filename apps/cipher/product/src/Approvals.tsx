import { useRef, useState } from 'react';
import { Bar, Button, CheckBox, Dialog, Label, MessageStrip, Option, Select, Table, TableCell, TableHeaderCell, TableHeaderRow, TableRow, TextArea, Title, Toolbar, ToolbarSpacer } from '@ui5/webcomponents-react';
import { api, ApiError } from './api/client';
import type { ApprovalPacket, Project } from './api/types';
import { Empty, Fact, Failure, Loading, Pagination, Status } from './components';
import { useResource } from './hooks';

const timestamp = (value: string) => new Intl.DateTimeFormat('en-US', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value));

export default function Approvals({ project, onEffect }: { project: Project; onEffect: () => void }) {
  const [cursor, setCursor] = useState<string>();
  const [pages, setPages] = useState<(string | undefined)[]>([]);
  const packets = useResource(`${project.company}/${project.id}/approvals/${project.version}/${cursor ?? ''}`, signal => api.approvals(project.company, project.id, signal, cursor));
  const [requestOpen, setRequestOpen] = useState(false);
  const [selected, setSelected] = useState<string>();
  const [notice, setNotice] = useState('');
  return <>
    <Toolbar design="Transparent"><Title level="H2">Approval inbox</Title><ToolbarSpacer /><Button icon="refresh" onClick={packets.refresh}>Refresh approvals</Button>{project.capabilities?.includes('approval.request') && <Button design="Emphasized" disabled={! ['Open', 'On hold'].includes(project.status)} title={['Open', 'On hold'].includes(project.status) ? 'Create an independently reviewed status request' : 'Closed projects cannot be reopened through this approval policy'} onClick={() => setRequestOpen(true)}>Request status change</Button>}</Toolbar>
    {notice && <MessageStrip design="Positive" onClose={() => setNotice('')}>{notice}</MessageStrip>}
    {packets.loading ? <Loading label="Loading approval packets…" /> : packets.error ? <Failure error={packets.error} onRetry={packets.refresh} /> : packets.data?.items.length ? <Table accessibleName="Project approvals" headerRow={<TableHeaderRow><TableHeaderCell minWidth="14rem">Requested change</TableHeaderCell><TableHeaderCell width="9rem">State</TableHeaderCell><TableHeaderCell minWidth="10rem">Requested by</TableHeaderCell><TableHeaderCell width="10rem">Review</TableHeaderCell></TableHeaderRow>}>
      {packets.data.items.map(packet => <TableRow key={packet.id} rowKey={packet.id}><TableCell><div className="record-cell"><strong>{packet.changes.status.from} → {packet.changes.status.to}</strong><span>{timestamp(packet.created_at)}</span></div></TableCell><TableCell><Status value={packet.state === 'Consumed' ? 'Executed' : packet.state} /></TableCell><TableCell>{packet.requester.display_name}</TableCell><TableCell><Button onClick={() => setSelected(packet.id)}>Review packet</Button></TableCell></TableRow>)}
    </Table> : <Empty title="No approval requests" icon="task">Project status changes require an independently reviewed packet before execution.</Empty>}
    <Pagination next={packets.data?.next_cursor} total={packets.data?.total} page={pages.length + 1} previous={Boolean(pages.length)} onNext={() => { if (packets.data?.next_cursor) { setPages([...pages, cursor]); setCursor(packets.data.next_cursor); } }} onPrevious={() => { setCursor(pages[pages.length - 1]); setPages(pages.slice(0, -1)); }} />
    {requestOpen && <RequestStatus project={project} onClose={() => setRequestOpen(false)} onSourceChanged={onEffect} onRequested={packet => { setRequestOpen(false); setSelected(packet.id); setCursor(undefined); setPages([]); packets.refresh(); setNotice('Status change requested. The project has not changed.'); }} />}
    {selected && <ReviewPacket project={project} packetId={selected} onClose={() => setSelected(undefined)} onChanged={effect => { packets.refresh(); if (effect) onEffect(); }} />}
  </>;
}

function RequestStatus({ project, onClose, onRequested, onSourceChanged }: { project: Project; onClose: () => void; onSourceChanged: () => void; onRequested: (packet: ApprovalPacket) => void }) {
  const [status, setStatus] = useState(project.status === 'Open' ? 'On hold' : 'Open');
  const [operationId, setOperationId] = useState(() => crypto.randomUUID());
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<ApiError>();
  const submit = async () => {
    if (saving) return;
    setSaving(true); setError(undefined);
    try { const result = await api.requestStatus({ company: project.company, project: project.id, status, expected_version: project.version, operation_id: operationId }); onRequested(result.packet); }
    catch (failure) { setError(failure as ApiError); }
    finally { setSaving(false); }
  };
  return <Dialog open headerText="Request project status change" className="form-dialog" onClose={() => { if (!saving) onClose(); }} footer={<Bar design="Footer" endContent={<><Button design="Emphasized" disabled={saving || status === project.status} onClick={submit}>{saving ? 'Requesting…' : 'Submit approval request'}</Button><Button disabled={saving} onClick={onClose}>Cancel</Button></>} />}><div className="dialog-form">
    <p>{project.name}</p>{error && <><Failure error={error} />{error.status === 412 && <Button onClick={() => { onClose(); onSourceChanged(); }}>Refresh project before requesting again</Button>}</>}<Fact label="Current status"><Status value={project.status} /></Fact>
    <Label for="requested-project-status" required>Requested status</Label><Select id="requested-project-status" accessibleName="Requested project status" onChange={event => { setStatus(event.detail.selectedOption.value!); setOperationId(crypto.randomUUID()); setError(undefined); }}>{['Open', 'On hold', 'Completed', 'Cancelled'].map(value => <Option key={value} value={value} selected={status === value}>{value}</Option>)}</Select>
    <MessageStrip design="Information" hideCloseButton>This creates an approval packet. A different person must review it before an authorized person executes the change. Project tasks are not changed.</MessageStrip><p className="caption">The packet includes the resulting native completion percentage. Completed status requires all project tasks to be terminal. The server checks the source version and policy again at execution.</p>
  </div></Dialog>;
}

function ReviewPacket({ project, packetId, onClose, onChanged }: { project: Project; packetId: string; onClose: () => void; onChanged: (effect: boolean) => void }) {
  const resource = useResource(`${project.company}/${project.id}/${packetId}`, signal => api.approval(project.company, project.id, packetId, signal));
  const [reviewed, setReviewed] = useState(false);
  const [reason, setReason] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<ApiError>();
  const [notice, setNotice] = useState('');
  const operations = useRef(new Map<string, string>());
  const packet = resource.data;
  const act = async (action: 'Grant' | 'Reject' | 'execute' | 'withdraw') => {
    if (!packet || saving) return;
    const key = JSON.stringify([packet.id, packet.manifest_hash, action, action === 'execute' ? '' : reason.trim()]);
    if (!operations.current.has(key)) operations.current.set(key, crypto.randomUUID());
    setSaving(true); setError(undefined); setNotice('');
    try {
      await api.approvalAction(action, { company: project.company, project: project.id, packet_id: packet.id, manifest_hash: packet.manifest_hash, reason: reason.trim(), operation_id: operations.current.get(key)! });
      setReviewed(false); setReason(''); resource.refresh(); onChanged(action === 'execute');
      setNotice(action === 'execute' ? 'The approved status change was executed.' : action === 'Grant' ? 'Approval granted. Execution is a separate action.' : action === 'Reject' ? 'Approval request rejected.' : 'Approval request withdrawn.');
    } catch (failure) {
      const problem = failure as ApiError; setError(problem);
      if ([403, 404, 409, 412].includes(problem.status)) { setReviewed(false); resource.refresh(); }
    }
    finally { setSaving(false); }
  };
  return <Dialog open headerText="Review approval packet" className="approval-dialog" onClose={() => { if (!saving) onClose(); }} footer={<Bar design="Footer" endContent={<Button disabled={saving} onClick={onClose}>Close review</Button>} />}>
    {resource.loading ? <Loading label="Loading exact approval packet…" /> : resource.error ? <Failure error={resource.error} onRetry={resource.refresh} /> : packet && <div className="dialog-form">
      <div className="approval-heading"><Title level="H3">{packet.subject.label}</Title><Status value={packet.state === 'Consumed' ? 'Executed' : packet.state} /></div>
      {error && <Failure error={error} />}{notice && <MessageStrip design="Positive" hideCloseButton>{notice}</MessageStrip>}
      <div className="approval-change"><Fact label="Status at request">{packet.changes.status.from}</Fact><span aria-hidden="true">→</span><Fact label="Requested status">{packet.changes.status.to}</Fact></div>
      <dl className="approval-metadata"><dt>Requested by</dt><dd>{packet.requester.display_name}</dd><dt>Expires</dt><dd>{timestamp(packet.expires_at)}</dd><dt>Policy</dt><dd>{packet.policy.label}{packet.policy.synthetic ? ' · Synthetic' : ''}</dd><dt>Resulting completion</dt><dd>{packet.native_completion.percent_complete}% · {packet.native_completion.percent_complete_method || 'Task Completion'}</dd><dt>Tasks reviewed</dt><dd>{packet.task_effects.count}</dd><dt>Task changes</dt><dd>{packet.task_effects.changes.length ? `${packet.task_effects.changes.length} reported changes` : 'None — project status only'}</dd></dl>
      <details><summary>Packet integrity</summary><p className="caption">Packet {packet.id}</p><p className="caption">Source version: {packet.source_version}</p><code className="packet-hash">{packet.manifest_hash}</code></details>
      {packet.decisions.length > 0 && <div><Title level="H4">Decision history</Title><ol className="approval-decisions">{packet.decisions.map(decision => <li key={decision.id}><strong>{decision.decision}</strong> · {decision.actor.display_name}<span className="caption">{timestamp(decision.at)}</span>{decision.reason && <p>{decision.reason}</p>}</li>)}</ol></div>}
      {packet.actions.disabled_reason && <MessageStrip design="Information" hideCloseButton>{packet.actions.disabled_reason}</MessageStrip>}
      {(packet.actions.can_decide || packet.actions.can_execute || packet.actions.can_withdraw) && <>
        <Label for="approval-reason">Decision or withdrawal note (optional)</Label><TextArea id="approval-reason" accessibleName="Approval decision note" rows={2} value={reason} onInput={event => { setReason(event.currentTarget!.value); setError(undefined); }} />
        {(packet.actions.can_decide || packet.actions.can_execute) && <CheckBox text="I reviewed this exact change and its source" accessibleName="I reviewed this exact change and its source" checked={reviewed} onChange={event => setReviewed(event.currentTarget!.checked)} />}
        <div className="approval-actions">{packet.actions.can_decide && <><Button design="Emphasized" disabled={saving || !reviewed} onClick={() => act('Grant')}>Grant approval</Button><Button design="Negative" disabled={saving || !reviewed} onClick={() => act('Reject')}>Reject request</Button></>}{packet.actions.can_execute && <Button design="Emphasized" disabled={saving || !reviewed} onClick={() => act('execute')}>Execute approved change</Button>}{packet.actions.can_withdraw && <Button disabled={saving} onClick={() => act('withdraw')}>Withdraw request</Button>}</div>
      </>}
    </div>}
  </Dialog>;
}
