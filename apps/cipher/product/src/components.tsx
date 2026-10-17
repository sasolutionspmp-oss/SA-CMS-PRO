import type { ReactNode } from 'react';
import { BusyIndicator, Button, Icon, MessageStrip, ObjectStatus, Title } from '@ui5/webcomponents-react';
import { ApiError } from './api/client';
import { human } from './hooks';

export function Status({ value }: { value: string }) {
  const normalized = value.toLowerCase();
  const state = ['completed', 'complete', 'succeeded', 'saved', 'open', 'active', 'ready', 'executed', 'granted', 'verified scale', 'current source'].includes(normalized) ? 'Positive'
    : ['failed', 'blocked', 'cancelled', 'rejected'].includes(normalized) ? 'Negative'
    : ['waiting_for_review', 'waiting-for-review', 'pending', 'not_scanned', 'quarantined', 'overdue', 'stale', 'expired', 'stale source'].includes(normalized) ? 'Critical'
    : 'Information';
  return <ObjectStatus state={state}>{human(value)}</ObjectStatus>;
}

export function Loading({ label = 'Loading workspace…' }: { label?: string }) {
  return <div className="loading-state" role="status"><BusyIndicator active delay={0} size="M" /><span>{label}</span></div>;
}

export function Failure({ error, onRetry }: { error: ApiError; onRetry?: () => void }) {
  const accessUnavailable = error.status === 403 || error.status === 404;
  const message = error.status === 403 ? 'Your current permissions do not allow this access or action.'
    : error.status === 404 ? 'This record is unavailable or you no longer have access.' : error.message;
  return <div className="failure-state" role="alert">
    <MessageStrip design={accessUnavailable ? "Information" : "Negative"} hideCloseButton>{message}</MessageStrip>
    <div className="failure-actions">
      {onRetry && !accessUnavailable && <Button icon="refresh" onClick={onRetry}>Try again</Button>}
      {error.status === 401 && <Button design="Emphasized" onClick={() => window.dispatchEvent(new Event('cipher:sign-in'))}>Sign in</Button>}
      {error.requestId && <span className="caption">Reference: {error.requestId}</span>}
    </div>
  </div>;
}

export function Empty({ title, children, icon = 'folder-blank', action }: { title: string; children?: ReactNode; icon?: string; action?: ReactNode }) {
  return <div className="empty-state"><div className="empty-icon"><Icon name={icon} /></div><Title level="H3">{title}</Title>
    {children && <p>{children}</p>}{action}</div>;
}

export function PageHeading({ eyebrow, title, description, actions }: { eyebrow?: string; title: string; description?: string; actions?: ReactNode }) {
  return <header className="page-heading"><div>{eyebrow && <span className="eyebrow">{eyebrow}</span>}
    <h1>{title}</h1>{description && <p>{description}</p>}</div>{actions && <div className="heading-actions">{actions}</div>}</header>;
}

export function Fact({ label, children, note }: { label: string; children: ReactNode; note?: string }) {
  return <div className="fact"><span className="fact-label">{label}</span><div className="fact-value">{children}</div>{note && <span className="caption">{note}</span>}</div>;
}

export function Pagination({ next, previous, page, total, onNext, onPrevious }: { next?: string | null; previous: boolean; page: number; total?: number | null; onNext: () => void; onPrevious: () => void }) {
  if (!next && !previous) return null;
  return <div className="page-controls" aria-label="Register pagination"><Button icon="navigation-left-arrow" disabled={!previous} onClick={onPrevious}>Previous page</Button><span>Page {page}{total !== undefined && total !== null ? ` · ${total} records` : ''}</span><Button icon="navigation-right-arrow" disabled={!next} onClick={onNext}>Next page</Button></div>;
}
