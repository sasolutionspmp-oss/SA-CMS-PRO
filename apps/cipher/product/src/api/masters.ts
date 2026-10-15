import { rpc } from './client';
import type { NativeMasterList, NativeMasterChoice } from './contracts.generated';
export type MasterKind = 'Customer' | 'Lead' | 'Currency' | 'Price List' | 'UOM' | 'Item';
export type { NativeMasterChoice };
export function masterChoices(company: string, kind: MasterKind, query = '', cursor?: string, signal?: AbortSignal, filter?: { currency?: string; dimension?: string; unit_id?: string }) {
  const method = kind === 'Customer' || kind === 'Lead' ? 'parties' : kind === 'Price List' ? 'price_lists' : kind === 'UOM' ? 'units' : kind === 'Currency' ? 'currencies' : 'items';
  return rpc<NativeMasterList>(`cipher_aec.api.masters.${method}`, { company, query, cursor, limit: 50, count_mode: 'exact', ...(kind === 'Customer' || kind === 'Lead' ? { party_type: kind } : {}), ...filter }, false, signal);
}
