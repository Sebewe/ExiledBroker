import { describe, expect, it } from 'vitest'
import type { MissedFlip, PreviewGameHour, PreviewGameOrder } from '../api/client'
import { buyIn, hourAt, isoAt, listingAt, placeFlip, placeOrder, quickSell, setListing, startGame, step, tally, total } from './game'
import { parse, type FlipTrade, type GameState } from './gameStore'

const LAUNCH = '2026-03-06T20:00:00Z'
const hour = (n: number, over: Partial<PreviewGameHour> = {}): PreviewGameHour => ({
  latest_hour: isoAt(LAUNCH, n),
  divine_chaos: 100,
  recap: [],
  orders: [],
  prices: {},
  ...over,
})
const loop = (over: Partial<PreviewGameOrder> = {}): PreviewGameOrder => ({
  kind: 'loop',
  item_id: 'currency:a',
  direction: 'chaos_first',
  filled: true,
  spent: 500, // 5 div
  pnl: 50, // +10%
  settle_at: isoAt(LAUNCH, 26),
  lot: 100, // a purchase: 1 div
  ...over,
})
const flip: MissedFlip = {
  item_id: 'currency:f',
  name: 'Orb of Conflict',
  price: 100,
  low: 80,
  high: 120,
  range: 0.4,
  volume: 50000,
  bid: 80,
  ask: 110,
  bid_lot: 1,
  bid_total: 80,
  ask_lot: 1,
  ask_total: 110,
  cut: 0.1,
}
const ok = (x: GameState | string) => {
  if (typeof x === 'string') throw new Error(x)
  return x
}

describe('the game clock', () => {
  it('numbers hours from launch: the first day ends at hour 24', () => {
    expect(hourAt(LAUNCH, '2026-03-07T19:00:00Z')).toBe(24)
    expect(isoAt(LAUNCH, 24)).toBe('2026-03-07T19:00:00.000Z')
  })
})

describe('loops and card turn-ins', () => {
  it('fills up to what the order could take, refunds the rest, and pays at the sale hour', () => {
    let s = ok(placeOrder(startGame('Mirage', 24), hour(24), loop(), 'Reverent Fragment', 8))
    expect(s.cash).toBe(2)
    s = step(s, hour(25))
    // 5 of the 8 Divines filled (the order spent 500c at 100c a Divine); 3 came back.
    expect(s.cash).toBeCloseTo(5)
    expect(s.open[0]).toMatchObject({ state: 'filled', stake: 5 })
    expect(total(s)).toBeCloseTo(10)
    s = step(s, hour(26))
    expect(s.open).toEqual([])
    expect(s.cash).toBeCloseTo(10.5) // +10% on the 5 that filled
    expect(s.done[0]).toMatchObject({ outcome: 'sold', cost: 5, at: 24, closed: 26 })
    expect(tally(s.done)).toMatchObject({ trades: 1, won: 1 })
    expect(tally(s.done).profit).toBeCloseTo(0.5)
  })

  it("gives everything back when the order didn't fill", () => {
    let s = ok(placeOrder(startGame('Mirage', 24), hour(24), loop({ filled: false, spent: null, pnl: null, settle_at: null }), 'X', 4))
    s = step(s, hour(25))
    expect(s.cash).toBe(10)
    expect(s.done[0]).toMatchObject({ outcome: 'unfilled', cost: 4, back: 4 })
    expect(tally(s.done)).toMatchObject({ trades: 0, unfilled: 1 })
  })

  it('keeps a sale past the data open, at what it cost', () => {
    let s = ok(placeOrder(startGame('Mirage', 24), hour(24), loop({ pnl: null, settle_at: null }), 'X', 5))
    s = step(step(s, hour(25)), hour(26))
    expect(s.open).toHaveLength(1)
    expect(total(s)).toBeCloseTo(10)
  })

  it('refuses no order, too much, and the same trade twice in an hour', () => {
    const s = startGame('Mirage', 24)
    expect(placeOrder(s, hour(24), loop({ filled: null }), 'X', 1)).toMatch(/No order/)
    expect(placeOrder(s, hour(24), loop(), 'X', 11)).toMatch(/don’t have/)
    expect(placeOrder(s, hour(24), loop(), 'X', 0)).toMatch(/at least one/)
    expect(placeOrder(s, hour(24), loop(), 'X', 1.5)).toMatch(/at least one/)
    expect(placeOrder(s, hour(24, { divine_chaos: null }), loop(), 'X', 1)).toMatch(/Divine price/)
    const once = ok(placeOrder(s, hour(24), loop(), 'X', 1))
    expect(placeOrder(once, hour(24), loop(), 'X', 1)).toMatch(/Already/)
  })

  it("can't buy into a trade whose smallest purchase costs more than what's free", () => {
    const s = ok(placeOrder(startGame('Mirage', 24), hour(24), loop(), 'X', 8)) // 2 div left
    expect(placeOrder(s, hour(24), loop({ item_id: 'currency:b', lot: 300 }), 'Y', 1)).toMatch(/One purchase costs 3.00 div/)
    expect(buyIn(s, hour(24), 300)).toMatchObject({ div: 3, max: 0 })
    expect(buyIn(s, hour(24), 50)).toMatchObject({ div: 0.5, max: 4 })
  })

  it('fills whole purchases only, and converts at the price fixed at the first trade', () => {
    let s = ok(placeOrder(startGame('Mirage', 24), hour(24), loop({ spent: 250, pnl: 25, lot: 100 }), 'X', 5))
    expect(s.rate).toBe(100)
    s = step(s, hour(25, { divine_chaos: 200 })) // the Divine's price moved: the game's didn't
    expect(s.open[0]).toMatchObject({ lots: 2, stake: 2 }) // 250c fills 2 whole 100c purchases
    expect(s.cash).toBeCloseTo(8)
    s = step(s, hour(26, { divine_chaos: 200 }))
    expect(s.cash).toBeCloseTo(10.2) // +10% on 2 div
  })
})

