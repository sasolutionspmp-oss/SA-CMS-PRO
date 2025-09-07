import React from 'react'

type Props = { headers: string[]; rows: string[][] }

export default function Table({ headers, rows }: Props) {
  return (
    <table className="min-w-full border">
      <thead>
        <tr>
          {headers.map((h) => (
            <th key={h} className="border px-2 py-1">
              {h}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={i}>
            {r.map((c, j) => (
              <td key={j} className="border px-2 py-1">
                {c}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  )
}
