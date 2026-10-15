import { Table, TableCell, TableHeaderCell, TableHeaderRow, TableRow, Title } from '@ui5/webcomponents-react';
import type { EstSnapshotRecord, EstLineInput } from './api/estimating.generated';
import { exactDisplay } from './estimate-editing';
import { Status } from './components';

type ComparableSnapshot = Pick<EstSnapshotRecord, 'result'> & { inputs: Pick<EstSnapshotRecord['inputs'], 'lines'> };
export default function EstimateComparison({ before, after, beforeLabel, afterLabel }: { before: ComparableSnapshot; after: ComparableSnapshot; beforeLabel: string; afterLabel: string }) {
  const ids = [...new Set([...before.inputs.lines.map(line => line.line_id), ...after.inputs.lines.map(line => line.line_id)])];
  return <div className="estimate-comparison"><div className="comparison-summary"><div><span className="caption">{beforeLabel}</span><strong>{before.result.total.currency} {exactDisplay(before.result.total.amount)}</strong></div><span aria-hidden="true">→</span><div><span className="caption">{afterLabel}</span><strong>{after.result.total.currency} {exactDisplay(after.result.total.amount)}</strong></div></div>
    <Table accessibleName="Estimate revision comparison" headerRow={<TableHeaderRow><TableHeaderCell minWidth="15rem">Stable line</TableHeaderCell><TableHeaderCell width="7rem">Change</TableHeaderCell><TableHeaderCell minWidth="9rem" horizontalAlign="End">{beforeLabel}</TableHeaderCell><TableHeaderCell minWidth="9rem" horizontalAlign="End">{afterLabel}</TableHeaderCell></TableHeaderRow>}>
      {ids.map(id => {
        const old = before.inputs.lines.find(line => line.line_id === id); const current = after.inputs.lines.find(line => line.line_id === id);
        const oldTotal = before.result.lines.find(line => line.line_id === id)?.extension; const newTotal = after.result.lines.find(line => line.line_id === id)?.extension;
        const state = !old ? 'Added' : !current ? 'Removed' : JSON.stringify(old) === JSON.stringify(current) && oldTotal?.amount === newTotal?.amount ? 'Unchanged' : 'Changed';
        return <TableRow key={id} rowKey={id}><TableCell><div className="record-cell"><strong>{current?.description || old?.description}</strong><span>{id}</span></div></TableCell><TableCell><Status value={state} /></TableCell><TableCell horizontalAlign="End"><ComparisonValue line={old} total={oldTotal?.amount} /></TableCell><TableCell horizontalAlign="End"><ComparisonValue line={current} total={newTotal?.amount} /></TableCell></TableRow>;
      })}
    </Table><Title level="H4">Comparison basis</Title><p className="caption">Rows match by stable line identity. Quantities, source revisions, inclusion, notes and server-calculated extensions are compared. These are saved draft revisions.</p>
  </div>;
}
function ComparisonValue({ line, total }: { line?: EstLineInput; total?: string }) { return line ? <div className="comparison-value"><strong className="exact-number">{total === undefined ? '—' : exactDisplay(total)}</strong><span className="caption">Qty. {line.quantity.amount}</span></div> : <span className="caption">Not in revision</span>; }
