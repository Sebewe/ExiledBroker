import type { FarmingHours, FarmingItem, FarmingMarket, HourEffect, HourProfile } from '../api/farming'

// The Farming page's sell helper, computed here so the typed quantity never reaches the
// server (docs/farming.md, "The response contract"). The square-root rule
// impact ≈ y · sigma_h · sqrt(Q / volume_h) gives the expected log-price drop from selling
// Q units at once into a market trading volume_h units an hour.

export type ImpactBand = 'low' | 'medium' | 'high'
export type MarketId = 'chaos' | 'divine'

/** Fraction of the price lost by selling `qty` at once (0.07 = about −7%), or null when the
 *  market has no price, volume or volatility to judge by. */
export function marketImpact(m: FarmingMarket | null | undefined, qty: number, y: number): number | null {
  if (!m || m.price == null || !m.volume_h || m.sigma_h == null || !(qty > 0)) return null
  return 1 - Math.exp(-y * m.sigma_h * Math.sqrt(qty / m.volume_h))
}

export function impactBand(impact: number): ImpactBand {
  return impact < 0.02 ? 'low' : impact < 0.1 ? 'medium' : 'high'
}

export type MarketSale = {
  market: MarketId
  /** One unit's price now, in Chaos (the Divine market's at the latest Divine rate). */
  unitChaos: number
  impact: number
  band: ImpactBand
  /** What the stack fetches, in Chaos, after the drop. */
  proceeds: number
  /** Hours of this market's usual volume the stack amounts to. */
  hoursOfVolume: number
  hoursTraded: number | null
}

function sale(market: MarketId, m: FarmingMarket | null, qty: number, y: number, rate: number): MarketSale | null {
  const impact = marketImpact(m, qty, y)
  if (impact == null || !m || m.price == null || !m.volume_h) return null
  const unitChaos = m.price * rate
  return {
    market,
    unitChaos,
    impact,
    band: impactBand(impact),
    proceeds: qty * unitChaos * (1 - impact),
    hoursOfVolume: qty / m.volume_h,
    hoursTraded: m.hours_traded,
  }
}

/** Selling `qty` of an item in each market, and which fetches more. The Divine market
 *  needs the latest Divine rate to compare; without it, it's left out. */
export function compareMarkets(item: FarmingItem, qty: number, y: number, divineChaos: number | null | undefined) {
  const chaos = sale('chaos', item.chaos, qty, y, 1)
  const divine = divineChaos ? sale('divine', item.divine, qty, y, divineChaos) : null
  const better: MarketId | null = chaos && divine ? (divine.proceeds > chaos.proceeds ? 'divine' : 'chaos') : (chaos ?? divine)?.market ?? null
  const gain = chaos && divine ? Math.abs(divine.proceeds - chaos.proceeds) : null
  return { chaos, divine, better, gain }
}

export type HourBar = { utc: number; label: string; price: number | null; volume: number | null }

/** A UTC hour as the viewer's (or `timeZone`'s) clock time: 23 → "01:00" in Paris. */
export function localHour(utc: number, timeZone?: string): string {
  const fmt = new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit', hourCycle: 'h23', timeZone })
  const day = new Date()
  return fmt.format(new Date(Date.UTC(day.getUTCFullYear(), day.getUTCMonth(), day.getUTCDate(), utc)))
}

/** The 24 UTC hours of a profile, relabelled and reordered in the viewer's time zone
 *  (or `timeZone`), starting from local midnight. */
export function localHours(price: HourProfile, volume: HourProfile | null, timeZone?: string): HourBar[] {
  const bars = Array.from({ length: 24 }, (_, utc) => ({ utc, label: localHour(utc, timeZone), price: price[utc] ?? null, volume: volume?.[utc] ?? null }))
  return bars.sort((a, b) => a.label.localeCompare(b.label))
}

/** The profile that applies to an item: its first mechanic's own, where that holds across
 *  leagues, else the pooled one. */
export function profileFor(hours: FarmingHours, mechanics: string[]): { mechanic: string | null; price: HourProfile; effect: HourEffect } {
  const own = mechanics.find((m) => hours.mechanics[m] && hours.mechanics[m].shown !== false)
  if (own) {
    const { price, ...effect } = hours.mechanics[own]!
    return { mechanic: own, price, effect }
  }
  return { mechanic: null, price: hours.price, effect: hours.effect }
}

/** The hours that sell highest, best first: up to `n`, and only those within a quarter of
 *  the best hour's lift over the average, so a flat profile names just its peak. */
export function bestHours(bars: HourBar[], n = 3): HourBar[] {
  const ranked = bars.filter((b) => b.price != null).sort((a, b) => b.price! - a.price!)
  const top = ranked[0]?.price ?? 0
  return ranked.filter((b, i) => i === 0 || (top > 0 && b.price! >= top * 0.75)).slice(0, n)
}
