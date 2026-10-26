import { Eye, EyeOff, History } from 'lucide-react'
import type { ReactNode } from 'react'
import type { PreviewTradeNext } from '../api/client'
import { usePreview } from '../lib/preview'
import { recapTally } from '../lib/reveal'
import { trackFeature } from '../lib/usage'
import { Skeleton } from './QueryState'

// The preview's "what happened next" (docs/preview.md). It sits behind a button, so a
// visitor makes their own call from the chosen day first (the user's choice); only the
// preview shows it, and nothing is fetched until it's opened. Price check's part is in
// RevealItem.tsx, so the recap (the first page a visitor sees) doesn't load it.

/** The closed reveal: a prompt and a button. Open, `children` and a way to hide them. */
export function RevealPanel({ open, onToggle, prompt, children }: { open: boolean; onToggle: () => void; prompt: ReactNode; children?: ReactNode }) {
  return (
    <section aria-label="What happened next" className="flex flex-col gap-3 rounded-xl border border-dashed border-accent/40 bg-surface p-4 sm:p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="flex min-w-0 items-start gap-2 text-sm text-muted">
          <History aria-hidden className="mt-0.5 size-4 shrink-0 text-accent" />
          <span>{prompt}</span>
        </p>
        <button
          type="button"
          aria-expanded={open}
          onClick={() => {
            if (!open) trackFeature('preview-reveal')
            onToggle()
          }}
          className="inline-flex cursor-pointer items-center gap-1.5 rounded-md border border-accent/50 bg-accent/15 px-3 py-1.5 text-sm font-semibold text-accent-strong hover:bg-accent/25"
        >
          {open ? <EyeOff aria-hidden className="size-4" /> : <Eye aria-hidden className="size-4" />}
          {open ? 'Hide what happened' : 'Show what happened next'}
        </button>
      </div>
      {open && children}
    </section>
  )
}

// --- Market recap ---------------------------------------------------------------------

/** The recap's reveal bar: the prompt, and once open, how the page's trades did. */
export function RecapReveal({
  open,
  onToggle,
  trades,
  hours,
  loading,
}: {
  open: boolean
  onToggle: () => void
  trades: PreviewTradeNext[]
  hours: number | undefined
  loading: boolean
}) {
  const preview = usePreview()
  const t = recapTally(trades)
  return (
    <RevealPanel
      open={open}
      onToggle={onToggle}
      prompt={`These trades paid up to the end of day ${preview.day}. Pick the ones you'd take, then see whether they kept paying.`}
    >
      {loading ? (
        <Skeleton rows={1} />
      ) : hours === 0 ? (
        <p className="text-sm text-muted">The preview's data ends with this day, so there are no hours after it to show. Pick an earlier day.</p>
      ) : !t.shown ? (
        <p className="text-sm text-muted">There's no data for the hours after these trades.</p>
      ) : (
        <p className="text-sm">
          Of the {t.shown} {t.shown === 1 ? 'trade' : 'trades'} in this recap, <span className="num font-semibold">{t.nextHour}</span> paid the very next hour
          {t.nextKnown < t.shown ? ` (${t.nextKnown} traded then)` : ''}
          {t.dayKnown ? (
            <>
              {' '}
              and <span className="num font-semibold">{t.dayLater}</span> {t.dayLater === 1 ? 'was' : 'were'} still paying a day later
            </>
          ) : (
            ''
          )}
          . Each card shows its next {hours} {hours === 1 ? 'hour' : 'hours'}.
        </p>
      )}
    </RevealPanel>
  )
}

/** One recap card's next hours: a strip of paid / didn't pay / didn't trade, and its counts. */
export function TradeNext({ t, hours }: { t: PreviewTradeNext | undefined; hours: number }) {
  if (!t) return <p className="rounded-md border border-dashed border-border px-2 py-1.5 text-xs text-faint">No data for the hours after.</p>
  const word = (v: boolean | null, yes: string, no: string, none: string) => (v == null ? none : v ? yes : no)
  return (
    <div aria-label="What happened next" role="group" className="flex flex-col gap-1.5 rounded-md border border-dashed border-accent/40 bg-bg/40 px-2.5 py-2 text-xs text-muted">
      <div className="flex gap-0.5" aria-hidden>
        {t.paid.map((p, i) => (
          <span key={i} className={`h-2 flex-1 rounded-sm ${p == null ? 'bg-surface-2' : p ? 'bg-positive/80' : 'bg-negative/60'}`} />
        ))}
      </div>
      <p>
        Next {hours} {hours === 1 ? 'hour' : 'hours'}: paid in <span className="num text-text">{t.paid_hours}</span> of{' '}
        <span className="num text-text">{t.traded_hours}</span> traded.
      </p>
      <p>
        Next hour: <span className="text-text">{word(t.next_hour_paid, 'paid', "didn't pay", "didn't trade")}</span>
        {' · '}A day later: <span className="text-text">{word(t.still_paid, 'still paying', 'stopped', 'not known')}</span>
      </p>
    </div>
  )
}
