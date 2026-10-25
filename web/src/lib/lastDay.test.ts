import { describe, expect, it } from 'vitest'
import type { DayHour } from '../api/client'
import { lastDay } from './lastDay'

const h = (hour: number, x: Partial<DayHour>): DayHour => ({
  hour: `2026-10-22T${String(hour).padStart(2, '0')}:00:00Z`,
  chaos_price: null,
  chaos_units: null,
  divine_price: null,
  divine_units: null,
  divine_rate: 200,
  ...x,
})

describe('lastDay', () => {
  it('is nothing without trades', () => {
    expect(lastDay([], 200)).toBeNull()
  })

  it('adds up both markets, values them in Chaos and finds the busiest hour', () => {
    const d = lastDay(
      [
        h(10, { chaos_price: 2, chaos_units: 100 }),
        h(20, { chaos_price: 2, chaos_units: 300, divine_price: 0.01, divine_units: 50 }),
      ],
      200,
    )!
    expect(d.hours).toBe(2)
    expect([d.chaosUnits, d.divineUnits, d.units]).toEqual([400, 50, 450])
    expect(d.valueChaos).toBeCloseTo(2 * 400 + 0.01 * 50 * 200)
    expect(d.busiest).toEqual({ hour: 20, units: 350 })
  })

  it('finds the highest price in Divines across markets, ignoring tiny fills', () => {
    const d = lastDay(
      [
        h(1, { chaos_price: 2, chaos_units: 100 }), // 0.01 div
        h(2, { chaos_price: 2.4, chaos_units: 100 }), // 0.012 div: the best real hour
        h(3, { chaos_price: 2.2, chaos_units: 100 }),
        h(4, { chaos_price: 9, chaos_units: 1 }), // one small fill: not counted
      ],
      200,
    )!
    expect(d.dearest?.hour).toBe(2)
    expect(d.dearest?.divine).toBeCloseTo(0.012)
    expect(d.dearest?.over).toBeCloseTo(0.012 / 0.011 - 1)
  })

  it('prices an hour with no Divine rate from its Divine market only', () => {
    const d = lastDay([h(5, { chaos_price: 2, chaos_units: 10, divine_price: 0.02, divine_units: 10, divine_rate: null })], 100)!
    expect(d.dearest?.divine).toBeCloseTo(0.02)
    expect(d.valueChaos).toBeCloseTo(20 + 0.02 * 10 * 100)
  })
})
