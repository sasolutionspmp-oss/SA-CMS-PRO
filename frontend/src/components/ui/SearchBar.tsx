import React, { useState } from 'react'

type Props = { onSearch: (q: string) => void }

export default function SearchBar({ onSearch }: Props) {
  const [value, setValue] = useState('')
  return (
    <input
      value={value}
      onChange={(e) => {
        setValue(e.target.value)
        onSearch(e.target.value)
      }}
      className="border px-1"
      placeholder="Search..."
    />
  )
}
