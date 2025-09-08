import React, { useState } from 'react'
import Table from './Table'

type Props = { headers: string[]; rows: string[][] }

export default function DataGrid({ headers, rows }: Props) {
  const [query, setQuery] = useState('')
  const filtered = rows.filter((r) => r.some((c) => c.includes(query)))
  return (
    <div>
      <input
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        className="border mb-2 px-1"
        placeholder="Search"
      />
      <Table headers={headers} rows={filtered} />
    </div>
  )
}
