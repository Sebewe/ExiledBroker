import type { PreviewRecapNext, PreviewTradeNext } from '../api/client'

// The preview's "what happened next" on the recap (docs/preview.md): whether each of the
// chosen day's trades kept paying over the next 24 hours. Price check's part, the price
// after the day against its call, is lib/revealItem.ts.

/** A recap trade's key: kind, item and (for loops) direction, as on the recap's rows. */
export const tradeKey = (kind: PreviewTradeNext['kind'], itemId: string, direction?: string | null) =>
  `${kind}|${itemId}|${kind === 'loop' ? (direction ?? '') : ''}`

export function tradesByKey(next: PreviewRecapNext | undefined): Map<string, PreviewTradeNext> {
  return new Map((next?.trades ?? []).map((x) => [tradeKey(x.kind, x.item_id, x.direction), x]))
}

/** How many of `trades` paid the very next hour, and how many still paid a day later
 *  (counted over those with a known answer). */
export function recapTally(trades: PreviewTradeNext[]) {
  const nextKnown = trades.filter((x) => x.next_hour_paid != null)
  const dayKnown = trades.filter((x) => x.still_paid != null)
  return {
    shown: trades.length,
    nextHour: nextKnown.filter((x) => x.next_hour_paid).length,
    nextKnown: nextKnown.length,
    dayLater: dayKnown.filter((x) => x.still_paid).length,
    dayKnown: dayKnown.length,
  }
}
