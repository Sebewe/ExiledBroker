import type { MissedFlip, PreviewGameHour, PreviewGameOrder } from '../api/client'
import { EMPTY, START_CASH, type Done, type FlipTrade, type GameState, type OrderTrade, type Trade } from './gameStore'

// The preview's trading game (docs/preview.md): a player starts with 10 Divines at the
// end of a day of the rewound league and steps the clock an hour at a time. Each hour's
// document (`game/{n}`) is the Market recap then, the orders a player can take and the
// Chaos prices of the items it lists to flip.
// - Loops and card turn-ins: the recap's own order that hour, filled by the Backtest's
//   rules. A stake fills up to what that order could (a tenth of what traded, 10 Divines
//   at most), earns the order's return on it, and is tied up until the hour it sold.
// - Flips: a bid at the recap's price, filled the next hour if a trade went under it
//   (up to a tenth of what traded), then the items are held and listed, at the recap's
//   ask cut each hour unless the player sets a price, selling when a trade goes over it,
//   a tenth of the hour's trades at most. Quick-selling takes the hour's lowest trade.
// Nothing can be bought but what the recap lists, so the only way up is trading.

const HOUR = 3_600_000
export const CAPTURE = 0.1 // share of an hour's trades one player can take
export const TRADE_DIVINES = 10 // at most this much in one order

/** The game hour (hours since launch) whose latest loaded hour is `iso`. */
export const hourAt = (launchedAt: string, iso: string) => Math.round((Date.parse(iso) - Date.parse(launchedAt)) / HOUR) + 1

/** The latest loaded hour of game hour `n`, ISO. */
export const isoAt = (launchedAt: string, n: number) => new Date(Date.parse(launchedAt) + (n - 1) * HOUR).toISOString()

/** The launch day game hour `n` is in (hour 24 is the end of day 1). */
export const dayOf = (n: number) => Math.max(1, Math.ceil(n / 24))

export const orderKey = (kind: string, itemId: string, direction?: string | null) => `${kind}|${itemId}|${kind === 'loop' ? (direction ?? '') : ''}`

/** The order a loop or card offers in this hour; undefined: none placed (it didn't pay
 *  from the bid then). */
export function orderIn(doc: PreviewGameHour | undefined, kind: 'loop' | 'card', itemId: string, direction?: string | null): PreviewGameOrder | undefined {
  const o = doc?.orders.find((x) => x.kind === kind && x.item_id === itemId && (kind !== 'loop' || x.direction === direction))
  return o && o.filled != null ? o : undefined
}

let seq = 0
const newId = () => `${Date.now().toString(36)}-${(seq++).toString(36)}`

export function startGame(league: string, n: number): GameState {
  return { ...EMPTY, league, n, start: n }
}

/** Already placed this trade this hour (one order a trade an hour: the market's share
 *  can't be taken twice). */
export const placedNow = (s: GameState, kind: string, itemId: string, direction?: string | null) =>
  s.open.some((t) => t.at === s.n && orderKey(t.kind, t.item_id, t.kind === 'loop' ? t.direction : null) === orderKey(kind, itemId, direction))

function check(s: GameState, doc: PreviewGameHour, stake: number): string | null {
  if (!doc.divine_chaos) return 'There is no Divine price this hour yet.'
  if (!(stake > 0)) return 'Put in more than nothing.'
  if (stake > s.cash + 1e-9) return 'You don’t have that many Divines free.'
  return null
}

/** Place a loop's or card turn-in's order this hour: the new state, or why not. */
export function placeOrder(s: GameState, doc: PreviewGameHour, o: PreviewGameOrder, name: string, stake: number): GameState | string {
  const why = check(s, doc, stake)
  if (why) return why
  if (o.filled == null) return 'No order this hour: it didn’t pay from the bid.'
  if (placedNow(s, o.kind, o.item_id, o.direction)) return 'Already placed this hour.'
  const settle = o.settle_at ? s.n + Math.round((Date.parse(o.settle_at) - Date.parse(doc.latest_hour)) / HOUR) : null
  const t: OrderTrade = {
    id: newId(),
    kind: o.kind,
    item_id: o.item_id,
    name,
    direction: o.direction,
    at: s.n,
    stake,
    rate: doc.divine_chaos!,
    filled: o.filled,
    spent: o.spent ?? null,
    pnl: o.pnl ?? null,
    settle,
    state: 'placed',
  }
  return { ...s, cash: s.cash - stake, open: [...s.open, t] }
}

/** Bid on a flip this hour. */
export function placeFlip(s: GameState, doc: PreviewGameHour, f: MissedFlip, stake: number): GameState | string {
  const why = check(s, doc, stake)
  if (why) return why
  if (placedNow(s, 'flip', f.item_id)) return 'Already placed this hour.'
  const t: FlipTrade = {
    id: newId(),
    kind: 'flip',
    item_id: f.item_id,
    name: f.name,
    at: s.n,
    stake,
    rate: doc.divine_chaos!,
    bid: f.bid,
    ask: f.ask,
    cut: f.cut,
    units: 0,
    left: 0,
    got: 0,
    listing: null,
    mark: f.price,
    state: 'bidding',
  }
  return { ...s, cash: s.cash - stake, open: [...s.open, t] }
}

