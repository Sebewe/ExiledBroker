import { inUnit, price } from './format'

/** Formats a Chaos amount: anything worth a Divine or more (judged by `ref`, so a pair
 *  of prices shares a unit) in Divines at the league's latest rate, the rest in Chaos. */
export type Money = (chaos: number | null | undefined, ref?: number | null) => string

export function makeMoney(divineChaos: number | null | undefined): Money {
  return (chaos, ref = chaos) =>
    divineChaos && Math.abs(ref ?? 0) >= divineChaos ? price(inUnit(chaos, 'divine', divineChaos), 'divine') : price(chaos, 'chaos')
}
