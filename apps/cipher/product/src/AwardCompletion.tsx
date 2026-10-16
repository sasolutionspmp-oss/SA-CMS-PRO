import { Link, MessageStrip, Title } from '@ui5/webcomponents-react';
import type { AwHandoffResponse, AwPlanResponse } from './api/awards.generated';
import { companyApprovals } from './api/company-approvals';
import { ApiError } from './api/client';
import { awardExecutionExpectation, matchesAwardAdoption } from './award-governance';
import { sameAwardIntent } from './award-draft';
import { useResource } from './hooks';
import { Fact, Failure, Loading } from './components';

export default function AwardCompletion({ record, plan, navigate }: { record: AwHandoffResponse; plan: AwPlanResponse; navigate: (path: string) => void }) {
  const adoption = record.adoption;
  const review = useResource(adoption ? `${record.handoff.company}/award-consumed-review/${adoption.packet_id}` : null, async signal => {
    const packet = await companyApprovals.read(record.handoff.company, adoption!.packet_id, signal);
    if (packet.id !== adoption!.packet_id || packet.company !== record.handoff.company || packet.state !== 'Consumed') throw new ApiError('The recorded award does not match its original reviewed plan.', 'INVALID_CONTRACT', 200);
    return packet;
  });
  if (!adoption) return null;
  if (review.loading) return <Loading label="Verifying the recorded Company award and original review…" />;
  if (review.error) return <Failure error={review.error} onRetry={review.refresh} />;
  if (!review.data) return null;
  // The immutable review can stay cached while current authorized handoff/plan props refresh.
  // Validate those current props on every render before exposing a positive completion.
  const binding = awardExecutionExpectation(review.data);
  if (!binding || review.data.id !== adoption.packet_id || review.data.company !== record.handoff.company || review.data.state !== 'Consumed' || adoption.id !== record.handoff.adoption || binding.plan_digest !== plan.version || !sameAwardIntent(binding.plan, plan.plan) || !binding.granted_decisions.includes(adoption.decision_id) || !matchesAwardAdoption(adoption, binding)) return <Failure error={new ApiError('The recorded award does not match its original reviewed plan.', 'INVALID_CONTRACT', 200)} />;
  const access = record.project_access; const native = adoption.native_snapshot.projection.header;
  return <section className="surface estimate-section-pad" aria-label="Recorded Company award"><MessageStrip design="Positive" hideCloseButton>Project award recorded against the exact independently approved plan.</MessageStrip><Title level="H2">{plan.plan.definition.project_definition.project_name}</Title><div className="project-facts"><Fact label="Created Project reference">{adoption.target_project}</Fact><Fact label="Sales Order at award">{adoption.sales_order} · Draft</Fact><Fact label="Contract at award">{plan.plan.definition.contract_definition.number} · Draft</Fact><Fact label="Accepted cost budget">{plan.plan.controls_plan.currency} {plan.plan.controls_plan.totals.total.amount}</Fact></div><p>Saved selling value: {native.currency} {native.grand_total}. Initial team: {adoption.team.length} people.</p>
    {access.standing === 'available' && access.project_id === adoption.target_project ? <Link href={`/projects/${encodeURIComponent(adoption.target_project)}`} onClick={event => { event.preventDefault(); navigate(`/projects/${encodeURIComponent(adoption.target_project)}`); }}>Open currently authorized Project</Link> : <MessageStrip design="Information" hideCloseButton>This Project is outside your current access. Your authorized Company award references remain available here.</MessageStrip>}
    <p className="caption">These are the recorded draft states at award. Project content is read separately with current Project authorization; this Company outcome does not grant access or submit native records.</p><Link href={`/company/work/${encodeURIComponent(adoption.packet_id)}?company=${encodeURIComponent(record.handoff.company)}`}>Open original award approval</Link><details><summary>Recorded award lineage</summary><p>Adoption {adoption.id} · Plan {adoption.award_revision}</p><p>Contract {adoption.contract} · Budget {adoption.budget}</p><p>Issue {adoption.issue}</p><code>{adoption.issue_digest}</code><p>Approved plan</p><code>{adoption.plan_digest}</code><p>Cost plan</p><code>{adoption.controls_plan_digest}</code><p>Native reconciliation</p><code>{adoption.native_digest}</code><p>Original operation {adoption.operation_id}</p></details>
  </section>;
}
