import type { FarmingHours, FarmingImpact, FarmingItem, FarmingMarket, HourEffect, HourProfile } from '../api/client'

// The Farming page's sell helper, computed here so the typed quantity never reaches the
// server (docs/farming.md, "The response contract"). Finding 7: hourly prices swing more
// than a stack moves them, so no price drop can be calibrated. A stack is shown instead as
// hours of the market's trading, Q / volume_h, banded by `impact.bands`.

export type ImpactBand = 'low' | 'medium' | 'high'
export type MarketId = 'chaos' | 'divine'

/** Two band edges, in hours of trading: low below the first, high from the second. */
export type Bands = readonly [number, number]

/** The contract's bands, for a response that lacks them. */
export const DEFAULT_BANDS: Bands = [0.25, 1]

/** The response's bands (a list in the API's schema), or the contract's when it doesn't
 *  carry two increasing edges. */
export function bandsOf(impact: FarmingImpact | null | undefined): Bands {
  const [low, high] = impact?.bands ?? []
  return low != null && high != null && low > 0 && high > low ? [low, high] : DEFAULT_BANDS
}

/** How many hours of this market's typical trading `qty` units amount to, or null when the
 *  market has no volume to judge by. */
export function hoursOfTrading(m: FarmingMarket | null | undefined, qty: number): number | null {
  if (!m || !m.volume_h || !(m.volume_h > 0) || !(qty > 0)) return null
  return qty / m.volume_h
}

/** low: sells into the market as it is; medium: a large part of the hour's trading;
 *  high: as much as the market trades in an hour, or more (the contract's
 *  low < bands[0] <= medium < bands[1] <= high). */
export function impactBand(hours: number, bands: Bands = DEFAULT_BANDS): ImpactBand {
  return hours < bands[0] ? 'low' : hours < bands[1] ? 'medium' : 'high'
}

export type MarketStack = {
  market: MarketId
  /** The stack in hours of this market's typical trading. */
  hours: number
  band: ImpactBand
  /** Units traded in a typical hour. */
  volumeH: number
  /** One unit's price now, in Chaos (the Divine market's at the latest Divine rate); null
   *  without a recent price, or for the Divine market before there's a rate. */
  unitChaos: number | null
  /** The Divine market before there's a Divine rate: its prices can only be given in
   *  Divines. Never set for the Chaos market, nor by a missing price alone. */
  noRate: boolean
  /** One unit's price in the market's own currency (Chaos, or Divines). */
  unit: number | null
  /** The stack's value at that price, in Chaos (null as `unitChaos`). */
  valueChaos: number | null
  /** Typical hourly swing (informative only: not an input to the hours). */
  sigmaH: number | null
  hoursTraded: number | null
}

function stack(market: MarketId, m: FarmingMarket | null, qty: number, bands: Bands, rate: number | null): MarketStack | null {
  const hours = hoursOfTrading(m, qty)
  if (hours == null || !m) return null
  const unitChaos = m.price == null || rate == null ? null : m.price * rate
  return {
    market,
    hours,
    band: impactBand(hours, bands),
    volumeH: m.volume_h!,
    unitChaos,
    noRate: rate == null,
    unit: m.price,
    valueChaos: unitChaos == null ? null : qty * unitChaos,
    sigmaH: m.sigma_h,
    hoursTraded: m.hours_traded,
  }
}

/** A stack of `qty` in each market: the Chaos market first (it carries most of an item's
 *  trading), the Divine market as its own hours of trading. `divineChaos` only converts
 *  the Divine market's price; its hours need no rate. */
export function stackInMarkets(item: FarmingItem, qty: number, divineChaos: number | null | undefined, bands: Bands = DEFAULT_BANDS) {
  const chaos = stack('chaos', item.chaos, qty, bands, 1)
  const divine = stack('divine', item.divine, qty, bands, divineChaos || null)
  return { chaos, divine }
}

/** A stack's hours of trading in words: "about 2 minutes", "1.5 hours", "3 days". Under an
 *  hour always reads in minutes (at most 59), so it never says "an hour" for a stack that
 *  is still below the top band's edge. */
export function tradingTime(hours: number): string {
  const minutes = hours * 60
  if (minutes < 1) return 'under a minute'
  if (hours < 1) {
    const m = Math.min(59, Math.round(minutes))
    return `about ${m} minute${m === 1 ? '' : 's'}`
  }
  if (hours < 9.95) return hours.toFixed(1) === '1.0' ? 'an hour' : `${hours.toFixed(1)} hours`
  if (hours < 47.5) return `${Math.round(hours)} hours`
  return `${Math.round(hours / 24)} days`
}

/** A UTC hour as the viewer's (or `timeZone`'s) clock time: 23 → "01:00" in Paris. */
export function localHour(utc: number, timeZone?: string): string {
  const fmt = new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit', hourCycle: 'h23', timeZone })
  const day = new Date()
  return fmt.format(new Date(Date.UTC(day.getUTCFullYear(), day.getUTCMonth(), day.getUTCDate(), utc)))
}

/** The profile that applies to an item: its first mechanic's own, where that holds across
 *  leagues, else the pooled one. */
export function profileFor(hours: FarmingHours, mechanics: string[]): { mechanic: string | null; price: HourProfile; effect: HourEffect } {
  // The response carries only the baskets whose own profile holds across leagues.
  for (const mechanic of mechanics) {
    const own = hours.mechanics[mechanic]
    if (own) {
      const { price, ...effect } = own
      return { mechanic, price, effect }
    }
  }
  return { mechanic: null, price: hours.price, effect: hours.effect }
}

/** The busiest and quietest `span` consecutive UTC hours of a day's volume shares (wrapping
 *  past midnight), and how many times busier the one is than the other: Infinity when
 *  nothing trades in the quiet hours. Null without a full day of shares, or with no trades
 *  at all. */
export function busiestHours(volume: HourProfile | null | undefined, span = 4) {
  if (!volume || volume.length !== 24 || volume.some((v) => v == null)) return null
  const sums = Array.from({ length: 24 }, (_, start) => Array.from({ length: span }, (_, i) => volume[(start + i) % 24]!).reduce((a, b) => a + b, 0))
  const busiest = sums.indexOf(Math.max(...sums))
  const quietest = sums.indexOf(Math.min(...sums))
  const share = sums[busiest]!
  if (!(share > 0)) return null
  const ratio = sums[quietest]! > 0 ? share / sums[quietest]! : Infinity
  return { start: busiest, end: (busiest + span) % 24, share, quietStart: quietest, quietEnd: (quietest + span) % 24, ratio }
}
