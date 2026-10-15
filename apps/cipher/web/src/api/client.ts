import fixture from './fixture.json';
import { sumCents } from '../copy/format';
import type { Collection, Envelope, Records, Workspace } from './types';

export const dataSource = import.meta.env.VITE_DATA_SOURCE === 'fixture' ? 'fixture' : 'api';
const collections: Collection[] = ['projects', 'commitments', 'bills', 'approvals'];

function validateEnvelope<K extends Collection>(raw: unknown, collection: K): Envelope<Records[K]> {
  if (!raw || typeof raw !== 'object') throw new Error('The practice server returned an unreadable list.');
  const envelope = raw as Partial<Envelope<Records[K]>>;
  if (envelope.contractVersion !== 'cipher.practice-read.v1' || envelope.mode !== 'practice' || envelope.synthetic !== true ||
      envelope.currency !== 'USD' || envelope.collection !== collection || !Array.isArray(envelope.value) ||
      !Number.isSafeInteger(envelope.count) || envelope.count! < 0 ||
      !(envelope.nextCursor === null || typeof envelope.nextCursor === 'string')) {
    throw new Error('This view requires the supported synthetic practice workspace.');
  }
  for (const row of envelope.value) {
    if (!row || typeof row !== 'object' || typeof row.id !== 'string') throw new Error('A practice record is incomplete.');
    const record = row as unknown as Record<string, unknown>;
    const stringFields: Record<Collection, string[]> = {
      projects: ['id', 'name', 'entity', 'currency'],
      commitments: ['id', 'projectId', 'supplierId', 'title', 'status'],
      bills: ['id', 'projectId', 'commitmentId', 'status', 'periodId'],
      approvals: ['id', 'operation', 'subjectType', 'subjectId', 'status', 'requestedAt', 'expiresAt'],
    };
    const numberFields: Record<Collection, string[]> = {
      projects: ['budgetCents'],
      commitments: ['version', 'originalAmountCents', 'executedAmountCents', 'retainageRateMicros'],
      bills: ['sequence', 'amountDueCents', 'currentDueCents', 'retainageCents', 'thisPeriodCents'],
      approvals: [],
    };
    if (stringFields[collection].some(key => typeof record[key] !== 'string') ||
        numberFields[collection].some(key => !Number.isSafeInteger(record[key])) ||
        (collection === 'projects' && record.currency !== 'USD') ||
        (collection === 'bills' && record.journalId !== null && typeof record.journalId !== 'string') ||
        (collection === 'approvals' && (record.amountCents !== null && !Number.isSafeInteger(record.amountCents))) ||
        (collection === 'approvals' && record.projectId !== null && typeof record.projectId !== 'string')) {
      throw new Error('A practice record is incomplete or has an unsupported shape.');
    }
    for (const key of ['customerName', 'supplierName', 'projectName', 'commitmentTitle', 'periodLabel', 'displayName', 'subjectLabel', 'title', 'requestedByName']) {
      if (record[key] !== undefined && record[key] !== null && typeof record[key] !== 'string') {
        throw new Error('A practice record contains an unreadable name.');
      }
    }
    for (const [key, value] of Object.entries(row)) {
      if ((key.endsWith('Cents') || key.endsWith('Micros')) && !(collection === 'approvals' && key === 'amountCents' && value === null) && !Number.isSafeInteger(value)) {
        throw new Error('A practice amount could not be read accurately.');
      }
    }
  }
  return envelope as Envelope<Records[K]>;
}

async function readCollection<K extends Collection>(collection: K, signal: AbortSignal): Promise<Records[K][]> {
  if (dataSource === 'fixture') return validateEnvelope(fixture[collection], collection).value;
  const rows: Records[K][] = [];
  let cursor: string | null = null;
  const seen = new Set<string>();
  do {
    const query = new URLSearchParams({ top: '50' });
    if (cursor) query.set('cursor', cursor);
    const response = await fetch(`/api/practice/v1/${collection}?${query}`, {
      method: 'GET', headers: { Accept: 'application/json' }, credentials: 'same-origin', cache: 'no-store', signal,
    });
    if (!response.ok) throw new Error(`The practice workspace did not respond (${response.status}).`);
    const page = validateEnvelope(await response.json(), collection);
    rows.push(...page.value);
    cursor = page.nextCursor;
    if (cursor && (seen.has(cursor) || seen.size > 100)) throw new Error('The practice list could not finish loading.');
    if (cursor) seen.add(cursor);
  } while (cursor);
  return rows;
}

export async function loadWorkspace(signal: AbortSignal): Promise<Workspace> {
  const lists = await Promise.all(collections.map(collection => readCollection(collection, signal)));
  const workspace: Workspace = {
    projects: lists[0] as Records['projects'][], commitments: lists[1] as Records['commitments'][],
    bills: lists[2] as Records['bills'][], approvals: lists[3] as Records['approvals'][], source: dataSource, loadedAt: new Date(),
  };
  // Check every displayed project aggregate before publishing records to React.
  for (const project of workspace.projects) {
    sumCents(workspace.commitments.filter(row => row.projectId === project.id && ['executed', 'closed'].includes(row.status)).map(row => row.executedAmountCents));
    sumCents(workspace.bills.filter(row => row.projectId === project.id).map(row => row.currentDueCents));
  }
  return workspace;
}
