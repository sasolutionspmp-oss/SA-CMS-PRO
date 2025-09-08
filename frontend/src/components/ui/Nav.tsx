import React from 'react'
import { Link } from 'react-router-dom'

const links = [
  { to: '/', label: 'Ingest' },
  { to: '/search', label: 'Search' },
  { to: '/estimate', label: 'Estimate' },
  { to: '/compliance', label: 'Compliance' },
  { to: '/pm', label: 'PM' },
  { to: '/safety', label: 'Safety' },
  { to: '/finance', label: 'Finance' },
  { to: '/settings', label: 'Settings' },
  { to: '/history', label: 'History' },
]

export default function Nav() {
  return (
    <nav className="w-48 bg-gray-800 text-white p-4">
      <ul>
        {links.map((l) => (
          <li key={l.to} className="mb-2">
            <Link to={l.to}>{l.label}</Link>
          </li>
        ))}
      </ul>
    </nav>
  )
}
