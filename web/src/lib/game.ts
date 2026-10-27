import type { MissedFlip, PreviewGameHour, PreviewGameOrder } from '../api/client'
import { EMPTY, START_CHAOS, START_DIV, type Done, type FlipTrade, type GameState, type OrderTrade, type Trade } from './gameStore'

// The preview's trading game (docs/preview.md): a player starts with 10 Divines and 200
// Chaos at the end of a day of the rewound league and steps the clock an hour at a time.
// Each hour's document (`game/{n}`) is the Market recap then, the orders a player can take
// and the Chaos prices of the items it lists to flip.
// - The wallet holds Divines and Chaos apart. Trades are paid in Chaos and pay out in
//   Chaos. Divines exchange at the hour's average Divine price, whole Divines at a time:
//   by the player (the bar's Exchange), or on their own when a trade needs more Chaos
//   than the wallet has.
// - Purchases are whole, at the real price: a player buys a number of the trade's
//   smallest whole purchases (a loop's or card's whole lot at its bid, a flip's whole
//   bid), so a trade costs at least its smallest buy-in.
// - Loops and card turn-ins: the recap's own order that hour, filled by the Backtest's
//   rules. Purchases fill up to what that order could (a tenth of what traded, 10 Divines
//   at most), earn the order's return, and are tied up until the hour it sold. Nothing
//   sells by itself at a loss: where the sale never filled (the Backtest gives up and
//   counts it lost), the player is left holding the items, flagged "Dump now", and
//   sells them (at the hour's lowest trade) or holds on.
// - Flips: a bid at the recap's price, filled the next hour if a trade went under it
//   (whole bids, up to a tenth of what traded), then the items are held and listed, at
//   the recap's ask cut each hour unless the player sets a price, selling when a trade
//   goes over it, a tenth of the hour's trades at most. Quick-selling takes the hour's
//   lowest trade.
// Nothing can be bought but what the recap lists, so the only way up is trading.

const HOUR = 3_600_000
export const CAPTURE = 0.1 // share of an hour's trades one player can take
export const TRADE_DIVINES = 10 // at most this much in one order
export const DUMP_AFTER = 6 // hours a flip is listed unsold before it can be flagged

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

/** The Divine's price in Chaos this hour (its market average); null before there is one. */
export const hourRate = (doc: PreviewGameHour | undefined) => doc?.divine_chaos || null

/** Chaos the wallet can pay this hour: its Chaos, and its whole Divines at the hour's price. */
export const spendable = (s: GameState, doc: PreviewGameHour | undefined) => s.chaos + Math.floor(s.div + 1e-9) * (hourRate(doc) ?? 0)

/** One purchase of a trade this hour (`chaos`), and how many the wallet can pay for
 *  (exchanging Divines as needed, 10 Divines' worth a trade at most). */
export function buyIn(s: GameState, doc: PreviewGameHour, chaos: number): { chaos: number; max: number } | null {
  if (!(chaos > 0)) return null
  const rate = hourRate(doc)
  const cap = Math.min(spendable(s, doc), rate ? TRADE_DIVINES * rate : Infinity)
  return { chaos, max: Math.floor((cap + 1e-9) / chaos) }
}

/** Chaos one purchase of an order costs (snapshots before purchases were whole: a
 *  hundredth of a Divine, near enough to any amount). */
export const orderLot = (o: PreviewGameOrder, doc: PreviewGameHour) => o.lot ?? (hourRate(doc) ?? 100) / 100

/** Pay `cost` Chaos, exchanging the whole Divines it takes when Chaos run short. */
export function pay(s: GameState, doc: PreviewGameHour, cost: number): GameState | string {
  const short = cost - s.chaos
  if (short <= 1e-9) return { ...s, chaos: s.chaos - cost }
  const rate = hourRate(doc)
  if (!rate) return 'Not enough Chaos, and no Divine price this hour to exchange at.'
  const n = Math.ceil(short / rate - 1e-9)
  if (n > Math.floor(s.div + 1e-9)) return 'Not enough Chaos and Divines for that.'
  return { ...s, rate, div: s.div - n, chaos: s.chaos + n * rate - cost }
}

/** Exchange `n` whole Divines at the hour's average price: `sell` Divines for Chaos, or
 *  buy Divines with Chaos. */
export function exchange(s: GameState, doc: PreviewGameHour, n: number, way: 'sell' | 'buy'): GameState | string {
  const rate = hourRate(doc)
  if (!rate) return 'No Divine price this hour yet.'
  if (!(n >= 1) || !Number.isInteger(n)) return 'Exchange whole Divines.'
  if (way === 'sell') return n > s.div + 1e-9 ? 'You don’t have that many Divines.' : { ...s, rate, div: s.div - n, chaos: s.chaos + n * rate }
  return n * rate > s.chaos + 1e-9 ? 'Not enough Chaos for that.' : { ...s, rate, div: s.div + n, chaos: s.chaos - n * rate }
}

