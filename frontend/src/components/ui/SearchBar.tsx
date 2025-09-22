import React, { useState } from 'react'
import { SearchIcon } from '../icons'

type Props = { onSearch: (q: string) => void; placeholder?: string }

export default function SearchBar({ onSearch, placeholder = 'Search everything...' }: Props) {
  const [value, setValue] = useState('')
  return (
    <label className="flex w-full items-center gap-3 rounded-full border border-brand-primary/10 bg-white/95 px-5 py-3 text-sm text-text-secondary shadow-subtle focus-within:border-brand-accent focus-within:ring-2 focus-within:ring-brand-accent/30">
      <SearchIcon className="h-5 w-5 text-brand-accent" />
      <input
        value={value}
        onChange={(e) => {
          setValue(e.target.value)
          onSearch(e.target.value)
        }}
        className="w-full border-none bg-transparent text-sm text-text-primary outline-none placeholder:text-text-tertiary"
        placeholder={placeholder}
      />
    </label>
  )
}
