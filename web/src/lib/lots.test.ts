import { describe, expect, it } from 'vitest'
import { eachText, lotText, whole } from './lots'

// The same cases as tests/test_missed.py: the browser and the server must agree.
describe('whole', () => {
  it('finds the smallest whole-number lot within 1%, never paying more or asking less', () => {
    const cases: [number, [number, number], [number, number]][] = [
      [16.8, [3, 50], [5, 84]],
      [5.5, [2, 11], [2, 11]],
      [662.4, [1, 662], [1, 663]],
      [4.27, [4, 17], [7, 30]],
      [0.0783, [64, 5], [38, 3]],
      [0.000519, [1927, 1], [1926, 1]],
    ]
    for (const [target, buy, sell] of cases) {
      const b = whole(target, 'buy')
      const s = whole(target, 'sell')
      expect([b.items, b.units], `buy ${target}`).toEqual(buy)
      expect([s.items, s.units], `sell ${target}`).toEqual(sell)
      expect(b.units / b.items).toBeLessThanOrEqual(target)
      expect(s.units / s.items).toBeGreaterThanOrEqual(target)
    }
  })

  it('writes the order as it is placed', () => {
    expect(lotText({ items: 64, units: 5 }, 'chaos')).toBe('5c for 64')
    expect(lotText({ items: 1, units: 663 }, 'chaos')).toBe('663c each')
    expect(lotText({ items: 1926, units: 1 }, 'divine')).toBe('1 div for 1926')
    expect(eachText({ items: 64, units: 5 }, 'chaos')).toBe('0.0781c each')
    expect(eachText({ items: 1, units: 663 }, 'chaos')).toBe('')
  })
})
