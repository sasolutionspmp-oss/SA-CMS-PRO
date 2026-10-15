export type Collection = 'projects' | 'commitments' | 'bills' | 'approvals';
export interface Project {
  id: string; name: string; entity: string; currency: 'USD'; budgetCents: number; customerName?: string | null;
}
export interface Commitment {
  id: string; projectId: string; supplierId: string; title: string; status: string; version: number;
  originalAmountCents: number; executedAmountCents: number; retainageRateMicros: number;
  supplierName?: string; projectName?: string;
}
export interface Bill {
  id: string; projectId: string; commitmentId: string; sequence: number; status: string; periodId: string;
  amountDueCents: number; currentDueCents: number; retainageCents: number; thisPeriodCents: number;
  journalId: string | null; displayName?: string; supplierName?: string; projectName?: string;
  commitmentTitle?: string; periodLabel?: string;
}
export interface Approval {
  id: string; projectId: string | null; operation: string; subjectType: string; subjectId: string; status: string;
  requestedAt: string; expiresAt: string; amountCents: number | null; title?: string; subjectLabel?: string;
  requestedByName?: string; projectName?: string;
}
export interface Records { projects: Project; commitments: Commitment; bills: Bill; approvals: Approval }
export interface Envelope<T> {
  contractVersion: 'cipher.practice-read.v1'; mode: 'practice'; synthetic: true; currency: 'USD';
  collection: Collection; projectId: string | null; value: T[]; count: number; nextCursor: string | null;
  facets: { statuses: { value: string; count: number }[] }; totals: Record<string, number>;
}
export interface Workspace {
  projects: Project[]; commitments: Commitment[]; bills: Bill[]; approvals: Approval[];
  source: 'api' | 'fixture'; loadedAt: Date;
}
