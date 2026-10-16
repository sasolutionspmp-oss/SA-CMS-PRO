import type { AwDefinition, AwSourcePreview, AwDelegationPolicyResponse, PcAllocation, PcWbsNode } from './api/awards.generated';

export type AwardDraft = Omit<AwDefinition, 'line_mappings' | 'award_evidence' | 'wbs_nodes' | 'budget_allocations' | 'team'> & {
  line_mappings: AwDefinition['line_mappings'][number][];
  award_evidence: AwDefinition['award_evidence'][number][];
  wbs_nodes: PcWbsNode[];
  budget_allocations: PcAllocation[];
  team: Omit<AwDefinition['team'], 'members'> & { members: AwDefinition['team']['members'][number][] };
};
export function costSources(source: AwSourcePreview) {
  const result = source.accepted_baseline.accepted_result;
  return [
    ...result.lines.filter(line => line.included).flatMap(line => line.components.map(component => ({
      key: `component/${line.line_id}/${component.component_id}`, label: line.description,
      detail: component.cost_type, amount: component.allocated_amount,
      source: { kind: 'component' as const, line_id: line.line_id, component_id: component.component_id },
    }))),
    ...result.adjustments.map(adjustment => ({ key: `adjustment/${adjustment.line_id}`, label: adjustment.label,
      detail: adjustment.kind, amount: adjustment.amount,
      source: { kind: 'adjustment' as const, adjustment_id: adjustment.line_id },
    })),
  ];
}
export function newAwardDraft(source: AwSourcePreview, policy: AwDelegationPolicyResponse): AwardDraft {
  const issue = source.issue;
  const rootId = crypto.randomUUID();
  return {
    issue_id: issue.id,
    project_definition: { project_name: '', expected_start_date: '', expected_end_date: '' },
    native_order_definition: { customer: source.pursuit.party_type === 'Customer' ? source.pursuit.party_id : '', transaction_date: '', delivery_date: '', selling_price_list: issue.composition.price_list },
    contract_definition: { number: '', kind: 'prime', direction: 'receivable', party_type: 'Customer', party: source.pursuit.party_type === 'Customer' ? source.pursuit.party_id : '', currency: issue.composition.currency, original_value: { currency: issue.composition.currency, amount: issue.pricing.total } },
    line_mappings: issue.selected_lines.map(row => ({ proposal_line_id: row.line.id, item_code: issue.composition.price_lines.find(line => line.id === row.line.id)?.item_code || '', delivery_date: '' })),
    award_evidence: [], party_correspondence: source.pursuit.party_type === 'Lead' ? { lead: source.pursuit.party_id, customer: '', explanation: '' } : null,
    team: { delegator_person: policy.requester_person, policy_id: policy.policy.id, policy_digest: policy.policy.digest, members: [] },
    wbs_nodes: [{ id: rootId, code: '01', parent_id: null, title: '', is_leaf: true, accountable_person: null, phase: '', active_from: null, active_until: null }],
    budget_allocations: costSources(source).map(row => ({ id: crypto.randomUUID(), source: row.source, wbs_id: rootId, code_revision_id: '', type_revision_id: '' })),
  };
}
export function awardProblem(draft: AwardDraft): string {
  const dates = [draft.project_definition.expected_start_date, draft.project_definition.expected_end_date, draft.native_order_definition.transaction_date, draft.native_order_definition.delivery_date, ...draft.line_mappings.map(row => row.delivery_date)];
  if (dates.some(value => { const parsed = new Date(`${value}T12:00:00Z`); return !/^\d{4}-\d{2}-\d{2}$/.test(value) || Number.isNaN(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== value; })) return 'Enter valid ISO dates for the Project, order and each delivery.';
  if (!draft.project_definition.project_name.trim() || !draft.contract_definition.number.trim() || !draft.native_order_definition.customer || !draft.native_order_definition.selling_price_list) return 'Enter the Project name, contract number, existing Customer and selling price list.';
  if (!draft.line_mappings.length || draft.line_mappings.some(row => !row.item_code)) return 'Map every selected selling line to an existing Item.';
  if (!draft.award_evidence.length) return 'Attach at least one exact Company source page as award evidence.';
  if (draft.party_correspondence && !draft.party_correspondence.explanation.trim()) return 'Explain the correspondence between the issued Lead and existing Customer.';
  const members = new Set(draft.team.members.map(member => member.person_id));
  if (!members.size || draft.team.members.some(member => !member.abilities.includes('project.read'))) return 'Select the initial Project team and grant each member Project read access.';
  if (!draft.wbs_nodes.length || draft.wbs_nodes.some(node => !node.code.trim() || !node.title.trim() || (node.accountable_person && !members.has(node.accountable_person)))) return 'Give each WBS node a code and title, with any accountable person selected from the initial team.';
  const leaves = new Set(draft.wbs_nodes.filter(node => node.is_leaf).map(node => node.id));
  if (!draft.budget_allocations.length || draft.budget_allocations.some(row => !leaves.has(row.wbs_id) || !row.code_revision_id || !row.type_revision_id)) return 'Allocate every accepted component and adjustment to a leaf WBS node and exact cost code/type revisions.';
  return '';
}
// The owning authoring contract sorts team identities/abilities. This preserves
// the selected set; it supplies no authority and computes no server digest.
export function awardDefinition(draft: AwardDraft): AwDefinition {
  const copy = structuredClone(draft);
  copy.team.members = copy.team.members.map(member => ({ ...member, abilities: [...member.abilities].sort() as typeof member.abilities })).sort((a, b) => a.person_id.localeCompare(b.person_id));
  return copy as AwDefinition;
}
export function sameAwardIntent(left: unknown, right: unknown): boolean {
  const ordered = (value: unknown): unknown => Array.isArray(value) ? value.map(ordered) : value && typeof value === 'object' ? Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, item]) => [key, ordered(item)])) : value;
  return JSON.stringify(ordered(left)) === JSON.stringify(ordered(right));
}
