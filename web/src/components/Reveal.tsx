import { Eye, EyeOff, History } from 'lucide-react'
import { type ReactNode, useEffect } from 'react'
import type { PreviewTradeNext } from '../api/client'
import { usePreview } from '../lib/preview'
import type { Money } from '../lib/money'
import { type HourFill, hourFills, recapTally } from '../lib/reveal'
import { trackFeature } from '../lib/usage'
import { Skeleton } from './QueryState'

// The preview's "what happened next" (docs/preview.md). It sits behind a button, so a
// visitor makes their own call from the chosen day first (the user's choice); only the
// preview shows it, and nothing is fetched until it's opened. Price check's part is in
// RevealItem.tsx, so the recap (the first page a visitor sees) doesn't load it.

/** The reveal: its prompt and, open, `children`, in the page; the toggle is a bar fixed to
 *  the bottom of the screen, so a visitor can flip it from anywhere on the page (the
 *  user's choice). The bar sits under the page's popups (z-20, like the header), and the
 *  body is padded by its height while it's shown (`has-reveal-bar` in index.css). */
export function RevealPanel({ open, onToggle, prompt, children }: { open: boolean; onToggle: () => void; prompt: ReactNode; children?: ReactNode }) {
  const preview = usePreview()
  useEffect(() => {
    document.body.classList.add('has-reveal-bar')
    return () => document.body.classList.remove('has-reveal-bar')
  }, [])
  return (
    <>
      <section aria-label="What happened next" className="flex flex-col gap-3 rounded-xl border border-dashed border-accent/40 bg-surface p-4 sm:p-5">
        <p className="flex min-w-0 items-start gap-2 text-sm text-muted">
          <History aria-hidden className="mt-0.5 size-4 shrink-0 text-accent" />
          <span>{prompt}</span>
        </p>
        {open && children}
      </section>
      <div role="region" aria-label="Preview reveal" className="fixed inset-x-0 bottom-0 z-20 border-t border-accent/40 bg-bg/90 pb-[env(safe-area-inset-bottom)] shadow-lg shadow-shadow/40 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-7xl items-center justify-between gap-3 px-4">
          <p className="flex min-w-0 items-center gap-2 text-sm text-muted">
            <History aria-hidden className="size-4 shrink-0 text-accent" />
            {/* On a phone the button needs the room: just the day. */}
            <span className="truncate">
              Day {preview.day}
              <span className="hidden sm:inline">{open ? ': showing what happened after it' : ': make your call, then check it'}</span>
            </span>
          </p>
          <button
            type="button"
            aria-expanded={open}
            onClick={() => {
              if (!open) trackFeature('preview-reveal')
              onToggle()
            }}
            className="inline-flex shrink-0 cursor-pointer items-center gap-1.5 rounded-md border border-accent/50 bg-accent/15 px-3 py-1.5 text-sm font-semibold text-accent-strong hover:bg-accent/25"
          >
            {open ? <EyeOff aria-hidden className="size-4" /> : <Eye aria-hidden className="size-4" />}
            {open ? 'Hide what happened' : 'Show what happened next'}
          </button>
        </div>
      </div>
    </>
  )
}

// --- Market recap ---------------------------------------------------------------------

/** A signed amount: "+12c", "−1.5 div". */
const signed = (money: Money, chaos: number) => `${chaos < 0 ? '−' : '+'}${money(Math.abs(chaos))}`