describe('flips', () => {
  const held = () => {
    const s = ok(placeFlip(startGame('Mirage', 24), hour(24), flip, 5)) // 5 bids of 1 item at 80c: 4 div
    return step(s, hour(25, { prices: { 'currency:f': [78, 90, 100, 1000] } }))
  }

  it('bids in whole lots', () => {
    const lots = { ...flip, bid_lot: 4, bid_total: 320 } // 4 items for 320c: 3.2 div a bid
    expect(placeFlip(startGame('Mirage', 24), hour(24), lots, 4)).toMatch(/don’t have/)
    const s = step(ok(placeFlip(startGame('Mirage', 24), hour(24), lots, 3)), hour(25, { prices: { 'currency:f': [78, 90, 100, 90] } }))
    // A tenth of 90 traded is 9 items: 2 whole lots of 4.
    expect(s.open[0]).toMatchObject({ lots: 2, units: 8 })
    expect(s.cash).toBeCloseTo(10 - 6.4)
  })

  it("buys the next hour if a trade went under the bid, as many as a tenth of the hour's trades", () => {
    const s = held()
    expect(s.open[0]).toMatchObject({ state: 'holding', units: 5, left: 5, mark: 90 })
    expect(s.cash).toBeCloseTo(6)
    const thin = step(ok(placeFlip(startGame('Mirage', 24), hour(24), flip, 5)), hour(25, { prices: { 'currency:f': [78, 90, 100, 30] } }))
    expect(thin.open[0]).toMatchObject({ units: 3 })
    expect(thin.cash).toBeCloseTo(10 - 2.4)
  })

  it("gives the bid back when nothing traded under it", () => {
    const s = step(ok(placeFlip(startGame('Mirage', 24), hour(24), flip, 5)), hour(25, { prices: { 'currency:f': [85, 90, 100, 1000] } }))
    expect(s.cash).toBe(10)
    expect(s.done[0]!.outcome).toBe('unfilled')
  })

  it('lists at the ask, cut each hour, and sells when a trade goes over it', () => {
    let s = held()
    const t = () => s.open[0] as FlipTrade
    expect(listingAt(t(), 26)).toBeCloseTo(110)
    expect(listingAt(t(), 27)).toBeCloseTo(99)
    s = step(s, hour(26, { prices: { 'currency:f': [90, 100, 105, 1000] } })) // under 110: unsold
    expect(t().left).toBe(5)
    s = step(s, hour(27, { prices: { 'currency:f': [90, 100, 105, 20] } })) // over 99: 2 of 20 traded
    expect(t().left).toBe(3)
    expect(t().got).toBeCloseTo(1.98)
    s = step(s, hour(28, { prices: { 'currency:f': [80, 95, 100, 1000] } })) // over 89.1: the rest
    expect(s.open).toEqual([])
    expect(s.done[0]).toMatchObject({ outcome: 'sold', cost: 4 })
    expect(s.done[0]!.back).toBeCloseTo(1.98 + (3 * 89.1) / 100)
  })

  it("holds at the player's price, and sells now at the hour's lowest trade", () => {
    const h = held()
    const id = h.open[0]!.id
    let s = setListing(h, id, 200)
    s = step(s, hour(26, { prices: { 'currency:f': [90, 100, 150, 1000] } }))
    expect((s.open[0] as FlipTrade).left).toBe(5) // never over 200
    expect(total(s)).toBeCloseTo(6 + (5 * 100) / 100)
    expect(quickSell(s, hour(26), id)).toMatch(/didn’t trade/)
    s = ok(quickSell(s, hour(26, { prices: { 'currency:f': [90, 100, 150, 1000] } }), id))
    expect(s.cash).toBeCloseTo(6 + 4.5)
    expect(s.done[0]).toMatchObject({ outcome: 'quick-sold', cost: 4, back: 4.5 })
  })
})

describe('the stored game', () => {
  it('starts fresh from anything unreadable', () => {
    expect(parse(null).n).toBe(0)
    expect(parse('{').cash).toBe(10)
    expect(parse(JSON.stringify({ v: 2, league: 'Mirage', n: 'x', cash: 1, open: [], done: [] })).n).toBe(0)
    // A game from before whole purchases starts over.
    expect(parse(JSON.stringify({ league: 'Mirage', n: 30, start: 24, cash: 7, open: [], done: [] })).n).toBe(0)
    const s = parse(JSON.stringify({ v: 2, league: 'Mirage', n: 30, start: 24, rate: 120, cash: 7, open: [{ id: 'a', stake: 3, at: 29, lots: 3 }, { junk: true }], done: [] }))
    expect(s).toMatchObject({ league: 'Mirage', n: 30, cash: 7, rate: 120 })
    expect(s.open).toHaveLength(1)
  })

  it('keeps the closed trades across a reload', () => {
    const done = { id: 'b', kind: 'loop', item_id: 'currency:x', name: 'X', at: 24, closed: 26, cost: 1, back: 1.4, outcome: 'sold' }
    const s = parse(JSON.stringify({ v: 2, league: 'Mirage', n: 30, start: 24, cash: 7, open: [], done: [done, { id: 'c', at: 25 }] }))
    expect(s.done).toEqual([done])
  })
})
