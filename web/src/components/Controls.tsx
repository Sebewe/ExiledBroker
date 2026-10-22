import { useId, useState, type ReactNode } from 'react'

export function Field({ label, hint, children }: { label: string; hint?: string; children: (id: string) => ReactNode }) {
  const id = useId()
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-xs font-medium text-muted" title={hint}>
        {label}
      </label>
      {children(id)}
    </div>
  )
}

/** A small set of choices, all visible (2–5 options). */
export function Segmented<T extends string | number>({
  label,
  value,
  options,
  onChange,
  format = String,
}: {
  label: string
  value: T
  options: readonly T[]
  onChange: (v: T) => void
  format?: (v: T) => string
}) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs font-medium text-muted">{label}</span>
      <div role="radiogroup" aria-label={label} className="inline-flex flex-wrap rounded-md border border-border bg-surface p-0.5">
        {options.map((o) => (
          <button
            key={String(o)}
            type="button"
            role="radio"
            aria-checked={o === value}
            onClick={() => onChange(o)}
            className={`min-h-8 cursor-pointer rounded px-2.5 text-sm whitespace-nowrap transition-colors duration-150 ${
              o === value ? 'bg-surface-2 text-accent-strong shadow-sm' : 'text-muted hover:text-text'
            }`}
          >
            {format(o)}
          </button>
        ))}
      </div>
    </div>
  )
}

export function NumberField({
  label,
  value,
  onChange,
  min,
  max,
  step,
  suffix,
  hint,
}: {
  label: string
  value: number
  onChange: (v: number) => void
  min: number
  max: number
  step: number
  suffix?: string
  hint?: string
}) {
  // While editing, the box shows exactly what was typed, so it can be emptied (an
  // empty box counts as 0). Leaving the field shows the number actually used.
  const [draft, setDraft] = useState<string | null>(null)
  return (
    <Field label={label} hint={hint}>
      {(id) => (
        <div className="flex items-center rounded-md border border-border bg-surface focus-within:border-accent">
          <input
            id={id}
            type="number"
            inputMode="decimal"
            value={draft ?? String(value)}
            min={min}
            max={max}
            step={step}
            onChange={(e) => {
              setDraft(e.target.value)
              const v = e.target.value === '' ? 0 : e.target.valueAsNumber
              if (Number.isFinite(v)) onChange(Math.min(max, Math.max(min, v)))
            }}
            onBlur={() => setDraft(null)}
            className="num h-9 w-24 bg-transparent px-2.5 text-sm outline-none"
          />
          {suffix && <span className="pr-2.5 text-sm text-faint">{suffix}</span>}
        </div>
      )}
    </Field>
  )
}

export function Select({
  label,
  value,
  options,
  onChange,
}: {
  label: string
  value: string
  options: string[]
  onChange: (v: string) => void
}) {
  return (
    <Field label={label}>
      {(id) => (
        <select
          id={id}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="h-9 min-w-40 cursor-pointer rounded-md border border-border bg-surface px-2.5 text-sm"
        >
          {options.map((o) => (
            <option key={o}>{o}</option>
          ))}
        </select>
      )}
    </Field>
  )
}

export function Toolbar({ children }: { children: ReactNode }) {
  return <div className="flex flex-wrap items-end gap-x-5 gap-y-3 rounded-lg border border-border bg-surface/60 p-3">{children}</div>
}
