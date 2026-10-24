import type { FarmingHours, FarmingItem, FarmingMarket } from '../api/farming'

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

/** The 24 UTC hours of a profile, relabelled and reordered in the viewer's time zone
 *  (or `timeZone`), starting from local midnight. */
export function localHours(hours: Pick<FarmingHours, 'price' | 'volume'>, timeZone?: string): HourBar[] {
  const fmt = new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit', hourCycle: 'h23', timeZone })
  const day = new Date()
  const bars = Array.from({ length: 24 }, (_, utc) => {
    const label = fmt.format(new Date(Date.UTC(day.getUTCFullYear(), day.getUTCMonth(), day.getUTCDate(), utc)))
    return { utc, label, price: hours.price[utc] ?? null, volume: hours.volume[utc] ?? null }
  })
  return bars.sort((a, b) => a.label.localeCompare(b.label))
}

/** The `n` hours that sold highest, best first. */
export function bestHours(bars: HourBar[], n = 3): HourBar[] {
  return bars
    .filter((b) => b.price != null)
    .sort((a, b) => b.price! - a.price!)
    .slice(0, n)
}
