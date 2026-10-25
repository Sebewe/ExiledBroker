import type { EChartsCoreOption } from 'echarts/core'
import type { Horizon, Outlook, SeriesPoint, Verdict } from '../api/client'
import { alpha, axisStyle, baseOptions, HOUR, line, type ChartTokens } from './chartOptions'
import { price, signedPct } from './format'

// The Price check page's pure parts (docs/price-check.md): the chart's ranges, the outlook
// band past the last hour, the chart's option, and the verdict in words.

export type Range = '3d' | '14d' | 'launch'
export const RANGES: Record<Range, string> = { '3d': '3 days', '14d': '14 days', launch: 'Launch fortnight' }

const DAY = 24 * HOUR

/** The latest hour with a price, or null for a series with none. */
export function latestHour(series: SeriesPoint[]): number | null {
  for (let i = series.length - 1; i >= 0; i--) {
    const [t, c, d] = series[i]!
    if (c != null || d != null) return Date.parse(t)
  }
  return null
}

/** The hours a range shows, [from, to] in ms: the latest 3 or 14 days, or the league's first
 *  14 days (from `launchedAt`, else the series' first hour). Null without any price. */
export function rangeBounds(series: SeriesPoint[], range: Range, launchedAt?: string | null): [number, number] | null {
  const latest = latestHour(series)
  if (latest == null) return null
  if (range === 'launch') {
    const start = launchedAt ? Date.parse(launchedAt) : Date.parse(series[0]![0])
    // Floor to the hour: the series is hourly.
    const from = Math.floor(start / HOUR) * HOUR
    return [from, Math.min(latest, from + 14 * DAY - HOUR)]
  }
  const days = range === '3d' ? 3 : 14
  return [latest - days * DAY + HOUR, latest]
}

export function inRange(series: SeriesPoint[], [from, to]: [number, number]): SeriesPoint[] {
  return series.filter(([t]) => {
    const at = Date.parse(t)
    return at >= from && at <= to
  })
}

export type BandPoint = { at: number; low: number; high: number; typical: number | null }

/** The outlook as a band in Divines past the latest hour: the item's latest Divine price
 *  (its own Divine leg, else its latest Chaos price at the league's Divine rate) moved by
 *  each horizon's low, high and typical change. Null without an outlook, a price to start
 *  from, or any horizon with a range. */
export function outlookBand(series: SeriesPoint[], outlook: Outlook | null | undefined, divineChaos: number | null | undefined): BandPoint[] | null {
  const latest = latestHour(series)
  if (!outlook || latest == null) return null
  const start = anchorDivine(series, divineChaos)
  if (start == null) return null
  const points: BandPoint[] = [{ at: latest, low: start, high: start, typical: start }]
  for (const [h, hours] of [
    [outlook.h24, 24],
    [outlook.d3, 72],
  ] as const) {
    if (h.low == null || h.high == null) continue
    points.push({ at: latest + hours * HOUR, low: start * (1 + h.low), high: start * (1 + h.high), typical: h.typical == null ? null : start * (1 + h.typical) })
  }
  return points.length > 1 ? points : null
}

/** The item's price in Divines now: its latest Divine leg in the last day, else its latest
 *  Chaos price over the Divine rate. */
function anchorDivine(series: SeriesPoint[], divineChaos: number | null | undefined): number | null {
  const latest = latestHour(series)!
  for (let i = series.length - 1; i >= 0; i--) {
    const [t, , d] = series[i]!
    if (Date.parse(t) < latest - DAY) break
    if (d != null) return d
  }
  if (!divineChaos) return null
  for (let i = series.length - 1; i >= 0; i--) {
    const c = series[i]![1]
    if (c != null) return c / divineChaos
  }
  return null
}

/** Whether a series has any price in Divines. */
export const hasDivine = (series: SeriesPoint[]) => series.some(([, , d]) => d != null)

/** The chart: Chaos on the left axis, Divines on the right (decided with the user: one
 *  chart shows when an item "rose" in Chaos only because the Divine moved), linear, UTC,
 *  lines broken at missing hours, and the outlook band (in Divines) past the latest hour. */
