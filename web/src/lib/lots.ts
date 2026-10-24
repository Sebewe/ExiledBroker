// Orders as the exchange takes them: whole numbers on both sides (so many Chaos or
// Divines for so many items), filled in whole lots. The same rule as the server's
// `services/missed.whole`, which the backtest and the recap's flips use: the smallest lot
// within LOT_TOLERANCE of the target price, a bid rounded down and an ask up, so an
// order never pays more or asks less than the target.

export const LOT_MAX = 20 // items in a lot, for an item worth a currency unit or more
export const UNITS_MAX = 50 // currency units in a lot, for an item worth less than one
export const LOT_TOLERANCE = 0.01

export interface Lot {
  items: number
  units: number // whole Chaos or Divines for those items
}

export function whole(target: number, side: 'buy' | 'sell'): Lot {
  const round = side === 'buy' ? Math.floor : Math.ceil
  const close = (price: number) => Math.abs(price - target) <= LOT_TOLERANCE * target
  if (target >= 1) {
    for (let n = 1; n < LOT_MAX; n++) if (close(round(target * n) / n)) return { items: n, units: round(target * n) }
    return { items: LOT_MAX, units: round(target * LOT_MAX) }
  }
  // Under a unit an item: so many items for each whole number of units.
  const items = (m: number) => (side === 'buy' ? Math.ceil(m / target) : Math.floor(m / target))
  for (let m = 1; m < UNITS_MAX; m++) if (close(m / items(m))) return { items: items(m), units: m }
  return { items: items(UNITS_MAX), units: UNITS_MAX }
}

export type Currency = 'chaos' | 'divine'

const unit = (n: number, c: Currency) => (c === 'chaos' ? `${n}c` : `${n} div`)

/** "5c for 64", "663c each", "1 div for 1926". */
export function lotText(lot: Lot, c: Currency) {
  return `${unit(lot.units, c)} ${lot.items === 1 ? 'each' : `for ${lot.items}`}`
}

/** The price each, when the lot is more than one item: "0.0781c each". */
export function eachText(lot: Lot, c: Currency) {
  if (lot.items === 1) return ''
  const each = lot.units / lot.items
  const shown = each >= 10 ? each.toFixed(1) : each >= 1 ? each.toFixed(2) : each.toPrecision(3)
  return c === 'chaos' ? `${shown}c each` : `${shown} div each`
}
