import { describe, expect, it } from 'vitest'
import type { MissedFlip, PreviewGameHour, PreviewGameOrder } from '../api/client'
import { buyIn, exchange, hourAt, isoAt, listingAt, pay, placeFlip, placeOrder, profit, quickSell, setListing, startGame, startWorth, step, tally, total } from './game'
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

describe('the wallet', () => {
  it('starts with 10 Divines and 200 Chaos, and exchanges whole Divines at the hour\'s average', () => {
    let s = startGame('Mirage', 24)
    expect(s).toMatchObject({ div: 10, chaos: 200 })
    s = ok(exchange(s, hour(24), 2, 'sell'))
    expect(s).toMatchObject({ div: 8, chaos: 400, rate: 100 })
    s = ok(exchange(s, hour(24, { divine_chaos: 130 }), 3, 'buy'))
    expect(s.div).toBe(11)
    expect(s.chaos).toBeCloseTo(10)
    expect(exchange(s, hour(24), 1, 'buy')).toMatch(/Not enough Chaos/)
    expect(exchange(s, hour(24), 12, 'sell')).toMatch(/that many Divines/)
    expect(exchange(s, hour(24), 0.5, 'sell')).toMatch(/whole Divines/)
    expect(exchange(s, hour(24, { divine_chaos: null }), 1, 'sell')).toMatch(/No Divine price/)
  })

  it('pays in Chaos, exchanging the whole Divines it takes when Chaos run short', () => {
    const s = ok(pay(startGame('Mirage', 24), hour(24), 250))
    expect(s).toMatchObject({ div: 9, chaos: 50 })
    expect(ok(pay(s, hour(24), 50))).toMatchObject({ div: 9, chaos: 0 })
    expect(pay(s, hour(24, { divine_chaos: null }), 60)).toMatch(/no Divine price/)
  })

  it('values everything in Divines at the hour\'s price, against what it started with', () => {
    const s = startGame('Mirage', 24)
    expect(total(s, 100)).toBeCloseTo(12)
    expect(startWorth(s, 200)).toBeCloseTo(11)
    expect(profit(s, 200)).toBeCloseTo(0)
  })
})

describe('loops and card turn-ins', () => {
  it('fills whole purchases up to what the order could take, refunds the rest, and pays at the sale hour', () => {
    let s = ok(placeOrder(startGame('Mirage', 24), hour(24), loop(), 'Reverent Fragment', 8))
    // 800c: the 200 Chaos, and 6 Divines exchanged at 100c.
    expect(s).toMatchObject({ div: 4, chaos: 0 })
    s = step(s, hour(25))
    // 5 of the 8 purchases filled (the order spent 500c); 300c came back.
    expect(s.chaos).toBeCloseTo(300)
    expect(s.open[0]).toMatchObject({ state: 'filled', stake: 500, lots: 5 })
    expect(total(s, 100)).toBeCloseTo(12)
    s = step(s, hour(26))
    expect(s.open).toEqual([])
    expect(s.chaos).toBeCloseTo(850) // +10% on the 500 that filled
    expect(s.done[0]).toMatchObject({ outcome: 'sold', cost: 500, at: 24, closed: 26 })
    expect(tally(s.done)).toMatchObject({ trades: 1, won: 1 })
    expect(tally(s.done).profit).toBeCloseTo(50)
    expect(profit(s, 100)).toBeCloseTo(0.5)
  })

  it("gives everything back when the order didn't fill", () => {
    let s = ok(placeOrder(startGame('Mirage', 24), hour(24), loop({ filled: false, spent: null, pnl: null, settle_at: null }), 'X', 1))
    expect(s.chaos).toBe(100)
    s = step(s, hour(25))
    expect(s.chaos).toBe(200)
    expect(s.done[0]).toMatchObject({ outcome: 'unfilled', cost: 100, back: 100 })
    expect(tally(s.done)).toMatchObject({ trades: 0, unfilled: 1 })
  })

  it('keeps a sale past the data open, at what it cost', () => {
    let s = ok(placeOrder(startGame('Mirage', 24), hour(24), loop({ pnl: null, settle_at: null }), 'X', 5))
    s = step(step(s, hour(25)), hour(26))
    expect(s.open).toHaveLength(1)
    expect(total(s, 100)).toBeCloseTo(12)
  })

  it('refuses no order, too much, part purchases and the same trade twice in an hour', () => {
    const s = startGame('Mirage', 24)
    expect(placeOrder(s, hour(24), loop({ filled: null }), 'X', 1)).toMatch(/No order/)
    expect(placeOrder(s, hour(24), loop(), 'X', 11)).toMatch(/10 Divines/)
    expect(placeOrder(s, hour(24), loop({ lot: 120 }), 'X', 11)).toMatch(/Not enough Chaos and Divines/)
    expect(placeOrder(s, hour(24), loop(), 'X', 0)).toMatch(/at least one/)
    expect(placeOrder(s, hour(24), loop(), 'X', 1.5)).toMatch(/at least one/)
    const once = ok(placeOrder(s, hour(24), loop(), 'X', 1))
    expect(placeOrder(once, hour(24), loop(), 'X', 1)).toMatch(/Already/)
  })

  it('trades from Chaos alone before there is a Divine price', () => {
    const s = startGame('Mirage', 24)
    const early = hour(24, { divine_chaos: null })
    expect(placeOrder(s, early, loop(), 'X', 3)).toMatch(/Not enough/)
    expect(ok(placeOrder(s, early, loop(), 'X', 2))).toMatchObject({ div: 10, chaos: 0 })
  })

  it("can't buy into a trade whose smallest purchase costs more than the wallet", () => {
    const s = startGame('Mirage', 24)
    expect(placeOrder(s, hour(24), loop({ lot: 1300 }), 'Y', 1)).toMatch(/One purchase costs 1300c/)
    expect(buyIn(s, hour(24), 1300)).toMatchObject({ max: 0 })
    expect(buyIn(s, hour(24), 300)).toMatchObject({ max: 3 }) // 10 Divines' worth a trade
  })
})

