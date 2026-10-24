import { describe, expect, it } from 'vitest'
import type { FarmingItem } from '../api/client'
import { bandsOf, busiestHours, hoursOfTrading, impactBand, localHour, profileFor, stackInMarkets, tradingTime } from './impact'

const item = (divine: FarmingItem['divine']): FarmingItem => ({
  item_id: 'currency:splinter-of-xoph',
  name: 'Splinter of Xoph',
  mechanics: ['breach'],
  chaos: { price: 1.4, volume_h: 3200, sigma_h: 0.031, hours_traded: 0.92 },
  divine,
})

describe('hoursOfTrading', () => {
  it('is the stack over the units the market trades in an hour', () => {
    const m = { price: 1, volume_h: 200, sigma_h: 0.1, hours_traded: 1 }
    expect(hoursOfTrading(m, 50)).toBe(0.25)
    expect(hoursOfTrading(m, 600)).toBe(3)
  })

  it('is unknown without a market, volume or quantity', () => {
    expect(hoursOfTrading(null, 10)).toBeNull()
    expect(hoursOfTrading({ price: 1, volume_h: 0, sigma_h: 0.1, hours_traded: 0 }, 10)).toBeNull()
    expect(hoursOfTrading({ price: 1, volume_h: null, sigma_h: 0.1, hours_traded: 0 }, 10)).toBeNull()
    expect(hoursOfTrading({ price: 1, volume_h: 10, sigma_h: 0.1, hours_traded: 1 }, 0)).toBeNull()
  })

  it("doesn't need a price or a swing: neither is an input", () => {
    expect(hoursOfTrading({ price: null, volume_h: 10, sigma_h: null, hours_traded: null }, 5)).toBe(0.5)
  })
})

describe('impactBand', () => {
  it('bands at a quarter of an hour and an hour by default, edges included above', () => {
    expect([0.1, 0.25, 0.9, 1, 5].map((h) => impactBand(h))).toEqual(['low', 'medium', 'medium', 'high', 'high'])
  })

  it("follows the response's bands", () => {
    expect([0.3, 1, 3].map((h) => impactBand(h, [0.5, 2]))).toEqual(['low', 'medium', 'high'])
  })

  it("takes the response's two edges, else the contract's", () => {
    expect(bandsOf({ y: null, bands: [0.5, 2], note: null })).toEqual([0.5, 2])
    expect(bandsOf(null)).toEqual([0.25, 1])
    expect(bandsOf({ y: null, bands: [0.5], note: null })).toEqual([0.25, 1])
    expect(bandsOf({ y: null, bands: [2, 0.5], note: null })).toEqual([0.25, 1])
  })
})

describe('stackInMarkets', () => {
  it('gives each market its own hours, the Divine market priced at the latest rate', () => {
    // Divine market: 0.008 div = 1.6c a unit, but it trades 40 an hour against 3200.
    const { chaos, divine } = stackInMarkets(item({ price: 0.008, volume_h: 40, sigma_h: 0.05, hours_traded: 0.21 }), 100, 200)
    expect(chaos).toMatchObject({ market: 'chaos', hours: 100 / 3200, band: 'low', unitChaos: 1.4, valueChaos: 140, sigmaH: 0.031 })
    expect(divine).toMatchObject({ market: 'divine', hours: 2.5, band: 'high', volumeH: 40, hoursTraded: 0.21 })
    expect(divine!.unitChaos).toBeCloseTo(1.6)
    expect(divine!.valueChaos).toBeCloseTo(160)
  })

  it('has no Divine market without its trades, and no Chaos value for it without a rate', () => {
    expect(stackInMarkets(item(null), 10, 200).divine).toBeNull()
    const noRate = stackInMarkets(item({ price: 0.008, volume_h: 40, sigma_h: 0.05, hours_traded: 0.2 }), 10, null).divine
    expect(noRate).toMatchObject({ hours: 0.25, band: 'medium', unit: 0.008, unitChaos: null, valueChaos: null, noRate: true })
  })

  it('tells a missing price from a missing Divine rate', () => {
    const noPrice = { ...item({ price: null, volume_h: 40, sigma_h: 0.05, hours_traded: 0.2 }), chaos: { price: null, volume_h: 3200, sigma_h: 0.03, hours_traded: 0.9 } }
    const { chaos, divine } = stackInMarkets(noPrice, 3200, 200)
    expect(chaos).toMatchObject({ hours: 1, band: 'high', unit: null, unitChaos: null, valueChaos: null, noRate: false })
    expect(divine).toMatchObject({ unit: null, unitChaos: null, noRate: false })
  })
})

describe('tradingTime', () => {
  it('reads as minutes, hours or days', () => {
    expect([0.01, 1 / 60, 0.03, 0.5, 0.995, 1, 1.04, 1.25, 12.4, 125].map(tradingTime)).toEqual([
      'under a minute',
      'about 1 minute',
      'about 2 minutes',
      'about 30 minutes',
      'about 59 minutes', // below the top band's edge: never "an hour"
      'an hour',
      'an hour',
      '1.3 hours',
      '12 hours',
      '5 days',
    ])
  })
})

describe('busiestHours', () => {
  it('finds the busiest and quietest four hours, across midnight', () => {
    // Busy 22:00–02:00 UTC, quiet 10:00–14:00.
    const evening = Array.from({ length: 24 }, (_, h) => (h >= 22 || h < 2 ? 2 : h >= 10 && h < 14 ? 0.5 : 1))
    expect(busiestHours(evening)).toMatchObject({ start: 22, end: 2, quietStart: 10, quietEnd: 14, ratio: 4 })
  })

  it('is endlessly busier when nothing trades in the quiet hours', () => {
    const gap = Array.from({ length: 24 }, (_, h) => (h >= 2 && h < 6 ? 0 : 1 / 20))
    expect(busiestHours(gap)).toMatchObject({ quietStart: 2, quietEnd: 6, ratio: Infinity })
  })

  it('needs a full day of shares, with some trades', () => {
    expect(busiestHours(Array(24).fill(0))).toBeNull()
    expect(busiestHours(null)).toBeNull()
    expect(busiestHours([...Array(23).fill(1 / 24), null])).toBeNull()
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
      essence: { ...effect, gain: 0.09, price: own, items: 42, stability: 0.9 },
    },
  }

  it("uses the item's mechanic's own profile where it holds, else the pooled one", () => {
    // The response leaves out the baskets whose own profile doesn't hold (here Breach).
    expect(profileFor(hours, ['legion', 'essence'])).toMatchObject({ mechanic: 'essence', price: own, effect: { gain: 0.09 } })
    expect(profileFor(hours, ['breach'])).toMatchObject({ mechanic: null, price: pooled, effect: { gain: 0.02 } })
    expect(profileFor(hours, [])).toMatchObject({ mechanic: null, price: pooled })
  })

  it('names a UTC hour in local time', () => {
    expect(localHour(23, 'Europe/Paris')).toMatch(/^0[01]:00$/) // CET or CEST
    expect(localHour(6, 'UTC')).toBe('06:00')
    expect(localHour(19, 'Asia/Kolkata')).toBe('00:30')
  })
})
