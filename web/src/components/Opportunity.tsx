import { ArrowRight, ChevronDown } from 'lucide-react'
import { useId, useState, type ReactNode } from 'react'
import { ItemName } from './ItemLink'

// The trading cards on the Market recap: the key item top left, one headline amount top
// right, a route, its price below, the odds behind a "Details" toggle, and the card's
// buttons in a bar along the bottom.

export function Pill({ children, accent = false }: { children: ReactNode; accent?: boolean }) {
  return (
    <span
      className={`max-w-[10rem] truncate rounded-full border px-2 py-0.5 text-xs ${accent ? 'border-accent/50 text-accent-strong' : 'border-border text-text'}`}
    >
      {children}
    </span>
  )
}

export const RouteArrow = () => <ArrowRight aria-hidden className="size-3 shrink-0 text-faint" />

/** Steps joined by arrows; the item itself plain, the currencies in gold. */
export function Route({ steps, item }: { steps: string[]; item: string }) {
  return (
    <div className="flex flex-wrap items-center gap-1">
      {steps.map((step, i) => (
        <span key={i} className="flex items-center gap-1">
          {i > 0 && <RouteArrow />}
          <Pill accent={step !== item}>{step}</Pill>
        </span>
      ))}
    </div>
  )
}

export const loopRoute = (name: string, direction: string) =>
  direction === 'chaos_first' ? ['Chaos', name, 'Divine', 'Chaos'] : ['Chaos', 'Divine', name, 'Chaos']

export function Opportunity({
  title,
  href,
  amount,
  label,
  muted = false,
  children,
  footer,
  details,
  actions,
}: {
  title: string
  href?: string // the item's Price check
  amount: string
  label: string
  muted?: boolean // nothing to gain at the viewer's settings, or its orders never went through
  children: ReactNode
  footer: ReactNode // the price, always shown
  details?: ReactNode // the odds and the rest of the facts, behind "Details"
  actions?: ReactNode // the card's buttons, in a bar along its bottom edge
}) {
  return (
    <li className="flex min-w-0 flex-col gap-3 rounded-lg border border-border bg-surface p-4 transition-colors duration-150 hover:border-accent/30">
      <div className="flex items-start justify-between gap-3">
        <h3 className="min-w-0 truncate pt-1 font-semibold" title={title}>
          <ItemName name={title} href={href} />
        </h3>
        <div className="shrink-0 text-right">
          <div className={`num text-2xl font-semibold ${muted ? 'text-muted' : 'text-positive'}`}>{amount}</div>
          <div className="text-[11px] text-faint">{label}</div>
        </div>
      </div>
      {children}
      <div className="mt-auto flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted">{footer}</div>
      {details && <Details>{details}</Details>}
      {/* Full-width buttons that share the bar, so they line up across a row of cards. */}
      {actions && <div className="-mx-4 -mb-4 flex flex-wrap items-center gap-2 rounded-b-lg border-t border-border bg-surface-2/40 px-4 py-3">{actions}</div>}
    </li>
  )
}

/** A thin 0–100% bar with its label, e.g. how often something paid. */
export function Meter({ label, value, hint }: { label: string; value: number | null | undefined; hint?: string }) {
  const v = Math.max(0, Math.min(1, value ?? 0))
  return (
    <div className="flex items-center gap-2 text-xs text-muted" title={hint}>
      <span className="w-24 shrink-0">{label}</span>
      <span className="h-1.5 flex-1 rounded-full bg-surface-2">
        <span className="block h-1.5 rounded-full bg-positive/80" style={{ width: `${v * 100}%` }} />
      </span>
      <span className="num w-9 text-right text-text">{value == null ? '–' : `${Math.round(v * 100)}%`}</span>
    </div>
  )
}

/** The card's odds and extra facts, closed by default (one toggle per card). */
function Details({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false)
  const id = useId()
  return (
    <div className="flex flex-col gap-2">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen(!open)}
        className="-my-1 flex min-h-8 w-fit cursor-pointer items-center gap-1 text-xs text-muted hover:text-accent"
      >
        Details
        <ChevronDown aria-hidden className={`size-3.5 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>
      <div id={id} hidden={!open} className="flex flex-col gap-2">
        {open && children}
      </div>
    </div>
  )
}

/** A small "nothing here" line, with a hint of what to try instead. */
export function Empty({ children, hint }: { children: ReactNode; hint?: ReactNode }) {
  return (
    <div className="rounded-md border border-dashed border-border px-3 py-2 text-xs">
      <p className="text-muted">{children}</p>
      {hint && <p className="mt-0.5 text-faint">{hint}</p>}
    </div>
  )
}
