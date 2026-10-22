export type Unit = 'chaos' | 'divine'
export const UNIT_SUFFIX: Record<Unit, string> = { chaos: 'c', divine: 'div' }

/** A Chaos amount in the chosen unit, converted with the latest Divine price (in the
 *  browser: the server sends Chaos only, plus that one rate). */
export function inUnit(chaos: number | null | undefined, unit: Unit, divineChaos: number | null | undefined) {
  if (chaos === null || chaos === undefined) return null
  if (unit === 'chaos') return chaos
  return divineChaos ? chaos / divineChaos : null
}

/** A price with sensible precision: 12,345 / 123.4 / 1.23 / 0.0123. */
export function price(value: number | null | undefined, unit: Unit = 'chaos'): string {
  if (value === null || value === undefined) return '–'
  const abs = Math.abs(value)
  const text =
    abs >= 1000
      ? value.toLocaleString('en-US', { maximumFractionDigits: 0 })
      : abs >= 10
        ? value.toFixed(1)
        : abs >= 1
          ? value.toFixed(2)
          : value.toPrecision(3)
  return `${text}${UNIT_SUFFIX[unit]}`
}

export function pct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined) return '–'
  return `${(value * 100).toFixed(digits)}%`
}

/** Signed percentage, for edges and changes: +3.2% / −1.0%. */
export function signedPct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined) return '–'
  const s = (value * 100).toFixed(digits)
  return value > 0 ? `+${s}%` : value < 0 ? `−${s.slice(1)}%` : `${s}%`
}

export function count(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined) return '–'
  return value.toLocaleString('en-US', { maximumFractionDigits: digits })
}

export function score(value: number | null | undefined): string {
  return value === null || value === undefined ? '–' : value.toFixed(2)
}

const UTC_HOUR = new Intl.DateTimeFormat('en-US', {
  month: 'short',
  day: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
  timeZone: 'UTC',
})

/** "Oct 22, 08:00 UTC" */
export function utcHour(iso: string | null | undefined): string {
  return iso ? `${UTC_HOUR.format(new Date(iso))} UTC` : '–'
}

/** "2h 05m" */
export function duration(ms: number): string {
  const minutes = Math.max(0, Math.round(ms / 60_000))
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  return h ? `${h}h ${String(m).padStart(2, '0')}m` : `${m}m`
}

/** A value's tone: profit is green, loss is red. */
export function tone(value: number | null | undefined): string {
  if (value === null || value === undefined || value === 0) return ''
  return value > 0 ? 'text-positive' : 'text-negative'
}
