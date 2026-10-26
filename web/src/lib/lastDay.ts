import type { DayHour } from '../api/client'

// The "best time to sell" box, from the item's last 24 hours of trading (the user: this
// league's last day, not past leagues). GGG's volumes are unsigned (finding 7): every unit
// traded was both sold and bought, so there's one number for both.

/** An hour counts for the highest price only if it traded at least this share of the
 *  median hour's units: a single small fill shouldn't be "the best hour". */
export const MIN_SHARE = 0.25

export type LastDay = {
  /** Hours that traded in the last 24. */
  hours: number
  /** Units traded in each market and in all. */
  chaosUnits: number
  divineUnits: number
  units: number
  /** What those units were worth, in Chaos (the Divine market's at each hour's rate,
   *  or `divineChaos` where the hour has none); null when nothing could be valued. */
  valueChaos: number | null
  /** The hour (UTC, 0–23) with the most units traded, and how many. */
  busiest: { hour: number; units: number } | null
  /** The hour with the highest price per unit, in `unit` (Divines: both markets, by
   *  units; Chaos: Divine Orb's own price), and how far it sits over the day's median
   *  hourly price (0.05 = 5%). */
  dearest: { hour: number; price: number; over: number | null } | null
  unit: 'divine' | 'chaos'
}

const median = (xs: number[]) => {
  if (!xs.length) return null
  const s = [...xs].sort((a, b) => a - b)
  const m = s.length >> 1
  return s.length % 2 ? s[m]! : (s[m - 1]! + s[m]!) / 2
}

/** One hour's price in Divines: the two markets weighted by units traded. */
function divinePrice(h: DayHour): number | null {
  let units = 0
  let sum = 0
  if (h.chaos_price != null && h.chaos_units && h.divine_rate) {
    units += h.chaos_units
    sum += (h.chaos_price / h.divine_rate) * h.chaos_units
  }
  if (h.divine_price != null && h.divine_units) {
    units += h.divine_units
    sum += h.divine_price * h.divine_units
  }
  return units ? sum / units : null
}

/** `unit` "chaos" is Divine Orb's view: its hours have no Divine rate, so its price is
 *  its Chaos price. */
export function lastDay(rows: DayHour[], divineChaos: number | null | undefined, unit: 'divine' | 'chaos' = 'divine'): LastDay | null {
  if (!rows.length) return null
  let chaosUnits = 0
  let divineUnits = 0
  let value = 0
  let valued = false
  for (const h of rows) {
    chaosUnits += h.chaos_units ?? 0
    divineUnits += h.divine_units ?? 0
    if (h.chaos_price != null && h.chaos_units) {
      value += h.chaos_price * h.chaos_units
      valued = true
    }
    const rate = h.divine_rate ?? divineChaos
    if (h.divine_price != null && h.divine_units && rate) {
      value += h.divine_price * h.divine_units * rate
      valued = true
    }
  }
  const units = (h: DayHour) => (h.chaos_units ?? 0) + (h.divine_units ?? 0)
  const hourOf = (h: DayHour) => new Date(h.hour).getUTCHours()

  const top = rows.reduce((a, b) => (units(b) > units(a) ? b : a))
  const typicalUnits = median(rows.map(units)) ?? 0
  const priced = rows
    .map((h) => ({ h, p: unit === 'chaos' ? h.chaos_price : divinePrice(h) }))
    .filter((x): x is { h: DayHour; p: number } => x.p != null && units(x.h) >= MIN_SHARE * typicalUnits)
  const best = priced.length ? priced.reduce((a, b) => (b.p > a.p ? b : a)) : null
  const mid = median(priced.map((x) => x.p))

  return {
    hours: rows.length,
    chaosUnits,
    divineUnits,
    units: chaosUnits + divineUnits,
    valueChaos: valued ? value : null,
    busiest: units(top) > 0 ? { hour: hourOf(top), units: units(top) } : null,
    dearest: best ? { hour: hourOf(best.h), price: best.p, over: mid ? best.p / mid - 1 : null } : null,
    unit,
  }
}
