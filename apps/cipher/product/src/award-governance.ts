import type { CompanyApprovalPacket } from './api/contracts.generated';
import type { AwAdoption, AwAwardEffect, AwPlan } from './api/awards.generated';
import { sameAwardIntent } from './award-draft';
import { nativePaymentPolicy } from './award-contract';

const sha = /^[a-f0-9]{64}$/;
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
export interface AwardReviewBinding { plan: AwPlan; plan_digest: string; controls_plan_digest: string }
export interface AwardExecutionExpectation extends AwardReviewBinding { packet_id: string; granted_decisions: string[] }

export function awardReviewBinding(packet: CompanyApprovalPacket): AwardReviewBinding | undefined {
  if (packet.action !== 'award.project.create.v1' || packet.subject.type !== 'Cipher Award Handoff Revision') return;
  try {
    const effect = packet.review_manifest.effect; const plan = effect.plan as AwPlan;
    if (effect.action !== packet.action || effect.award_revision_id !== packet.subject.id || plan?.id !== packet.subject.id || plan.schema !== 'cipher.award.plan.v1' || plan.company !== packet.company || plan.scope_type !== 'Company' || plan.project !== null || effect.award_id !== plan.handoff || effect.plan_digest !== packet.source_version || !sha.test(String(effect.plan_digest)) || !sha.test(String(effect.controls_plan_digest)) || packet.review_manifest.subject.name !== packet.subject.id || packet.review_manifest.subject.doctype !== packet.subject.type) return;
    if (plan.issue !== plan.definition.issue_id || plan.source_facts.issue_digest !== plan.issue_digest || plan.source_facts.native_sources?.payment_schedule_policy !== nativePaymentPolicy || !sha.test(plan.issue_digest) || plan.controls_plan.company !== packet.company || plan.controls_plan.acceptance.id !== plan.source_facts.accepted_estimate.acceptance_id || plan.controls_plan.acceptance.digest !== plan.source_facts.accepted_estimate.acceptance_digest || !sameAwardIntent(effect.initial_team, plan.definition.team) || plan.ids.id !== plan.id || !uuid.test(plan.ids.adoption_id) || !uuid.test(plan.ids.contract_id) || !uuid.test(plan.ids.profile_id)) return;
    if (!Array.isArray(plan.lines) || !plan.lines.length || new Set(plan.lines.map(line => line.proposal_line_id)).size !== plan.lines.length || plan.lines.some(line => plan.ids.line_ids[line.proposal_line_id] !== line.award_line_id)) return;
    const output = plan.source_facts.issued_output;
    if (!output?.revision_id || !output.document_id || !sha.test(output.source_sha256) || !Number.isInteger(output.byte_length) || output.byte_length < 1 || !Array.isArray(plan.definition.team.members) || !plan.definition.team.members.length || !Array.isArray(plan.controls_plan.budget_lines) || !Array.isArray(plan.source_facts.award_evidence)) return;
    return { plan, plan_digest: String(effect.plan_digest), controls_plan_digest: String(effect.controls_plan_digest) };
  } catch { return; }
}
export function awardExecutionExpectation(packet: CompanyApprovalPacket): AwardExecutionExpectation | undefined {
  const binding = awardReviewBinding(packet); if (!binding) return;
  const latest = packet.decisions.at(-1);
  return structuredClone({ ...binding, packet_id: packet.id, granted_decisions: latest?.decision === 'Grant' && latest.actor.id !== packet.requester.id ? [latest.id] : [] });
}
export function matchesAwardAdoption(adoption: AwAdoption, expected: AwardReviewBinding): boolean {
  try {
    const plan = expected.plan; const binding = adoption.effect_binding; const native = adoption.native_snapshot; const header = native?.projection.header;
    if (adoption.schema !== 'cipher.award.adoption.v1' || adoption.scope_type !== 'Company' || adoption.project !== null || adoption.company !== plan.company || adoption.status !== 'adopted' || adoption.id !== plan.ids.adoption_id || adoption.handoff !== plan.handoff || adoption.award_revision !== plan.id || adoption.plan_digest !== expected.plan_digest || adoption.controls_plan_digest !== expected.controls_plan_digest || adoption.issue !== plan.issue || adoption.issue_digest !== plan.issue_digest || adoption.pursuit !== plan.source_facts.pursuit || adoption.opportunity !== plan.source_facts.opportunity || adoption.contract !== plan.ids.contract_id || adoption.profile !== plan.ids.profile_id || !uuid.test(adoption.budget) || !adoption.target_project || !adoption.sales_order) return false;
    if (!sameAwardIntent(adoption.accepted_estimate, plan.source_facts.accepted_estimate) || !sameAwardIntent(adoption.team, plan.definition.team.members) || !Array.isArray(adoption.line_adoptions) || new Set(adoption.line_adoptions).size !== plan.lines.length || adoption.line_adoptions.length !== plan.lines.length || plan.lines.some(line => !adoption.line_adoptions.includes(line.award_line_id))) return false;
    if (binding.company !== plan.company || binding.project !== adoption.target_project || binding.award_id !== plan.handoff || binding.award_revision_id !== plan.id || binding.plan_digest !== expected.plan_digest || binding.packet_id !== adoption.packet_id || binding.decision_id !== adoption.decision_id || binding.operation_id !== adoption.operation_id) return false;
    if (!sha.test(adoption.native_digest) || adoption.native_digest !== native.digest || native.derived_digest !== native.digest || adoption.native_version !== native.version || header.company !== plan.company || header.project !== adoption.target_project || header.name !== adoption.sales_order || header.docstatus !== 0 || header.cipher_award_handoff !== plan.handoff || header.cipher_issue !== plan.issue || header.cipher_issue_digest !== plan.issue_digest || header.cipher_accepted_baseline !== plan.source_facts.accepted_estimate.acceptance_id) return false;
    const rows = native.projection.rows;
    return Array.isArray(rows) && rows.length === plan.lines.length && new Set(rows.map(row => row.cipher_award_line_id)).size === plan.lines.length && plan.lines.every(line => rows.some(row => row.cipher_award_line_id === line.award_line_id && row.cipher_proposal_line_id === line.proposal_line_id && row.item_code === line.item_code));
  } catch { return false; }
}
export function matchesAwardEffect(effect: unknown, expected: AwardExecutionExpectation | undefined, operationId: string): boolean {
  if (!effect || typeof effect !== 'object' || !expected) return false;
  const value = effect as AwAwardEffect; const adoption = value.adoption;
  return Boolean(adoption && sha.test(value.version) && adoption.packet_id === expected.packet_id && expected.granted_decisions.includes(adoption.decision_id) && adoption.operation_id === operationId && adoption.author_person === expected.plan.author_person && matchesAwardAdoption(adoption, expected));
}
