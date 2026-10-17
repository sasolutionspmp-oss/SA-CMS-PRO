import type { AwDefinition, AwHandoffResponse, AwPlan, AwPlanPreview, AwPlanResponse, AwSourcePreview, ComAcceptedEstimate } from './api/awards.generated';
import { sameAwardIntent } from './award-draft';

const checksum = /^[a-f0-9]{64}$/;
export const nativePaymentPolicy = 'native-default-100-percent-transaction-date-v1';
export function matchesHandoff(data: AwHandoffResponse, company: string, id?: string) {
  return Boolean(data?.handoff?.id && (!id || data.handoff.id === id) && data.handoff.company === company && data.handoff.scope_type === 'Company' && data.handoff.project === null && checksum.test(data.version) && data.availability?.action === 'award.project.create.v1' && typeof data.availability.action_available === 'boolean' && ['not_created', 'available', 'not_available'].includes(data.project_access?.standing));
}
export function matchesAwardSource(data: AwSourcePreview, company: string, issueId: string) {
  const baseline = data?.accepted_baseline; const accepted = data?.issue?.accepted_estimate;
  const output = data?.issue?.prepared_output;
  if (!output || output.company !== company || output.proposal_revision_id !== data.issue.proposal_revision || output.revision_id !== data.issue.output_revision || !checksum.test(output.source_sha256) || !Number.isInteger(output.page_count) || output.page_count < 1) return false;
  return Boolean(data?.company === company && data.issue?.id === issueId && data.issue.company === company && data.issue.status === 'issued' && checksum.test(data.issue_digest) && baseline?.company === company && baseline.project === null && baseline.scope_type === 'Company' && baseline.status === 'accepted' && baseline.id === accepted?.acceptance_id && baseline.estimate_revision === accepted.revision_id && baseline.calculation_snapshot === accepted.snapshot_id && checksum.test(data.accepted_baseline_digest) && data.accepted_baseline_digest === accepted.acceptance_digest && data.pursuit?.id === accepted.pursuit_id && data.pursuit.company === company && data.input_qualification?.policy === 'qualified-original-estimate-inputs-v1' && typeof data.input_qualification.eligible === 'boolean' && data.availability?.action === 'award.project.create.v1' && typeof data.availability.action_available === 'boolean' && (data.handoff === null || matchesHandoff(data.handoff, company)));
}
export function matchesAwardPlan(data: AwPlanResponse, company: string, handoffId: string, issueId: string, revisionId: string) {
  const plan = data?.plan;
  return Boolean(plan?.id === revisionId && plan.company === company && plan.scope_type === 'Company' && plan.project === null && plan.handoff === handoffId && plan.issue === issueId && plan.definition?.issue_id === issueId && plan.controls_plan?.company === company && plan.source_facts?.native_sources?.payment_schedule_policy === nativePaymentPolicy && checksum.test(data.version));
}
export interface AwardExpectedSource {
  // The server's immutable Issue digest binds its original proposal revision.
  // No direct revision comparison or browser-derived digest is claimed here.
  issue_id: string; issue_digest: string;
  output: { document_id: string; revision_id: string; source_sha256: string; byte_length: number; input_digest: string };
  accepted: ComAcceptedEstimate;
  selling_lines: { id: string; quantity: string; rate: string; amount: string; unit_id: string; unit_revision: number }[];
}
export function awardExpectedSource(source: AwSourcePreview): AwardExpectedSource {
  const output = source.issue.prepared_output;
  return structuredClone({ issue_id: source.issue.id, issue_digest: source.issue_digest,
    output: { document_id: output.document_id, revision_id: output.revision_id, source_sha256: output.source_sha256, byte_length: output.byte_length, input_digest: output.input_digest },
    accepted: source.issue.accepted_estimate, selling_lines: source.issue.selected_lines.map(row => ({ id: row.line.id, quantity: row.line.quantity, rate: row.line.rate, amount: row.line.amount, unit_id: row.line.unit_id, unit_revision: row.line.unit_revision })) });
}
export function matchesPlanIntent(plan: AwPlan | AwPlanPreview, company: string, definition: AwDefinition, expected: AwardExpectedSource) {
  const controls = plan?.controls_plan; const facts = plan?.source_facts; const accepted = expected.accepted;
  if (plan?.issue !== expected.issue_id || plan.issue !== definition.issue_id || plan.issue_digest !== expected.issue_digest || facts?.issue_digest !== expected.issue_digest || facts?.native_sources?.payment_schedule_policy !== nativePaymentPolicy || !sameAwardIntent(plan.definition, definition) || !sameAwardIntent(facts.accepted_estimate, accepted) || !sameAwardIntent(facts.issued_output, expected.output)) return false;
  if (controls?.company !== company || controls.acceptance?.id !== accepted.acceptance_id || controls.acceptance.digest !== accepted.acceptance_digest || controls.acceptance.estimate_id !== accepted.estimate_id || controls.acceptance.revision_id !== accepted.revision_id || controls.acceptance.snapshot_id !== accepted.snapshot_id || controls.acceptance.manifest_digest !== accepted.manifest_digest) return false;
  if (!Array.isArray(plan.lines) || plan.lines.length !== expected.selling_lines.length || new Set(plan.lines.map(line => line.proposal_line_id)).size !== plan.lines.length) return false;
  return plan.lines.every(line => {
    const original = expected.selling_lines.find(row => row.id === line.proposal_line_id); const mapping = definition.line_mappings.find(row => row.proposal_line_id === line.proposal_line_id);
    return Boolean(original && mapping && line.quantity === original.quantity && line.rate === original.rate && line.amount === original.amount && line.unit?.id === original.unit_id && line.unit.revision === original.unit_revision && line.item_code === mapping.item_code && line.delivery_date === mapping.delivery_date && line.currency === accepted.currency);
  });
}
