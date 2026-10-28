import type { PreviewItemNext, PriceCheckItem, Verdict } from '../api/client'
import { pctTone, price, signedPct } from '../lib/format'
import { hasHistory, VERDICT_SHORT } from '../lib/priceCheck'
import { usePreview } from '../lib/preview'
import { outcome, type Outcome } from '../lib/revealItem'
import { Skeleton } from './QueryState'
import { RevealPanel } from './Reveal'

// The preview's reveal on Price check (docs/preview.md): the price 1 and 3 days after the
// chosen day against that day's calls. What came next is drawn dotted on the item's own
// chart (PriceCheck.tsx), so opening it adds lines and these cards, and nothing moves.

type NextQuery = { data?: PreviewItemNext; error: unknown }

/** Price check's reveal: the price 1 and 3 days after the chosen day, against its calls.
 *  `drawn`: whether the item's chart shows what came next (a range ending at the day). */
export function ItemReveal({ item, next, drawn, open, onToggle }: { item: PriceCheckItem; next: NextQuery; drawn: boolean; open: boolean; onToggle: () => void }) {
  const preview = usePreview()
  return (
    <RevealPanel
      open={open}
      onToggle={onToggle}
      prompt={`This is ${item.name} as it stood at the end of day ${preview.day}. Make your call, then see what its price did next.`}
    >
      <ItemNext item={item} q={next} drawn={drawn} />
    </RevealPanel>
  )
}

function ItemNext({ item, q, drawn }: { item: PriceCheckItem; q: NextQuery; drawn: boolean }) {
  const preview = usePreview()
  const cutoff = preview.hour
  const next = q.data
  if (q.error) return <p className="text-sm text-muted">What came next isn't in the preview for this item.</p>
  if (!next || !cutoff) return <Skeleton rows={2} />
  const call = (h: 'h24' | 'd3'): Verdict => (item.outlook && hasHistory(item.outlook[h]) ? item.outlook[h].verdict : 'none')
  const days = [
    { title: '1 day later', o: outcome(next, cutoff, 24, call('h24')), verdict: call('h24') },
    { title: '3 days later', o: outcome(next, cutoff, 72, call('d3')), verdict: call('d3') },
  ]
  const unit = next.unit === 'chaos' ? 'chaos' : 'divine'
  return (
    <>
      <div className="grid gap-3 sm:grid-cols-2">
        {days.map((d) => (
          <OutcomeCard key={d.title} title={d.title} o={d.o} verdict={d.verdict} unit={unit} />
        ))}
      </div>
      <p className="text-xs text-faint">
        {drawn ? 'The dotted lines on the chart above are what came next. ' : 'Pick a range that ends at the chosen day to see what came next on the chart. '}
        Typical prices: the median of the 6 hours before each point, in {unit === 'chaos' ? 'Chaos' : 'Divines, as the calls are judged'}. A Sell call held if the price fell, a Hold call
        if it didn't.
      </p>
    </>
  )
}

function OutcomeCard({ title, o, verdict, unit }: { title: string; o: Outcome; verdict: Verdict; unit: 'chaos' | 'divine' }) {
  return (
    <div role="group" aria-label={title} className="flex flex-col gap-1.5 rounded-lg border border-border bg-bg/40 p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium text-muted">{title}</span>
        {verdict !== 'none' && <span className="text-xs text-faint">Call: {VERDICT_SHORT[verdict]}</span>}
      </div>
      {!o.known ? (
        <p className="text-sm text-muted">The preview's data ends before then.</p>
      ) : o.change == null ? (
        <p className="text-sm text-muted">It didn't trade enough around then to compare.</p>
      ) : (
        <>
          <p className={`num text-xl font-semibold ${pctTone(o.change, pctDigits(o.change))}`}>{signedPct(o.change, pctDigits(o.change))}</p>
          <p className="num text-xs text-faint">
            {price(o.from, unit)} → {price(o.to, unit)}
          </p>
          <p className="text-sm text-muted">{verdictText(verdict, o)}</p>
        </>
      )}
    </div>
  )
}

/** Whole percents, but a change under 1% keeps a decimal: −0.5%, not −0%. */
const pctDigits = (change: number) => (Math.abs(change) < 0.01 ? 1 : 0)

function verdictText(verdict: Verdict, o: Outcome): string {
  const moved = o.change! < 0 ? 'It fell' : o.change! > 0 ? 'It rose' : 'It held its price'
  if (verdict === 'none') return `${moved}. There was no call to judge.`
  if (verdict === 'sell') return o.held ? `${moved}: selling then paid. The call held.` : `${moved}: holding would have paid. The call missed.`
  return o.held ? `${moved}: holding paid. The call held.` : `${moved}: selling then would have paid. The call missed.`
}
