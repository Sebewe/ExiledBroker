import type { PreviewItemNext, SeriesPoint, Verdict } from '../api/client'
import { HOUR } from './chartOptions'

// The preview's "what happened next" on Price check (docs/preview.md): what the price did
// 1 and 3 days after the chosen day against that day's call. Pure parts; the chart is
// the item's own (lib/priceCheck.priceChartOption's `next`).

/** Hours a "typical price" looks back over: the median of the latest priced hours, as
 *  the movers' prices are, so one junk hour in a thin market doesn't decide the outcome. */
const TYPICAL_HOURS = 6

export type Outcome = {
  hours: number
  /** The typical price at the chosen day's end, and `hours` later (Divines, or Chaos for
   *  an item priced in Chaos). Null: no price there. */
  from: number | null
  to: number | null
  change: number | null
  /** Whether the call held: Sell, it fell; Hold, it didn't. Null without a call or a change. */
  held: boolean | null
  /** False: the snapshot ends before `hours` after the chosen day. */
  known: boolean
}

const value = (next: PreviewItemNext, p: SeriesPoint) => (next.unit === 'chaos' ? p[1] : p[2])

function median(xs: number[]): number | null {
  if (!xs.length) return null
  const s = [...xs].sort((a, b) => a - b)
  const m = Math.floor(s.length / 2)
  return s.length % 2 ? s[m]! : (s[m - 1]! + s[m]!) / 2
}

/** The median price of the hours in (at − 6 h, at]. */
export function typicalAt(next: PreviewItemNext, at: number): number | null {
  const xs: number[] = []
  for (const p of next.series) {
    const t = Date.parse(p[0])
    const v = value(next, p)
    if (t > at - TYPICAL_HOURS * HOUR && t <= at && v != null) xs.push(v)
  }
  return median(xs)
}

/** The last hour the snapshot has, in ms (its series runs to `next_until`). */
function lastHour(next: PreviewItemNext): number | null {
  const last = next.series[next.series.length - 1]
  return last ? Date.parse(last[0]) : null
}

/** What happened `hours` after `cutoff` (the chosen day's last hour), against `verdict`. */
export function outcome(next: PreviewItemNext, cutoff: string, hours: number, verdict: Verdict): Outcome {
  const start = Date.parse(cutoff)
  const end = start + hours * HOUR
  const last = lastHour(next)
  const known = last != null && last >= end
  const from = typicalAt(next, start)
  const to = known ? typicalAt(next, end) : null
  const change = from && to != null ? to / from - 1 : null
  const held = change == null || verdict === 'none' ? null : verdict === 'sell' ? change < 0 : change >= 0
  return { hours, from, to, change, held, known }
}
