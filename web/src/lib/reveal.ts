import type { PreviewRecapNext, PreviewTradeNext } from '../api/client'

// The preview's "what happened next" on the recap (docs/preview.md): whether each of the
// chosen day's trades kept paying over the next 24 hours, its order placed each hour and
// filled by the Backtest's rules. Price check's part, the price after the day against its
// call, is lib/revealItem.ts.

/** A recap trade's key: kind, item and (for loops) direction, as on the recap's rows. */
export const tradeKey = (kind: PreviewTradeNext['kind'], itemId: string, direction?: string | null) =>
  `${kind}|${itemId}|${kind === 'loop' ? (direction ?? '') : ''}`

export function tradesByKey(next: PreviewRecapNext | undefined): Map<string, PreviewTradeNext> {
  return new Map((next?.trades ?? []).map((x) => [tradeKey(x.kind, x.item_id, x.direction), x]))
}

/** One hour of a trade's orders: none placed, placed and not filled, filled with the sale
 *  not known yet, or filled and sold at a profit or a loss. */
export type HourFill = 'none' | 'unfilled' | 'open' | 'paid' | 'lost'

/** A trade's hours (a snapshot built before fills were stored has none: `paid` alone). */
export function hourFills(t: PreviewTradeNext): HourFill[] {
  const filled = (t.filled as (boolean | null)[] | undefined) ?? []
  return t.paid.map((p, i) => {
    const f = filled.at(i)
    if (f === undefined) return p == null ? 'none' : p ? 'paid' : 'lost'
    if (f == null) return 'none'
    if (!f) return 'unfilled'
    return p == null ? 'open' : p ? 'paid' : 'lost'
  })
}

/** How many of `trades` paid the very next hour, and how many still paid a day later
 *  (counted over those with a known answer); and, following every order they'd have
 *  placed, how many were placed and filled and what the known sales made (Chaos). */
export function recapTally(trades: PreviewTradeNext[]) {
  const nextKnown = trades.filter((x) => x.next_hour_paid != null)
  const dayKnown = trades.filter((x) => x.still_paid != null)
  return {
    shown: trades.length,
    nextHour: nextKnown.filter((x) => x.next_hour_paid).length,
    nextKnown: nextKnown.length,
    dayLater: dayKnown.filter((x) => x.still_paid).length,
    dayKnown: dayKnown.length,
    orders: trades.reduce((n, x) => n + (x.orders ?? 0), 0),
    fills: trades.reduce((n, x) => n + (x.fills ?? 0), 0),
    profit: trades.reduce((n, x) => n + (x.profit ?? 0), 0),
  }
}
