import { describe, expect, it } from 'vitest'
import { duration, pct, pctTone, price, signedPct, utcHour } from './format'

describe('format', () => {
  it('prices with sensible precision', () => {
    expect(price(12345.6)).toBe('12,346c')
    expect(price(123.45)).toBe('123.5c')
    expect(price(1.234)).toBe('1.23c')
    expect(price(0.012345)).toBe('0.0123c')
    expect(price(2.5, 'divine')).toBe('2.50div')
    expect(price(1.78e-15, 'divine')).toBe('0.00div')
    expect(price(null)).toBe('–')
    expect(price(999.96, 'divine')).toBe('1,000div') // rounds up into the next tier
    expect(price(9.996)).toBe('10.0c')
    expect(price(0.99996)).toBe('1.00c')
  })
  it('percentages', () => {
    expect(pct(0.256)).toBe('25.6%')
    expect(signedPct(0.032)).toBe('+3.2%')
    expect(signedPct(-0.01)).toBe('−1.0%')
    expect(signedPct(undefined)).toBe('–')
    expect(signedPct(-0.0004)).toBe('0.0%') // rounds to nothing: no sign
    expect(signedPct(-0.004, 0)).toBe('0%')
    expect(signedPct(-0.005, 1)).toBe('−0.5%')
    expect(pctTone(-0.0004)).toBe('') // prints 0.0%: no loss colour
    expect(pctTone(-0.005)).toBe('text-negative')
  })
  it('times are UTC', () => {
    expect(utcHour('2026-10-22T08:00:00Z')).toBe('Oct 22, 08:00 UTC')
    expect(duration(2 * 3_600_000 + 5 * 60_000)).toBe('2h 05m')
    expect(duration(47 * 3_600_000 + 59 * 60_000)).toBe('47h 59m')
    expect(duration(5606 * 3_600_000 + 13 * 60_000)).toBe('233d 14h')
  })
})
