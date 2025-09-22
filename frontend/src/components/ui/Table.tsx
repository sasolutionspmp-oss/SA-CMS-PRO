import React from 'react'
import { cn } from '../../lib/utils'

export type TableRow = {
  id: string
  cells: React.ReactNode[]
  accent?: 'positive' | 'warning' | 'danger'
  onClick?: () => void
}

type Props = {
  headers: string[]
  rows: TableRow[]
  compact?: boolean
  className?: string
  emptyState?: React.ReactNode
}

export default function Table({ headers, rows, compact = false, className, emptyState }: Props) {
  const spacing = compact ? 'px-3 py-2 text-xs' : 'px-4 py-3 text-sm'

  return (
    <div className={cn('overflow-hidden rounded-2xl border border-brand-primary/8 bg-white/95 shadow-subtle', className)}>
      <table className="w-full border-collapse text-left">
        <thead className="bg-surface-muted/60 text-xs uppercase tracking-[0.18em] text-text-tertiary">
          <tr>
            {headers.map((header) => (
              <th key={header} className={cn('px-4 py-3 font-semibold', compact ? 'py-2 text-[11px]' : '')}>
                {header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-brand-primary/8">
          {rows.length === 0 && (
            <tr>
              <td colSpan={headers.length} className="px-6 py-10 text-center text-sm text-text-secondary">
                {emptyState || 'No records available'}
              </td>
            </tr>
          )}
          {rows.map((row) => (
            <tr
              key={row.id}
              onClick={row.onClick}
              className={cn(
                'transition-colors duration-200 hover:bg-brand-highlight/10',
                row.onClick && 'cursor-pointer',
                row.accent === 'positive' && 'bg-success/5 hover:bg-success/10',
                row.accent === 'warning' && 'bg-warning/5 hover:bg-warning/10',
                row.accent === 'danger' && 'bg-danger/5 hover:bg-danger/10'
              )}
            >
              {row.cells.map((cell, cellIndex) => (
                <td key={cellIndex} className={cn(spacing, cellIndex === 0 && 'font-semibold text-text-primary')}>
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
