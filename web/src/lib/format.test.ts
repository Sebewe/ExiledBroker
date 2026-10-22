import { describe, expect, it } from 'vitest'
import { line } from './chartOptions'
import { duration, pct, price, signedPct, utcHour } from './format'

describe('format', () => {
  it('prices with sensible precision', () => {
    expect(price(12345.6)).toBe('12,346c')
    expect(price(123.45)).toBe('123.5c')
    expect(price(1.234)).toBe('1.23c')
    expect(price(0.012345)).toBe('0.0123c')
    expect(price(2.5, 'divine')).toBe('2.50div')
    expect(price(null)).toBe('–')
  })
  it('percentages', () => {
    expect(pct(0.256)).toBe('25.6%')
    expect(signedPct(0.032)).toBe('+3.2%')
    expect(signedPct(-0.01)).toBe('−1.0%')
    expect(signedPct(undefined)).toBe('–')
  })
  it('times are UTC', () => {
    expect(utcHour('2026-10-22T08:00:00Z')).toBe('Oct 22, 08:00 UTC')
    expect(duration(2 * 3_600_000 + 5 * 60_000)).toBe('2h 05m')
  })
})

describe('line', () => {
  it('breaks at missing hours and marks lone points', () => {
    const s = line('x', [
      ['2026-07-25T00:00:00Z', 1],
      ['2026-07-25T01:00:00Z', 2],
      ['2026-10-01T00:00:00Z', 3], // weeks later, alone
    ])
    const values = s.data.map((d) => (Array.isArray(d) ? d[1] : d.value[1]))
    expect(values).toEqual([1, 2, null, 3])
    expect(Array.isArray(s.data[3])).toBe(false) // the lone point gets a dot
  })
})
