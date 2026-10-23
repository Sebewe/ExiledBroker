import { describe, expect, it } from 'vitest'
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
