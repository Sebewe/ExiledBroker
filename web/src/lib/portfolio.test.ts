import { afterEach, describe, expect, it } from 'vitest'
import type { PreviewItemNext } from '../api/client'
import { atFor, DIVINE, hoursFrom, keptAsChaos, MAX_POSITIONS, parse, portfolio, valueStake } from './portfolio'

const HOUR = 3_600_000
const T0 = Date.parse('2026-03-07T23:00:00Z')
const iso = (ms: number) => new Date(ms).toISOString()

/** A path priced `before` up to T0 and `after` from the hour after it. */
function path(before: number, after: number | null, unit: 'divine' | 'chaos' = 'divine'): PreviewItemNext {
  return {
    item_id: 'currency:x',
    name: 'X',
    unit,
    series: Array.from({ length: 30 }, (_, i) => {
      const at = T0 - 10 * HOUR + i * HOUR
      const v = at <= T0 ? before : after
      return unit === 'chaos' ? [iso(at), v, null] : [iso(at), v == null ? null : v * 100, v]
    }),
  }
}

afterEach(() => {
  localStorage.clear()
  portfolio.reload()
})

describe('the stored portfolio', () => {
  it('reads anything broken as empty', () => {
    expect(parse(null).positions).toEqual([])
    expect(parse('{not json').positions).toEqual([])
    expect(parse('{"positions": 3}').positions).toEqual([])
  })

  it('drops bad stakes, repeats and the Divine Orb, and caps the count', () => {
    const raw = JSON.stringify({
      day: 5,
      at: 7,
      positions: [
        { item_id: 'a', name: 'A', stake: 10 },
        { item_id: 'a', name: 'A again', stake: 5 },
        { item_id: 'b', name: 'B', stake: -1 },
        { item_id: DIVINE, name: 'Divine Orb', stake: 10 },
        ...Array.from({ length: 12 }, (_, i) => ({ item_id: `x${i}`, name: `X${i}`, stake: 1 })),
      ],
    })
    const s = parse(raw)
    expect(s.positions[0]).toEqual({ item_id: 'a', name: 'A', stake: 10 })
    expect(s.positions.map((p) => p.item_id)).not.toContain(DIVINE)
    expect(s.positions.map((p) => p.item_id)).not.toContain('b')
    expect(s.positions).toHaveLength(MAX_POSITIONS)
    expect([s.day, s.at]).toEqual([5, 7])
  })

  it('adds, changes and removes stakes, and keeps them in localStorage', () => {
    expect(portfolio.add({ item_id: 'a', name: 'A' })).toBe(true)
    expect(portfolio.add({ item_id: 'a', name: 'A' })).toBe(false)
    expect(portfolio.add({ item_id: DIVINE, name: 'Divine Orb' })).toBe(false)
    portfolio.setStake('a', 25)
    portfolio.setStake('a', Number.NaN) // ignored
    portfolio.setAt(3, 4.4)
    expect(parse(localStorage.getItem('eb-portfolio'))).toEqual({ positions: [{ item_id: 'a', name: 'A', stake: 25 }], day: 3, at: 4 })
    portfolio.remove('a')
    expect(parse(localStorage.getItem('eb-portfolio')).positions).toEqual([])
  })

  it('starts the clock again on another day, and never past the end', () => {
    const s = { positions: [], day: 3, at: 30 }
    expect(atFor(s, 3, 100)).toBe(30)
    expect(atFor(s, 3, 10)).toBe(9)
    expect(atFor(s, 5, 100)).toBe(0)
  })
})

describe('valuing it', () => {
  const hours = hoursFrom(iso(T0), iso(T0 + 12 * HOUR))

  it('steps hourly from the day end to the snapshot end', () => {
    expect(hours).toHaveLength(13)
    expect(hours[0]).toBe('2026-03-07T23:00:00.000Z')
    expect(hoursFrom('nope', iso(T0))).toEqual([])
  })

  it('buys at the day end and is worth the typical price after', () => {
    const v = valueStake(path(0.01, 0.02), 10, hours)
    expect(v.entry).toBeCloseTo(0.01)
    expect(v.worth[0]).toBeCloseTo(10)
    // The typical price is the 6-hour median: it has turned by the 4th hour after.
    expect(v.worth[3]).toBeCloseTo(15) // three of each: the middle of the two
    expect(v.worth[6]).toBeCloseTo(20)
  })

  it('carries the price through hours that did not trade', () => {
    const v = valueStake(path(0.01, null), 10, hours)
    expect(v.worth.every((w) => w != null && Math.abs(w - 10) < 1e-9)).toBe(true)
  })

  it('buys nothing when the item had not traded by the day end', () => {
    const v = valueStake(path(Number.NaN, 0.02), 10, hours)
    expect(v.entry).toBeNull()
    expect(v.worth.every((w) => w == null)).toBe(true)
  })

  it('values Chaos kept instead in Divines as the Divine rises', () => {
    const kept = keptAsChaos(path(100, 200, 'chaos'), 10, hours)
    expect(kept[0]).toBeCloseTo(10)
    expect(kept[12]).toBeCloseTo(5)
  })
})
