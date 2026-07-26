import { useEffect, useMemo, useRef, useState } from 'react'
import type { Account } from '../api'

type Props = {
  accounts: Account[]
  onSelect: (accountId: number) => void
  disabled?: boolean
  placeholder?: string
  className?: string
}

export function AccountPicker({
  accounts,
  onSelect,
  disabled,
  placeholder = 'Search account…',
  className = '',
}: Props) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const rootRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    const list = [...accounts].sort((a, b) => a.code.localeCompare(b.code))
    if (!q) return list.slice(0, 40)
    return list
      .filter(
        (a) =>
          a.code.toLowerCase().includes(q) ||
          a.name.toLowerCase().includes(q) ||
          a.account_type.toLowerCase().includes(q),
      )
      .slice(0, 40)
  }, [accounts, query])

  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) {
        setOpen(false)
        setQuery('')
      }
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [open])

  return (
    <div className={`account-picker ${className}`} ref={rootRef}>
      <input
        ref={inputRef}
        className="input account-picker-input"
        disabled={disabled}
        placeholder={placeholder}
        value={query}
        onFocus={() => setOpen(true)}
        onChange={(e) => {
          setQuery(e.target.value)
          setOpen(true)
        }}
        onKeyDown={(e) => {
          if (e.key === 'Escape') {
            setOpen(false)
            setQuery('')
          }
          if (e.key === 'Enter' && filtered[0]) {
            e.preventDefault()
            onSelect(filtered[0].id)
            setQuery('')
            setOpen(false)
          }
        }}
      />
      {open && !disabled && (
        <div className="account-picker-menu">
          {filtered.length === 0 && <div className="hint">No accounts match</div>}
          {filtered.map((a) => (
            <button
              key={a.id}
              type="button"
              className="account-picker-option"
              onClick={() => {
                onSelect(a.id)
                setQuery('')
                setOpen(false)
              }}
            >
              <span className="account-picker-code">{a.code}</span>
              <span>{a.name}</span>
              <span className="hint">{a.account_type}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
