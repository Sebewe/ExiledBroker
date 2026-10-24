import { ApiError } from './client'

// The Farming page's response, as fixed in docs/farming.md ("The response contract").
// Written by hand until the endpoint lands (workstream G); then these become aliases of
// the generated `Schemas['…']` and `getFarming` an `api.GET('/api/farming/{league}')`.

export type FarmingPhase = 'pre_launch' | 'launch' | 'later'
export type OutlookWindowId = 'day1' | 'days2_4' | 'days5_10'

export type FarmingMechanic = {
  id: string
  name: string
  items: number
  priced_items: number
  /** Basket index: geometric mean of item price over its day-1 median. */
  index: number | null
  /** Median past-league index at this day_offset (null after day 14 or with no history). */
  usual: number | null
  usual_low: number | null
  usual_high: number | null
  /** Fractional changes (0.04 = +4%). */
  change_24h: number | null
  change_7d: number | null
  /** Median Chaos traded an hour across the basket, last 3 days. */
  chaos_volume_h: number | null
  /** Percentile among mechanics, 0–1: Easy to sell. */
  liquidity: number | null
  score: number | null
}

export type OutlookWindow = { growth: number | null; worst: number | null }

export type FarmingOutlook = {
  id: string
  name: string
  leagues: number
  windows: Partial<Record<OutlookWindowId, OutlookWindow | null>>
}

/** One market's recent trading for an item: `price` in that market's currency (Chaos, or
 *  Divines for the Divine market), `volume_h` in units of the item an hour, `sigma_h` the
 *  hourly log-price volatility and `hours_traded` the share of hours with trades. */
export type FarmingMarket = {
  price: number | null
  volume_h: number | null
  sigma_h: number | null
  hours_traded: number | null
}

export type FarmingItem = {
  item_id: string
  name: string
  mechanics: string[]
  chaos: FarmingMarket | null
  divine: FarmingMarket | null
}

export type FarmingHours = {
  /** 24 values by UTC hour: median deviation from the day's mean (log). */
  price: (number | null)[]
  /** 24 values by UTC hour: share of the day's volume. */
  volume: (number | null)[]
  /** Size of the best-vs-worst hour gap. */
  effect: number | null
  verdict: 'small' | 'worth_it' | null
}

export type Farming = {
  league: string
  latest_hour: string | null
  day_offset: number | null
  phase: FarmingPhase
  mechanics: FarmingMechanic[]
  outlook: FarmingOutlook[]
  items: FarmingItem[]
  hours: FarmingHours | null
  impact: { y: number; note: string | null } | null
}

/** GET /api/farming/{league}, or an ApiError carrying the API's `detail` (503: no data). */
export async function getFarming(league: string): Promise<Farming> {
  const base = globalThis.location?.origin ?? ''
  const response = await globalThis.fetch(`${base}/api/farming/${encodeURIComponent(league)}`)
  const body: unknown = await response.json().catch(() => undefined)
  if (!response.ok) {
    const detail = typeof body === 'object' && body && 'detail' in body ? String(body.detail) : response.statusText
    throw new ApiError(response.status, detail)
  }
  return body as Farming
}
