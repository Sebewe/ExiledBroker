import { Search } from 'lucide-react'
import { useId, useRef, useState, type KeyboardEvent } from 'react'
import { matchOptions, type SearchOption } from '../lib/search'

// A type-to-filter picker for long item lists (hundreds of items), in place of a native
// <select>: the box shows the chosen item, typing filters the list that opens below it.

// Rows rendered at once; past that the list says to keep typing.
const LIMIT = 50

export function ItemSearch<T extends SearchOption>({
  label,
  options,
  value,
  onChange,
  placeholder = 'Type to search…',
  size = 'md',
}: {
  label: string
  options: T[]
  value: string | undefined
  onChange: (id: string) => void
  placeholder?: string
  /** "lg": the Price check page's headline box, as wide as its column. */
  size?: 'md' | 'lg'
}) {
  const lg = size === 'lg'
  const id = useId()
  const listId = `${id}-list`
  const input = useRef<HTMLInputElement>(null)
  const selected = options.find((o) => o.id === value)
  // null: closed, showing the chosen item; a string: open, filtering by it.
  const [query, setQuery] = useState<string | null>(null)
  const [active, setActive] = useState(0)
  const open = query !== null
  const matches = open ? matchOptions(options, query) : []
  const shown = matches.slice(0, LIMIT)

  const close = () => {
    setQuery(null)
    setActive(0)
  }
  const choose = (o: T) => {
    onChange(o.id)
    close()
    input.current?.blur()
  }
  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault()
      if (!open) return setQuery('')
      const step = e.key === 'ArrowDown' ? 1 : -1
      setActive((i) => (shown.length ? (i + step + shown.length) % shown.length : 0))
    } else if (e.key === 'Enter' && open) {
      e.preventDefault()
      const o = shown[active]
      if (o) choose(o)
    } else if (e.key === 'Escape' && open) {
      e.preventDefault()
      close()
    }
  }

  return (
    <div className={`relative flex flex-col gap-1 ${lg ? 'w-full max-w-2xl' : ''}`}>
      <label htmlFor={id} className={lg ? 'text-sm font-medium text-muted' : 'text-xs font-medium text-muted'}>
        {label}
      </label>
      <div
        className={`flex max-w-full items-center gap-2 border bg-surface focus-within:border-accent ${
          lg ? 'h-12 w-full rounded-lg border-accent/40 px-3.5 shadow-sm shadow-shadow/20' : 'h-9 w-72 rounded-md border-border px-2.5'
        }`}
      >
        <Search aria-hidden className={`shrink-0 ${lg ? 'size-5 text-accent' : 'size-4 text-faint'}`} />
        <input
          ref={input}
          id={id}
          type="text"
          role="combobox"
          aria-expanded={open}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={open && shown[active] ? `${listId}-${active}` : undefined}
          autoComplete="off"
          spellCheck={false}
          value={open ? query : (selected?.name ?? '')}
          placeholder={placeholder}
          onFocus={() => setQuery('')}
          onBlur={close}
          onChange={(e) => {
            setQuery(e.target.value)
            setActive(0)
          }}
          onKeyDown={onKey}
          className={`min-w-0 flex-1 truncate bg-transparent outline-none placeholder:text-faint ${lg ? 'text-base' : 'text-sm'}`}
        />
      </div>
      {open && (
        <ul
          id={listId}
          role="listbox"
          aria-label={label}
          // Keep focus in the box while clicking a row, so blur doesn't close it first.
          onMouseDown={(e) => e.preventDefault()}
          className={`absolute top-full left-0 z-30 mt-1 max-h-80 ${lg ? 'w-full' : 'w-80'} max-w-[calc(100vw-2rem)] overflow-y-auto rounded-md border border-border bg-surface p-1 shadow-lg shadow-shadow/40`}
        >
          {shown.length === 0 && <li className="px-2.5 py-2 text-sm text-muted">No item matches "{query.trim()}".</li>}
          {shown.map((o, i) => (
            <li
              key={o.id}
              id={`${listId}-${i}`}
              role="option"
              aria-selected={o.id === value}
              onMouseEnter={() => setActive(i)}
              onClick={() => choose(o)}
              className={`flex cursor-pointer items-baseline justify-between gap-3 rounded px-2.5 py-1.5 text-sm ${
                i === active ? 'bg-surface-2' : ''
              } ${o.id === value ? 'text-accent-strong' : ''}`}
            >
              <span className="truncate" title={o.name}>
                {o.name}
              </span>
              {o.group && <span className="shrink-0 text-xs text-faint">{o.group}</span>}
            </li>
          ))}
          {matches.length > LIMIT && (
            <li className="px-2.5 py-1.5 text-xs text-faint">
              {matches.length - LIMIT} more: keep typing to narrow it down.
            </li>
          )}
        </ul>
      )}
    </div>
  )
}