/** A flip's listing in game hour `n` (Chaos an item): the player's, or the recap's ask
 *  cut once for each hour it has been listed (it's listed from the hour after the buy). */
export const listingAt = (t: FlipTrade, n: number) => t.listing ?? t.ask * (1 - t.cut) ** Math.max(0, n - (t.at + 2))

const done = (t: Trade, closed: number, cost: number, back: number, outcome: Done['outcome']): Done => ({
  id: t.id,
  kind: t.kind,
  item_id: t.item_id,
  name: t.name,
  direction: t.kind === 'flip' ? null : t.direction,
  at: t.at,
  closed,
  cost,
  back,
  outcome,
})

/** Step the clock to the next hour (`next`: its document): fills, sales and refunds. */
export function step(s: GameState, next: PreviewGameHour): GameState {
  const n = s.n + 1
  const rate = next.divine_chaos
  let cash = s.cash
  const open: Trade[] = []
  const closed: Done[] = []
  for (let t of s.open) {
    if (t.kind !== 'flip') {
      if (t.state === 'placed') {
        if (!t.filled || !t.spent) {
          cash += t.stake
          closed.push(done(t, n, t.stake, t.stake, 'unfilled'))
          continue
        }
        const filled = Math.min(t.stake, t.spent / t.rate)
        cash += t.stake - filled
        t = { ...t, stake: filled, state: 'filled' }
      }
      if (t.settle != null && t.pnl != null && t.spent && n >= t.settle) {
        const back = t.stake * (1 + t.pnl / t.spent)
        cash += back
        closed.push(done(t, n, t.stake, back, 'sold'))
        continue
      }
      open.push(t)
      continue
    }
    const p = next.prices[t.item_id]
    const [lo, avg, hi, traded] = p ?? [null, null, null, null]
    if (avg != null) t = { ...t, mark: avg }
    if (t.state === 'bidding') {
      const r = t.rate
      const take = lo != null && lo <= t.bid ? Math.floor(Math.min((t.stake * r) / t.bid, CAPTURE * (traded ?? 0), (TRADE_DIVINES * r) / t.bid)) : 0
      if (take < 1) {
        cash += t.stake
        closed.push(done(t, n, t.stake, t.stake, 'unfilled'))
        continue
      }
      const cost = (take * t.bid) / r
      cash += t.stake - cost
      open.push({ ...t, stake: cost, units: take, left: take, state: 'holding' })
      continue
    }
    if (n >= t.at + 2 && hi != null && rate) {
      const ask = listingAt(t, n)
      const sold = hi > ask ? Math.min(t.left, Math.floor(CAPTURE * (traded ?? 0))) : 0
      if (sold > 0) {
        const got = (sold * ask) / rate
        cash += got
        t = { ...t, left: t.left - sold, got: t.got + got }
      }
    }
    if (t.left <= 0) closed.push(done(t, n, t.stake, t.got, 'sold'))
    else open.push(t)
  }
  return { ...s, n, cash, open, done: [...s.done, ...closed] }
}

/** Sell what's left of a flip at this hour's lowest trade. */
export function quickSell(s: GameState, doc: PreviewGameHour, id: string): GameState | string {
  const t = s.open.find((x) => x.id === id)
  if (!t || t.kind !== 'flip' || t.state !== 'holding') return 'Nothing held to sell.'
  const lo = doc.prices[t.item_id]?.[0]
  const rate = doc.divine_chaos
  if (lo == null || !rate) return 'It didn’t trade this hour: there’s no price to sell at.'
  const got = (t.left * lo) / rate
  return {
    ...s,
    cash: s.cash + got,
    open: s.open.filter((x) => x.id !== id),
    done: [...s.done, done(t, s.n, t.stake, t.got + got, 'quick-sold')],
  }
}

/** Set a flip's listing (Chaos an item), or null to follow the recap's. */
export function setListing(s: GameState, id: string, listing: number | null): GameState {
  if (listing != null && !(listing > 0 && Number.isFinite(listing))) return s
  return { ...s, open: s.open.map((t) => (t.id === id && t.kind === 'flip' ? { ...t, listing } : t)) }
}

/** What an open trade is worth now, in Divines: orders at what they tied up, items held
 *  at their last average price. */
export function worth(t: Trade, rate: number | null | undefined): number {
  if (t.kind !== 'flip' || t.state === 'bidding') return t.stake
  return (t.left * t.mark) / (rate || t.rate)
}

/** Everything: free Divines and the open trades' worth. */
export const total = (s: GameState, rate: number | null | undefined) => s.cash + s.open.reduce((sum, t) => sum + worth(t, rate), 0)

export const profit = (s: GameState, rate: number | null | undefined) => total(s, rate) - START_CASH

/** The closed trades' tally: how many made money, and what they made. */
export function tally(xs: Done[]) {
  const traded = xs.filter((x) => x.outcome !== 'unfilled')
  return {
    trades: traded.length,
    won: traded.filter((x) => x.back > x.cost).length,
    profit: traded.reduce((sum, x) => sum + x.back - x.cost, 0),
    unfilled: xs.length - traded.length,
  }
}
