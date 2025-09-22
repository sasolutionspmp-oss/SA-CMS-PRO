import React, { useMemo, useState } from 'react'
import Table, { TableRow } from './Table'
import { SearchIcon } from '../icons'
import { cn } from '../../lib/utils'

type Props = {
  title?: string
  headers: string[]
  rows: (TableRow & { searchText?: string })[]
  searchPlaceholder?: string
  toolbar?: React.ReactNode
  className?: string
}

export default function DataGrid({
  title,
  headers,
  rows,
  searchPlaceholder = 'Search records',
  toolbar,
  className,
}: Props) {
  const [query, setQuery] = useState('')

  const filtered = useMemo(() => {
    if (!query) return rows
    const normalized = query.trim().toLowerCase()
    return rows.filter((row) => {
      if (row.searchText) {
        return row.searchText.toLowerCase().includes(normalized)
      }
      return row.cells.some((cell) =>
        typeof cell === 'string' ? cell.toLowerCase().includes(normalized) : false
      )
    })
  }, [rows, query])

  return (
    <div className={cn('space-y-4', className)}>
      {(title || toolbar) && (
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          {title && <h3 className="text-lg font-semibold text-text-primary">{title}</h3>}
          {toolbar && <div className="flex flex-wrap gap-3">{toolbar}</div>}
        </div>
      )}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <label className="flex w-full items-center gap-3 rounded-full border border-brand-primary/10 bg-white/95 px-4 py-2 text-sm text-text-secondary shadow-subtle focus-within:border-brand-accent focus-within:ring-2 focus-within:ring-brand-accent/30 sm:max-w-sm">
          <SearchIcon className="h-4 w-4 text-brand-accent" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={searchPlaceholder}
            className="w-full border-none bg-transparent text-sm text-text-primary outline-none placeholder:text-text-tertiary"
          />
        </label>
      </div>
      <Table headers={headers} rows={filtered} />
    </div>
  )
}
