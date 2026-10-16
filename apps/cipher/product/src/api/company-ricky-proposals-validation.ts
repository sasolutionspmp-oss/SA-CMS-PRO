import { companyRickyProposalSchema } from './company-ricky-proposals.generated';
import type { CompanyRickyProposalSelection, CompanyRickyProposalRunResponse, CompanyRickyProposalStartResponse, CompanyRickyProposalStopResponse, CompanyRickyProposalEventsResponse, CompanyRickyProposalResponse } from './company-ricky-proposals.generated';
import type { CompanyCitation } from './company-documents.generated';
import { sameSelectedValue } from './company-ricky-validation';

type Shape = { [key: string]: unknown };
const definitions = companyRickyProposalSchema.$defs as unknown as Record<string, Shape>;
const uuid = (value: unknown): value is string => typeof value === 'string' && /^[a-f0-9]{8}-[a-f0-9]{4}-[45][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/.test(value);
const record = (value: unknown): value is Record<string, unknown> => Boolean(value && typeof value === 'object' && !Array.isArray(value));
const closed = (value: unknown, fields: string[]): value is Record<string, unknown> => record(value) && Object.keys(value).length === fields.length && fields.every(key => Object.hasOwn(value, key));
const boundedText = (value: unknown, limit = 2000): value is string => typeof value === 'string' && value.length <= limit;
const sha = (value: unknown): value is string => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
export const suggestionActions = ['aec.scope.draft', 'aec.estimate.draft'] as const;
export const terminalSuggestion = (status: string) => ['waiting-for-review', 'failed', 'cancelled'].includes(status);
export const suggestionPointerKey = (user: string, person: string, company: string) => JSON.stringify(['cipher.company.ricky.proposals.v1', user, person, company]);

// Only the finite keywords present in the generated published contract are
// supported. A future unhandled constraint fails closed rather than disappearing.
function shape(value: unknown, schema: Shape, depth = 0): boolean {
  if (depth > 40) return false;
  const supported = ['$ref', '$id', '$schema', 'type', 'properties', 'required', 'additionalProperties', 'items', 'maxItems', 'minLength', 'maxLength', 'minimum', 'maximum', 'format', 'pattern', 'enum', 'const', 'oneOf', 'anyOf'];
  if (Object.keys(schema).some(key => !supported.includes(key))) return false;
  if (schema.type && !['null','boolean','string','integer','number','array','object'].includes(String(schema.type))) return false;
  if (schema.$ref) { const name = String(schema.$ref).replace(/^#\/\$defs\//, ''); return Boolean(definitions[name] && shape(value, definitions[name], depth + 1)); }
  if (schema.oneOf && (schema.oneOf as Shape[]).filter(branch => shape(value, branch, depth + 1)).length !== 1) return false;
  if (schema.anyOf && !(schema.anyOf as Shape[]).some(branch => shape(value, branch, depth + 1))) return false;
  if (Object.hasOwn(schema, 'const') && !sameSelectedValue(value, schema.const)) return false;
  if (schema.enum && !(schema.enum as unknown[]).some(option => sameSelectedValue(value, option))) return false;
  if (schema.type === 'null' && value !== null || schema.type === 'boolean' && typeof value !== 'boolean' || schema.type === 'string' && typeof value !== 'string' || schema.type === 'integer' && !Number.isSafeInteger(value) || schema.type === 'number' && (typeof value !== 'number' || !Number.isFinite(value))) return false;
  if (schema.type === 'object' && !record(value)) return false;
  if (record(value) && (schema.type === 'object' || schema.properties || schema.required || Object.hasOwn(schema, 'additionalProperties'))) {
    const properties = (schema.properties || {}) as Record<string, Shape>;
    if ((schema.required as string[] || []).some(key => !Object.hasOwn(value, key)) || schema.additionalProperties === false && Object.keys(value).some(key => !Object.hasOwn(properties, key))) return false;
    if (Object.entries(properties).some(([key, child]) => Object.hasOwn(value, key) && !shape(value[key], child, depth + 1))) return false;
  }
  if (schema.type === 'array') {
    if (!Array.isArray(value) || typeof schema.maxItems === 'number' && value.length > schema.maxItems) return false;
    if (schema.items && !value.every(item => shape(item, schema.items as Shape, depth + 1))) return false;
  }
  if (typeof value === 'string') {
    if (typeof schema.minLength === 'number' && [...value].length < schema.minLength || typeof schema.maxLength === 'number' && [...value].length > schema.maxLength || schema.pattern && !new RegExp(String(schema.pattern)).test(value)) return false;
    if (schema.format === 'uuid' && !uuid(value) || schema.format === 'date-time' && (!/T.*(?:Z|[+-]\d{2}:\d{2})$/.test(value) || Number.isNaN(Date.parse(value)))) return false;
    if (schema.format && !['uuid', 'date-time'].includes(String(schema.format))) return false;
  }
  if (typeof value === 'number' && (typeof schema.minimum === 'number' && value < schema.minimum || typeof schema.maximum === 'number' && value > schema.maximum)) return false;
  return true;
}
export const publishedSuggestionShape = (name: keyof typeof companyRickyProposalSchema.$defs, value: unknown) => shape(value, definitions[name]);

export function validSuggestionSelection(value: CompanyRickyProposalSelection): boolean {
  if (!publishedSuggestionShape('CompanyRickyProposalSelection', value) || !value.sources.length || new Set(value.sources.map(row => row.citation_id)).size !== value.sources.length || new Set(value.measurement_ids).size !== value.measurement_ids.length || JSON.stringify(value.arguments).length > 4096) return false;
  const args = value.arguments; const sourceIds = value.sources.map(row => row.citation_id);
  const claims = args.unverified_claims;
  if (!Array.isArray(claims) || claims.length > 8 || !claims.every(row => boundedText(row))) return false;
  const cited = (ids: unknown) => Array.isArray(ids) && ids.length > 0 && ids.length <= 8 && ids.every(id => sourceIds.includes(String(id))) && new Set(ids).size === ids.length;
  if (value.action === 'aec.scope.draft') return closed(args, ['proposal_revision_id', 'sections', 'unverified_claims']) && uuid(args.proposal_revision_id) && Array.isArray(args.sections) && args.sections.length > 0 && args.sections.length <= 8 && args.sections.every(row => closed(row, ['heading', 'text', 'citation_ids']) && boundedText(row.heading, 200) && row.heading.length > 0 && boundedText(row.text) && cited(row.citation_ids));
  return closed(args, ['base_revision_id', 'selections', 'notes', 'citation_ids', 'unverified_claims']) && uuid(args.base_revision_id) && boundedText(args.notes) && cited(args.citation_ids) && Array.isArray(args.selections) && args.selections.length > 0 && args.selections.length <= 8 && new Set(args.selections.map(row => record(row) ? row.line_record_id : '')).size === args.selections.length && args.selections.every(row => closed(row, ['line_record_id', 'source_kind', 'source_id', 'target_unit_id']) && uuid(row.line_record_id) && uuid(row.source_id) && uuid(row.target_unit_id) && (row.source_kind === 'estimate-line' || row.source_kind === 'measurement' && value.measurement_ids.includes(row.source_id)));
}

export function matchesSuggestionRun(value: CompanyRickyProposalRunResponse, company: string, id?: string): boolean {
  if (!publishedSuggestionShape('CompanyRickyProposalRunResponse', value) || value.company !== company || id && value.id !== id || !validSuggestionSelection(value.selection) || value.action !== value.selection.action || value.cancel_requested !== (value.status === 'cancelled')) return false;
  if (value.status === 'waiting-for-review') return value.result !== null && value.result_digest !== null && value.completed_at !== null && value.error === null;
  return value.result === null && value.result_digest === null && (terminalSuggestion(value.status) ? value.completed_at !== null : value.completed_at === null) && (value.status === 'failed' ? value.error !== null : value.error === null);
}
export function matchesSuggestionAdmission(value: CompanyRickyProposalStartResponse, company: string, selection: CompanyRickyProposalSelection, expectedDigest: string): boolean {
  if (!publishedSuggestionShape('CompanyRickyProposalStartResponse', value)) return false;
  const { operation: _operation, ...run } = value;
  return matchesSuggestionRun(run, company) && run.status === 'queued' && sameSelectedValue(run.selection, selection) && run.selection_digest === expectedDigest;
}
export const matchesSuggestionStop = (value: CompanyRickyProposalStopResponse, company: string, id: string) => publishedSuggestionShape('CompanyRickyProposalStopResponse', value) && value.company === company && value.id === id && terminalSuggestion(value.status) && value.cancel_requested === (value.status === 'cancelled');
export const matchesSuggestionEvents = (value: CompanyRickyProposalEventsResponse, run: CompanyRickyProposalRunResponse) => publishedSuggestionShape('CompanyRickyProposalEventsResponse', value) && new Set(value.items.map(row => row.id)).size === value.items.length && value.items.every(row => row.run_id === run.id && row.tool_name === run.action && (row.status === 'claimed' ? row.completed_at === null && row.error === null : row.completed_at !== null));

export function canonicalSuggestionJSON(value: unknown): string {
  if (Array.isArray(value)) return '[' + value.map(canonicalSuggestionJSON).join(',') + ']';
  if (record(value)) return '{' + Object.keys(value).sort().map(key => JSON.stringify(key) + ':' + canonicalSuggestionJSON(value[key])).join(',') + '}';
  if (value === null || typeof value === 'string' || typeof value === 'boolean' || typeof value === 'number' && Number.isSafeInteger(value)) return JSON.stringify(value);
  throw new Error('Only canonical finite suggestion values can be hashed.');
}
export async function suggestionDigest(value: unknown): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(canonicalSuggestionJSON(value)));
  return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('');
}
export async function validSuggestionRunDigests(run: CompanyRickyProposalRunResponse): Promise<boolean> {
  return run.selection_digest === await suggestionDigest(run.selection) && (run.result === null || run.result_digest === await suggestionDigest(run.result));
}

export async function matchesSavedSuggestion(proposal: CompanyRickyProposalResponse, run: CompanyRickyProposalRunResponse, citations: CompanyCitation[], snapshotId?: string): Promise<boolean> {
  if (!publishedSuggestionShape('CompanyRickyProposalResponse', proposal) || run.status !== 'waiting-for-review' || !run.result || proposal.company !== run.company || proposal.run_id !== run.id || proposal.id !== run.result.proposal_id || proposal.action !== run.action || proposal.version !== run.result.proposal_version || proposal.content_digest !== run.result.proposal_digest || proposal.preparation_digest !== run.result.preparation_digest) return false;
  const output = proposal.preparation; const manifest = proposal.source_manifest; const selection = run.selection; const args = selection.arguments;
  const unique = (keys: string[], sorted = true) => new Set(keys).size === keys.length && (!sorted || sameSelectedValue([...keys].sort(), keys));
  if (!unique(manifest.records.map(row => `${row.domain}/${row.kind}/${row.id}`)) || !unique(manifest.owners.map(row => `${row.domain}/${row.id}`)) || !unique(manifest.preparation_heads.map(row => `${row.domain}/${row.owner_id}`)) || !unique(manifest.qualified_units.map(row => row.id)) || !unique(manifest.quantity_standing.map(row => row.measurement_id)) || !unique(manifest.citations.map(row => row.id), false) || Date.parse(proposal.expires_at) < Date.parse(proposal.created_at)) return false;
  if (proposal.prepared_manifest_digest !== await suggestionDigest(manifest) || proposal.preparation_digest !== await suggestionDigest(output) || output.draft_digest !== await suggestionDigest(Object.fromEntries(Object.entries(output).filter(([key]) => key !== 'draft_digest'))) || manifest.selection_digest !== run.selection_digest || manifest.action_complete !== true || manifest.pursuit.id !== selection.pursuit_id || output.company !== run.company || output.pursuit_id !== selection.pursuit_id || output.kind !== proposal.kind || proposal.kind !== (run.action === 'aec.scope.draft' ? 'scope-draft.v1' : 'estimate-draft.v1')) return false;
  if (!sameSelectedValue(output.unverified_claims, args.unverified_claims) || citations.length !== selection.sources.length || manifest.citations.length !== citations.length) return false;
  for (const source of selection.sources) {
    const original = citations.find(row => row.id === source.citation_id);
    if (!original || original.company !== run.company || original.scope_type !== 'Company' || original.project !== null || original.revision_id !== source.revision_id || original.page !== source.page || original.excerpt_sha256 !== source.excerpt_sha256 || original.source_sha256 !== source.source_sha256 || manifest.citations.find(row => row.id === original.id)?.digest !== await suggestionDigest(original)) return false;
  }
  const used = run.action === 'aec.scope.draft' ? (args.sections as { citation_ids: string[] }[]).flatMap(row => row.citation_ids) : args.citation_ids as string[];
  const ids = [...new Set(used)];
  if (!sameSelectedValue(output.verified_source_references.map(row => row.citation_id), ids)) return false;
  for (const ref of output.verified_source_references) {
    const original = citations.find(row => row.id === ref.citation_id)!;
    if (!original || ref.document_id !== original.document_id || ref.revision_id !== original.revision_id || ref.page !== original.page || ref.excerpt_sha256 !== original.excerpt_sha256 || ref.source_sha256 !== original.source_sha256 || ref.canonical_digest !== await suggestionDigest(original)) return false;
  }
  const domain = run.action === 'aec.scope.draft' ? 'commercial' : 'estimate';
  const revisionId = domain === 'commercial' ? args.proposal_revision_id : args.base_revision_id;
  const heads = manifest.preparation_heads.filter(row => row.domain === domain && row.revision_id === revisionId);
  if (heads.length !== 1 || !manifest.owners.some(row => row.domain === domain && row.kind === (domain === 'commercial' ? 'proposal' : 'estimate') && row.id === heads[0].owner_id && row.pursuit_id === selection.pursuit_id) || !manifest.records.some(row => row.domain === domain && row.kind === (domain === 'commercial' ? 'proposal-revision' : 'revision') && row.id === heads[0].revision_id && row.digest === heads[0].digest)) return false;
  const checksum = (kind: string, id: string) => kind === 'pursuit' ? manifest.pursuit.digest : kind === 'proposal' || kind === 'estimate' ? manifest.owners.find(row => row.domain === domain && row.id === id)?.digest : manifest.records.find(row => row.domain === domain && row.kind === (kind === 'calculation-snapshot' ? 'snapshot' : kind === 'estimate-revision' ? 'revision' : kind) && row.id === id)?.digest;
  const dependencies = domain === 'commercial' ? [['pursuit', selection.pursuit_id], ['proposal', heads[0].owner_id], ['proposal-revision', String(revisionId)]] : [['estimate-revision', String(revisionId)], ['calculation-snapshot', snapshotId || ''], ['estimate', heads[0].owner_id], ['pursuit', selection.pursuit_id]];
  if (!sameSelectedValue(output.record_dependencies, dependencies.map(([kind, id]) => ({ kind, id, digest: checksum(kind, id) })))) return false;
  if (output.kind === 'scope-draft.v1') return run.action === 'aec.scope.draft' && sameSelectedValue(output.proposed_fields.sections, args.sections);
  if (run.action !== 'aec.estimate.draft' || output.proposed_fields.notes !== args.notes) return false;
  const chosen = args.selections as { line_record_id: string; source_kind: string; source_id: string; target_unit_id: string }[];
  return output.proposed_fields.quantity_selections.length === chosen.length && output.proposed_fields.quantity_selections.every((row, index) => {
    const selected = chosen[index]; const quantity = row.quantity;
    return row.line_record_id === selected.line_record_id && quantity.source_kind === selected.source_kind && quantity.source_id === selected.source_id && quantity.target_unit_id === selected.target_unit_id && quantity.eligible_for_new_use === true && /^(0|[1-9][0-9]*)$/.test(quantity.numerator) && /^[1-9][0-9]*$/.test(quantity.denominator) && quantity.source_digest === manifest.records.find(record => record.domain === (selected.source_kind === 'measurement' ? 'takeoff' : 'estimate') && record.kind === (selected.source_kind === 'measurement' ? 'measurement' : 'line') && record.id === selected.source_id)?.digest && manifest.qualified_units.some(unit => unit.id === quantity.target_unit_id) && manifest.qualified_units.some(unit => unit.id === quantity.source_unit_id) && sha(quantity.source_digest);
  });
}
