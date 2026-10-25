// ============================================================================================
// DRAFT, hand-written: the Price check responses as docs/price-check.md's "The response
// contract" describes them, until workstream C builds `/api/price-check/...`. Once it has,
// run `npm run gen:api`, export the generated types from `client.ts` under these names,
// switch the two fetchers below to `api.GET(...)`, and delete this file.
// ============================================================================================

import { ApiError } from './client'

// The best-hour and stack inputs (`farming_report`, read through services/sell_helper.py).
// The Farming page's response carried them; until C serves them, they're written out here.

/** How much one hour-of-day profile matters (finding 6). */
export type HourEffect = {
  best: number | null
  gain: number | null
  gap: number | null
  null95: number | null
  verdict: 'small' | 'worth_it'
  worst: number | null
}

/** A basket's own profile, where it holds across leagues. */
export type MechanicHours = HourEffect & { items: number; price: (number | null)[]; stability: number | null }

/** 24 values by UTC hour; null for an hour with no data. */
export type HourProfile = (number | null)[]

export type FarmingHours = {
  days: number
  divine: HourProfile
  divine_effect: HourEffect
  effect: HourEffect
  effect_divine_market: HourEffect
  leagues: number
  mechanics: Record<string, MechanicHours>
  phase: 'd0_2' | 'd2_7' | 'd7_14' | 'later'
  price: HourProfile
  price_divine_market: HourProfile
  volume: HourProfile | null
}

export type FarmingImpact = { bands: number[]; note: string | null; y: number | null }

/** "sell": past leagues say it falls from here; "hold": it rises; "none": no clear signal
 *  (or no verdict at all: not enough history, or the model doesn't beat "no change"). */
export type Verdict = 'sell' | 'hold' | 'none'

/** One row of the search list. Prices in Chaos (the browser converts with `divine_chaos`). */
export type PriceCheckListItem = {
  item_id: string
  name: string
  /** The item's group for the search box ("Essence"), or null. */
  label: string | null
  chaos: number | null
  /** Units traded an hour in its Chaos market, recent. */
  volume_h: number | null
  verdict_24h: Verdict
  /** DRAFT ADDITION (not in the contract yet, asked of C): the price's move over the last
   *  24 hours, judged in Divines like the verdict, as a fraction (−0.08 = −8%). The movers
   *  list shows it. */
  change_24h?: number | null
}

/** `GET /api/price-check/{league}`: the search list and the movers, one per data version. */
export type PriceCheckIndex = {
  league: string
  latest_hour: string | null
  /** Days since launch (0-based, fractional), or null before the first trades. */
  day_offset: number | null
  items: PriceCheckListItem[]
  /** Item ids, strongest calls first, at most 20. */
  movers: string[]
}

/** One horizon's outlook: what past leagues did from this point, as fractions (−0.03 = −3%). */
export type Horizon = {
  verdict: Verdict
  typical: number | null
  low: number | null
  high: number | null
  /** Past leagues behind it. */
  leagues: number
  /** The item's own past leagues, or its group's when it has too few. */
  basis: 'item' | 'group'
}

export type Outlook = {
  h24: Horizon
  d3: Horizon
  /** The verdict judges in Divines (decided 2026-10-25). */
  unit: 'divine' | 'chaos'
}

/** One market's recent trading, the stack seller's input (same fields as the Farming page's). */
export type StackMarket = {
  price: number | null
  volume_h: number | null
  sigma_h: number | null
  hours_traded: number | null
}

/** [hour (ISO, UTC), price in Chaos, price in Divines]; null where untraded. */
export type SeriesPoint = [string, number | null, number | null]

/** `GET /api/price-check/{league}/{item_id}`: one item. */
export type PriceCheckItem = {
  item_id: string
  name: string
  /** Hourly, over the launch fortnight and the latest 14 days. */
  series: SeriesPoint[]
  /** Null for an item with no history to judge by. */
  outlook: Outlook | null
  stack: { chaos: StackMarket | null; divine: StackMarket | null }
  /** Past leagues' launch windows against the settled price (×3.4 = three times as much). */
  launch_premium: { day1: number | null; days2_4: number | null; days5_10: number | null } | null
  /** The best-hour sentence's inputs, from `farming_report` (the Farming page's shape for now). */
  hours: FarmingHours | null
}

async function getJson<T>(path: string): Promise<T> {
  const response = await globalThis.fetch(new Request(new URL(path, globalThis.location?.origin ?? 'http://localhost')))
  if (!response.ok) {
    let detail = response.statusText
    try {
      const body = (await response.json()) as { detail?: unknown }
      if (body && body.detail != null) detail = String(body.detail)
    } catch {
      // not JSON: keep the status text
    }
    throw new ApiError(response.status, detail)
  }
  return (await response.json()) as T
}

export const fetchPriceCheck = (league: string) => getJson<PriceCheckIndex>(`/api/price-check/${encodeURIComponent(league)}`)

export const fetchPriceCheckItem = (league: string, itemId: string) =>
  getJson<PriceCheckItem>(`/api/price-check/${encodeURIComponent(league)}/${encodeURIComponent(itemId)}`)