/** Already placed this trade this hour (one order a trade an hour: the market's share
 *  can't be taken twice). */
export const placedNow = (s: GameState, kind: string, itemId: string, direction?: string | null) =>
  s.open.some((t) => t.at === s.n && orderKey(t.kind, t.item_id, t.kind === 'loop' ? t.direction : null) === orderKey(kind, itemId, direction))

function check(s: GameState, doc: PreviewGameHour, chaos: number, lots: number): string | null {
  const b = buyIn(s, doc, chaos)
  if (!b) return 'No price for this trade.'
  if (!(lots >= 1) || !Number.isInteger(lots)) return 'Buy at least one whole purchase.'
  if (b.max < 1) return `One purchase costs ${chaos.toFixed(0)}c: more than your Chaos and Divines can pay.`
  if (lots > b.max) return lots * chaos > spendable(s, doc) + 1e-9 ? 'Not enough Chaos and Divines for that.' : `${TRADE_DIVINES} Divines' worth at most in one trade.`
  return null
}

/** Place `lots` purchases of a loop's or card turn-in's order this hour: the new state,
 *  or why not. */
export function placeOrder(s: GameState, doc: PreviewGameHour, o: PreviewGameOrder, name: string, lots: number): GameState | string {
  if (o.filled == null) return 'No order this hour: it didn’t pay from the bid.'
  if (placedNow(s, o.kind, o.item_id, o.direction)) return 'Already placed this hour.'
  const lot = orderLot(o, doc)
  const why = check(s, doc, lot, lots)
  if (why) return why
  const stake = lots * lot
  const paid = pay(s, doc, stake)
  if (typeof paid === 'string') return paid
  const settle = o.settle_at ? s.n + Math.round((Date.parse(o.settle_at) - Date.parse(doc.latest_hour)) / HOUR) : null
  const t: OrderTrade = {
    id: newId(),
    kind: o.kind,
    item_id: o.item_id,
    name,
    direction: o.direction,
    at: s.n,
    stake,
    rate: hourRate(doc) ?? s.rate,
    lot,
    lots,
    filled: o.filled,
    spent: o.spent ?? null,
    pnl: o.pnl ?? null,
    settle,
    unsold: !!o.unsold,
    hold: o.hold ?? null,
    units: o.units ?? null,
    state: 'placed',
  }
  return { ...paid, rate: hourRate(doc) ?? paid.rate, open: [...paid.open, t] }
}

