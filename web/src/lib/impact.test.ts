import { describe, expect, it } from 'vitest'
import type { FarmingItem } from '../api/farming'
import { bestHours, compareMarkets, impactBand, localHour, localHours, marketImpact, profileFor } from './impact'

const item = (divine: FarmingItem['divine']): FarmingItem => ({
  item_id: 'currency:splinter-of-xoph',
  name: 'Splinter of Xoph',
  mechanics: ['breach'],
  chaos: { price: 1.4, volume_h: 3200, sigma_h: 0.031, hours_traded: 0.92 },
  divine,
})

describe('marketImpact', () => {
  it('grows with the square root of the stack against an hour of volume', () => {
    const m = { price: 1, volume_h: 100, sigma_h: 0.1, hours_traded: 1 }
    expect(marketImpact(m, 100, 1)).toBeCloseTo(1 - Math.exp(-0.1))
    expect(marketImpact(m, 400, 1)).toBeCloseTo(1 - Math.exp(-0.2))
    expect(marketImpact(m, 100, 0.5)).toBeCloseTo(1 - Math.exp(-0.05))
  })

  it('stays below the whole price for a big stack', () => {
    expect(marketImpact({ price: 1, volume_h: 1, sigma_h: 1, hours_traded: 1 }, 25, 1)).toBeLessThan(1)
  })

  it('is unknown without a market, volume, volatility or quantity', () => {
    expect(marketImpact(null, 10, 1)).toBeNull()
    expect(marketImpact({ price: 1, volume_h: 0, sigma_h: 0.1, hours_traded: 0 }, 10, 1)).toBeNull()
    expect(marketImpact({ price: 1, volume_h: 10, sigma_h: null, hours_traded: 1 }, 10, 1)).toBeNull()
    expect(marketImpact({ price: null, volume_h: 10, sigma_h: 0.1, hours_traded: 1 }, 10, 1)).toBeNull()
    expect(marketImpact({ price: 1, volume_h: 10, sigma_h: 0.1, hours_traded: 1 }, 0, 1)).toBeNull()
  })

  it('bands', () => {
    expect([0.005, 0.05, 0.3].map(impactBand)).toEqual(['low', 'medium', 'high'])
  })
})

describe('compareMarkets', () => {
  it('converts the Divine market at the latest rate and picks the one that fetches more', () => {
    // Divine market: 0.008 div = 1.6c a unit but very thin, so a big stack sinks it.
    const it_ = item({ price: 0.008, volume_h: 40, sigma_h: 0.05, hours_traded: 0.21 })
    const small = compareMarkets(it_, 10, 0.8, 200)
    expect(small.divine!.unitChaos).toBeCloseTo(1.6)
    expect(small.better).toBe('divine')
    const big = compareMarkets(it_, 5000, 0.8, 200)
    expect(big.better).toBe('chaos')
    expect(big.divine!.band).toBe('high')
    expect(big.divine!.hoursOfVolume).toBe(125)
    expect(big.gain).toBeCloseTo(Math.abs(big.divine!.proceeds - big.chaos!.proceeds))
  })

  it('is the Chaos market alone without a Divine market or rate', () => {
    expect(compareMarkets(item(null), 10, 0.8, 200)).toMatchObject({ divine: null, better: 'chaos', gain: null })
    const noRate = compareMarkets(item({ price: 0.008, volume_h: 40, sigma_h: 0.05, hours_traded: 0.2 }), 10, 0.8, null)
    expect(noRate).toMatchObject({ divine: null, better: 'chaos' })
  })
})

describe('localHours', () => {
  const price = Array.from({ length: 24 }, (_, h) => h / 100)
  const volume = Array(24).fill(1 / 24)

  it('keeps UTC order in UTC', () => {
    const bars = localHours(price, volume, 'UTC')
    expect(bars.map((b) => b.utc)).toEqual(Array.from({ length: 24 }, (_, h) => h))
    expect(bars[0]?.label).toBe('00:00')
  })

  it('starts from local midnight elsewhere, half-hour zones included', () => {
    const tokyo = localHours(price, volume, 'Asia/Tokyo') // UTC+9
    expect(tokyo[0]).toMatchObject({ utc: 15, label: '00:00' })
    const india = localHours(price, volume, 'Asia/Kolkata') // UTC+5:30
    expect(india[0]).toMatchObject({ utc: 19, label: '00:30' })
  })

  it('picks the best hours by price', () => {
    expect(bestHours(localHours(price, volume, 'UTC')).map((b) => b.utc)).toEqual([23, 22, 21])
    const peak = Array.from({ length: 24 }, (_, h) => (h === 23 ? 0.04 : h === 22 ? 0.035 : h === 21 ? 0.02 : 0))
    expect(bestHours(localHours(peak, null, 'UTC')).map((b) => b.utc)).toEqual([23, 22])
  })
})

describe('profileFor', () => {
  const effect = { gain: 0.02, gap: 0.04, best: 23, worst: 6, null95: 0.01, verdict: 'worth_it' as const }
  const pooled = Array(24).fill(0)
  const own = Array(24).fill(0.01)
  const hours = {
    phase: 'd2_7' as const,
    leagues: 5,
    days: 30,
    price: pooled,
    price_divine_market: pooled,
    divine: pooled,
    volume: null,
    effect,
    effect_divine_market: effect,
    divine_effect: effect,
    mechanics: {
      essence: { ...effect, gain: 0.09, price: own, items: 42, stability: 0.9, shown: true },
      breach: { ...effect, price: own, items: 20, stability: 0.2, shown: false },
    },
  }

  it("uses the item's mechanic's own profile where it holds, else the pooled one", () => {
    expect(profileFor(hours, ['legion', 'essence'])).toMatchObject({ mechanic: 'essence', price: own, effect: { gain: 0.09 } })
    expect(profileFor(hours, ['breach'])).toMatchObject({ mechanic: null, price: pooled, effect: { gain: 0.02 } })
    expect(profileFor(hours, [])).toMatchObject({ mechanic: null, price: pooled })
  })

  it('names a UTC hour in local time', () => {
    expect(localHour(23, 'Europe/Paris')).toMatch(/^0[01]:00$/) // CET or CEST
    expect(localHour(6, 'UTC')).toBe('06:00')
  })
})