describe('flips', () => {
  const held = () => {
    const s = ok(placeFlip(startGame('Mirage', 24), hour(24), flip, 5)) // 5 bids of 1 item at 80c
    return step(s, hour(25, { prices: { 'currency:f': [78, 90, 100, 1000] } }))
  }

  it('bids in whole lots', () => {
    const lots = { ...flip, bid_lot: 4, bid_total: 320 } // 4 items for 320c
    expect(placeFlip(startGame('Mirage', 24), hour(24), lots, 4)).toMatch(/Not enough/)
    let s = ok(placeFlip(startGame('Mirage', 24), hour(24), lots, 3))
    expect(s).toMatchObject({ div: 2, chaos: 40 })
    s = step(s, hour(25, { prices: { 'currency:f': [78, 90, 100, 90] } }))
    // A tenth of 90 traded is 9 items: 2 whole lots of 4.
    expect(s.open[0]).toMatchObject({ lots: 2, units: 8, stake: 640 })
    expect(s.chaos).toBeCloseTo(360)
  })

  it("buys the next hour if a trade went under the bid, as many as a tenth of the hour's trades", () => {
    const s = held()
    expect(s.open[0]).toMatchObject({ state: 'holding', units: 5, left: 5, mark: 90, stake: 400 })
    expect(s).toMatchObject({ div: 8, chaos: 0 })
    const thin = step(ok(placeFlip(startGame('Mirage', 24), hour(24), flip, 5)), hour(25, { prices: { 'currency:f': [78, 90, 100, 30] } }))
    expect(thin.open[0]).toMatchObject({ units: 3 })
    expect(thin.chaos).toBeCloseTo(160)
  })

  it('gives the bid back when nothing traded under it', () => {
    const s = step(ok(placeFlip(startGame('Mirage', 24), hour(24), flip, 5)), hour(25, { prices: { 'currency:f': [85, 90, 100, 1000] } }))
    expect(s.chaos).toBe(400)
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
    expect(t().got).toBeCloseTo(198)
    s = step(s, hour(28, { prices: { 'currency:f': [80, 95, 100, 1000] } })) // over 89.1: the rest
    expect(s.open).toEqual([])
    expect(s.done[0]).toMatchObject({ outcome: 'sold', cost: 400 })
    expect(s.done[0]!.back).toBeCloseTo(198 + 3 * 89.1)
  })

  it("holds at the player's price, and sells now at the hour's lowest trade", () => {
    const h = held()
    const id = h.open[0]!.id
    let s = setListing(h, id, 200)
    s = step(s, hour(26, { prices: { 'currency:f': [90, 100, 150, 1000] } }))
    expect((s.open[0] as FlipTrade).left).toBe(5) // never over 200
    expect(total(s, 100)).toBeCloseTo(8 + (5 * 100) / 100)
    expect(quickSell(s, hour(26), id)).toMatch(/didn’t trade/)
    s = ok(quickSell(s, hour(26, { prices: { 'currency:f': [90, 100, 150, 1000] } }), id))
    expect(s.chaos).toBeCloseTo(450)
    expect(s.done[0]).toMatchObject({ outcome: 'quick-sold', cost: 400, back: 450 })
  })
})

describe('the stored game', () => {
  it('starts fresh from anything unreadable', () => {
    expect(parse(null).n).toBe(0)
    expect(parse('{')).toMatchObject({ div: 10, chaos: 200 })
    expect(parse(JSON.stringify({ v: 3, league: 'Mirage', n: 'x', div: 1, chaos: 1, open: [], done: [] })).n).toBe(0)
    // A game from before the Chaos wallet starts over.
    expect(parse(JSON.stringify({ v: 2, league: 'Mirage', n: 30, start: 24, rate: 120, cash: 7, open: [], done: [] })).n).toBe(0)
    const s = parse(JSON.stringify({ v: 3, league: 'Mirage', n: 30, start: 24, rate: 120, div: 7, chaos: 50, open: [{ id: 'a', stake: 3, at: 29, lots: 3 }, { junk: true }], done: [] }))
    expect(s).toMatchObject({ league: 'Mirage', n: 30, div: 7, chaos: 50, rate: 120 })
    expect(s.open).toHaveLength(1)
  })

  it('keeps the closed trades across a reload', () => {
    const done = { id: 'b', kind: 'loop', item_id: 'currency:x', name: 'X', at: 24, closed: 26, cost: 1, back: 1.4, outcome: 'sold' }
    const s = parse(JSON.stringify({ v: 3, league: 'Mirage', n: 30, start: 24, div: 7, chaos: 0, open: [], done: [done, { id: 'c', at: 25 }] }))
    expect(s.done).toEqual([done])
  })
})
