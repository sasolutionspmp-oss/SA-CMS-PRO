import type { ComIssue } from './api/commercial.generated';
import type { DistAttachment, DistInstruction, DistRecipient, DistDispatchDetail, DistRecipientDelivery } from './api/distribution.generated';
export const digestPattern = /^[a-f0-9]{64}$/;
export const uuidPattern = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
export function sameRecipients(a: DistRecipient[], b: DistRecipient[]) {
  return Array.isArray(a) && Array.isArray(b) && a.length === b.length && a.every((row, index) => row && b[index] && row.id === b[index].id && row.name === b[index].name && row.email === b[index].email && row.organization === b[index].organization);
}
export function sameAttachment(a: DistAttachment | undefined, b: DistAttachment | undefined) {
  return Boolean(a && b && a.revision_id === b.revision_id && a.document_id === b.document_id && a.sha256 === b.sha256 && a.byte_length === b.byte_length && a.media_type === 'application/pdf' && b.media_type === 'application/pdf');
}
export function matchesInstruction(value: DistInstruction | undefined, company: string, issue: ComIssue | undefined) {
  if (!value || !issue || issue.company !== company || value.company !== company || value.scope_type !== 'Company' || value.project !== null || value.issue_id !== issue.id || !uuidPattern.test(value.id) || value.mode !== 'fixture' || value.profile?.id !== 'local-fixture-v1' || value.profile.mode !== 'fixture' || !digestPattern.test(value.issue_digest) || !digestPattern.test(value.message_digest) || !digestPattern.test(value.cover_digest) || !Array.isArray(value.recipients) || !value.recipients.length || value.recipients.length > 30 || new Set(value.recipients.map(row => row?.id)).size !== value.recipients.length || typeof value.message?.subject !== 'string' || typeof value.message.body !== 'string') return false;
  const prepared = issue.prepared_output;
  if (!sameAttachment(value.attachment, { revision_id: prepared.revision_id, document_id: prepared.document_id, sha256: prepared.source_sha256, byte_length: prepared.byte_length, media_type: 'application/pdf' })) return false;
  return value.recipients.every(row => row && digestPattern.test(row.id) && prepared.binding.recipients.some(original => row.name === original.name && row.email === original.email && row.organization === original.organization));
}
export function matchesDispatch(value: DistDispatchDetail | undefined, company: string, issueId: string, dispatchId?: string) {
  return Boolean(value && value.mode === 'fixture' && value.dispatch?.mode === 'fixture' && value.dispatch.company === company && value.dispatch.scope_type === 'Company' && value.dispatch.project === null && value.dispatch.issue_id === issueId && (!dispatchId || value.dispatch.id === dispatchId) && Array.isArray(value.deliveries) && value.deliveries.length <= 30 && value.deliveries.every(row => row && row.mode === 'fixture' && digestPattern.test(row.recipient_id)));
}
export function acknowledgment(delivery: DistRecipientDelivery, instruction: DistInstruction) {
  const result = delivery.receipt;
  if (!instruction.recipients.some(row => row.id === delivery.recipient_id) || delivery.state !== 'Succeeded' || !result || result.mode !== 'fixture' || !('receipt' in result)) return;
  const receipt = result.receipt;
  if (!digestPattern.test(delivery.logical_key || '') || !digestPattern.test(delivery.payload_hash || '') || !receipt || receipt.logical_key !== delivery.logical_key || receipt.payload_hash !== delivery.payload_hash || receipt.mode !== 'fixture' || receipt.attachment_sha256 !== instruction.attachment.sha256 || receipt.byte_length !== instruction.attachment.byte_length || !digestPattern.test(receipt.logical_key) || !digestPattern.test(receipt.payload_hash) || !receipt.acknowledgment_id || !receipt.accepted_at) return;
  return receipt;
}
export const dispatchLabel = (state: string) => ({ SucceededFixture: 'Fixture acknowledgments recorded', PartiallySucceeded: 'Partially acknowledged fixture', Unknown: 'Awaiting fixture readback', Claimed: 'Fixture attempt in progress', Succeeded: 'Fixture acknowledgment recorded', Queued: 'Queued fixture', Cancelled: 'Cancelled', Failed: 'Failed' }[state] || state);

export function matchesDistributionEffect(effect: unknown, packet: { company: string; id: string; subject: { id: string }; source_version: string; manifest_hash: string; review_manifest?: { sources: { [key: string]: unknown }[] } }) {
  if (!effect || typeof effect !== 'object') return false;
  const value = effect as { dispatch?: { id?: string; company?: string; scope_type?: string; project?: unknown; instruction_id?: string; instruction_digest?: string; issue_id?: string; packet_id?: string; packet_manifest_hash?: string; mode?: string }; mode?: string; delivery_status?: string }; const dispatch = value.dispatch; const source = packet.review_manifest?.sources.find(row => row && typeof row.issue_id === 'string');
  return Boolean(dispatch && uuidPattern.test(dispatch.id || '') && dispatch.company === packet.company && dispatch.scope_type === 'Company' && dispatch.project === null && dispatch.instruction_id === packet.subject.id && source && dispatch.issue_id === source.issue_id && dispatch.instruction_digest === packet.source_version && dispatch.packet_id === packet.id && dispatch.packet_manifest_hash === packet.manifest_hash && dispatch.mode === 'fixture' && value.mode === 'fixture' && value.delivery_status === 'Queued');
}

export function matchesDeliveryInventory(data: DistDispatchDetail | undefined, instruction: DistInstruction | undefined, version: string | undefined, company: string, issueId: string, dispatchId: string) {
  return Boolean(data && instruction && matchesDispatch(data, company, issueId, dispatchId) && instruction.company === company && instruction.issue_id === issueId && data.dispatch.instruction_id === instruction.id && data.dispatch.instruction_digest === version && data.deliveries.length === instruction.recipients.length && new Set(data.deliveries.map(row => row.operation_id)).size === data.deliveries.length && new Set(data.deliveries.map(row => row.recipient_id)).size === instruction.recipients.length && data.deliveries.every(row => instruction.recipients.some(recipient => recipient.id === row.recipient_id)));
}
