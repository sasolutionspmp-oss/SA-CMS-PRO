import { useState, type ReactNode } from 'react';
import {
  Button, DrawerBody, DrawerHeader, DrawerHeaderTitle, OverlayDrawer, useRestoreFocusSource, useRestoreFocusTarget,
  Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow,
} from '@fluentui/react-components';
import { CheckmarkCircleRegular, ClockRegular, DismissRegular, InfoRegular, QuestionCircleRegular, WarningRegular } from '@fluentui/react-icons';
import { statusText, help } from '../copy/terms';
import { AppLink } from '../app/navigation';

export function StatusChip({ status }: { status: string }) {
  const tone = ['executed', 'posted', 'approved', 'granted', 'paid', 'consumed', 'closed'].includes(status) ? 'positive'
    : ['invalidated', 'expired'].includes(status) ? 'warning' : ['rejected', 'void', 'corrected'].includes(status) ? 'negative' : 'neutral';
  const Icon = tone === 'positive' ? CheckmarkCircleRegular : tone === 'warning' || tone === 'negative' ? WarningRegular : ClockRegular;
  return <span className={`cipher-status cipher-status-${tone}`}><Icon aria-hidden="true" />{statusText(status)}</span>;
}
export function PageHeader({ title, subtitle, helpKind = 'record', helpContent, children }: {
  title: string; subtitle?: string; helpKind?: keyof typeof help; helpContent?: ReactNode; children?: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const restoreTarget = useRestoreFocusTarget();
  const restoreSource = useRestoreFocusSource();
  return <>
    <header className="cipher-page-header"><div><h1 tabIndex={-1} data-page-heading>{title}</h1>{subtitle && <p className="cipher-subtitle">{subtitle}</p>}</div>
      <div className="cipher-page-actions">{children}<Button {...restoreTarget} appearance="subtle" icon={<QuestionCircleRegular />} onClick={() => setOpen(true)}>Help</Button></div>
    </header>
    <OverlayDrawer {...restoreSource} open={open} onOpenChange={(_, data) => setOpen(data.open)} position="end" size="medium">
      <DrawerHeader><DrawerHeaderTitle action={<Button appearance="subtle" aria-label="Close help" icon={<DismissRegular />} onClick={() => setOpen(false)} />}>About this page</DrawerHeaderTitle></DrawerHeader>
      <DrawerBody>{helpContent ?? <><p>{help[helpKind]}</p><h2>Practice workspace</h2><p>Read views let you explore the work without changing a record. Use the navigation to return to projects or review requests.</p><AppLink href="/projects">Open practice projects</AppLink></>}</DrawerBody>
    </OverlayDrawer>
  </>;
}
export function Notice({ children }: { children: ReactNode }) {
  return <div className="cipher-notice"><InfoRegular aria-hidden="true" /><span>{children}</span></div>;
}
export function Section({ title, children, extra }: { title: string; children: ReactNode; extra?: ReactNode }) {
  return <section className="cipher-section"><div className="cipher-section-heading"><h2>{title}</h2>{extra}</div>{children}</section>;
}
export function KeyFacts({ facts }: { facts: { label: string; value: ReactNode; note?: string }[] }) {
  return <dl className="cipher-facts">{facts.map(fact => <div key={fact.label}><dt>{fact.label}</dt><dd>{fact.value}{fact.note && <p className="cipher-caption">{fact.note}</p>}</dd></div>)}</dl>;
}
export interface Column<T> { key: string; label: string; render: (row: T) => ReactNode; money?: boolean }
export function RecordTable<T extends { id: string }>({ label, rows, columns, empty = 'No records match these filters.' }: {
  label: string; rows: T[]; columns: Column<T>[]; empty?: string;
}) {
  return rows.length ? <div className="cipher-table-region" tabIndex={0} role="region" aria-label={`${label}, scrollable table`}>
    <Table aria-label={label} className="cipher-table" size="small">
      <TableHeader><TableRow>{columns.map((column, index) => <TableHeaderCell key={column.key} className={`${column.money ? 'cipher-money' : ''} ${index === 0 ? 'cipher-table-frozen' : ''}`}>{column.label}</TableHeaderCell>)}</TableRow></TableHeader>
      <TableBody>{rows.map(row => <TableRow key={row.id}>{columns.map((column, index) => <TableCell key={column.key} className={`${column.money ? 'cipher-money' : ''} ${index === 0 ? 'cipher-table-frozen' : ''}`}>{column.render(row)}</TableCell>)}</TableRow>)}</TableBody>
    </Table>
  </div> : <p className="cipher-empty" role="status">{empty}</p>;
}
export function TechnicalDetails({ entries }: { entries: { label: string; value: string | number }[] }) {
  return <details className="cipher-details"><summary>Technical details</summary><dl>{entries.map(entry => <div key={entry.label}><dt>{entry.label}</dt><dd><code>{entry.value}</code></dd></div>)}</dl></details>;
}
