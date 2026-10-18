import type * as C from './api/closeout.generated';

export const categories = ['commissioning', 'punch', 'om', 'warranty', 'training', 'asset_handover'] as const;
export type Category = typeof categories[number];
export const categoryLabels: Record<Category, string> = { commissioning: 'Commissioning test', punch: 'Punch item', om: 'Operations and maintenance manual', warranty: 'Warranty', training: 'Training', asset_handover: 'Asset handover' };
export const requiredLink: Partial<Record<Category, C.CloseoutLink['kind']>> = { commissioning: 'engineering_check', punch: 'quality_closure', om: 'document_adoption', warranty: 'document_adoption' };
export type Actor = { user: string; personId: string };
export type Scope = { company: string; project: string };
export const closeoutPath = (project: string, id?: string) => `/projects/${encodeURIComponent(project)}/closeout${id ? '/' + encodeURIComponent(id) : ''}`;
export function sameActor(a: Actor & Scope, b: Actor & Scope) { return a.company === b.company && a.project === b.project && a.user === b.user && a.personId === b.personId; }
export function independent(actor: Actor, record: { author_person: string }) { return Boolean(actor.personId && record.author_person && actor.personId !== record.author_person); }
export function currentRequirements(revision: C.CloseoutPackageRevision, requirements: C.CloseoutRequirement[]) {
  return revision.requirements.map(ref => requirements.find(row => row.id === ref.id)).filter((row): row is C.CloseoutRequirement => Boolean(row));
}
export function requirementStanding(header: C.CloseoutHeader, requirement: C.CloseoutRequirement, results: C.CloseoutResult[]) {
  const head = header.result_heads.find(ref => ref.requirement_id === requirement.id);
  const result = head && results.find(row => row.id === head.result_id && row.requirement_id === requirement.id && row.package_revision === header.current_revision);
  const acceptance = result && header.accepted_results.find(ref => ref.requirement_id === requirement.id && ref.result_id === result.id);
  return { result, acceptance, satisfied: Boolean(result?.definition.outcome === 'pass' && acceptance), label: !result ? 'No result' : result.definition.outcome === 'fail' ? 'Failed' : acceptance ? 'Passed · Reviewed' : 'Passed · Review needed' };
}
export function turnoverBlocked(header: C.CloseoutHeader, requirements: C.CloseoutRequirement[], results: C.CloseoutResult[]) {
  return requirements.filter(row => row.required && !requirementStanding(header, row, results).satisfied);
}
export function canAcceptResult(actor: Actor, caps: string[], header: C.CloseoutHeader, result: C.CloseoutResult) {
  return header.status !== 'accepted' && caps.includes('closeout.check') && independent(actor, result) && result.package_revision === header.current_revision && result.definition.outcome === 'pass' && header.result_heads.some(ref => ref.requirement_id === result.requirement_id && ref.result_id === result.id) && !header.accepted_results.some(ref => ref.result_id === result.id);
}
export function canAcceptTurnover(actor: Actor, caps: string[], header: C.CloseoutHeader, revision: C.CloseoutPackageRevision, turnover: C.CloseoutTurnover) {
  return header.status === 'assembled' && caps.includes('closeout.accept') && independent(actor, revision) && independent(actor, turnover) && header.turnover_head === turnover.id && header.current_revision === turnover.package_revision && header.accepted_turnover !== turnover.id;
}
export function resultFields(category: Category) {
  return ({ commissioning: ['test_method', 'observed_result', 'acceptance_criteria_as_recorded'], punch: [], om: ['manual_title', 'manual_revision_as_recorded'], warranty: ['manufacturer', 'warranty_identifier', 'starts_on', 'expires_on'], training: ['attendees_as_recorded'], asset_handover: ['asset_tag', 'serial_number', 'recipient_as_recorded'] } as const)[category];
}
export const fieldLabels: Record<string, string> = { title: 'Title', description: 'Description', asset_tag: 'Asset tag', location: 'Location', notes: 'Result notes', performed_on: 'Performed on', performed_by: 'Performed by', test_method: 'Test method', observed_result: 'Observed result', acceptance_criteria_as_recorded: 'Pass criteria', manual_title: 'Manual title', manual_revision_as_recorded: 'Manual revision', manufacturer: 'Manufacturer', warranty_identifier: 'Warranty reference', starts_on: 'Warranty start date', expires_on: 'Warranty end date', attendees_as_recorded: 'Attendees', serial_number: 'Serial number', recipient_as_recorded: 'Recipient' };
