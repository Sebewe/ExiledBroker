import { ArrowRight } from 'lucide-react'
import type { ReactNode } from 'react'
import { ItemName } from './ItemLink'

// The trading cards on the Market recap: the key
// item top left, one headline amount top right, a route, and a few facts below.

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
}: {
  title: string
  href?: string // the item's Price check
  amount: string
  label: string
  muted?: boolean // nothing to gain at the viewer's settings, or its orders never went through
  children: ReactNode
  footer: ReactNode
}) {
  return (
    <li className="flex min-w-0 flex-col gap-3 rounded-lg border border-border bg-surface p-4">
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

export function Empty({ children }: { children: ReactNode }) {
  return <p className="rounded-lg border border-dashed border-border px-3 py-4 text-center text-sm text-faint">{children}</p>
}