/** The recap's reveal bar: the prompt, and once open, how the page's trades did. */
export function RecapReveal({
  open,
  onToggle,
  trades,
  hours,
  loading,
  money,
}: {
  open: boolean
  onToggle: () => void
  trades: PreviewTradeNext[]
  hours: number | undefined
  loading: boolean
  money: Money
}) {
  const preview = usePreview()
  const t = recapTally(trades)
  return (
    <RevealPanel
      open={open}
      onToggle={onToggle}
      prompt={`These trades paid up to the end of day ${preview.day}. Pick the ones you'd take, then see whether their orders filled and paid.`}
    >
      {loading ? (
        <Skeleton rows={1} />
      ) : hours === 0 ? (
        <p className="text-sm text-muted">The preview's data ends with this day, so there are no hours after it to show. Pick an earlier day.</p>
      ) : !t.shown ? (
        <p className="text-sm text-muted">There's no data for the hours after these trades.</p>
      ) : (
        <div className="flex flex-col gap-1.5 text-sm">
          <p>
            Of the {t.shown} {t.shown === 1 ? 'trade' : 'trades'} in this recap, <span className="num font-semibold">{t.nextHour}</span> paid the very next hour
            {t.nextKnown < t.shown ? ` (${t.nextKnown} had an order placed then)` : ''}
            {t.dayKnown ? (
              <>
                {' '}
                and <span className="num font-semibold">{t.dayLater}</span> {t.dayLater === 1 ? 'was' : 'were'} still paying a day later
              </>
            ) : (
              ''
            )}
            .
          </p>
          {t.orders > 0 && (
            <p className="text-muted">
              Placing the recap's order every hour it listed one: <span className="num text-text">{t.fills}</span> of <span className="num text-text">{t.orders}</span>{' '}
              {t.orders === 1 ? 'order' : 'orders'} filled
              {t.fills > 0 ? (
                <>
                  , making{' '}
                  <span className={`num font-semibold ${t.profit < 0 ? 'text-negative' : t.profit > 0 ? 'text-positive' : 'text-text'}`}>{signed(money, t.profit)}</span>
                </>
              ) : (
                ''
              )}{' '}
              over the next {hours} {hours === 1 ? 'hour' : 'hours'}. A fill counts when a trade went past the order (the optimistic way, as in the Backtest), so real fills are likely fewer.
            </p>
          )}
        </div>
      )}
    </RevealPanel>
  )
}

const FILL_STYLE: Record<HourFill, string> = {
  none: 'bg-surface-2',
  unfilled: 'border border-faint/60 bg-transparent',
  open: 'bg-faint/50',
  paid: 'bg-positive/80',
  lost: 'bg-negative/60',
}

/** The very next hour, in words: what the recap's own order did. */
function nextHour(fill: HourFill | undefined, pnl: number | null | undefined, money: Money): string {
  switch (fill) {
    case 'paid':
    case 'lost':
      return pnl == null ? (fill === 'paid' ? 'paid' : "didn't pay") : `filled, ${signed(money, pnl)}`
    case 'unfilled':
      return "the order didn't fill"
    case 'open':
      return 'filled, not sold yet'
    default:
      return 'no order placed'
  }
}

/** One recap card's next hours: a strip of each hour's order (paid / lost / didn't fill /
 *  none placed), and its counts. */
export function TradeNext({ t, hours, money }: { t: PreviewTradeNext | undefined; hours: number; money: Money }) {
  if (!t) return <p className="rounded-md border border-dashed border-border px-2 py-1.5 text-xs text-faint">No orders to replay for the hours after.</p>
  const fills = hourFills(t)
  const withFills = (t.filled as unknown[] | undefined)?.length === t.paid.length && t.paid.length > 0
  return (
    <div aria-label="What happened next" role="group" className="flex flex-col gap-1.5 rounded-md border border-dashed border-accent/40 bg-bg/40 px-2.5 py-2 text-xs text-muted">
      <div className="flex gap-0.5" aria-hidden>
        {fills.map((f, i) => (
          <span key={i} className={`h-2 flex-1 rounded-sm ${FILL_STYLE[f]}`} />
        ))}
      </div>
      {withFills ? (
        <p>
          Next {hours} {hours === 1 ? 'hour' : 'hours'}: <span className="num text-text">{t.fills}</span> of <span className="num text-text">{t.orders}</span>{' '}
          {t.orders === 1 ? 'order' : 'orders'} filled, <span className="num text-text">{t.paid_hours}</span> paid
          {t.fills > 0 && (
            <>
              {' '}
              (<span className={`num ${t.profit < 0 ? 'text-negative' : t.profit > 0 ? 'text-positive' : 'text-text'}`}>{signed(money, t.profit)}</span>)
            </>
          )}
          .
        </p>
      ) : (
        <p>
          Next {hours} {hours === 1 ? 'hour' : 'hours'}: paid in <span className="num text-text">{t.paid_hours}</span> of <span className="num text-text">{t.traded_hours}</span> traded.
        </p>
      )}
      <p>
        Next hour: <span className="text-text">{nextHour(fills.at(0), (t.pnl as (number | null)[] | undefined)?.at(0), money)}</span>
        {' · '}A day later: <span className="text-text">{t.still_paid == null ? 'not known' : t.still_paid ? 'still paying' : 'stopped'}</span>
      </p>
    </div>
  )
}