export function priceChartOption(t: ChartTokens, points: SeriesPoint[], bounds: [number, number], band: BandPoint[] | null): EChartsCoreOption {
  const chaos = { ...line('Chaos', points.map(([at, c]) => [at, c])), yAxisIndex: 0, color: t.accent, lineStyle: { width: 2 }, tooltip: { valueFormatter: (v: number | null) => price(v, 'chaos') } }
  const divine = { ...line('Divine', points.map(([at, , d]) => [at, d])), yAxisIndex: 1, color: t.info, lineStyle: { width: 2 }, tooltip: { valueFormatter: (v: number | null) => price(v, 'divine') } }
  const iso = (ms: number) => new Date(ms).toISOString()
  const bandSeries = band
    ? [
        // Stacked: an invisible floor at the low edge, then the range on top of it, shaded.
        { name: 'band-low', type: 'line', stack: 'outlook', yAxisIndex: 1, symbol: 'none', lineStyle: { opacity: 0 }, tooltip: { show: false }, data: band.map((b) => [iso(b.at), b.low]) },
        {
          name: 'Outlook range',
          type: 'line',
          stack: 'outlook',
          yAxisIndex: 1,
          symbol: 'none',
          color: t.info,
          lineStyle: { opacity: 0 },
          areaStyle: { color: alpha(t.info, 0.18) },
          tooltip: { show: false },
          data: band.map((b) => [iso(b.at), b.high - b.low]),
        },
        {
          name: 'Outlook (typical)',
          type: 'line',
          yAxisIndex: 1,
          symbol: 'none',
          color: t.info,
          lineStyle: { type: 'dashed', width: 1.5 },
          tooltip: { valueFormatter: (v: number | null) => price(v, 'divine') },
          data: band.filter((b) => b.typical != null).map((b) => [iso(b.at), b.typical]),
        },
      ]
    : []
  const axis = axisStyle(t)
  return {
    ...baseOptions(t),
    legend: { ...(baseOptions(t).legend as object), data: band ? ['Chaos', 'Divine', 'Outlook range'] : ['Chaos', 'Divine'] },
    grid: { left: 8, right: 8, top: 40, bottom: 8, containLabel: true },
    xAxis: { type: 'time', min: bounds[0], max: band ? band[band.length - 1]!.at : bounds[1], ...axis, splitLine: { show: false } },
    yAxis: [
      { type: 'value', name: 'Chaos', position: 'left', scale: true, ...axis, axisLabel: { ...axis.axisLabel, formatter: (v: number) => price(v, 'chaos') } },
      { type: 'value', name: 'Divine', position: 'right', scale: true, ...axis, splitLine: { show: false }, axisLabel: { ...axis.axisLabel, formatter: (v: number) => price(v, 'divine') } },
    ],
    series: [chaos, divine, ...bandSeries],
  }
}

// --- The verdict in words ------------------------------------------------------------

export const VERDICT_WORD: Record<Verdict, string> = { sell: 'Sell now', hold: 'Hold', none: 'No clear signal' }
export const VERDICT_SHORT: Record<Verdict, string> = { sell: 'Sell', hold: 'Hold', none: '–' }

const HORIZON_TEXT = { h24: 'the next 24 hours', d3: 'the next 3 days' } as const

/** Whether the model judged this horizon (a verdict, possibly "none", and a band): in the
 *  launch fortnight, for an item at least 2 past leagues traded at this point. */
export const hasHistory = (h: Horizon | null | undefined): h is Horizon => !!h && h.state === 'judged' && h.typical != null

/** Shown outside the launch fortnight, where no horizon has a call (decided after finding 9). */
export const BETWEEN_LAUNCHES = "Calls appear in a league's first two weeks; after that past leagues don't predict the next few days."

/** Whether both horizons are past the days past leagues' paths cover. */
export const isLater = (o: Outlook | null | undefined) => !!o && o.h24.state === 'later' && o.d3.state === 'later'

/** The verdict's one-line reason: "In past leagues it fell 8% in Divines over the next 3
 *  days from this point (−12% to +2%, 4 leagues)." */
export function reason(h: Horizon | null | undefined, horizon: keyof typeof HORIZON_TEXT): string {
  if (h?.state === 'later') return horizon === 'd3' ? 'Past leagues have no 3-day path from this late in a league.' : BETWEEN_LAUNCHES
  if (!hasHistory(h)) return 'Fewer than two past leagues traded it at this point, so there is nothing to judge by.'
  const who = 'it'
  const leagues = `${h.leagues} league${h.leagues === 1 ? '' : 's'}`
  const range = h.low != null && h.high != null ? `${signedPct(h.low, 0)} to ${signedPct(h.high, 0)}, ` : ''
  const typical = h.typical!
  const move = Math.abs(typical) < 0.005 ? 'held about level' : `${typical < 0 ? 'fell' : 'rose'} ${signedPct(Math.abs(typical), 0).replace('+', '')}`
  if (h.verdict === 'none')
    return `Past leagues don't agree: over ${HORIZON_TEXT[horizon]} from this point ${who} moved ${range.replace(/, $/, '')}${range ? ', ' : ''}typically ${signedPct(typical, 0)} in Divines (${leagues}).`
  return `In past leagues ${who} ${move} in Divines over ${HORIZON_TEXT[horizon]} from this point (${range}${leagues}).`
}