/** Bid for `lots` of a flip's whole bids this hour. */
export function placeFlip(s: GameState, doc: PreviewGameHour, f: MissedFlip, lots: number): GameState | string {
  if (placedNow(s, 'flip', f.item_id)) return 'Already placed this hour.'
  const why = check(s, doc, f.bid_total, lots)
  if (why) return why
  const stake = lots * f.bid_total
  const paid = pay(s, doc, stake)
  if (typeof paid === 'string') return paid
  const t: FlipTrade = {
    id: newId(),
    kind: 'flip',
    item_id: f.item_id,
    name: f.name,
    at: s.n,
    stake,
    rate: hourRate(doc) ?? s.rate,
    lot: f.bid_lot,
    lotCost: f.bid_total,
    lots,
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
  return { ...paid, rate: hourRate(doc) ?? paid.rate, open: [...paid.open, t] }
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
  let chaos = s.chaos
  const open: Trade[] = []
  const closed: Done[] = []
  for (let t of s.open) {
    if (t.kind !== 'flip') {
      if (t.state === 'placed') {
        if (!t.filled || !t.spent) {
          chaos += t.stake
          closed.push(done(t, n, t.stake, t.stake, 'unfilled'))
          continue
        }
        // Whole purchases, as many as the order filled.
        const lots = Math.min(t.lots, Math.floor(t.spent / t.lot + 1e-9))
        if (lots < 1) {
          chaos += t.stake
          closed.push(done(t, n, t.stake, t.stake, 'unfilled'))
          continue
        }
        const filled = lots * t.lot
        chaos += t.stake - filled
        t = { ...t, stake: filled, lots, state: 'filled' }
      }
      if (t.state === 'filled' && t.settle != null && n >= t.settle) {
        if (t.unsold && t.hold && t.units) {
          // The sale never filled: the items stay with the player, to sell or hold.
          t = { ...t, state: 'held', left: t.lots * t.units, mark: next.prices[t.hold]?.[1] ?? null }
          open.push(t)
          continue
        }
        if (t.pnl != null && t.spent) {
          const back = t.stake * (1 + t.pnl / t.spent)
          chaos += back
          closed.push(done(t, n, t.stake, back, 'sold'))
          continue
        }
      }
      if (t.state === 'held' && t.hold) {
        const avg = next.prices[t.hold]?.[1]
        if (avg != null) t = { ...t, mark: avg }
      }
      open.push(t)
      continue
    }
    const p = next.prices[t.item_id]
    const [lo, avg, hi, traded] = p ?? [null, null, null, null]
    if (avg != null) t = { ...t, mark: avg }
    if (t.state === 'bidding') {
      // Whole bids: as many as were placed, a tenth of what traded, 10 Divines at most.
      const lots = lo != null && lo <= t.bid ? Math.floor(Math.min(t.lots, (CAPTURE * (traded ?? 0)) / t.lot, (TRADE_DIVINES * (t.rate || Infinity)) / t.lotCost) + 1e-9) : 0
      if (lots < 1) {
        chaos += t.stake
        closed.push(done(t, n, t.stake, t.stake, 'unfilled'))
        continue
      }
      const cost = lots * t.lotCost
      const units = lots * t.lot
      chaos += t.stake - cost
      open.push({ ...t, stake: cost, lots, units, left: units, state: 'holding' })
      continue
    }
    if (n >= t.at + 2 && hi != null) {
      const ask = listingAt(t, n)
      const sold = hi > ask ? Math.min(t.left, Math.floor(CAPTURE * (traded ?? 0))) : 0
      if (sold > 0) {
        const got = sold * ask
        chaos += got
        t = { ...t, left: t.left - sold, got: t.got + got }
      }
    }
    if (t.left <= 0) closed.push(done(t, n, t.stake, t.got, 'sold'))
    else open.push(t)
  }
  return { ...s, n, rate: hourRate(next) ?? s.rate, chaos, open, done: [...s.done, ...closed] }
}

/** Items a trade holds now (a flip's, or an order's whose sale never filled): the item,
 *  how many, and what's been sold of them already (Chaos); null: none held. */
export function holding(t: Trade): { item: string; left: number; got: number } | null {
  if (t.kind === 'flip') return t.state === 'holding' ? { item: t.item_id, left: t.left, got: t.got } : null
  return t.state === 'held' && t.hold ? { item: t.hold, left: t.left ?? 0, got: 0 } : null
}

/** "Dump now": holding it no longer pays. An order's items whose sale never filled; a
 *  flip whose price fell under what it cost after DUMP_AFTER hours listed unsold. */
export function dumpNow(t: Trade, n: number): boolean {
  if (t.kind !== 'flip') return t.state === 'held'
  if (t.state !== 'holding' || t.left !== t.units) return false
  return n - (t.at + 2) >= DUMP_AFTER && t.mark < t.stake / t.units
}

/** Sell what a trade holds at this hour's lowest trade. */
export function quickSell(s: GameState, doc: PreviewGameHour, id: string): GameState | string {
  const t = s.open.find((x) => x.id === id)
  const h = t && holding(t)
  if (!t || !h) return 'Nothing held to sell.'
  const lo = doc.prices[h.item]?.[0]
  if (lo == null) return 'It didn’t trade this hour: there’s no price to sell at.'
  const got = h.left * lo
  return {
    ...s,
    chaos: s.chaos + got,
    open: s.open.filter((x) => x.id !== id),
    done: [...s.done, done(t, s.n, t.stake, h.got + got, 'quick-sold')],
  }
}

/** Set a flip's listing (Chaos an item), or null to follow the recap's. */
export function setListing(s: GameState, id: string, listing: number | null): GameState {
  if (listing != null && !(listing > 0 && Number.isFinite(listing))) return s
  return { ...s, open: s.open.map((t) => (t.id === id && t.kind === 'flip' ? { ...t, listing } : t)) }
}

/** What an open trade is worth now, in Chaos: orders at what they tied up, items held
 *  at their last average price. */
export function worth(t: Trade): number {
  if (t.kind !== 'flip') return t.state === 'held' && t.mark != null ? (t.left ?? 0) * t.mark : t.stake
  if (t.state === 'bidding') return t.stake
  return t.left * t.mark
}

/** Everything, in Divines at `rate` (the hour's, else the latest seen): the wallet and
 *  the open trades' worth. */
export function total(s: GameState, rate?: number | null): number {
  const r = rate || s.rate
  const chaos = s.chaos + s.open.reduce((sum, t) => sum + worth(t), 0)
  return s.div + (r ? chaos / r : 0)
}

/** What the player started with, in Divines at `rate`: the gain is measured against it. */
export const startWorth = (s: GameState, rate?: number | null) => START_DIV + (rate || s.rate ? START_CHAOS / (rate || s.rate) : 0)

export const profit = (s: GameState, rate?: number | null) => total(s, rate) - startWorth(s, rate)

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
